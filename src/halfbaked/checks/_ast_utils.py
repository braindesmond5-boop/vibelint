"""Shared AST helpers.

Most of the code here exists to *avoid* false positives. A linter that cries
wolf gets uninstalled, so the guards matter more than the detection.
"""

from __future__ import annotations

import ast
from typing import Optional, Union

FunctionNode = Union[ast.FunctionDef, ast.AsyncFunctionDef]

#: Decorators that legitimately mark a function as having no body.
ABSTRACT_DECORATORS = {
    "abstractmethod",
    "abstractproperty",
    "abstractclassmethod",
    "abstractstaticmethod",
    "overload",
}

#: Base classes whose methods are expected to be empty.
INTERFACE_BASES = {"ABC", "ABCMeta", "Protocol", "TypedDict"}


def annotate_parents(tree: ast.AST) -> None:
    """Give every node a `parent` link, so checks can look upward.

    FileContext already does this when the file is parsed. This remains for
    checks used against a bare tree, and returns immediately if the links are
    already in place - it used to be the single most expensive thing the tool
    did, because seven checks each re-walked every file.
    """
    if getattr(tree, "_halfbaked_parented", False):
        return
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node  # type: ignore[attr-defined]
    tree._halfbaked_parented = True  # type: ignore[attr-defined]


def parent_of(node: ast.AST) -> Optional[ast.AST]:
    return getattr(node, "parent", None)


def enclosing_class(node: ast.AST) -> Optional[ast.ClassDef]:
    """The class a node lives in, if any."""
    current = parent_of(node)
    while current is not None:
        if isinstance(current, ast.ClassDef):
            return current
        current = parent_of(current)
    return None


def enclosing_function(node: ast.AST) -> Optional[FunctionNode]:
    current = parent_of(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = parent_of(current)
    return None


def decorator_names(node: FunctionNode) -> set:
    """Flat set of decorator names, ignoring how they were reached."""
    names = set()
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def is_abstract(node: FunctionNode) -> bool:
    """True if this function is *meant* to have no implementation."""
    if decorator_names(node) & ABSTRACT_DECORATORS:
        return True

    owner = enclosing_class(node)
    if owner is None:
        return False

    for base in owner.bases:
        # `Protocol[T]` and `Generic[T]` are Subscript nodes wrapping the real
        # name, so read through the subscript before matching.
        target = base.value if isinstance(base, ast.Subscript) else base
        name = (
            target.attr
            if isinstance(target, ast.Attribute)
            else getattr(target, "id", "")
        )
        if name in INTERFACE_BASES:
            return True

    # `class Foo(metaclass=ABCMeta)`
    for keyword in owner.keywords:
        if keyword.arg == "metaclass":
            value = keyword.value
            name = (
                value.attr
                if isinstance(value, ast.Attribute)
                else getattr(value, "id", "")
            )
            if name in INTERFACE_BASES:
                return True

    return False


def strip_docstring(body: list) -> list:
    """The statements of a body, minus a leading docstring."""
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def has_docstring(node: FunctionNode) -> bool:
    return len(node.body) != len(strip_docstring(node.body))


def is_ellipsis(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is Ellipsis
    )


def raises_not_implemented(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Raise) or stmt.exc is None:
        return False
    exc = stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc
    name = exc.attr if isinstance(exc, ast.Attribute) else getattr(exc, "id", "")
    return name in {"NotImplementedError", "NotImplemented"}


def stub_kind(node: FunctionNode) -> Optional[str]:
    """Classify an unimplemented function body, or None if it has real code.

    Returns one of: "pass", "ellipsis", "docstring", "not_implemented".
    """
    body = strip_docstring(node.body)

    if not body:
        # Body was nothing but a docstring.
        return "docstring"
    if len(body) != 1:
        return None

    only = body[0]
    if isinstance(only, ast.Pass):
        return "pass"
    if is_ellipsis(only):
        return "ellipsis"
    if raises_not_implemented(only):
        return "not_implemented"
    return None


def call_name(node: ast.Call) -> Optional[str]:
    """The bare name being called: `a.b.c()` -> "c", `foo()` -> "foo"."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def attribute_root(node: ast.Attribute) -> Optional[str]:
    """The leftmost name of an attribute chain: `a.b.c` -> "a"."""
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        current = current.value
    if isinstance(current, ast.Name):
        return current.id
    return None


#: Nodes that open a new scope, so their contents belong to them, not to us.
SCOPE_BOUNDARIES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def walk_own_scope(node: ast.AST):
    """Every descendant of `node` that is still in `node`'s own scope.

    Stops at nested functions, classes and lambdas. Cheaper than `ast.walk`
    followed by an `enclosing_function` test on every hit, and correct by
    construction rather than by filtering afterwards.
    """
    stack = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        yield current
        if isinstance(current, SCOPE_BOUNDARIES):
            continue
        stack.extend(ast.iter_child_nodes(current))


def imported_project_modules(ctx) -> dict:
    """Local alias -> the project module it refers to.

    Only names bound by an `import` statement that resolves to a module in this
    project. Anything else - a third-party package, an instance, a local
    variable - is deliberately absent, because we cannot know its type and
    guessing produces confident nonsense.
    """
    found = {}

    for node in ctx.nodes(ast.Import, ast.ImportFrom):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    # `import a.b as c` binds `c` to module `a.b`.
                    module = ctx.index.module_for(alias.name)
                    if module is not None:
                        found[alias.asname] = module
                else:
                    # `import a.b` binds `a`, which refers to package `a`.
                    root = alias.name.split(".")[0]
                    module = ctx.index.module_for(root)
                    if module is not None:
                        found[root] = module
        elif node.module and not node.level:
            for alias in node.names:
                if alias.name == "*":
                    continue
                module = ctx.index.module_for(f"{node.module}.{alias.name}")
                if module is not None:
                    found[alias.asname or alias.name] = module

    return found


def dotted_path(node: ast.AST) -> Optional[str]:
    """Reconstruct `a.b.c` from an attribute chain, or None if not pure names."""
    parts = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))
