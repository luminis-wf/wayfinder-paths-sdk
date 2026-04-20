from __future__ import annotations

import sys
from pathlib import Path

# Put the path root on sys.path so `from controller import ...` works when
# pytest is invoked from the repo root.
_PATH_ROOT = Path(__file__).resolve().parents[1]
if str(_PATH_ROOT) not in sys.path:
    sys.path.insert(0, str(_PATH_ROOT))
