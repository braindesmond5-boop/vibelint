"""Imports of packages that do not exist.

A model reaching for a plausible-sounding package is the classic hallucination:
`import fastjson`, `from datetime_utils import parse`. The name reads perfectly
and there is nothing behind it.

The bar for reporting is deliberately high. We only call an import a ghost when
it is absent from the standard library, from everything installed, from the
project's own modules, *and* from its declared dependencies. Anything less and
we would flag every uninstalled requirement in a freshly cloned repo.
"""

from __future__ import annotations

import ast
import difflib
from pathlib import Path
from typing import Iterable, List, Optional, Set

from vibelint.checks._ast_utils import annotate_parents, dotted_path, parent_of
from vibelint.checks.base import Check
from vibelint.context import FileContext
from vibelint.environment import (
    installed_top_level,
    known_import_names,
    module_is_importable,
    stdlib_modules,
)
from vibelint.finding import Finding, Severity


class GhostImportCheck(Check):
    code = "VC001"
    label = "GHOST IMPORT"
    description = "Imports of packages that do not exist anywhere"
    severity = Severity.CRITICAL

    def __init__(self) -> None:
        self._root: Optional[Path] = None
        self._known: Set[str] = set()

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        known = self._known_names(ctx.root)

        for node in ctx.nodes(ast.Import, ast.ImportFrom):
            # An import the author already knows might fail is deliberate,
            # not hallucinated. This is how every compatibility shim is written.
            if _is_guarded(node):
                continue

            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if self._is_real(top, ctx, known):
                        continue
                    yield self._ghost(ctx, node, alias.name, top, known)

            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    yield from self._check_relative(ctx, node)
                    continue
                if node.module is None:
                    continue
                top = node.module.split(".")[0]
                if self._is_real(top, ctx, known):
                    continue
                yield self._ghost(ctx, node, node.module, top, known)

    # -- internals -------------------------------------------------------

    def _known_names(self, root: Path) -> Set[str]:
        if self._root != root:
            self._root = root
            self._known = known_import_names(root)
        return self._known

    def _is_real(self, top: str, ctx: FileContext, known: Set[str]) -> bool:
        if top in known:
            return True
        if ctx.index.defines_module(top):
            return True
        # A sibling file or package next to the one being scanned.
        if _exists_beside(ctx, top):
            return True
        return module_is_importable(top)

    def _ghost(
        self,
        ctx: FileContext,
        node: ast.AST,
        full_name: str,
        top: str,
        known: Set[str],
    ) -> Finding:
        suggestion = _closest(top, known)
        return self.finding(
            ctx,
            node,
            f"`{full_name}` does not exist: not in the standard library, not installed, "
            f"not part of this project, and not in your dependencies",
            suggestion=(
                f"Did you mean `{suggestion}`?"
                if suggestion
                else "Check the real package name before installing anything with this name - "
                "attackers register hallucinated package names on PyPI."
            ),
        )

    def _check_relative(self, ctx: FileContext, node: ast.ImportFrom) -> Iterable[Finding]:
        """Relative imports pointing at modules the project does not have."""
        from vibelint.indexer import dotted_name_for

        current = dotted_name_for(ctx.path, ctx.root)
        parts = current.split(".") if current else []

        # `from . import x` inside package `a.b.c` resolves against `a.b`.
        trim = node.level if ctx.path.name != "__init__.py" else node.level - 1
        if trim > len(parts):
            return
        base_parts = parts[: len(parts) - trim] if trim > 0 else parts
        base = ".".join(base_parts)

        # If we cannot see the surrounding package, stay quiet rather than guess.
        if base and not any(
            name == base or name.startswith(base + ".") for name in ctx.index.modules
        ):
            return

        if node.module:
            target = f"{base}.{node.module}" if base else node.module
            if any(
                name == target or name.startswith(target + ".")
                for name in ctx.index.modules
            ):
                return
            yield self.finding(
                ctx,
                node,
                f"relative import `{'.' * node.level}{node.module}` points at a module that does not exist in this project",
                suggestion=_closest(target.split(".")[-1], set(ctx.index.modules)) and
                f"Did you mean `{_closest(target.split('.')[-1], {m.split('.')[-1] for m in ctx.index.modules})}`?"
                or "Create the module, or fix the import path.",
                severity=Severity.CRITICAL,
            )
            return

        base_module = ctx.index.module_for(base)
        for alias in node.names:
            if alias.name == "*":
                continue
            submodule = f"{base}.{alias.name}" if base else alias.name
            if submodule in ctx.index.modules:
                continue
            if base_module is not None and alias.name in base_module.all_names:
                continue
            if base_module is None:
                continue
            yield self.finding(
                ctx,
                node,
                f"`{alias.name}` is imported from `{'.' * node.level}` but no such module or name exists there",
                suggestion="Fix the import, or write the thing it refers to.",
                severity=Severity.CRITICAL,
            )


#: Exceptions that mean "this import is allowed to fail".
IMPORT_GUARDS = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _is_guarded(node: ast.AST) -> bool:
    """Whether an import is deliberately optional.

    Two shapes, both meaning the author already knows the package may be
    absent, so reporting it as a hallucination would be plain wrong:

        try:                          if sys.version_info >= (3, 11):
            import tomllib                import tomllib
        except ImportError:           else:
            tomllib = None                import tomli as tomllib
    """
    current = parent_of(node)
    child: ast.AST = node

    while current is not None:
        if isinstance(current, ast.Try) and _catches_import_error(current):
            # The fallback import lives in the handler, not the try body, so
            # both sides of the shim have to count as guarded.
            in_scope = (
                child in current.body
                or child in current.orelse
                or any(child in handler.body for handler in current.handlers)
            )
            if in_scope:
                return True

        if isinstance(current, ast.If) and _tests_environment(current.test):
            return True

        child = current
        current = parent_of(current)

    return False


def _catches_import_error(node: ast.Try) -> bool:
    for handler in node.handlers:
        if handler.type is None:
            return True
        entries = (
            list(handler.type.elts)
            if isinstance(handler.type, ast.Tuple)
            else [handler.type]
        )
        for entry in entries:
            label = (
                entry.attr
                if isinstance(entry, ast.Attribute)
                else getattr(entry, "id", "")
            )
            if label in IMPORT_GUARDS:
                return True
    return False


def _tests_environment(test: ast.expr) -> bool:
    """True for `if sys.version_info ...` and `if TYPE_CHECKING:` style guards."""
    for node in ast.walk(test):
        if isinstance(node, ast.Attribute):
            path = dotted_path(node)
            if path and ("version_info" in path or "platform" in path):
                return True
        elif isinstance(node, ast.Name):
            if node.id in {"TYPE_CHECKING", "sys"} or "VERSION" in node.id.upper():
                return True
    return False


def _exists_beside(ctx: FileContext, top: str) -> bool:
    """Whether `top` is a module or package sitting next to this file."""
    for base in (ctx.path.parent, ctx.root):
        try:
            if (base / f"{top}.py").is_file() or (base / top / "__init__.py").is_file():
                return True
        except OSError:  # noqa: VC030
            # Deliberate: an unreadable directory simply cannot confirm the
            # module exists, and the caller has other ways to check.
            continue
    return False


def _closest(name: str, candidates: Set[str]) -> Optional[str]:
    """The nearest real name, if one is close enough to be worth suggesting."""
    if not candidates:
        return None
    matches = difflib.get_close_matches(name, sorted(candidates), n=1, cutoff=0.75)
    return matches[0] if matches else None
