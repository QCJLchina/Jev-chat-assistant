import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WINDOWS_DIR = ROOT / "windows"
for path in (ROOT, WINDOWS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

