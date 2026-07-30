"""Builds a map of everything the project defines, before any check runs.

A single file cannot tell you whether `helpers.format_date()` is real. Only the
whole project can. So we make one pass to collect every function, class and
method that actually exists, then hand that index to the checks.
"""

from __future__ import annotations

import ast
import tokenize
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple

from vibelint.context import ModuleInfo, ProjectIndex

# Directories that are never the user's own source code.
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "env",
    ".env",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "site-packages",
    "dist",
    "build",
    ".eggs",
    # Vendored copies of other people's libraries. Not the user's code, and
    # frequently full of legacy compatibility shims that look like flops.
    "_vendor",
    "vendor",
    "vendored",
    "third_party",
    "migrations",
}


def discover_python_files(target: Path, root: Optional[Path] = None) -> List[Path]:
    """Every .py file under `target` that plausibly belongs to the user.

    Filtering is done on the path *relative to the project root*, never the
    absolute path. Otherwise a repository that merely happens to live in a
    directory called `build` or `env` is skipped in its entirety, and the tool
    cheerfully reports "no flops found" having read nothing at all.
    """
    if target.is_file():
        return [target] if target.suffix == ".py" else []

    base = root or target

    found: List[Path] = []
    for path in sorted(target.rglob("*.py")):
        try:
            parts = path.relative_to(base).parts
        except ValueError:
            parts = path.relative_to(target).parts

        if any(part in SKIP_DIRS for part in parts):
            continue
        if any(part.endswith(".egg-info") for part in parts):
            continue
        found.append(path)
    return found


def discover_project_root(target: Path) -> Path:
    """The directory the project actually starts at.

    Scanning `repo/pkg/api/` must not make `from pkg.core import db` look
    hallucinated, so we climb out of any package (a directory with an
    `__init__.py`) and then look for a project marker. Editors and pre-commit
    hooks invoke linters on single files constantly, and that path has to
    behave the same as scanning the whole tree.
    """
    current = target if target.is_dir() else target.parent
    current = current.resolve()

    # Climb out of the package this file belongs to.
    while (current / "__init__.py").is_file() and current.parent != current:
        current = current.parent

    package_root = current

    # Then look upward for something that marks the top of a project.
    markers = ("pyproject.toml", "setup.py", "setup.cfg", ".git", "requirements.txt")
    for candidate in [current, *current.parents]:
        if candidate == candidate.parent:  # filesystem root
            break
        if any((candidate / marker).exists() for marker in markers):
            return candidate

    return package_root


def dotted_name_for(path: Path, root: Path) -> str:
    """Turn `pkg/sub/mod.py` into `pkg.sub.mod`, collapsing `__init__.py`."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = Path(path.name)

    parts = list(relative.parts)
    if parts and parts[-1] == "__init__.py":
        parts = parts[:-1]
    elif parts:
        parts[-1] = parts[-1][: -len(".py")]

    # A `src/` layout is packaging scaffolding, not part of the import path.
    if parts and parts[0] == "src":
        parts = parts[1:]

    return ".".join(parts)


def parse_file(path: Path) -> Tuple[Optional[ast.Module], str, Optional[SyntaxError]]:
    """Read and parse a file, returning (tree, source, error).

    A file that will not parse is not an AI problem, it is a broken file, so we
    surface the error rather than pretending the file is clean.
    """
    try:
        # tokenize.open honours a PEP 263 coding declaration and strips a UTF-8
        # BOM. Plain read_text("utf-8") leaves the BOM in the string, and
        # ast.parse then rejects the file as containing U+FEFF - a file that
        # CPython itself runs perfectly well.
        with tokenize.open(str(path)) as handle:
            source = handle.read()
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError, LookupError):
        try:
            source = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return None, "", None

    try:
        return ast.parse(source, filename=str(path)), source, None
    except SyntaxError as exc:
        return None, source, exc


#: Statements whose bodies still execute at module level, so definitions inside
#: them are part of the module's public surface.
_MODULE_LEVEL_BLOCKS = (
    ast.If,
    ast.Try,
    ast.With,
    ast.AsyncWith,
    ast.For,
    ast.AsyncFor,
    ast.While,
)


def _module_level_statements(body: Iterable[ast.stmt]) -> Iterator[ast.stmt]:
    """Module-level statements, descending through control flow but not scopes.

    Platform switches and import shims define things conditionally:

        if sys.platform == "win32":
            def get_home(): ...
        try:
            from ujson import dumps
        except ImportError:
            from json import dumps

    Reading only `tree.body` misses all of it, and then every call to those
    names gets reported as a ghost.
    """
    for node in body:
        yield node
        if isinstance(node, _MODULE_LEVEL_BLOCKS):
            yield from _module_level_statements(node.body)
            yield from _module_level_statements(getattr(node, "orelse", []) or [])
            yield from _module_level_statements(getattr(node, "finalbody", []) or [])
            for handler in getattr(node, "handlers", []) or []:
                yield from _module_level_statements(handler.body)


def _collect_module_info(tree: ast.Module, path: Path, dotted: str) -> ModuleInfo:
    info = ModuleInfo(path=path, dotted_name=dotted)

    for node in _module_level_statements(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info.functions.add(node.name)
            if isinstance(node, ast.AsyncFunctionDef):
                info.async_functions.add(node.name)
        elif isinstance(node, ast.ClassDef):
            info.classes.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    info.assignments.add(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                info.assignments.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    continue
                info.imported_names.add(alias.asname or alias.name.split(".")[0])

    return info


def _collect_methods(tree: ast.Module) -> Dict[str, Set[str]]:
    """Method names per class defined in this file."""
    methods: Dict[str, Set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        names = {
            item.name
            for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        # Class-level attributes are reachable through instances too.
        for item in node.body:
            if isinstance(item, ast.Assign):
                names.update(
                    t.id for t in item.targets if isinstance(t, ast.Name)
                )
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                names.add(item.target.id)
        methods.setdefault(node.name, set()).update(names)
    return methods


def build_index(
    root: Path, files: Iterable[Path], cache: Optional[dict] = None
) -> ProjectIndex:
    """Walk every file once and record what the project actually defines.

    `cache` receives each parse result so the scanning pass can reuse it.
    Without it every file gets parsed twice, once here and once to be checked.
    """
    index = ProjectIndex(root=root)

    for path in files:
        parsed = parse_file(path)
        if cache is not None:
            cache[path] = parsed
        tree, _source, _error = parsed
        if tree is None:
            continue

        dotted = dotted_name_for(path, root)
        index.modules[dotted] = _collect_module_info(tree, path, dotted)

        for class_name, method_names in _collect_methods(tree).items():
            index.class_methods.setdefault(class_name, set()).update(method_names)
            index.all_method_names.update(method_names)
            for method in method_names:
                index.method_owners.setdefault(method, set()).add(class_name)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    name = (
                        base.attr
                        if isinstance(base, ast.Attribute)
                        else getattr(base, "id", "")
                    )
                    if name:
                        index.subclasses.setdefault(name, set()).add(node.name)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                index.all_async_names.add(node.name)
            elif isinstance(node, ast.FunctionDef):
                index.all_sync_names.add(node.name)

    return index
