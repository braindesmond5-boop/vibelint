"""Runs every check over every file and collects the results."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from halfbaked.checks import Check, run_checks, select_checks
from halfbaked.context import FileContext
from halfbaked.finding import Finding, Severity
from halfbaked.indexer import (
    build_index,
    discover_project_root,
    discover_python_files,
    parse_file,
)

#: `# halfbaked: ignore`, `# noqa`, `# noqa: VC010,VC020`
#:
#: `vibelint` is the tool's former name and stays accepted forever. Suppression
#: comments live in other people's source files, and silently ceasing to honour
#: one would reintroduce a finding they had already decided to accept - the
#: worst possible way for a rename to reach a user.
SUPPRESSION = re.compile(
    r"#\s*(?:halfbaked|vibelint|noqa)\s*:?\s*(?P<codes>[A-Za-z0-9, ]*)",
    re.IGNORECASE,
)


@dataclass
class ScanResult:
    root: Path
    findings: List[Finding] = field(default_factory=list)
    files_scanned: int = 0
    files_skipped: int = 0
    duration: float = 0.0
    suppressed: int = 0

    @property
    def counts(self) -> dict:
        counts = {severity: 0 for severity in Severity}
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts

    @property
    def affected_files(self) -> int:
        return len({finding.path for finding in self.findings})

    def worst_severity(self) -> Optional[Severity]:
        if not self.findings:
            return None
        # Enum members are not orderable, so compare on the underlying value.
        return min((f.severity for f in self.findings), key=lambda s: s.value)

    def sorted_findings(self) -> List[Finding]:
        return sorted(self.findings, key=lambda f: f.sort_key)


def scan(
    target: Path,
    checks: Optional[Sequence[Check]] = None,
    *,
    include_tests: bool = True,
) -> ScanResult:
    """Scan a file or directory and return everything found."""
    started = time.perf_counter()

    target = target.resolve()
    # The root is where the *project* starts, not where the scan does. Scanning
    # one file must still resolve that file's imports against the whole project.
    root = discover_project_root(target)

    files = discover_python_files(target, root)
    if not include_tests:
        files = [f for f in files if not _looks_like_test(f, root)]

    # The index covers the whole project even when scanning one file, so that
    # "this function does not exist" is answered against the real codebase.
    parsed: dict = {}
    index = build_index(root, discover_python_files(root, root), parsed)

    active_checks = list(checks) if checks is not None else select_checks()

    result = ScanResult(root=root)

    for path in files:
        tree, source, error = parsed.get(path) or parse_file(path)

        if error is not None:
            result.findings.append(_syntax_finding(path, source, error))
            # Counted as scanned: it was read and it produced a finding, so
            # leaving it out yields summaries like "1 of 0 files affected".
            result.files_scanned += 1
            continue

        if tree is None:
            result.files_skipped += 1
            continue

        ctx = FileContext(path=path, source=source, tree=tree, index=index, root=root)
        result.files_scanned += 1

        for finding in run_checks(active_checks, ctx):
            if _is_suppressed(ctx, finding):
                result.suppressed += 1
                continue
            result.findings.append(finding)

    result.duration = time.perf_counter() - started
    return result


def _syntax_finding(path: Path, source: str, error: SyntaxError) -> Finding:
    lines = source.splitlines()
    lineno = error.lineno or 1
    snippet = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""
    return Finding(
        path=path,
        line=lineno,
        column=error.offset or 0,
        code="VC000",
        label="BROKEN SYNTAX",
        message=f"this file does not parse: {error.msg}",
        severity=Severity.CRITICAL,
        suggestion="Nothing else can be checked in this file until it parses.",
        snippet=snippet,
    )


def _is_suppressed(ctx: FileContext, finding: Finding) -> bool:
    """Honour `# noqa` / `# halfbaked: ignore` on the reported line."""
    line = ctx.line_text(finding.line)
    if "#" not in line:
        return False

    match = SUPPRESSION.search(line)
    if match is None:
        return False

    codes = match.group("codes") or ""
    listed = {
        code.strip().upper()
        for code in codes.replace(" ", ",").split(",")
        if code.strip()
    }
    # `# halfbaked: ignore VC001` reads naturally and was documented, but the
    # word "ignore" is not a code - drop it before matching, or the whole
    # suppression silently does nothing.
    listed -= {"IGNORE", "DISABLE", "SKIP", "SILENCE"}

    # A bare `# noqa` or `# halfbaked: ignore` suppresses everything on the line.
    if not listed:
        return True
    return finding.code.upper() in listed


def _looks_like_test(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = (path.name,)
    return (
        path.name.startswith("test_")
        or path.name.endswith("_test.py")
        or "tests" in parts
    )
