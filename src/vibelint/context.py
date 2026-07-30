"""What a check gets to look at when it runs.

Checks never touch the filesystem themselves. They are handed a `FileContext`
for the file under inspection, which also carries a `ProjectIndex` describing
every other file in the project. That two-level view is what lets vibelint
catch calls to functions that were never actually written.
"""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


def _extract_comments(source: str) -> List[Tuple[int, str]]:
    """Pull real comments out of source, tolerating files that fail to tokenise."""
    found: List[Tuple[int, str]] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT:
                found.append((token.start[0], token.string.lstrip("#")))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):  # noqa: VC030
        # Deliberate: tokenising stops at the first malformed construct, and the
        # comments found before that point are still worth checking. A file that
        # will not parse at all is reported separately as VC000.
        pass
    return found


@dataclass
class ModuleInfo:
    """The public surface of one Python file in the project."""

    path: Path
    dotted_name: str
    functions: Set[str] = field(default_factory=set)
    async_functions: Set[str] = field(default_factory=set)
    classes: Set[str] = field(default_factory=set)
    assignments: Set[str] = field(default_factory=set)
    # Names this module re-exports via `from x import y`, which callers may
    # legitimately reach through it.
    imported_names: Set[str] = field(default_factory=set)

    @property
    def all_names(self) -> Set[str]:
        return self.functions | self.classes | self.assignments | self.imported_names


@dataclass
class ProjectIndex:
    """Every symbol the project defines, gathered before any check runs."""

    root: Path
    modules: Dict[str, ModuleInfo] = field(default_factory=dict)
    # Every method name defined on any class anywhere in the project. Used as a
    # deliberately permissive fallback: if a name is a method *somewhere*, we do
    # not flag a call to it, because we cannot always resolve receiver types.
    all_method_names: Set[str] = field(default_factory=set)
    # Class name -> methods defined on it, including inherited-in-project bases.
    class_methods: Dict[str, Set[str]] = field(default_factory=dict)
    # Every `async def` name anywhere in the project. Calling one of these
    # without `await` produces a coroutine that never runs.
    all_async_names: Set[str] = field(default_factory=set)
    # Names that are `def` somewhere too. A name that is both sync and async in
    # different places is ambiguous, so we refuse to flag it.
    all_sync_names: Set[str] = field(default_factory=set)
    # Method name -> every class that defines it. A name owned by more than one
    # class is an override point, so an empty body there is a hook, not a stub.
    method_owners: Dict[str, Set[str]] = field(default_factory=dict)
    # Base class name -> classes deriving from it. A class with children is a
    # base class, whatever its name says.
    subclasses: Dict[str, Set[str]] = field(default_factory=dict)

    def is_override_point(self, method: str, owner: str) -> bool:
        """Whether an empty method body is a deliberate extension hook.

        True when the owning class is subclassed anywhere in the project, or
        when another class defines the same method - both mean subclasses are
        expected to supply the implementation.
        """
        if self.subclasses.get(owner):
            return True
        return len(self.method_owners.get(method, ())) > 1

    def module_for(self, dotted_name: str) -> Optional[ModuleInfo]:
        return self.modules.get(dotted_name)

    def defines_module(self, dotted_name: str) -> bool:
        root = dotted_name.split(".")[0]
        return any(
            name == dotted_name or name.split(".")[0] == root
            for name in self.modules
        )


@dataclass
class FileContext:
    """One file, parsed and ready to inspect.

    The tree is walked exactly once here and the nodes bucketed by type. Fifteen
    checks each calling `ast.walk` themselves turned out to dominate the whole
    runtime, and every check only ever wants two or three node types anyway.
    """

    path: Path
    source: str
    tree: ast.Module
    index: ProjectIndex
    root: Path

    def __post_init__(self) -> None:
        self._lines = self.source.splitlines()
        self._by_type: Dict[tuple, List[ast.AST]] = {}
        self._comments: Optional[List[Tuple[int, str]]] = None

        # Single traversal: link parents and collect every node at the same time.
        nodes: List[ast.AST] = []
        for node in ast.walk(self.tree):
            nodes.append(node)
            for child in ast.iter_child_nodes(node):
                child.parent = node  # type: ignore[attr-defined]
        self._all_nodes = nodes
        self.tree.parent = None  # type: ignore[attr-defined]
        # Tells annotate_parents() the work is already done.
        self.tree._vibelint_parented = True  # type: ignore[attr-defined]

    @property
    def all_nodes(self) -> List[ast.AST]:
        """Every node in the file, walked once at construction."""
        return self._all_nodes

    def nodes(self, *types: type) -> List[ast.AST]:
        """Every node matching the given AST types, cached per type set."""
        cached = self._by_type.get(types)
        if cached is None:
            cached = [node for node in self._all_nodes if isinstance(node, types)]
            self._by_type[types] = cached
        return cached

    @property
    def lines(self) -> List[str]:
        return self._lines

    @property
    def comments(self) -> List[Tuple[int, str]]:
        """Every real comment as (line number, text after the `#`).

        Tokenised rather than scanned for `#`, because a `#` inside a string
        is not a comment and an apostrophe inside a comment is not a string.
        Guessing at that with quote counting silently loses every comment
        containing the word "don't".
        """
        if self._comments is None:
            self._comments = _extract_comments(self.source)
        return self._comments

    def line_text(self, lineno: int) -> str:
        """The source of a 1-indexed line, stripped. Empty if out of range."""
        lines = self.lines
        if 1 <= lineno <= len(lines):
            return lines[lineno - 1].strip()
        return ""

    @property
    def is_test_file(self) -> bool:
        name = self.path.name
        return (
            name.startswith("test_")
            or name.endswith("_test.py")
            or "tests" in self.path.parts
            or "test" in self.path.parts
        )

    @property
    def relative_path(self) -> Path:
        try:
            return self.path.relative_to(self.root)
        except ValueError:
            return self.path
