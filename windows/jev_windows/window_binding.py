"""Explicit, process-local window following. This module never captures pixels.

Integration: keep one service shared by controller and analysis. Call bind only
after selection completion with the assistant/selection overlay hidden. For each
capture (including retry), freeze a copy of the ORIGINAL descriptor, hide/settle,
resolve it, screenshot(resolved.rect), validate_after(descriptor, resolved), then
restore and call capture_desktop_chat(resolved.rect, existing-frame callback).
Do not replace that rectangle with a pre-hide rectangle or resolve again for OCR.

Only descriptors are persisted. ResolvedSelection and candidate IDs are transient.
Restart/closed/reused windows require explicit candidates + confirm; no automatic
title matching or rebinding. Failed post-frame validation must discard the frame.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
import json
import math
import ntpath
import threading
import time
import uuid

from . import windows_api as native
from .i18n import msg
from .models import Rect


class BindingError(RuntimeError):
    """Localized error, also exposing a stable key for native callers."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(msg(key))


@dataclass(frozen=True)
class WindowGeometry:
    client_rect: Rect
    dpi: int


@dataclass(frozen=True)
class ResolvedSelection:
    rect: Rect
    title: str
    identity: tuple
    geometry: WindowGeometry
    _fingerprint: str = field(repr=False)
    _generation: str = field(repr=False)


@dataclass(frozen=True)
class _RuntimeBinding:
    identity: tuple
    generation: str


@dataclass(frozen=True)
class _Candidate:
    fingerprint: str
    identity: tuple
    expires: float


_FIELDS = {"version", "binding_id", "app_path", "window_class", "relative_rect",
           "reference_width", "reference_height", "reference_dpi"}
_RECT_FIELDS = {"left", "top", "right", "bottom"}
_DESKTOP_CLASSES = {"progman", "workerw", "shell_traywnd", "shell_secondarytraywnd", "#32769"}


def _safe_display(value: str) -> str:
    # Remove control/format characters (including bidi overrides) from UI text.
    import unicodedata
    return "".join(c for c in value if not unicodedata.category(c).startswith("C"))[:256].strip()


def _contains(outer: Rect, inner: Rect) -> bool:
    return (inner.width > 0 and inner.height > 0 and outer.left <= inner.left
            and outer.top <= inner.top and inner.right <= outer.right and inner.bottom <= outer.bottom)


def _overlaps(a: Rect, b: Rect) -> bool:
    return max(a.left, b.left) < min(a.right, b.right) and max(a.top, b.top) < min(a.bottom, b.bottom)


def _descriptor(value: dict) -> tuple[dict, str]:
    try:
        d = copy.deepcopy(value)
        if not isinstance(d, dict) or set(d) != _FIELDS or type(d["version"]) is not int or d["version"] != 1:
            raise ValueError
        if not isinstance(d["binding_id"], str) or str(uuid.UUID(d["binding_id"])) != d["binding_id"]:
            raise ValueError
        if (not isinstance(d["app_path"], str) or not ntpath.isabs(d["app_path"])
                or "\0" in d["app_path"] or not isinstance(d["window_class"], str)
                or not d["window_class"] or "\0" in d["window_class"]):
            raise ValueError
        for name in ("reference_width", "reference_height", "reference_dpi"):
            if type(d[name]) is not int or not 0 < d[name] <= 1000000:
                raise ValueError
        region = d["relative_rect"]
        if (not isinstance(region, dict) or set(region) != _RECT_FIELDS
                or any(type(v) is not int for v in region.values())):
            raise ValueError
        if not _contains(Rect(0, 0, d["reference_width"], d["reference_height"]), Rect(**region)):
            raise ValueError
        return d, json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
        raise BindingError("binding.invalid") from exc


def validate_descriptor(value: dict) -> dict:
    """Validate persisted data without runtime; strip all non-contract keys.

    Returns a detached JSON-compatible copy. Invalid/missing contract fields
    raise BindingError('binding.invalid'); callers may clear configuration then.
    """
    if not isinstance(value, dict):
        raise BindingError("binding.invalid")
    filtered = {key: value[key] for key in _FIELDS if key in value}
    if isinstance(filtered.get("relative_rect"), dict):
        filtered["relative_rect"] = {key: filtered["relative_rect"][key]
                                     for key in _RECT_FIELDS if key in filtered["relative_rect"]}
    return _descriptor(filtered)[0]


class WindowBindingService:
    """Thread-safe service; native module functions are injectable test seams."""

    def __init__(self):
        self._bindings: dict[str, _RuntimeBinding] = {}
        self._candidates: dict[str, _Candidate] = {}
        self._lock = threading.RLock()

    def _eligible(self, window: native.WindowSnapshot) -> None:
        if (window.pid == native.current_process_id()
                or window.window_class.casefold() in _DESKTOP_CLASSES
                or not window.visible or window.minimized or window.cloaked):
            raise BindingError("binding.unavailable")

    def _snapshot(self, hwnd: int) -> native.WindowSnapshot:
        try:
            return native.window_snapshot(hwnd)
        except native.NativeWindowError as exc:
            raise BindingError("binding.unavailable") from exc

    def _live(self, fingerprint: str) -> tuple[_RuntimeBinding, native.WindowSnapshot]:
        binding = self._bindings.get(fingerprint)
        if binding is None:
            raise BindingError("binding.needsConfirmation")
        try:
            window = self._snapshot(binding.identity[0])
        except BindingError as exc:
            self._bindings.pop(fingerprint, None)
            raise BindingError("binding.needsConfirmation") from exc
        if window.identity != binding.identity:
            self._bindings.pop(fingerprint, None)
            raise BindingError("binding.needsConfirmation")
        self._eligible(window)
        return binding, window

    def _region(self, descriptor: dict, window: native.WindowSnapshot) -> Rect:
        dpi = window.dpi
        if dpi <= 0:
            raise BindingError("binding.unavailable")
        reference_dpi = descriptor["reference_dpi"]
        # Compare logical client dimensions, not physical pixels across monitors.
        for actual, reference in ((window.client_rect.width, descriptor["reference_width"]),
                                  (window.client_rect.height, descriptor["reference_height"])):
            if abs(actual * 96 / dpi - reference * 96 / reference_dpi) > 2:
                raise BindingError("binding.reselectRequired")
        r = descriptor["relative_rect"]
        ratio = dpi / reference_dpi
        # Round outward: never silently omit pixels at fractional DPI boundaries.
        rect = Rect(window.client_rect.left + math.floor(r["left"] * ratio),
                    window.client_rect.top + math.floor(r["top"] * ratio),
                    window.client_rect.left + math.ceil(r["right"] * ratio),
                    window.client_rect.top + math.ceil(r["bottom"] * ratio))
        if not _contains(window.client_rect, rect):
            raise BindingError("binding.reselectRequired")
        return rect

    def _unoccluded(self, window: native.WindowSnapshot, rect: Rect) -> None:
        try:
            if not native.selection_on_screen(rect):
                raise BindingError("binding.offscreen")
            for hwnd in native.root_windows():
                if hwnd == window.hwnd:
                    return
                bounds = native.visible_window_bounds(hwnd)
                if bounds is not None and _overlaps(bounds, rect):
                    raise BindingError("binding.occluded")
            raise BindingError("binding.unavailable")
        except native.NativeWindowError as exc:
            raise BindingError("binding.unavailable") from exc

    def _stable(self, window: native.WindowSnapshot) -> None:
        fresh = self._snapshot(window.hwnd)
        self._eligible(fresh)
        if (fresh.identity != window.identity or fresh.client_rect != window.client_rect
                or fresh.dpi != window.dpi):
            raise BindingError("binding.changed")

    def bind(self, rect: Rect) -> dict:
        with self._lock:
            if (not isinstance(rect, Rect) or any(type(v) is not int for v in
                    (rect.left, rect.top, rect.right, rect.bottom)) or not rect.width or not rect.height):
                raise BindingError("binding.invalid")
            try:
                hwnd = native.root_window_at(rect.left + rect.width // 2, rect.top + rect.height // 2)
            except native.NativeWindowError as exc:
                raise BindingError("binding.unavailable") from exc
            window = self._snapshot(hwnd)
            self._eligible(window)
            if not _contains(window.client_rect, rect):
                raise BindingError("binding.reselectRequired")
            self._unoccluded(window, rect)
            self._stable(window)
            client = window.client_rect
            descriptor = {
                "version": 1, "binding_id": str(uuid.uuid4()), "app_path": window.app_path,
                "window_class": window.window_class,
                "relative_rect": {"left": rect.left - client.left, "top": rect.top - client.top,
                                  "right": rect.right - client.left, "bottom": rect.bottom - client.top},
                "reference_width": client.width, "reference_height": client.height,
                "reference_dpi": window.dpi,
            }
            descriptor, fingerprint = _descriptor(descriptor)
            self._bindings[fingerprint] = _RuntimeBinding(window.identity, str(uuid.uuid4()))
            return descriptor

    def resolve(self, descriptor: dict) -> ResolvedSelection:
        with self._lock:
            d, fingerprint = _descriptor(descriptor)
            binding, window = self._live(fingerprint)
            rect = self._region(d, window)
            self._unoccluded(window, rect)
            self._stable(window)
            return ResolvedSelection(rect, _safe_display(window.title), window.identity,
                                     WindowGeometry(window.client_rect, window.dpi),
                                     fingerprint, binding.generation)

    def validate_after(self, descriptor: dict, resolved: ResolvedSelection) -> None:
        """Call after screenshot, while still hidden, before any OCR or frame use."""
        with self._lock:
            _, fingerprint = _descriptor(descriptor)
            if not isinstance(resolved, ResolvedSelection) or fingerprint != resolved._fingerprint:
                raise BindingError("binding.changed")
            fresh = self.resolve(descriptor)
            if (fresh._generation != resolved._generation or fresh.identity != resolved.identity
                    or fresh.geometry != resolved.geometry or fresh.rect != resolved.rect):
                raise BindingError("binding.changed")

    def status(self, descriptor: dict | None) -> dict:
        """Read identity/geometry only: assistant occlusion is normal in UI."""
        display_name = ""
        try:
            if descriptor is None:
                return {"status": "none", "display_name": ""}
            d, fingerprint = _descriptor(descriptor)
            display_name = _safe_display(ntpath.basename(d["app_path"]))
            with self._lock:
                _, window = self._live(fingerprint)
                rect = self._region(d, window)
                if not native.selection_on_screen(rect):
                    raise BindingError("binding.offscreen")
                self._stable(window)
            return {"status": "bound", "display_name": display_name,
                    "rect": {"left": rect.left, "top": rect.top,
                             "right": rect.right, "bottom": rect.bottom}}
        except native.NativeWindowError:
            return {"status": "invalid", "display_name": display_name, "reason": "binding.unavailable"}
        except BindingError as exc:
            return {"status": "needs_confirmation" if exc.key == "binding.needsConfirmation" else "invalid",
                    "display_name": display_name, "reason": exc.key}

    def _expire_candidates(self, fingerprint: str | None = None) -> None:
        now = time.monotonic()
        self._candidates = {key: value for key, value in self._candidates.items()
                            if now < value.expires and value.fingerprint != fingerprint}

    def candidates(self, descriptor: dict) -> list[dict]:
        with self._lock:
            d, fingerprint = _descriptor(descriptor)
            self._expire_candidates(fingerprint)
            result = []
            expires = time.monotonic() + 60
            try:
                handles = native.root_windows()
            except native.NativeWindowError as exc:
                raise BindingError("binding.unavailable") from exc
            for hwnd in handles:
                try:
                    window = self._snapshot(hwnd)
                    self._eligible(window)
                except BindingError:
                    continue
                if (window.app_path.casefold() != d["app_path"].casefold()
                        or window.window_class != d["window_class"]):
                    continue
                candidate_id = uuid.uuid4().hex[:12]
                while candidate_id in self._candidates:
                    candidate_id = uuid.uuid4().hex[:12]
                self._candidates[candidate_id] = _Candidate(fingerprint, window.identity, expires)
                result.append({"id": candidate_id,
                               "title": _safe_display(window.title) or _safe_display(ntpath.basename(window.app_path))})
            return result

    def confirm(self, descriptor: dict, candidate_id: str) -> dict:
        with self._lock:
            d, fingerprint = _descriptor(descriptor)
            self._expire_candidates()
            candidate = self._candidates.pop(candidate_id, None) if isinstance(candidate_id, str) else None
            if candidate is None or candidate.fingerprint != fingerprint:
                raise BindingError("binding.candidateExpired")
            window = self._snapshot(candidate.identity[0])
            self._eligible(window)
            if window.identity != candidate.identity:
                raise BindingError("binding.needsConfirmation")
            rect = self._region(d, window)  # Changed logical size requires a new selection.
            # The confirmation dialog/assistant is visible here. Occlusion is a
            # capture-time guard, not a reason to reject the user's choice.
            try:
                if not native.selection_on_screen(rect):
                    raise BindingError("binding.offscreen")
            except native.NativeWindowError as exc:
                raise BindingError("binding.unavailable") from exc
            self._stable(window)
            # Rotate ID and retire the original: frozen retries cannot follow a
            # user-confirmed replacement, even one with the same exe/class.
            d["binding_id"] = str(uuid.uuid4())
            d, new_fingerprint = _descriptor(d)
            self._bindings.pop(fingerprint, None)
            self._expire_candidates(fingerprint)
            self._bindings[new_fingerprint] = _RuntimeBinding(window.identity, str(uuid.uuid4()))
            return d

    def same_target(self, old_descriptor: dict | None, new_descriptor: dict | None) -> bool:
        """Compare freshly validated live identities, ignoring reselection/moves.

        Missing runtime (including after restart/confirmation) returns False.
        A resize can invalidate the old region yet still be the same live target.
        """
        with self._lock:
            try:
                _, old_key = _descriptor(old_descriptor)
                _, new_key = _descriptor(new_descriptor)
                _, old = self._live(old_key)
                _, new = self._live(new_key)
                return old.identity == new.identity
            except BindingError:
                return False

    def clear(self, descriptor: dict | None = None) -> None:
        """Forget one descriptor, or all runtime handles/candidate IDs if None."""
        with self._lock:
            if descriptor is None:
                self._bindings.clear()
                self._candidates.clear()
                return
            try:
                _, fingerprint = _descriptor(descriptor)
            except BindingError:
                return
            self._bindings.pop(fingerprint, None)
            self._expire_candidates(fingerprint)
