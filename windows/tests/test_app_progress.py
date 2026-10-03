from jev_windows import app, analysis, task_controller
from jev_windows.calibration import overlay_geometry
from jev_windows.config import AppConfig
from jev_windows.models import Rect


def test_progress_poll_omits_credentials_and_unchanged_payload(monkeypatch):
    monkeypatch.setattr(AppConfig, "load", classmethod(lambda cls: cls()))

    def unexpected_credential_read(*_args):
        raise AssertionError("progress polling must not read credentials")

    monkeypatch.setattr(app, "load_api_key", unexpected_credential_read)
    monkeypatch.setattr(app, "load_model_api_key", unexpected_credential_read)
    api = app.DesktopApi()

    first = api.get_progress()
    assert first["revision"] == 0
    assert first["phase"] == "idle"
    assert api.get_progress(first["revision"]) == {"revision": 0}

    api._set_progress(phase="recognizing", status="正在识别文字")
    changed = api.get_progress(first["revision"])
    assert changed["revision"] == 1
    assert changed["phase"] == "recognizing"
    assert changed["status"] == "正在识别文字"

    monkeypatch.setattr(app, "load_api_key", lambda: "")
    monkeypatch.setattr(app, "load_model_api_key", lambda _profile_id: "")
    assert api.get_state()["revision"] == changed["revision"]


def test_second_analysis_cannot_start_while_first_worker_is_pending(monkeypatch):
    monkeypatch.setattr(
        AppConfig,
        "load",
        classmethod(lambda cls: cls(language="zh-CN", chat_rect=Rect(0, 0, 800, 600), selection_mode="screen")),
    )
    # Analysis orchestration lives in its own module now; patch its seams.
    monkeypatch.setattr(task_controller, "load_api_key", lambda: "test-key")
    monkeypatch.setattr(task_controller, "load_model_api_key", lambda _profile_id: "")
    started = []

    class PendingWorker:
        def __init__(self, *, target, daemon, args=()):
            self.target = target
            self.daemon = daemon
            self.args = args

        def start(self):
            started.append(self)

    monkeypatch.setattr(analysis.threading, "Thread", PendingWorker)
    api = app.DesktopApi()

    first = api.analyze()
    assert first["ok"] is True
    assert first["task_id"] == api.get_progress()["task_id"]
    assert api.get_progress()["phase"] == "capturing"
    result = api.analyze()
    assert result["ok"] is False
    assert result["error"] == "分析正在进行中。"
    assert result["error_message"]["key"] == "error.busy"
    assert len(started) == 1


def test_overlay_geometry_selects_negative_secondary_screen_coordinates():
    assert overlay_geometry(Rect(-1920, 0, 0, 1080)) == "1920x1080+-1920+0"
    assert overlay_geometry(Rect(100, -250, 900, 350)) == "800x600+100+-250"


def test_desktop_startup_exposes_bridge_methods_without_task_cache(monkeypatch):
    monkeypatch.setattr(AppConfig, "load", classmethod(lambda cls: cls(model_profiles=[])))
    monkeypatch.setattr(app, "ensure_dpi_awareness", lambda: None)
    monkeypatch.setattr(app.DesktopApi, "start_background_check", lambda self: None)
    created, exposed = {}, {}
    class Window:
        def expose(self, *methods):
            exposed.update({method.__name__: method for method in methods})
    def create(*args, **kwargs):
        created.update(kwargs)
        return Window()
    monkeypatch.setattr(app.webview, "create_window", create)
    monkeypatch.setattr(app.webview, "start", lambda **kwargs: None)
    app.main()
    assert "js_api" not in created
    assert {"get_progress", "analyze", "analyze_text", "cancel_analysis", "retry_analysis"} <= exposed.keys()
    assert not {"analysis", "progress", "window", "publish", "retry", "start"} & exposed.keys()
    assert all(callable(method) and not method.__name__.startswith("_") for method in exposed.values())
