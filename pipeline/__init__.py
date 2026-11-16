"""Crawl and build steps for the Agent Files Index. Run each step with `python -m pipeline.<step> RAW_DIR`."""
from __future__ import annotations

import sys
from pathlib import Path


def paths_from_argv(*names: str) -> list[Path]:
    """The step's folder arguments; exits with a usage line when the count is wrong."""
    if len(sys.argv) != len(names) + 1:
        sys.exit(f"usage: python -m pipeline.{Path(sys.argv[0]).stem} {' '.join(names)}")
    return [Path(a) for a in sys.argv[1:]]
