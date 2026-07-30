"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from vibelint import __version__
from vibelint.checks import check_catalog, select_checks
from vibelint.finding import Severity
from vibelint.reporter import JsonReporter, TextReporter
from vibelint.scanner import ScanResult, scan

EXIT_CLEAN = 0
EXIT_FLOPS_FOUND = 1
EXIT_USAGE_ERROR = 2

FAIL_LEVELS = {
    "critical": Severity.CRITICAL,
    "warning": Severity.WARNING,
    "note": Severity.NOTE,
    "never": None,
}

DESCRIPTION = """\
Find the mistakes AI leaves behind in your code.

Scans a Python project for the specific ways generated code goes wrong:
functions that were never written, imports of packages that do not exist,
tests that cannot fail, errors swallowed in silence, placeholder values
wired into real code paths.
"""

EPILOG = """\
examples:
  vibelint                     check the current directory
  vibelint src/                check one directory
  vibelint app.py              check a single file
  vibelint --only VC040        show only test-theater findings
  vibelint --ignore VC021      hide a rule you disagree with
  vibelint --json              machine-readable output for CI
  vibelint --list              describe every check

Silence one line with a trailing comment:
  result = risky()  # vibelint: ignore
  result = risky()  # noqa: VC030
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vibelint",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="file or directory to check (default: current directory)",
    )
    parser.add_argument(
        "--only",
        metavar="CODE",
        action="append",
        help="run only these checks (repeatable, e.g. --only VC001 --only VC040)",
    )
    parser.add_argument(
        "--ignore",
        metavar="CODE",
        action="append",
        help="skip these checks (repeatable)",
    )
    parser.add_argument(
        "--fail-on",
        choices=sorted(FAIL_LEVELS),
        default="warning",
        help="lowest severity that should exit non-zero (default: warning)",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="do not scan test files",
    )
    parser.add_argument("--json", action="store_true", help="output JSON instead of text")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="one line per finding, no snippets or suggestions",
    )
    parser.add_argument("--no-color", action="store_true", help="disable coloured output")
    parser.add_argument(
        "--list", action="store_true", help="list every check and what it catches"
    )
    parser.add_argument("--version", action="version", version=f"vibelint {__version__}")

    return parser


def print_catalog(stream=None) -> None:
    # Resolved at call time, not import time: binding sys.stdout as a default
    # sends output to whatever stdout was when this module was first imported,
    # which loses it entirely for any caller that redirects.
    stream = stream if stream is not None else sys.stdout
    catalog = check_catalog()
    width = max(len(check.label) for check in catalog.values())

    stream.write("\n")
    for code, check in sorted(catalog.items()):
        stream.write(
            f"  {code}  {check.label.ljust(width)}  {check.description}\n"
        )
    stream.write(f"\n  {len(catalog)} checks\n\n")


def resolve_exit_code(result: ScanResult, fail_on: str) -> int:
    threshold = FAIL_LEVELS[fail_on]
    if threshold is None:
        return EXIT_CLEAN

    worst = result.worst_severity()
    if worst is None:
        return EXIT_CLEAN

    # Severity values ascend as importance descends, so "at least as severe as
    # the threshold" is a <= comparison.
    return EXIT_FLOPS_FOUND if worst.value <= threshold.value else EXIT_CLEAN


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        print_catalog()
        return EXIT_CLEAN

    target = Path(args.path)
    if not target.exists():
        parser.error(f"path does not exist: {target}")

    # Name a mistyped code rather than letting it silently select nothing.
    known = set(check_catalog())
    unknown = sorted(
        {code.upper() for code in (args.only or []) + (args.ignore or [])} - known
    )
    if unknown:
        parser.error(
            f"unknown check code{'s' if len(unknown) > 1 else ''}: "
            f"{', '.join(unknown)}. Run `vibelint --list` to see them all."
        )

    checks = select_checks(enabled=args.only, disabled=args.ignore)

    if not checks:
        parser.error("no checks selected; --only and --ignore cancelled each other out")

    result = scan(target, checks, include_tests=not args.skip_tests)

    if args.json:
        JsonReporter().report(result)
    else:
        color = False if args.no_color else None
        TextReporter(color=color, quiet=args.quiet).report(result)

    return resolve_exit_code(result, args.fail_on)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
