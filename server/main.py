"""Entry point of configs made before 2.3 (`python .../server/main.py`). New configs run `python -m yab_mcp`."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yab_mcp.cli import main  # noqa: E402

main()
