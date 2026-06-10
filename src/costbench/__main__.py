"""Enable ``python -m costbench`` as an entry point.

Mirrors the ``costbench`` console script. Useful where the console script is not
on PATH — e.g. running from a source checkout on a host (Railpack/Railway) that
installs dependencies but serves the UI assets from the source tree.
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
