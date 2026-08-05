"""The check registry.

Adding a rule to halfbaked means writing a Check subclass and listing it here.
Nothing else in the codebase needs to know it exists.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from halfbaked.checks.async_misuse import BlockingInAsyncCheck, LostAwaitCheck
from halfbaked.checks.base import Check, run_checks
from halfbaked.checks.fake_values import (
    EnvFallbackCheck,
    FakeEndpointCheck,
    FakeSecretCheck,
)
from halfbaked.checks.ghost_calls import GhostAttributeCheck, GhostCallCheck
from halfbaked.checks.ghost_imports import GhostImportCheck
from halfbaked.checks.placeholders import ConfessionCheck, PlaceholderCheck
from halfbaked.checks.silent_errors import EmptyFinallyCheck, SilentFailureCheck
from halfbaked.checks.test_theater import (
    ConstantAssertionCheck,
    MockTautologyCheck,
    NoAssertionCheck,
)

#: Every check, in the order their codes were assigned.
CHECK_CLASSES = [
    GhostImportCheck,
    GhostCallCheck,
    GhostAttributeCheck,
    PlaceholderCheck,
    ConfessionCheck,
    FakeSecretCheck,
    FakeEndpointCheck,
    EnvFallbackCheck,
    SilentFailureCheck,
    EmptyFinallyCheck,
    NoAssertionCheck,
    ConstantAssertionCheck,
    MockTautologyCheck,
    LostAwaitCheck,
    BlockingInAsyncCheck,
]


def all_checks() -> List[Check]:
    """A fresh instance of every check."""
    return [cls() for cls in CHECK_CLASSES]


def select_checks(
    enabled: Optional[Sequence[str]] = None,
    disabled: Optional[Sequence[str]] = None,
) -> List[Check]:
    """Instantiate checks, honouring --only and --ignore.

    Codes are matched case-insensitively, so `vc010` and `VC010` both work.
    """
    checks = all_checks()

    if enabled:
        wanted = {code.upper() for code in enabled}
        checks = [c for c in checks if c.code.upper() in wanted]

    if disabled:
        unwanted = {code.upper() for code in disabled}
        checks = [c for c in checks if c.code.upper() not in unwanted]

    return checks


def check_catalog() -> Dict[str, Check]:
    """Code -> check, for `halfbaked --list`."""
    return {check.code: check for check in all_checks()}


__all__ = [
    "Check",
    "run_checks",
    "all_checks",
    "select_checks",
    "check_catalog",
    "CHECK_CLASSES",
]
