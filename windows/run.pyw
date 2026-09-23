import sys
from pathlib import Path


# Keep the calibrated Jev question set single-sourced in tools/jev when running
# from source. PyInstaller follows the same import during the packaged build.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jev_windows.app import main


if __name__ == "__main__":
    main()
