"""Allow `python -m vibelint` as well as the `vibelint` command.

Installed console scripts land in a directory that is not always on PATH -
`~/Library/Python/3.x/bin` on macOS, `%APPDATA%\\Python\\Scripts` on Windows.
Rather than make that the user's problem, the package is runnable directly.
"""

import sys

from vibelint.cli import main

if __name__ == "__main__":
    sys.exit(main())
