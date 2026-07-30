"""Calls to functions that were never written.

Models assume convenient helpers exist. The generated code calls
`utils.format_timestamp(...)` or `sanitize_input(...)`, the name sounds exactly
like something the project would have, and nothing anywhere defines it.

This only fires on names we can fully account for. If the file uses a star
import, or the name is bound anywhere at all, we stay quiet - a wrong ghost
report is far more damaging than a missed one.
"""

from __future__ import annotations

import ast
import builtins
import difflib
from typing import Dict, Iterable, Optional, Set

from vibelint.checks._ast_utils import (
    annotate_parents,
    attribute_root,
    imported_project_modules,
)
from vibelint.checks.base import Check
from vibelint.context import FileContext, ModuleInfo
from vibelint.finding import Finding, Severity

#: Builtins added after 3.9. `dir(builtins)` only describes the interpreter
#: running vibelint, so linting a 3.11 codebase from 3.9 would otherwise report
#: `anext()` and `ExceptionGroup` as hallucinated - a confident falsehood.
LATER_BUILTINS = {
    "aiter",  # 3.10
    "anext",  # 3.10
    "ExceptionGroup",  # 3.11
    "BaseExceptionGroup",  # 3.11
    "EncodingWarning",  # 3.10
    "PythonFinalizationError",  # 3.13
}

#: Removed after 3.9 but still valid in older targets.
LEGACY_BUILTINS = {"unicode", "basestring", "long", "xrange", "raw_input", "reduce"}

BUILTIN_NAMES = set(dir(builtins)) | LATER_BUILTINS

#: `match` statement nodes bind names too, but only exist on Python 3.10+.
MATCH_BINDING_NODES = tuple(
    node
    for node in (getattr(ast, "MatchAs", None), getattr(ast, "MatchStar", None))
    if node is not None
)

#: Names that are conventionally injected rather than defined or imported.
IMPLICIT_NAMES = {
    "self",
    "cls",
    "__name__",
    "__file__",
    "__doc__",
    "__package__",
    "__spec__",
    "__loader__",
    "__builtins__",
    "__debug__",
    "_",  # gettext, and REPL convention
    "reveal_type",  # type-checker only
}


class GhostCallCheck(Check):
    code = "VC002"
    label = "GHOST FUNCTION"
    description = "Calls to functions that do not exist"
    severity = Severity.CRITICAL

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        if _has_star_import(ctx):
            return  # Cannot know what a star import brought in.

        bound = _bound_names(ctx.all_nodes)

        for node in ctx.nodes(ast.Call):
            if not isinstance(node.func, ast.Name):
                continue

            name = node.func.id
            if name in bound or name in BUILTIN_NAMES or name in IMPLICIT_NAMES:
                continue

            # Defined elsewhere in the project but not imported here: still a
            # crash, but a different one, and the fix is different too.
            owner = _module_defining(ctx, name)
            if owner is not None:
                yield self.finding(
                    ctx,
                    node,
                    f"`{name}()` is never imported in this file (it exists in `{owner}`), so this raises NameError",
                    suggestion=f"Add `from {owner} import {name}`.",
                )
                continue

            yield self.finding(
                ctx,
                node,
                f"`{name}()` is not defined anywhere in this project or the standard library",
                suggestion=_suggest(name, bound, ctx),
            )


class GhostAttributeCheck(Check):
    code = "VC003"
    label = "GHOST METHOD"
    description = "Calls to methods that do not exist on a project module"
    severity = Severity.CRITICAL

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        if _has_star_import(ctx):
            return

        local_modules = imported_project_modules(ctx)
        if not local_modules:
            return

        for node in ctx.nodes(ast.Call):
            if not isinstance(node.func, ast.Attribute):
                continue

            attribute = node.func
            root = attribute_root(attribute)
            if root is None or root not in local_modules:
                continue

            module = local_modules[root]
            # Only judge a direct `module.name()`, never a deeper chain, since
            # anything past the first hop could be an object we cannot resolve.
            if not isinstance(attribute.value, ast.Name):
                continue

            if attribute.attr in module.all_names:
                continue
            # A name that is a method somewhere in the project might be reached
            # through re-export; too ambiguous to call a ghost.
            if attribute.attr in ctx.index.all_method_names:
                continue

            suggestion = _closest(attribute.attr, module.all_names)
            yield self.finding(
                ctx,
                node,
                f"`{module.dotted_name}` has no `{attribute.attr}` - this call fails with AttributeError",
                suggestion=(
                    f"Did you mean `{root}.{suggestion}()`?"
                    if suggestion
                    else f"Write `{attribute.attr}()` in {module.dotted_name}, or call something that exists."
                ),
            )


# -- helpers -------------------------------------------------------------


def _has_star_import(ctx: FileContext) -> bool:
    for node in ctx.nodes(ast.ImportFrom):
        if any(alias.name == "*" for alias in node.names):
            return True
    return False


def _bound_names(all_nodes) -> Set[str]:
    """Every name bound anywhere in the file, at any scope.

    Scope is deliberately ignored. Tracking it properly would let us catch a
    few more bugs and would also produce false positives on every conditional
    definition and late binding, which is a bad trade for this tool.
    """
    names: Set[str] = set()

    for node in all_nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    continue
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.arguments):
            for arg in [*node.args, *node.posonlyargs, *node.kwonlyargs]:
                names.add(arg.arg)
            if node.vararg:
                names.add(node.vararg.arg)
            if node.kwarg:
                names.add(node.kwarg.arg)
        elif MATCH_BINDING_NODES and isinstance(node, MATCH_BINDING_NODES):
            if node.name:
                names.add(node.name)

    return names


def _module_defining(ctx: FileContext, name: str) -> Optional[str]:
    """The project module that defines `name` at top level, if exactly one does."""
    owners = [
        module.dotted_name
        for module in ctx.index.modules.values()
        if name in module.functions or name in module.classes
    ]
    if len(owners) == 1:
        return owners[0]
    return None


def _closest(name: str, candidates: Set[str]) -> Optional[str]:
    if not candidates:
        return None
    matches = difflib.get_close_matches(name, sorted(candidates), n=1, cutoff=0.7)
    return matches[0] if matches else None


def _suggest(name: str, bound: Set[str], ctx: FileContext) -> str:
    pool = set(bound) | BUILTIN_NAMES | ctx.index.all_method_names
    match = _closest(name, pool)
    if match:
        return f"Did you mean `{match}()`?"
    return f"Write `{name}()`, or replace the call with something that exists."
