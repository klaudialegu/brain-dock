"""Keeps `python -m brain_dock.importer` working; the code is in brain_dock.modules.job_search."""

import sys

from brain_dock.modules.job_search.importer import main

if __name__ == "__main__":
    sys.exit(main())
