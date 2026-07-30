"""Placeholder values wired into real code paths.

When a model does not know your API key, your domain, or your database name, it
invents one that looks plausible and moves on. The code runs, the shape is
right, and it fails only when it reaches something real.

Skipped in test files, where fake values are the entire point.
"""

from __future__ import annotations

import ast
import re
from typing import Iterable, List, Optional, Tuple  # noqa: F401

from vibelint.checks._ast_utils import call_name, dotted_path, parent_of
from vibelint.checks.base import Check
from vibelint.context import FileContext
from vibelint.finding import Finding, Severity

#: Names that indicate a value is meant to be a real credential or endpoint.
SENSITIVE_NAME = re.compile(
    r"(api[_-]?key|apikey|secret|token|password|passwd|pwd|access[_-]?key"
    r"|private[_-]?key|client[_-]?secret|credential|auth[_-]?key|bearer)",
    re.IGNORECASE,
)

#: Values that are obviously stand-ins rather than real settings.
#:
#: The third element is the strength. A STRONG placeholder is one nobody types
#: on purpose - "changeme", "<your-key>", "{{ token }}" - and is worth reporting
#: wherever it appears. A WEAK one is an ordinary English word that merely often
#: shows up as a placeholder, so it is only meaningful next to a credential:
#: `os.getenv("BUILD_ID", "n/a")` is a perfectly good display default.
STRONG, WEAK = True, False

PLACEHOLDER_VALUE = [
    (re.compile(r"^your[-_ ]", re.I), "starts with 'your-'", STRONG),
    (re.compile(r"[-_ ]here$", re.I), "ends with '-here'", STRONG),
    (re.compile(r"^<.*>$"), "is an unfilled angle-bracket placeholder", STRONG),
    (re.compile(r"^\{\{.*\}\}$"), "is an unfilled template placeholder", STRONG),
    (re.compile(r"^(x{3,}|y{3,}|z{3,})$", re.I), "is a row of filler characters", STRONG),
    (re.compile(r"^(change[-_ ]?me|replace[-_ ]?me|fill[-_ ]?me[-_ ]?in)", re.I), "says to replace it", STRONG),
    (re.compile(r"^(insert|enter|add|paste)[-_ ]", re.I), "instructs you to fill it in", STRONG),
    (re.compile(r"^(abc123|test123|123456+|password\d*|secret\d*|foobar)$", re.I), "is a stock dummy value", STRONG),
    (re.compile(r"^sk-(xxx|your|abc|123|test|placeholder)", re.I), "is a fake API key shaped like a real one", STRONG),
    (re.compile(r"^(sk|pk)-[a-z]{0,4}\d{0,4}$", re.I), "is too short to be a real key", STRONG),
    (re.compile(r"^(placeholder|dummy|fake|sample|example|todo|tbd|n/?a|unknown)$", re.I), "is a placeholder word", WEAK),
]

#: Domains that are documentation examples, never real infrastructure.
PLACEHOLDER_HOST = re.compile(
    r"https?://(?:[\w.-]+\.)?(example\.(com|org|net)|your[-_]?(domain|site|company|app|api)"
    r"|mysite\.|mycompany\.|foo\.bar|test\.test|api\.example)",
    re.IGNORECASE,
)

#: Functions whose default argument is a live fallback, not a test fixture.
ENV_LOOKUPS = {"getenv", "get"}


class FakeSecretCheck(Check):
    code = "VC020"
    label = "FAKE VALUE"
    description = "Placeholder credentials left in real code"
    severity = Severity.CRITICAL
    runs_on_tests = False

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        for name, value, node in _named_string_values(ctx.all_nodes):
            if not SENSITIVE_NAME.search(name):
                continue
            # `PASSWORD_FIELD = "password"` and `{"token": "token"}` are schema
            # constants naming a field, not credentials someone forgot to fill
            # in. Telling the user to read those from the environment is absurd.
            if _describes_itself(name, value):
                continue
            reason = _placeholder_reason(value)
            if reason is None:
                continue
            yield self.finding(
                ctx,
                node,
                f"`{name}` is set to a value that {reason}, so anything using it will fail against a real service",
                suggestion=f"Read it from the environment: `os.environ[\"{name.upper()}\"]`.",
            )


class FakeEndpointCheck(Check):
    code = "VC021"
    label = "FAKE ENDPOINT"
    description = "Example domains used as real endpoints"
    severity = Severity.WARNING
    runs_on_tests = False

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        for node in ctx.nodes(ast.Constant):
            if not isinstance(node.value, str):
                continue
            # A bare string statement is a docstring or a comment-in-prose.
            # Mentioning example.com in documentation is not a configuration bug.
            if isinstance(parent_of(node), ast.Expr):
                continue
            match = PLACEHOLDER_HOST.search(node.value)
            if match is None:
                continue
            yield self.finding(
                ctx,
                node,
                f"`{_truncate(node.value)}` points at a documentation placeholder domain, not a real service",
                suggestion="Point this at your actual endpoint, or move it into configuration.",
            )


class EnvFallbackCheck(Check):
    code = "VC022"
    label = "FAKE FALLBACK"
    description = "Environment lookups that fall back to a placeholder"
    severity = Severity.CRITICAL
    runs_on_tests = False

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        for node in ctx.nodes(ast.Call):
            if (call_name(node) or "") not in ENV_LOOKUPS:
                continue
            if not _is_environment_lookup(node):
                continue
            if len(node.args) < 2:
                continue

            key, default = node.args[0], node.args[1]
            if not isinstance(default, ast.Constant) or not isinstance(default.value, str):
                continue

            key_name = str(key.value) if isinstance(key, ast.Constant) else ""

            match = _placeholder_match(default.value)
            if match is None:
                continue
            reason, strong = match

            # A weak placeholder like "n/a" or "unknown" is a normal display
            # default. Only next to a credential name does it mean the config
            # was never filled in.
            if not strong and not (key_name and SENSITIVE_NAME.search(key_name)):
                continue
            if not key_name:
                key_name = "this variable"

            yield self.finding(
                ctx,
                node,
                f"if `{key_name}` is unset, this silently falls back to a value that {reason}",
                suggestion=(
                    f"Fail loudly instead: `os.environ[\"{key_name}\"]` raises if it is missing, "
                    "which is what you want for required configuration."
                ),
            )


# -- helpers -------------------------------------------------------------


def _named_string_values(all_nodes) -> List[Tuple[str, str, ast.AST]]:
    """Every (name, string value, node) pair the file assigns, in any form."""
    found: List[Tuple[str, str, ast.AST]] = []

    def record(name: Optional[str], value_node: ast.AST, anchor: ast.AST) -> None:
        if not name or not isinstance(value_node, ast.Constant):
            return
        if isinstance(value_node.value, str) and value_node.value:
            found.append((name, value_node.value, anchor))

    for node in all_nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    record(target.id, node.value, node)
                elif isinstance(target, ast.Attribute):
                    record(target.attr, node.value, node)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name):
                record(node.target.id, node.value, node)
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg:
                    record(keyword.arg, keyword.value, keyword.value)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    record(key.value, value, value)

    return found


def _placeholder_reason(value: str) -> Optional[str]:
    match = _placeholder_match(value)
    return match[0] if match else None


def _placeholder_match(value: str) -> Optional[Tuple[str, bool]]:
    """(reason, is_strong) for a placeholder-looking value, or None."""
    text = value.strip()
    if not text:
        return None
    for pattern, reason, strong in PLACEHOLDER_VALUE:
        if pattern.search(text):
            return reason, strong
    return None


def _is_environment_lookup(node: ast.Call) -> bool:
    """True for os.getenv(...) and os.environ.get(...)."""
    path = dotted_path(node.func) if isinstance(node.func, ast.Attribute) else None
    if path is None:
        return False
    return path in {"os.getenv", "os.environ.get", "environ.get"} or path.endswith(
        ("os.getenv", "os.environ.get")
    )


def _describes_itself(name: str, value: str) -> bool:
    """Whether a value is just naming its own field rather than holding a secret.

    `PASSWORD_FIELD = "password"` is a schema constant. `CLIENT_SECRET =
    "{{ client_secret }}"` is an unfilled template that happens to contain its
    own name, so template and bracket syntax disqualifies a value outright.
    """
    if re.search(r"[<>{}$%]", value):
        return False
    flat_name = re.sub(r"[^a-z0-9]", "", name.lower())
    flat_value = re.sub(r"[^a-z0-9]", "", value.lower())
    if not flat_value:
        return False
    return flat_value == flat_name or flat_value in flat_name


def _truncate(value: str, limit: int = 48) -> str:
    # Collapse whitespace first: a newline inside a reported value breaks the
    # alignment of every line of the report after it.
    flat = " ".join(value.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
