"""The result of a single check firing on a single line of code."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class Severity(enum.Enum):
    """How much a finding should worry you.

    CRITICAL - this code is broken or will break. It cannot work as written.
    WARNING  - this code runs, but it is hiding a problem from you.
    NOTE     - worth a look, but it may well be intentional.
    """

    CRITICAL = 0
    WARNING = 1
    NOTE = 2

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Finding:
    """One problem, at one place in the code.

    `label` is the short human tag shown in the report (e.g. "GHOST METHOD").
    `code` is the stable machine identifier (e.g. "VC003") used for ignores
    and config, so the wording of `label` can change without breaking anyone.
    """

    path: Path
    line: int
    column: int
    code: str
    label: str
    message: str
    severity: Severity
    suggestion: Optional[str] = None
    snippet: Optional[str] = None

    @property
    def sort_key(self):
        return (self.severity.value, str(self.path), self.line, self.column)

    def location(self, root: Optional[Path] = None) -> str:
        path = self.path
        if root is not None:
            try:
                path = self.path.relative_to(root)
            except ValueError:  # noqa: VC030
                # Deliberate: the file sits outside the scan root, so the
                # absolute path is the correct thing to display.
                pass
        return f"{path}:{self.line}"
