"""Turning findings into something a human wants to read.

The report is the product. Someone runs this once, and either the output makes
the problem obvious in two seconds or they never run it again. So every finding
shows three things: what is wrong, the line it is wrong on, and what to do.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, TextIO

from vibelint.finding import Finding, Severity
from vibelint.scanner import ScanResult

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

SEVERITY_COLOR = {
    Severity.CRITICAL: "\033[31m",  # red
    Severity.WARNING: "\033[33m",  # yellow
    Severity.NOTE: "\033[36m",  # cyan
}

SEVERITY_MARK = {
    Severity.CRITICAL: "x",
    Severity.WARNING: "!",
    Severity.NOTE: "-",
}


def _enable_windows_ansi() -> bool:
    """Turn on ANSI escape handling in a Windows console.

    Windows 10 and later can interpret escape codes, but only once a console
    opts in. Without this the report prints literal noise like `<-[31m` around
    every coloured word.
    """
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def supports_color(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if not (hasattr(stream, "isatty") and stream.isatty()):
        return False
    return _enable_windows_ansi()


def supports_unicode(stream: TextIO) -> bool:
    """Whether the box-drawing characters can actually be written.

    Piping to a file on Windows uses the locale encoding, which cannot
    represent the rule and bullet characters - and an encoding error while
    printing a report would crash the run over decoration.
    """
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return False
    try:
        "─·…".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


class TextReporter:
    """Human-readable report, grouped by file."""

    def __init__(self, stream: TextIO = None, color: bool = None, quiet: bool = False):
        self.stream = stream or sys.stdout
        self.color = supports_color(self.stream) if color is None else color
        self.quiet = quiet

        unicode_ok = supports_unicode(self.stream)
        self.rule = "─" if unicode_ok else "-"
        self.bullet = "·" if unicode_ok else "*"
        self.ellipsis = "…" if unicode_ok else "..."

    # -- colour helpers --------------------------------------------------

    def _paint(self, text: str, *codes: str) -> str:
        if not self.color or not codes:
            return text
        return "".join(codes) + text + RESET

    # -- output ----------------------------------------------------------

    def report(self, result: ScanResult) -> None:
        write = self.stream.write

        if not result.findings:
            write("\n")
            write(
                "  "
                + self._paint("No flops found.", BOLD)
                + self._paint(
                    f"  {_plural(result.files_scanned, 'file')} checked"
                    f" in {result.duration:.2f}s\n",
                    DIM,
                )
            )
            if result.files_skipped:
                write(
                    "  "
                    + self._paint(
                        f"{_plural(result.files_skipped, 'file')} could not be read\n",
                        DIM,
                    )
                )
            write("\n")
            return

        grouped = _group_by_file(result.sorted_findings())
        width = max(len(f.label) for f in result.findings)

        write("\n")
        for path, findings in grouped.items():
            self._write_file_block(path, findings, result.root, width)

        self._write_summary(result)

    def _write_file_block(
        self, path: Path, findings: List[Finding], root: Path, width: int
    ) -> None:
        write = self.stream.write

        try:
            display = path.relative_to(root)
        except ValueError:
            display = path

        write("  " + self._paint(str(display), BOLD) + "\n")

        for finding in findings:
            color = SEVERITY_COLOR[finding.severity]
            mark = SEVERITY_MARK[finding.severity]

            line_no = self._paint(f"{finding.line:>5}", DIM)
            marker = self._paint(mark, color, BOLD)
            label = self._paint(finding.label.ljust(width), color)

            write(f"  {line_no}  {marker}  {label}  {finding.message}\n")

            if finding.snippet and not self.quiet:
                snippet = _truncate(finding.snippet, 88, self.ellipsis)
                write("         " + self._paint(f"|  {snippet}", DIM) + "\n")

            if finding.suggestion and not self.quiet:
                write("         " + self._paint(f"-> {finding.suggestion}", DIM) + "\n")

            if not self.quiet:
                write("\n")

        if self.quiet:
            write("\n")

    def _write_summary(self, result: ScanResult) -> None:
        write = self.stream.write
        counts = result.counts

        total = len(result.findings)
        parts = [self._paint(_plural(total, "flop"), BOLD)]

        for severity in (Severity.CRITICAL, Severity.WARNING, Severity.NOTE):
            count = counts[severity]
            if count:
                # "critical" is an adjective and stays as-is; "warning" and
                # "note" are nouns and take a plural s.
                text = (
                    f"{count} critical"
                    if severity is Severity.CRITICAL
                    else _plural(count, severity.label)
                )
                parts.append(self._paint(text, SEVERITY_COLOR[severity]))

        parts.append(
            self._paint(
                f"{result.affected_files} of {_plural(result.files_scanned, 'file')} affected",
                DIM,
            )
        )

        write("  " + self._paint(self.rule * 60, DIM) + "\n")
        write("  " + self._paint(f"  {self.bullet}  ", DIM).join(parts) + "\n")

        footer = f"  checked in {result.duration:.2f}s"
        if result.suppressed:
            footer += f"  {self.bullet}  {result.suppressed} suppressed"
        if result.files_skipped:
            footer += f"  {self.bullet}  {result.files_skipped} unreadable"
        write(self._paint(footer, DIM) + "\n\n")


class JsonReporter:
    """Machine-readable output, for CI and editor integrations."""

    def __init__(self, stream: TextIO = None):
        self.stream = stream or sys.stdout

    def report(self, result: ScanResult) -> None:
        payload = {
            "root": str(result.root),
            "files_scanned": result.files_scanned,
            "files_skipped": result.files_skipped,
            "duration_seconds": round(result.duration, 4),
            "suppressed": result.suppressed,
            "summary": {
                severity.label: count for severity, count in result.counts.items()
            },
            "findings": [
                {
                    "path": str(finding.path),
                    "relative_path": _relative(finding.path, result.root),
                    "line": finding.line,
                    "column": finding.column,
                    "code": finding.code,
                    "label": finding.label,
                    "severity": finding.severity.label,
                    "message": finding.message,
                    "suggestion": finding.suggestion,
                    "snippet": finding.snippet,
                }
                for finding in result.sorted_findings()
            ],
        }
        json.dump(payload, self.stream, indent=2)
        self.stream.write("\n")


def _group_by_file(findings: List[Finding]) -> Dict[Path, List[Finding]]:
    grouped: Dict[Path, List[Finding]] = {}
    for finding in findings:
        grouped.setdefault(finding.path, []).append(finding)
    for items in grouped.values():
        items.sort(key=lambda f: (f.line, f.column))
    return grouped


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _plural(count: int, noun: str) -> str:
    """`1 file`, `3 files` - this line is the last thing every run prints."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _truncate(text: str, limit: int, ellipsis: str = "...") -> str:
    return text if len(text) <= limit else text[: limit - len(ellipsis)] + ellipsis
