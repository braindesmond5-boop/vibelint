"""Allow `python -m halfbaked` as well as the `halfbaked` command.

Installed console scripts land in a directory that is not always on PATH -
`~/Library/Python/3.x/bin` on macOS, `%APPDATA%\\Python\\Scripts` on Windows.
Rather than make that the user's problem, the package is runnable directly.
"""

import sys

from halfbaked.cli import main

if __name__ == "__main__":
    sys.exit(main())
