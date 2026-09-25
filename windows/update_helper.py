"""Standalone helper that swaps in a staged update after the main app exits.

Packaged as update_helper.exe by build.ps1; see jev_windows.updater for logic.
"""
import sys
from pathlib import Path

# Allow running both as a packaged exe and from source during development.
PACKAGE_PARENT = Path(__file__).resolve().parents[1]
for candidate in (PACKAGE_PARENT, Path(__file__).resolve().parent):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from jev_windows.updater import _run_helper_cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(_run_helper_cli())
