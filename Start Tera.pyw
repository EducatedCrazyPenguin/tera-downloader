"""Double-click to run Tera without a command window."""
import sys
from pathlib import Path

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from quiet_launcher import main

if __name__ == '__main__':
    raise SystemExit(main())
