from jev_windows import app, analysis
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
        classmethod(lambda cls: cls(language="zh-CN", chat_rect=Rect(0, 0, 800, 600))),
    )
    # Analysis orchestration lives in its own module now; patch its seams.
    monkeypatch.setattr(analysis, "load_api_key", lambda: "test-key")
    monkeypatch.setattr(analysis, "load_model_api_key", lambda _profile_id: "")
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

    assert api.analyze() == {"ok": True}
    assert api.get_progress()["phase"] == "capturing"
    result = api.analyze()
    assert result["ok"] is False
    assert result["error"] == "分析正在进行中。"
    assert result["error_message"]["key"] == "error.busy"
    assert len(started) == 1


def test_overlay_geometry_selects_negative_secondary_screen_coordinates():
    assert overlay_geometry(Rect(-1920, 0, 0, 1080)) == "1920x1080+-1920+0"
    assert overlay_geometry(Rect(100, -250, 900, 350)) == "800x600+100+-250"
