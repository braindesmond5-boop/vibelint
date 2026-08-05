"""Shared fixtures for the halfbaked test suite.

The whole suite is written in one shape: *given this source, expect these
codes on these lines*. Everything here exists to make that shape short.

    def test_bare_except_is_flagged(scan_code):
        findings = scan_code(
            '''
            try:
                risky()
            except:
                pass
            ''',
            only=["VC030"],
        )
        assert codes(findings) == ["VC030"]
        assert lines_for(findings, "VC030") == [3]
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import pytest

# Work whether or not PYTHONPATH=src was set by the caller.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from halfbaked.checks import select_checks  # noqa: E402
from halfbaked.finding import Finding, Severity  # noqa: E402
from halfbaked.scanner import ScanResult, scan  # noqa: E402

Sources = Union[str, Dict[str, str]]


# -- source helpers ------------------------------------------------------


def normalise(source: str) -> str:
    """Dedent a triple-quoted source block so line 1 is the first real line."""
    text = textwrap.dedent(source)
    if text.startswith("\n"):
        text = text[1:]
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def write_project(root: Path, files: Dict[str, str]) -> Path:
    """Write `{relative path: source}` into `root`, creating directories."""
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(normalise(source), encoding="utf-8")
    return root


# -- assertion helpers ---------------------------------------------------


def codes(findings: Sequence[Finding]) -> List[str]:
    """Every finding's code, in report order."""
    return [f.code for f in findings]


def code_set(findings: Sequence[Finding]) -> set:
    return {f.code for f in findings}


def lines_for(findings: Sequence[Finding], code: str) -> List[int]:
    """The lines a particular code fired on, ascending."""
    return sorted(f.line for f in findings if f.code == code)


def at(findings: Sequence[Finding]) -> List[tuple]:
    """`[(code, line), ...]` - the most readable form for exact assertions."""
    return sorted((f.code, f.line) for f in findings)


def severities(findings: Sequence[Finding], code: str) -> List[Severity]:
    return [f.severity for f in findings if f.code == code]


def messages(findings: Sequence[Finding]) -> str:
    """All messages joined, for loose `in` assertions."""
    return "\n".join(f.message for f in findings)


def describe(findings: Sequence[Finding]) -> str:
    """Readable dump used in assertion messages when something goes wrong."""
    if not findings:
        return "<no findings>"
    return "\n".join(
        "{0}:{1} {2} {3}".format(f.path.name, f.line, f.code, f.message)
        for f in findings
    )


# -- fixtures ------------------------------------------------------------


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """The directory each test's throwaway project is written into."""
    return tmp_path


@pytest.fixture
def scan_project(project_root: Path):
    """Write a project and return the full `ScanResult`.

    `files` maps a relative path to source text. `only`/`ignore` map onto
    `select_checks(enabled=..., disabled=...)`, and `target` lets a test scan
    a single file or subdirectory instead of the whole project.
    """

    def _run(
        files: Sources,
        only: Optional[Sequence[str]] = None,
        ignore: Optional[Sequence[str]] = None,
        target: Optional[str] = None,
        include_tests: bool = True,
    ) -> ScanResult:
        if isinstance(files, str):
            files = {"module.py": files}
        write_project(project_root, files)
        checks = select_checks(enabled=only, disabled=ignore)
        where = project_root if target is None else project_root / target
        return scan(where, checks, include_tests=include_tests)

    _run.root = project_root  # type: ignore[attr-defined]
    return _run


@pytest.fixture
def scan_code(scan_project):
    """Like `scan_project`, but returns just the findings, sorted by line.

    A bare string is written to `module.py`, so the common single-file case
    reads as `scan_code(source, only=["VC010"])`.
    """

    def _run(
        files: Sources,
        only: Optional[Sequence[str]] = None,
        ignore: Optional[Sequence[str]] = None,
        target: Optional[str] = None,
        include_tests: bool = True,
    ) -> List[Finding]:
        result = scan_project(
            files,
            only=only,
            ignore=ignore,
            target=target,
            include_tests=include_tests,
        )
        return sorted(result.findings, key=lambda f: (f.line, f.column, f.code))

    _run.root = scan_project.root  # type: ignore[attr-defined]
    return _run
