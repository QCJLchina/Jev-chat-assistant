"""Synthetic native seams only. Never inspect/capture the user's desktop."""
from contextlib import contextmanager
from dataclasses import replace
import copy
import json
from types import SimpleNamespace

import pytest

from jev_windows import window_binding as binding, windows_api as native
from jev_windows.i18n import describe
from jev_windows.models import Rect


@pytest.fixture
def desktop(monkeypatch):
    window = native.WindowSnapshot(10, 200, 123456, r"C:\Apps\Chat.exe", "ChatClient",
                                  Rect(100, 100, 900, 700), 96, "Synthetic Chat", True, False)
    state = SimpleNamespace(windows={10: window}, order=[10], hit=10,
                            bounds={}, monitors=[Rect(-2000, -1000, 3000, 2000)], now=0.0)

    def snapshot(hwnd):
        if hwnd not in state.windows:
            raise native.NativeWindowError("Synthetic closed window")
        return state.windows[hwnd]

    def no_pixels(*args, **kwargs):
        pytest.fail("Tests must never capture any desktop pixels")

    monkeypatch.setattr(native, "window_snapshot", snapshot)
    monkeypatch.setattr(native, "root_window_at", lambda x, y: state.hit)
    monkeypatch.setattr(native, "root_windows", lambda: list(state.order))
    monkeypatch.setattr(native, "visible_window_bounds", lambda hwnd: state.bounds.get(hwnd))
    monkeypatch.setattr(native, "current_process_id", lambda: 999)
    monkeypatch.setattr(native, "monitor_rects", lambda: state.monitors)
    monkeypatch.setattr(native, "screenshot", no_pixels)
    monkeypatch.setattr(binding.time, "monotonic", lambda: state.now)
    return state


def make_binding():
    service = binding.WindowBindingService()
    return service, service.bind(Rect(200, 200, 600, 500))


def error(key, call):
    with pytest.raises(binding.BindingError) as caught:
        call()
    assert caught.value.key == key
    assert describe(caught.value)["key"] == key


def test_descriptor_roundtrip_no_runtime_or_title(desktop):
    service, descriptor = make_binding()
    assert set(descriptor) == binding._FIELDS
    assert descriptor["relative_rect"] == dict(left=100, top=100, right=500, bottom=400)
    assert (descriptor["reference_width"], descriptor["reference_height"], descriptor["reference_dpi"]) == (800, 600, 96)
    restored = json.loads(json.dumps(descriptor))
    assert service.resolve(restored).rect == Rect(200, 200, 600, 500)
    assert "Synthetic Chat" not in json.dumps(descriptor)
    assert not {"hwnd", "pid", "creation_time", "title"} & descriptor.keys()
    assert binding.WindowBindingService().status(restored)["status"] == "needs_confirmation"


def test_validate_descriptor_strips_secrets_without_runtime(desktop):
    _, descriptor = make_binding()
    dirty = {**descriptor, "hwnd": 10, "pid": 200, "title": "secret"}
    dirty["relative_rect"] = {**descriptor["relative_rect"], "title": "secret"}
    cleaned = binding.validate_descriptor(dirty)
    assert cleaned == descriptor
    cleaned["relative_rect"]["left"] = 0
    assert descriptor["relative_rect"]["left"] == 100


@pytest.mark.parametrize("change", [
    {"version": True}, {"version": 2}, {"binding_id": "10"}, {"app_path": "relative.exe"},
    {"window_class": ""}, {"reference_width": 0}, {"reference_dpi": True},
    {"relative_rect": dict(left=-1, top=0, right=50, bottom=50)},
    {"relative_rect": dict(left=0, top=0, right=801, bottom=50)},
    {"relative_rect": dict(left=0.0, top=0, right=50, bottom=50)},
    {"relative_rect": dict(left=50, top=0, right=50, bottom=50)},
])
def test_invalid_persisted_descriptors_are_safe_states(desktop, change):
    service, descriptor = make_binding()
    descriptor.update(change)
    assert service.status(descriptor)["status"] == "invalid"
    error("binding.invalid", lambda: binding.validate_descriptor(descriptor))


@pytest.mark.parametrize("value", [None, [], "bad", {}, {"hwnd": 10}])
def test_status_handles_empty_and_malformed_values(desktop, value):
    result = binding.WindowBindingService().status(value)
    assert result["status"] == ("none" if value is None else "invalid")


def test_follow_moves_and_negative_coordinates(desktop):
    service, descriptor = make_binding()
    desktop.windows[10] = replace(desktop.windows[10], client_rect=Rect(-900, -300, -100, 300))
    resolved = service.resolve(copy.deepcopy(descriptor))
    assert resolved.rect == Rect(-800, -200, -400, 100)
    assert service.status(descriptor)["rect"] == dict(left=-800, top=-200, right=-400, bottom=100)
    service.validate_after(descriptor, resolved)


def test_follow_dpi_scales_reference_region(desktop):
    service, descriptor = make_binding()
    desktop.windows[10] = replace(desktop.windows[10], dpi=144, client_rect=Rect(1000, 0, 2200, 900))
    assert service.resolve(descriptor).rect == Rect(1150, 150, 1750, 600)


@pytest.mark.parametrize("extra,valid", [(2, True), (3, False)])
def test_logical_client_size_tolerance(desktop, extra, valid):
    service, descriptor = make_binding()
    desktop.windows[10] = replace(desktop.windows[10], client_rect=Rect(100, 100, 900 + extra, 700))
    if valid:
        service.resolve(descriptor)
    else:
        error("binding.reselectRequired", lambda: service.resolve(descriptor))


@pytest.mark.parametrize("change", [{"minimized": True}, {"visible": False}, {"cloaked": True},
                                      {"pid": 999}, {"window_class": "Progman"}, {"window_class": "WorkerW"}])
def test_bind_rejects_ineligible_windows(desktop, change):
    desktop.windows[10] = replace(desktop.windows[10], **change)
    error("binding.unavailable", lambda: make_binding())


@pytest.mark.parametrize("change", [{"minimized": True}, {"visible": False}, {"cloaked": True}])
def test_bound_window_temporarily_unavailable(desktop, change):
    service, descriptor = make_binding()
    original = desktop.windows[10]
    desktop.windows[10] = replace(original, **change)
    assert service.status(descriptor)["status"] == "invalid"
    error("binding.unavailable", lambda: service.resolve(descriptor))
    desktop.windows[10] = original
    assert service.status(descriptor)["status"] == "bound"


@pytest.mark.parametrize("region", [Rect(50, 200, 600, 500), Rect(200, 80, 600, 500),
                                    Rect(200, 200, 1000, 500), Rect(200, 200, 600, 800)])
def test_selection_must_fit_one_client(desktop, region):
    error("binding.reselectRequired", lambda: binding.WindowBindingService().bind(region))


def test_screen_monitor_gap_and_offscreen(desktop):
    desktop.monitors = [Rect(0, 0, 300, 1000), Rect(400, 0, 1000, 1000)]
    assert not native.selection_on_screen(Rect(200, 200, 600, 500))
    error("binding.offscreen", lambda: make_binding())
    desktop.monitors = [Rect(0, 0, 300, 1000), Rect(300, 0, 1000, 1000)]
    assert native.selection_on_screen(Rect(200, 200, 600, 500))
    assert not native.selection_on_screen(Rect(-1, 0, 10, 10))


def test_status_skips_assistant_occlusion_but_capture_rejects_it(desktop):
    service, descriptor = make_binding()
    desktop.order = [99, 10]
    desktop.bounds[99] = Rect(300, 300, 700, 600)
    assert service.status(descriptor)["status"] == "bound"
    error("binding.occluded", lambda: service.resolve(descriptor))
    # Even an assistant/owned/transparent fixture is never exempted at capture.
    error("binding.occluded", lambda: service.bind(Rect(200, 200, 600, 500)))
    desktop.bounds[99] = Rect(600, 200, 700, 500)  # touching edge, no overlap
    service.resolve(descriptor)
    desktop.bounds[99] = None  # hidden fixture
    service.resolve(descriptor)


def test_lower_z_windows_do_not_occlude(desktop):
    service, descriptor = make_binding()
    desktop.order = [10, 20]
    desktop.bounds[20] = Rect(200, 200, 600, 500)
    service.resolve(descriptor)
    desktop.order = [20]
    error("binding.occluded", lambda: service.resolve(descriptor))
    desktop.bounds[20] = None
    error("binding.unavailable", lambda: service.resolve(descriptor))


@pytest.mark.parametrize("change", [{"pid": 201}, {"creation_time": 999},
                                      {"window_class": "OtherClass"}, {"app_path": r"C:\Apps\Other.exe"}])
def test_reused_identity_permanently_retires_runtime(desktop, change):
    service, descriptor = make_binding()
    original = desktop.windows[10]
    desktop.windows[10] = replace(original, **change)
    assert service.status(descriptor)["status"] == "needs_confirmation"
    desktop.windows[10] = original
    assert service.status(descriptor)["status"] == "needs_confirmation"


def test_close_requires_confirmation_even_when_original_returns(desktop):
    service, descriptor = make_binding()
    original = desktop.windows.pop(10)
    error("binding.needsConfirmation", lambda: service.resolve(descriptor))
    desktop.windows[10] = original
    assert service.status(descriptor)["status"] == "needs_confirmation"


def test_candidates_confirm_explicitly_and_invalidate_original_retry(desktop):
    _, descriptor = make_binding()
    service = binding.WindowBindingService()
    choices = service.candidates(descriptor)
    assert len(choices) == 1 and set(choices[0]) == {"id", "title"}
    assert len(choices[0]["id"]) == 12
    assert service.status(descriptor)["status"] == "needs_confirmation"
    confirmed = service.confirm(descriptor, choices[0]["id"])
    assert confirmed["binding_id"] != descriptor["binding_id"]
    assert service.status(confirmed)["status"] == "bound"
    assert not service.same_target(descriptor, confirmed)
    error("binding.needsConfirmation", lambda: service.resolve(descriptor))
    error("binding.candidateExpired", lambda: service.confirm(descriptor, choices[0]["id"]))


def test_candidate_lists_expire_and_relisting_invalidates_ids(desktop):
    service, descriptor = make_binding()
    first = service.candidates(descriptor)[0]["id"]
    second = service.candidates(descriptor)[0]["id"]
    error("binding.candidateExpired", lambda: service.confirm(descriptor, first))
    desktop.now = 60.0
    error("binding.candidateExpired", lambda: service.confirm(descriptor, second))


def test_confirm_permits_visible_assistant_but_capture_guard_rejects_it(desktop):
    service, descriptor = make_binding()
    candidate = service.candidates(descriptor)[0]["id"]
    desktop.order = [99, 10]
    desktop.bounds[99] = Rect(200, 200, 600, 500)
    confirmed = service.confirm(descriptor, candidate)
    assert service.status(confirmed)["status"] == "bound"
    error("binding.occluded", lambda: service.resolve(confirmed))
    desktop.order = [10]
    resolved = service.resolve(confirmed)
    service.validate_after(confirmed, resolved)


def test_confirm_rejects_offscreen_selection(desktop):
    service, descriptor = make_binding()
    candidate = service.candidates(descriptor)[0]["id"]
    desktop.monitors = [Rect(0, 0, 100, 100)]
    error("binding.offscreen", lambda: service.confirm(descriptor, candidate))


def test_candidate_id_is_scoped_to_descriptor(desktop):
    service, first = make_binding()
    second = service.bind(Rect(300, 300, 500, 500))
    candidate = service.candidates(first)[0]["id"]
    error("binding.candidateExpired", lambda: service.confirm(second, candidate))


@pytest.mark.parametrize("change,key", [({"creation_time": 999}, "binding.needsConfirmation"),
    ({"client_rect": Rect(100, 100, 1000, 700)}, "binding.reselectRequired"),
    ({"visible": False}, "binding.unavailable")])
def test_confirm_revalidates_candidate_identity_and_size(desktop, change, key):
    service, descriptor = make_binding()
    candidate = service.candidates(descriptor)[0]["id"]
    desktop.windows[10] = replace(desktop.windows[10], **change)
    error(key, lambda: service.confirm(descriptor, candidate))


def test_candidates_match_exe_and_class_ignore_titles(desktop):
    service, descriptor = make_binding()
    original = desktop.windows[10]
    desktop.windows[20] = replace(original, hwnd=20, title="Same app different title")
    desktop.windows[30] = replace(original, hwnd=30, app_path=r"C:\Other\Chat.exe")
    desktop.windows[40] = replace(original, hwnd=40, window_class="OtherClass")
    desktop.order = [10, 20, 30, 40]
    assert len(service.candidates(descriptor)) == 2


def test_identical_descriptors_have_unique_binding_ids_and_targets(desktop):
    service, first = make_binding()
    desktop.windows[20] = replace(desktop.windows[10], hwnd=20)
    desktop.hit = 20
    desktop.order = [20, 10]
    second = service.bind(Rect(200, 200, 600, 500))
    assert first["binding_id"] != second["binding_id"]
    assert not service.same_target(first, second)
    assert service.resolve(first).identity[0] == 10
    assert service.resolve(second).identity[0] == 20


def test_same_target_reselection_and_resize_keep_context(desktop):
    service, first = make_binding()
    desktop.windows[10] = replace(desktop.windows[10], client_rect=Rect(0, 0, 1000, 800))
    second = service.bind(Rect(50, 50, 400, 300))
    assert service.same_target(first, second)
    assert not service.same_target(None, second)
    service.clear(first)
    assert not service.same_target(first, second)
    assert service.status(second)["status"] == "bound"
    candidate = service.candidates(second)[0]["id"]
    service.clear()
    assert service.status(second)["status"] == "needs_confirmation"
    error("binding.candidateExpired", lambda: service.confirm(second, candidate))


@pytest.mark.parametrize("change,key", [
    ({"client_rect": Rect(101, 100, 901, 700)}, "binding.changed"),
    ({"client_rect": Rect(100, 100, 901, 700)}, "binding.changed"),
    ({"dpi": 144, "client_rect": Rect(100, 100, 1300, 1000)}, "binding.changed"),
    ({"pid": 201}, "binding.needsConfirmation"),
    ({"visible": False}, "binding.unavailable"),
])
def test_post_frame_validation_rejects_changes_before_ocr(desktop, change, key):
    service, descriptor = make_binding()
    resolved = service.resolve(descriptor)
    desktop.windows[10] = replace(desktop.windows[10], **change)
    error(key, lambda: service.validate_after(descriptor, resolved))


def test_post_frame_new_occluder_and_cross_service_resolution(desktop):
    service, descriptor = make_binding()
    resolved = service.resolve(descriptor)
    desktop.order = [99, 10]
    desktop.bounds[99] = Rect(200, 200, 300, 300)
    error("binding.occluded", lambda: service.validate_after(descriptor, resolved))
    desktop.order = [10]
    other = binding.WindowBindingService()
    error("binding.needsConfirmation", lambda: other.validate_after(descriptor, resolved))
    second = service.bind(Rect(300, 300, 500, 500))
    error("binding.changed", lambda: service.validate_after(second, resolved))


def test_bind_and_resolve_detect_geometry_race(desktop, monkeypatch):
    service, descriptor = make_binding()
    original = desktop.windows[10]
    count = 0

    def racing_snapshot(hwnd):
        nonlocal count
        count += 1
        return original if count % 2 else replace(original, client_rect=Rect(101, 100, 901, 700))

    monkeypatch.setattr(native, "window_snapshot", racing_snapshot)
    error("binding.changed", lambda: service.resolve(descriptor))
    error("binding.changed", lambda: service.bind(Rect(200, 200, 600, 500)))


def test_safe_display_and_no_handle_or_pid_status(desktop):
    desktop.windows[10] = replace(desktop.windows[10], title="hello\n\u202esecret")
    service, descriptor = make_binding()
    status = service.status(descriptor)
    assert status["display_name"] == "Chat.exe"
    assert not {"hwnd", "pid", "identity", "title", "app_path"} & status.keys()
    assert service.candidates(descriptor)[0]["title"] == "hellosecret"


def test_native_failure_is_a_status_dict(desktop, monkeypatch):
    service, descriptor = make_binding()

    def fail(*args):
        raise native.NativeWindowError("Synthetic access denial")

    monkeypatch.setattr(native, "selection_on_screen", fail)
    assert service.status(descriptor)["status"] == "invalid"
    monkeypatch.setattr(native, "window_snapshot", fail)
    assert service.status(descriptor)["status"] == "needs_confirmation"


def test_capture_sequence_discards_changed_frame_before_ocr(desktop, monkeypatch):
    """Document main's capture contract using only a synthetic frame object."""
    from jev_windows import capture, workflow

    service, descriptor = make_binding()
    frozen = copy.deepcopy(descriptor)
    events = []
    frame = object()

    def recognize(rect, image):
        events.append("ocr")
        assert image is frame
        return [capture.TextBox("synthetic", Rect(250, 250, 350, 280))]

    monkeypatch.setattr(capture, "_ocr_boxes", recognize)
    monkeypatch.setattr(native, "virtual_screen_rect", lambda: Rect(0, 0, 2000, 2000))

    def grab(change=False):
        events.append("resolve")
        resolved = service.resolve(frozen)
        events.append("synthetic-frame")
        if change:
            desktop.windows[10] = replace(desktop.windows[10], client_rect=Rect(101, 100, 901, 700))
        events.append("validate")
        service.validate_after(frozen, resolved)
        return resolved, frame

    def run(change=False):
        resolved, image = workflow.capture_without_overlay(
            lambda: events.append("hide"), lambda: events.append("show"), lambda: grab(change),
            settle=lambda _: None)
        return capture.capture_desktop_chat(resolved.rect, lambda rect: (image, resolved.title))

    run()
    assert events == ["hide", "resolve", "synthetic-frame", "validate", "show", "ocr"]
    events.clear()
    error("binding.changed", lambda: run(change=True))
    assert events == ["hide", "resolve", "synthetic-frame", "validate", "show"]


def test_process_identity_uses_creation_filetime_and_closes_handle(monkeypatch):
    events = []

    def times(handle, created, exited, kernel, user):
        created._obj.dwHighDateTime = 2
        created._obj.dwLowDateTime = 3
        return True

    def image(handle, flags, buffer, length):
        buffer.value = r"C:\Synthetic\chat.exe"
        return True

    fake = SimpleNamespace(OpenProcess=lambda rights, inherit, pid: events.append((rights, pid)) or 77,
                           GetProcessTimes=times, QueryFullProcessImageNameW=image,
                           CloseHandle=lambda handle: events.append(("close", handle)))
    monkeypatch.setattr(native, "_KERNEL32", fake)
    assert native.process_identity(42) == (r"C:\Synthetic\chat.exe", (2 << 32) | 3)
    assert events == [(0x1000, 42), ("close", 77)]
    fake.GetProcessTimes = lambda *args: False
    with pytest.raises(native.NativeWindowError):
        native.process_identity(42)
    assert events[-1] == ("close", 77)


def test_physical_context_restores_on_error(monkeypatch):
    calls = []
    fake = SimpleNamespace(SetThreadDpiAwarenessContext=lambda context: calls.append(context) or 55)
    monkeypatch.setattr(native, "_USER32", fake)
    with pytest.raises(ValueError):
        with native.physical_window_coordinates():
            raise ValueError("synthetic")
    assert calls == [native._DPI_CONTEXT_PER_MONITOR_V2, 55]
    fake.SetThreadDpiAwarenessContext = lambda context: 0
    with pytest.raises(native.NativeWindowError):
        with native.physical_window_coordinates():
            pytest.fail("Should fail closed")


def test_native_snapshot_uses_both_client_to_screen_corners_and_fresh_process(monkeypatch):
    events = []

    @contextmanager
    def physical():
        events.append("physical")
        yield
        events.append("restore")

    monkeypatch.setattr(native, "physical_window_coordinates", physical)
    monkeypatch.setattr(native.win32gui, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(native.win32gui, "GetAncestor", lambda hwnd, flag: hwnd)
    monkeypatch.setattr(native.win32gui, "GetClassName", lambda hwnd: "Fixture")
    monkeypatch.setattr(native.win32gui, "GetClientRect", lambda hwnd: (0, 0, 800, 600))
    monkeypatch.setattr(native.win32gui, "ClientToScreen", lambda hwnd, pt: events.append(pt) or (pt[0] - 1000, pt[1] + 50))
    monkeypatch.setattr(native.win32gui, "GetWindowText", lambda hwnd: "Fixture")
    monkeypatch.setattr(native.win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(native.win32gui, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(native, "_window_cloaked", lambda hwnd: False)
    monkeypatch.setattr(native, "_window_process_id", lambda hwnd: 42)
    monkeypatch.setattr(native, "_USER32", SimpleNamespace(GetDpiForWindow=lambda hwnd: 144))

    def identity(pid):
        events.append("process")
        return r"C:\Fixture.exe", 123

    monkeypatch.setattr(native, "process_identity", identity)
    snapshot = native.window_snapshot(77)
    assert snapshot.client_rect == Rect(-1000, 50, -200, 650)
    assert snapshot.dpi == 144
    assert events == ["physical", "process", (0, 0), (800, 600), "process", "restore"]
    counter = 0

    def reused(pid):
        nonlocal counter
        counter += 1
        return r"C:\Fixture.exe", counter

    monkeypatch.setattr(native, "process_identity", reused)
    with pytest.raises(native.NativeWindowError):
        native.window_snapshot(77)


def test_native_z_order_keeps_owned_popups_and_detects_cycles(monkeypatch):
    monkeypatch.setattr(native.win32gui, "GetTopWindow", lambda parent: 20)
    monkeypatch.setattr(native.win32gui, "GetWindow", lambda hwnd, flag: {20: 10, 10: 0}[hwnd])
    assert native.root_windows() == [20, 10]
    monkeypatch.setattr(native.win32gui, "GetWindow", lambda hwnd, flag: 20)
    with pytest.raises(native.NativeWindowError):
        native.root_windows()


@pytest.fixture
def native_snapshot_seams(monkeypatch):
    """Exercise the real window_snapshot with every OS/window read mocked."""
    state = SimpleNamespace(minimized=False, client=(0, 0, 800, 600), dpi=96,
                            created=123, identity_reads=0, exists=True)

    def identity(pid):
        state.identity_reads += 1
        return r"C:\Synthetic\Chat.exe", state.created

    fake_user32 = SimpleNamespace(SetThreadDpiAwarenessContext=lambda context: 55,
                                 GetDpiForWindow=lambda hwnd: state.dpi)
    monkeypatch.setattr(native, "_USER32", fake_user32)
    monkeypatch.setattr(native.win32gui, "IsWindow", lambda hwnd: state.exists)
    monkeypatch.setattr(native.win32gui, "GetAncestor", lambda hwnd, flag: hwnd)
    monkeypatch.setattr(native.win32gui, "GetClassName", lambda hwnd: "SyntheticChat")
    monkeypatch.setattr(native.win32gui, "GetClientRect", lambda hwnd: state.client)
    monkeypatch.setattr(native.win32gui, "ClientToScreen", lambda hwnd, pt: (100 + pt[0], 100 + pt[1]))
    monkeypatch.setattr(native.win32gui, "GetWindowText", lambda hwnd: "Synthetic")
    monkeypatch.setattr(native.win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(native.win32gui, "IsIconic", lambda hwnd: state.minimized)
    monkeypatch.setattr(native, "_window_cloaked", lambda hwnd: False)
    monkeypatch.setattr(native, "_window_process_id", lambda hwnd: 200)
    monkeypatch.setattr(native, "process_identity", identity)
    monkeypatch.setattr(native, "current_process_id", lambda: 999)
    monkeypatch.setattr(native, "root_window_at", lambda x, y: 10)
    monkeypatch.setattr(native, "root_windows", lambda: [10])
    monkeypatch.setattr(native, "visible_window_bounds", lambda hwnd: None)
    monkeypatch.setattr(native, "monitor_rects", lambda: [Rect(0, 0, 2000, 2000)])

    def no_pixels(*args, **kwargs):
        pytest.fail("Tests must never capture any desktop pixels")

    monkeypatch.setattr(native, "screenshot", no_pixels)
    return state


@pytest.mark.parametrize("client,dpi", [((0, 0, 0, 0), 96), ((0, 0, 800, 600), 0),
                                       ((0, 0, 0, 0), 0)])
def test_native_minimized_geometry_keeps_binding_until_restore(native_snapshot_seams, client, dpi):
    state = native_snapshot_seams
    service, descriptor = make_binding()
    state.minimized, state.client, state.dpi = True, client, dpi
    state.identity_reads = 0
    snapshot = native.window_snapshot(10)
    assert snapshot.minimized is True
    assert snapshot.dpi == dpi
    assert snapshot.client_rect == Rect(100, 100, 100 + client[2], 100 + client[3])
    assert state.identity_reads == 2
    status = service.status(descriptor)
    assert status["status"] == "invalid"
    assert status["reason"] == "binding.unavailable"
    error("binding.unavailable", lambda: service.resolve(descriptor))
    state.minimized, state.client, state.dpi = False, (0, 0, 800, 600), 96
    assert service.status(descriptor)["status"] == "bound"
    resolved = service.resolve(descriptor)
    assert resolved.rect == Rect(200, 200, 600, 500)
    service.validate_after(descriptor, resolved)


@pytest.mark.parametrize("client,dpi", [((0, 0, 0, 0), 96), ((0, 0, 800, 600), 0),
                                       ((0, 0, 0, 0), 0)])
def test_native_nonminimized_invalid_geometry_still_rejected(native_snapshot_seams, client, dpi):
    state = native_snapshot_seams
    state.client, state.dpi = client, dpi
    with pytest.raises(native.NativeWindowError, match="Client geometry unavailable"):
        native.window_snapshot(10)


@pytest.mark.parametrize("change", ["closed", "creation_time"])
def test_native_invalid_identity_still_retires_minimized_binding(native_snapshot_seams, change):
    state = native_snapshot_seams
    service, descriptor = make_binding()
    state.minimized, state.client, state.dpi = True, (0, 0, 0, 0), 0
    if change == "closed":
        state.exists = False
    else:
        state.created += 1
    assert service.status(descriptor)["status"] == "needs_confirmation"
    state.exists, state.created = True, 123
    state.minimized, state.client, state.dpi = False, (0, 0, 800, 600), 96
    assert service.status(descriptor)["status"] == "needs_confirmation"


def test_native_minimized_invalid_geometry_still_double_validates_identity(native_snapshot_seams, monkeypatch):
    state = native_snapshot_seams
    state.minimized, state.client, state.dpi = True, (0, 0, 0, 0), 0
    reads = iter([(r"C:\Synthetic\Chat.exe", 123), (r"C:\Synthetic\Chat.exe", 124)])
    monkeypatch.setattr(native, "process_identity", lambda pid: next(reads))
    with pytest.raises(native.NativeWindowError, match="Window identity changed"):
        native.window_snapshot(10)


def test_native_visible_bounds_do_not_ignore_transparent_or_owned_fixture(monkeypatch):
    @contextmanager
    def physical():
        yield

    monkeypatch.setattr(native, "physical_window_coordinates", physical)
    monkeypatch.setattr(native.win32gui, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(native.win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(native.win32gui, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(native.win32gui, "GetWindowRect", lambda hwnd: (0, 0, 100, 100))
    monkeypatch.setattr(native, "_window_cloaked", lambda hwnd: False)
    assert native.visible_window_bounds(20) == Rect(0, 0, 100, 100)
    monkeypatch.setattr(native.win32gui, "IsWindowVisible", lambda hwnd: False)
    assert native.visible_window_bounds(20) is None
