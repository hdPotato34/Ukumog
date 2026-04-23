from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dev.tools.ml_match_suite import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(main())
