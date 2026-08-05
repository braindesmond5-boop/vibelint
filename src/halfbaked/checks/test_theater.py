"""Tests that look like tests but cannot fail.

This is the most dangerous flop in the whole tool, because it is invisible.
A suite of forty green tests where twelve assert nothing does not just fail to
catch bugs - it actively convinces you that you are covered.

Models produce these constantly: the test body sets up a scenario, and then
either asserts nothing at all, asserts a literal, or asserts something about a
mock it configured two lines earlier.
"""

from __future__ import annotations

import ast
import operator
import re
from typing import Iterable, List, Optional, Set

from halfbaked.checks._ast_utils import (
    annotate_parents,
    call_name,
    decorator_names,
    attribute_root,
    strip_docstring,
)
from halfbaked.checks.base import Check
from halfbaked.context import FileContext
from halfbaked.finding import Finding, Severity

#: Things that make a factory produce a mock rather than a real object.
MOCK_FACTORIES = {"Mock", "MagicMock", "AsyncMock", "NonCallableMock", "patch", "create_autospec"}

#: Decorators meaning "this is not a test", so silence is expected.
NON_TEST_DECORATORS = {"fixture", "skip", "skipif", "hookimpl"}


class NoAssertionCheck(Check):
    code = "VC040"
    label = "TEST THEATER"
    description = "Tests that assert nothing and therefore cannot fail"
    severity = Severity.CRITICAL

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        if not ctx.is_test_file:
            return

        for node in _test_functions(ctx):
            body = strip_docstring(node.body)
            if not body:
                continue  # An empty test is a placeholder; VC010 owns that.

            if _has_any_assertion(node):
                continue

            yield self.finding(
                ctx,
                node,
                f"{node.name}() runs code but never asserts anything, so it can only fail if the code crashes",
                suggestion="Assert on the result. A test that cannot fail is worse than no test, because it reads as coverage.",
            )


class ConstantAssertionCheck(Check):
    code = "VC041"
    label = "FAKE ASSERT"
    description = "Assertions on literals, which are true by construction"
    severity = Severity.CRITICAL

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        if not ctx.is_test_file:
            return

        for node in ctx.nodes(ast.Assert, ast.Call):
            if isinstance(node, ast.Assert):
                described = _constant_truth(node.test)
                if described is not None:
                    yield self.finding(
                        ctx,
                        node,
                        f"`assert {described}` is true no matter what the code does",
                        suggestion="Assert on a value the code under test produced.",
                    )
                continue

            if isinstance(node, ast.Call):
                tautology = _tautological_assert_call(node)
                if tautology is not None:
                    yield self.finding(
                        ctx,
                        node,
                        tautology,
                        suggestion="Compare the real result against the expected value.",
                    )


class MockTautologyCheck(Check):
    code = "VC042"
    label = "MOCK TAUTOLOGY"
    description = "Tests that only assert on values they mocked themselves"
    severity = Severity.WARNING

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        if not ctx.is_test_file:
            return

        for node in _test_functions(ctx):
            mocks = _mock_names(node)
            if not mocks:
                continue

            asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
            if not asserts:
                continue

            # Asserting that the code *called* a collaborator is real
            # verification, not a tautology - it is the entire point of a mock.
            if any(_verifies_interaction(a) for a in asserts):
                continue

            # If every assertion in the test only ever touches names the test
            # itself mocked, the test is checking the mock, not the code.
            if all(_only_touches(a, mocks) for a in asserts):
                yield self.finding(
                    ctx,
                    node,
                    f"{node.name}() only asserts on mocks it configured itself, so it tests the mock rather than the code",
                    suggestion="Assert on the real return value, or verify the call the code made instead.",
                )


# -- helpers -------------------------------------------------------------


def _test_functions(ctx: FileContext) -> List[ast.AST]:
    """Every function that a test runner would collect."""
    found = []
    for node in ctx.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
        if not node.name.startswith("test"):
            continue
        if decorator_names(node) & NON_TEST_DECORATORS:
            continue
        found.append(node)
    return found


def _has_any_assertion(node: ast.AST) -> bool:
    """Whether a test does anything that could conceivably fail on purpose."""
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            return True

        if isinstance(child, ast.Call):
            name = call_name(child) or ""
            # self.assertEqual(...), mock.assert_called_once(), self.fail()
            if name.startswith("assert") or name == "fail":
                return True
            # Delegating to a shared helper is legitimate verification.
            if name.startswith(("check_", "verify_", "_assert", "expect_")):
                return True

        # `with pytest.raises(ValueError):` is a real assertion.
        if isinstance(child, (ast.With, ast.AsyncWith)):
            for item in child.items:
                target = item.context_expr
                if isinstance(target, ast.Call):
                    if (call_name(target) or "") in {"raises", "warns", "deprecated_call"}:
                        return True

        # A test that re-raises or exits deliberately is signalling failure.
        if isinstance(child, ast.Raise):
            return True

    return False


def _constant_truth(node: ast.expr) -> Optional[str]:
    """If an expression is a constant that is always truthy, describe it."""
    if isinstance(node, ast.Constant):
        if node.value is True:
            return "True"
        if isinstance(node.value, (int, float)) and node.value:
            return repr(node.value)
        if isinstance(node.value, str) and node.value:
            return "a non-empty string"
    if isinstance(node, (ast.List, ast.Tuple, ast.Dict, ast.Set)):
        # `assert [1, 2]` - a non-empty literal container is always truthy.
        size = len(getattr(node, "elts", None) or getattr(node, "keys", []) or [])
        if size:
            return "a non-empty literal"
    # `assert 1 == 1` - a comparison between literals, decided at write time.
    if isinstance(node, ast.Compare) and _all_constants(node):
        if _compare_always_true(node):
            return _render_compare(node)
    return None


def _all_constants(node: ast.Compare) -> bool:
    """True when every operand of a comparison is a literal."""
    return isinstance(node.left, ast.Constant) and all(
        isinstance(operand, ast.Constant) for operand in node.comparators
    )


_COMPARE_SYMBOLS = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Is: "is",
    ast.IsNot: "is not",
}

#: Evaluated directly rather than through eval(), which must never be pointed
#: at code we are analysing.
_COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}


def _compare_always_true(node: ast.Compare) -> bool:
    """Whether a literals-only comparison is true regardless of the code."""
    left = node.left.value
    for op, comparator in zip(node.ops, node.comparators):
        func = _COMPARE_OPS.get(type(op))
        if func is None:
            return False
        try:
            if not func(left, comparator.value):
                return False
        except TypeError:
            return False
        left = comparator.value
    return True


def _render_compare(node: ast.Compare) -> str:
    """Reconstruct `1 == 1` for the report."""
    parts = [repr(node.left.value)]
    for op, operand in zip(node.ops, node.comparators):
        symbol = _COMPARE_SYMBOLS.get(type(op), "?")
        parts.append(f"{symbol} {operand.value!r}")
    return " ".join(parts)


def _tautological_assert_call(node: ast.Call) -> Optional[str]:
    """Detect assertEqual(1, 1), assertTrue(True) and friends."""
    name = call_name(node) or ""
    if not name.startswith("assert"):
        return None

    literal_args = [a for a in node.args if isinstance(a, ast.Constant)]

    if name in {"assertTrue", "assert_true"} and len(node.args) == 1:
        if isinstance(node.args[0], ast.Constant) and node.args[0].value:
            return f"`{name}({node.args[0].value!r})` is true by construction"

    if name in {"assertEqual", "assertEquals", "assertIs", "assert_equal"}:
        if len(node.args) >= 2 and len(literal_args) >= 2:
            left, right = node.args[0], node.args[1]
            if (
                isinstance(left, ast.Constant)
                and isinstance(right, ast.Constant)
                and left.value == right.value
            ):
                return f"`{name}({left.value!r}, {right.value!r})` compares a literal to itself"

    return None


def _mock_names(func: ast.AST) -> Set[str]:
    """Local names in this test that hold a mock, or something a mock produced.

    The second half matters: the usual shape is

        client = MagicMock()
        client.charge.return_value = {"status": "ok"}
        result = client.charge(...)
        assert result["status"] == "ok"

    where `result` came out of the mock, so asserting on it proves nothing.
    """
    names: Set[str] = set()

    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            if _is_mock_expression(node.value):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is None:
                    continue
                if _is_mock_expression(item.context_expr) and isinstance(
                    item.optional_vars, ast.Name
                ):
                    names.add(item.optional_vars.id)
        elif isinstance(node, ast.arguments):
            # `def test_x(mock_client)` - a fixture whose name says it is a mock.
            for arg in [*node.args, *node.kwonlyargs]:
                if re.search(r"(^|_)(mock|stub|fake|patched)(_|$)", arg.arg, re.I):
                    names.add(arg.arg)

    # Values produced *by* a mock are themselves untrustworthy. Repeat until
    # nothing new appears, so chains of derived values are covered.
    for _ in range(4):
        before = len(names)
        for node in ast.walk(func):
            if not isinstance(node, ast.Assign):
                continue
            if not _derives_from_mock(node.value, names):
                continue
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        if len(names) == before:
            break

    return names


def _derives_from_mock(value: ast.expr, mocks: Set[str]) -> bool:
    """Whether an expression's value came out of a mock.

    A mock merely *passed into* real code does not count - `result =
    process(mock_db)` is exactly the test we want people writing, and flagging
    it would make the check useless.
    """
    if isinstance(value, ast.Name):
        return value.id in mocks

    if isinstance(value, ast.Call):
        # The receiver of the call is what matters, not the arguments.
        return _root_name(value.func) in mocks

    if isinstance(value, (ast.Attribute, ast.Subscript)):
        return _root_name(value) in mocks

    if isinstance(value, ast.Await):
        return _derives_from_mock(value.value, mocks)

    return False


def _root_name(node: ast.expr) -> Optional[str]:
    """Leftmost name of an attribute/subscript/call chain."""
    current = node
    while True:
        if isinstance(current, ast.Attribute):
            current = current.value
        elif isinstance(current, ast.Subscript):
            current = current.value
        elif isinstance(current, ast.Call):
            current = current.func
        else:
            break
    return current.id if isinstance(current, ast.Name) else None


#: Attributes that record what the code under test actually did. Reading one is
#: verification of behaviour, not a restatement of something the test stubbed.
MOCK_VERIFICATION_ATTRS = {
    "called",
    "call_count",
    "call_args",
    "call_args_list",
    "mock_calls",
    "method_calls",
    "await_count",
    "await_args",
    "await_args_list",
    "call_list",
}


def _verifies_interaction(node: ast.AST) -> bool:
    """Whether an assertion checks that the code invoked a collaborator."""
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr in MOCK_VERIFICATION_ATTRS:
            return True
        if isinstance(child, ast.Call):
            name = call_name(child) or ""
            if name.startswith("assert_"):  # assert_called_once_with, etc.
                return True
    return False


def _is_mock_expression(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call):
        return False
    return (call_name(node) or "") in MOCK_FACTORIES


def _only_touches(node: ast.AST, names: Set[str]) -> bool:
    """True if every name referenced in this subtree is one of `names`.

    An assertion that mentions nothing at all (a pure literal) does not count
    as touching mocks - VC041 already reports those.
    """
    referenced = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            root = attribute_root(child)
            if root:
                referenced.add(root)
        elif isinstance(child, ast.Name):
            referenced.add(child.id)

    return bool(referenced) and referenced.issubset(names)
