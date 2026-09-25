"""Ensure update_helper.py stays a thin, importable wrapper of the updater CLI."""
import importlib.util
import sys
from pathlib import Path


def test_update_helper_reuses_updater_cli():
    helper_path = Path(__file__).resolve().parents[1] / "update_helper.py"
    spec = importlib.util.spec_from_file_location("update_helper", helper_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    from jev_windows import updater
    assert module._run_helper_cli is updater._run_helper_cli
