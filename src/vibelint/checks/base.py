"""The contract every check implements.

A check is deliberately small: it is handed one parsed file and yields findings.
It does no I/O and knows nothing about reporting, so checks stay easy to write,
easy to test, and easy to turn off.
"""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

from vibelint.context import FileContext
from vibelint.finding import Finding, Severity


class Check(abc.ABC):
    """Base class for every vibelint rule."""

    #: Stable machine identifier, e.g. "VC010". Used for config and ignores.
    code: str = ""
    #: Short human tag shown in the report, e.g. "PLACEHOLDER".
    label: str = ""
    #: One line explaining what this catches, shown by `vibelint --list`.
    description: str = ""
    #: Default severity; individual findings may override it.
    severity: Severity = Severity.WARNING
    #: Whether this check should also run on the project's test files.
    runs_on_tests: bool = True

    @abc.abstractmethod
    def check(self, ctx: FileContext) -> Iterable[Finding]:
        """Yield a finding for every problem in this file."""

    # -- helpers available to all checks ---------------------------------

    def finding(
        self,
        ctx: FileContext,
        node,
        message: str,
        *,
        suggestion: Optional[str] = None,
        severity: Optional[Severity] = None,
    ) -> Finding:
        """Build a Finding anchored to an AST node."""
        line = getattr(node, "lineno", 1)
        return Finding(
            path=ctx.path,
            line=line,
            column=getattr(node, "col_offset", 0),
            code=self.code,
            label=self.label,
            message=message,
            severity=severity or self.severity,
            suggestion=suggestion,
            snippet=ctx.line_text(line),
        )


def run_checks(checks: List[Check], ctx: FileContext) -> Iterator[Finding]:
    """Run every applicable check against one file."""
    for check in checks:
        if ctx.is_test_file and not check.runs_on_tests:
            continue
        # A single broken rule must never take down the whole run - but it must
        # not vanish either, or a file gets silently half-checked and the report
        # still says "no flops found".
        try:
            yield from check.check(ctx)
        except (Exception, RecursionError) as exc:
            yield Finding(
                path=ctx.path,
                line=1,
                column=0,
                code="VC999",
                label="CHECK FAILED",
                message=(
                    f"{check.code} could not run on this file "
                    f"({type(exc).__name__}), so it was not fully checked"
                ),
                severity=Severity.NOTE,
                suggestion="This is a bug in vibelint. Please report it with the file that triggered it.",
            )
