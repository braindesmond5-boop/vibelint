"""Async code that silently does nothing.

Forgetting `await` is the quietest bug in Python. The call returns a coroutine
object, the object is discarded, no error is raised, and the work simply never
happens. Models get this wrong constantly because the sync and async versions
of a function look identical at the call site.
"""

from __future__ import annotations

import ast
from typing import Iterable, Optional, Set

from halfbaked.checks._ast_utils import (
    annotate_parents,
    call_name,
    dotted_path,
    enclosing_function,
    imported_project_modules,
    parent_of,
    walk_own_scope,
)
from halfbaked.checks.base import Check
from halfbaked.context import FileContext
from halfbaked.finding import Finding, Severity

#: Functions that legitimately accept a bare coroutine without awaiting it.
COROUTINE_CONSUMERS = {
    "gather",
    "create_task",
    "ensure_future",
    "run",
    "wait",
    "wait_for",
    "as_completed",
    "shield",
    "run_coroutine_threadsafe",
    "to_thread",
    "TaskGroup",
}

#: Blocking calls that stall the entire event loop when used inside `async def`.
BLOCKING_CALLS = {
    "time.sleep": ("time.sleep", "asyncio.sleep"),
    "requests.get": ("requests", "an async client such as httpx.AsyncClient"),
    "requests.post": ("requests", "an async client such as httpx.AsyncClient"),
    "requests.put": ("requests", "an async client such as httpx.AsyncClient"),
    "requests.delete": ("requests", "an async client such as httpx.AsyncClient"),
    "requests.patch": ("requests", "an async client such as httpx.AsyncClient"),
    "requests.request": ("requests", "an async client such as httpx.AsyncClient"),
    "subprocess.run": ("subprocess.run", "asyncio.create_subprocess_exec"),
    "subprocess.call": ("subprocess.call", "asyncio.create_subprocess_exec"),
    "subprocess.check_output": ("subprocess.check_output", "asyncio.create_subprocess_exec"),
    "os.system": ("os.system", "asyncio.create_subprocess_shell"),
    "urllib.request.urlopen": ("urllib.request.urlopen", "an async HTTP client"),
}


class LostAwaitCheck(Check):
    code = "VC050"
    label = "LOST AWAIT"
    description = "Async functions called without await, so they never run"
    severity = Severity.CRITICAL

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        index = ctx.index
        project_modules = imported_project_modules(ctx)

        for node in ctx.nodes(ast.Call):
            name = _resolved_async_name(node, index, project_modules)
            if name is None:
                continue

            parent = parent_of(node)

            if isinstance(parent, ast.Await):
                continue
            if _is_consumed_by_asyncio(node):
                continue

            # Result thrown away entirely: unambiguously a bug.
            if isinstance(parent, ast.Expr):
                yield self.finding(
                    ctx,
                    node,
                    f"{name}() is async, but it is called without `await`, so its body never runs",
                    suggestion=f"Write `await {name}(...)`.",
                )
                continue

            # Result stored, but the variable is never awaited anywhere after.
            if isinstance(parent, ast.Assign):
                targets = [t.id for t in parent.targets if isinstance(t, ast.Name)]
                owner = enclosing_function(node)
                if targets and owner is not None and not _awaits_any(owner, set(targets)):
                    yield self.finding(
                        ctx,
                        node,
                        f"{name}() is async; `{targets[0]}` holds a coroutine that is never awaited",
                        suggestion=f"Write `{targets[0]} = await {name}(...)`.",
                    )


class BlockingInAsyncCheck(Check):
    code = "VC051"
    label = "BLOCKING ASYNC"
    description = "Blocking calls inside async functions, which freeze the event loop"
    severity = Severity.WARNING

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        for node in ctx.nodes(ast.AsyncFunctionDef):
            # walk_own_scope stops at nested functions, so a plain sync helper
            # defined inside a coroutine never has its calls blamed on the
            # coroutine that encloses it.
            for child in walk_own_scope(node):
                if not isinstance(child, ast.Call):
                    continue

                path = dotted_path(child.func) if isinstance(child.func, ast.Attribute) else None
                if path is None:
                    continue

                match = BLOCKING_CALLS.get(path)
                if match is None:
                    continue

                blocking, replacement = match
                yield self.finding(
                    ctx,
                    child,
                    f"`{path}()` blocks the event loop inside async `{node.name}()`, freezing every other task",
                    suggestion=f"Use {replacement} instead of {blocking}.",
                )


# -- helpers -------------------------------------------------------------


def _resolved_async_name(node: ast.Call, index, project_modules) -> Optional[str]:
    """The name of the async function being called, if we can actually prove it.

    Two shapes are safe to judge:

      `work()`            - a bare name, matched against the project's async defs
      `services.work()`   - an attribute on a module we know belongs to this
                            project, matched against that module's async defs

    Everything else is refused. Matching `a.b()` by the bare name `b` against a
    project-wide set means one `async def run` anywhere turns every
    `subprocess.run()` and `asyncio.run()` in the codebase into a critical
    finding - and `run`, `get`, `close`, `send` and `read` are the most common
    method names in Python.
    """
    func = node.func

    if isinstance(func, ast.Name):
        name = func.id
        # A name that is `def` somewhere and `async def` elsewhere is ambiguous.
        if name in index.all_async_names and name not in index.all_sync_names:
            return name
        return None

    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        module = project_modules.get(func.value.id)
        if module is not None and func.attr in module.async_functions:
            return func.attr
        return None

    return None


def _is_consumed_by_asyncio(node: ast.Call) -> bool:
    """True if the coroutine is handed to something that will run it.

    Covers `asyncio.gather(fetch(), fetch())`, `asyncio.create_task(work())`,
    and bare `gather(...)` when imported directly.
    """
    current = parent_of(node)
    depth = 0
    while current is not None and depth < 4:
        if isinstance(current, ast.Call):
            if (call_name(current) or "") in COROUTINE_CONSUMERS:
                return True
        # Walk out through the containers asyncio helpers accept.
        if not isinstance(current, (ast.Call, ast.List, ast.Tuple, ast.Set, ast.Starred)):
            return False
        current = parent_of(current)
        depth += 1
    return False


def _awaits_any(func: ast.AST, names: Set[str]) -> bool:
    """Whether any of `names` is awaited somewhere in this function."""
    for node in ast.walk(func):
        if not isinstance(node, ast.Await):
            continue
        for child in ast.walk(node.value):
            if isinstance(child, ast.Name) and child.id in names:
                return True
    return False
