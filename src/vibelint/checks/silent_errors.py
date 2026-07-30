"""Error handling that makes problems invisible instead of solving them.

When an AI cannot work out why something fails, the cheapest way to make the
code "work" is to catch everything and carry on. The program stops crashing,
which looks like success, and the actual bug is now permanently hidden.
"""

from __future__ import annotations

import ast
from typing import Iterable, Optional

from vibelint.checks._ast_utils import (
    annotate_parents,
    is_ellipsis,
    parent_of,
    strip_docstring,
)
from vibelint.checks.base import Check
from vibelint.context import FileContext
from vibelint.finding import Finding, Severity

#: Exceptions that should almost never be swallowed, because doing so breaks
#: Ctrl-C and hides interpreter-level failures.
NEVER_SWALLOW = {"BaseException", "KeyboardInterrupt", "SystemExit", "GeneratorExit"}


class SilentFailureCheck(Check):
    code = "VC030"
    label = "SILENT FAIL"
    description = "Errors that are caught and thrown away"
    severity = Severity.WARNING

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        for node in ctx.nodes(ast.ExceptHandler):
            # `try: import x / except ImportError: pass` is the optional-import
            # idiom. VC001 already treats it as proof the author knows what they
            # are doing, so flagging it here would contradict our own tool.
            owner = parent_of(node)
            if isinstance(owner, ast.Try) and _guards_only_imports(owner.body):
                continue

            body = strip_docstring(node.body)
            kind = _swallow_kind(body)
            swallows = kind is not None
            caught = _caught_name(node)

            if node.type is None:
                # `except:` catches KeyboardInterrupt and SystemExit too.
                yield self.finding(
                    ctx,
                    node,
                    "bare `except:` catches everything, including Ctrl-C and system exits"
                    + (" and then discards it" if swallows else ""),
                    suggestion="Catch the specific exception you expect, e.g. `except ValueError:`.",
                    severity=Severity.CRITICAL if swallows else Severity.WARNING,
                )
                continue

            if caught in NEVER_SWALLOW:
                # Catching these to clean up and re-raise, or to exit tidily on
                # Ctrl-C, is correct and extremely common. Only discarding them
                # is a bug.
                if not swallows:
                    continue
                yield self.finding(
                    ctx,
                    node,
                    f"`except {caught}` discards an interpreter-level failure, so Ctrl-C and exits stop working here",
                    suggestion="Catch `Exception` at most, and only around code you expect to fail.",
                    severity=Severity.CRITICAL,
                )
                continue

            if swallows:
                yield self.finding(
                    ctx,
                    node,
                    f"`except {caught}` {_SWALLOW_MESSAGES[kind]}",
                    suggestion="Log it, re-raise it, or handle it. If it is genuinely safe to ignore, say why in a comment.",
                    # `continue` inside a loop is usually a deliberate skip -
                    # "ignore the files I cannot read" - so it is only a note.
                    severity=Severity.NOTE if kind == "continue" else Severity.WARNING,
                )


class EmptyFinallyCheck(Check):
    code = "VC031"
    label = "SWALLOWED RETURN"
    description = "return/break inside finally, which discards exceptions"
    severity = Severity.CRITICAL

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        for node in ctx.nodes(ast.Try):
            if not node.finalbody:
                continue
            for stmt in _escaping_statements(node.finalbody):
                kind = "return" if isinstance(stmt, ast.Return) else "break"
                yield self.finding(
                    ctx,
                    stmt,
                    f"`{kind}` inside `finally` silently discards any exception in flight",
                    suggestion=f"Move the {kind} outside the finally block.",
                )


_SWALLOW_MESSAGES = {
    "pass": "is ignored silently, so this failure will never be seen",
    "ellipsis": "is ignored silently, so this failure will never be seen",
    "continue": "is skipped over silently, which hides why items were dropped",
    "return": "turns any failure into an ordinary-looking empty result, "
    "so callers cannot tell success from failure",
}


def _swallow_kind(body: list) -> Optional[str]:
    """How an except handler discards the error, or None if it handles it.

    `except Exception: return None` is the most common generated swallow of
    all, and it is worse than `pass`: the caller receives a value that looks
    like a legitimate empty answer.
    """
    if len(body) != 1:
        return None

    only = body[0]
    if isinstance(only, ast.Pass):
        return "pass"
    if isinstance(only, ast.Continue):
        return "continue"
    if is_ellipsis(only):
        return "ellipsis"
    if isinstance(only, ast.Return) and _is_empty_value(only.value):
        return "return"
    return None


def _is_empty_value(node: Optional[ast.expr]) -> bool:
    """Whether a returned value carries no information about the failure.

    Deliberately limited to None, the empty string and empty containers.
    `return False` is excluded: a validator answering "no" on a bad input is
    often exactly right, and guessing otherwise would flag correct code.
    """
    if node is None:  # bare `return`
        return True
    if isinstance(node, ast.Constant):
        return node.value is None or node.value == ""
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return False


def _guards_only_imports(body: list) -> bool:
    """Whether a try block contains nothing but imports."""
    if not body:
        return False
    return all(isinstance(stmt, (ast.Import, ast.ImportFrom)) for stmt in body)


#: Statements whose bodies belong to a different scope than the block itself.
_SCOPE_BOUNDARIES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_LOOPS = (ast.For, ast.AsyncFor, ast.While)


def _escaping_statements(body: list):
    """`return`/`break` that actually leave this block.

    A closure defined inside `finally` has its own `return`, and a loop written
    inside `finally` has its own `break`. Neither discards the exception in
    flight, so neither is a bug - only statements that escape the finally are.
    """
    stack = [(stmt, False) for stmt in body]

    while stack:
        node, inside_loop = stack.pop()

        if isinstance(node, ast.Return):
            yield node
            continue
        if isinstance(node, ast.Break):
            if not inside_loop:
                yield node
            continue
        if isinstance(node, _SCOPE_BOUNDARIES):
            continue

        in_loop = inside_loop or isinstance(node, _LOOPS)
        for child in ast.iter_child_nodes(node):
            stack.append((child, in_loop))


def _caught_name(node: ast.ExceptHandler) -> str:
    """Readable name of what an except clause catches."""
    target = node.type
    if target is None:
        return ""
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Tuple):
        return ", ".join(_name_of(el) for el in target.elts)
    return "..."


def _name_of(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return "..."
