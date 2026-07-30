"""Placeholder code that was shipped as if it were finished.

Two flavours, both extremely common in AI output:

1. Structural - a function whose body is `pass`, `...`, a lone docstring, or
   `raise NotImplementedError`, with no decorator marking it as abstract.
2. Confessional - a comment where the model quietly admits it did not do the
   work: "in a real implementation...", "for demonstration purposes...".

The second kind is the tell. Humans rarely write those sentences; models write
them constantly, and they sail straight through every existing linter.
"""

from __future__ import annotations

import re
from typing import Iterable, List

from vibelint.checks._ast_utils import (
    annotate_parents,
    enclosing_class,
    is_abstract,
    stub_kind,
)
from vibelint.checks.base import Check
from vibelint.context import FileContext
from vibelint.finding import Finding, Severity

import ast

#: Phrases where a model admits the code is not real. Matched case-insensitively
#: against comments only, never against string literals or prose in docstrings.
CONFESSION_PATTERNS: List[tuple] = [
    (r"\bin a real (implementation|application|app|system|scenario|world)\b",
     "the model is telling you this code is not the real implementation"),
    (r"\bin production,? you('d| would)\b",
     "the model is describing what production code would do, instead of doing it"),
    (r"\b(this is a |for )?(simplified|simplistic|naive|dummy|mock|placeholder|toy) (version|implementation|example)\b",
     "this is a stand-in, not working logic"),
    (r"\bfor (demonstration|illustration|example) purposes\b",
     "this code was written to look right, not to work"),
    (r"\b(replace|substitute) (this |these )?with (your|the) (actual|real|own)\b",
     "an unfilled blank was left for you"),
    (r"\b(add|implement|insert) your (own )?(code|logic|implementation) here\b",
     "an unfilled blank was left for you"),
    (r"\b(actual|real) (implementation|logic) (would |will )?(go|goes|belongs) here\b",
     "an unfilled blank was left for you"),
    (r"\bhandle (this |the )?error(s)? (properly|appropriately) (here|later)\b",
     "error handling was deferred and never written"),
]

# Deliberately absent: bare TODO and FIXME. Humans write those constantly, every
# other linter already reports them, and including them buried the findings that
# are actually specific to generated code.

#: Classes whose empty methods are extension points by convention.
BASE_CLASS_NAME = re.compile(
    r"^(Base|Abstract|_Base|_Abstract)|(Base|ABC|Interface|Mixin|Protocol|Adapter)$"
)

_COMPILED = [(re.compile(pattern, re.IGNORECASE), why) for pattern, why in CONFESSION_PATTERNS]

#: One regex matching any confession phrase, run over the raw source before we
#: bother tokenising. Extracting comments properly costs a full tokenise pass,
#: and on a large codebase that was a fifth of the entire runtime - spent almost
#: entirely on files with nothing to find.
_ANY_CONFESSION = re.compile(
    "|".join(f"(?:{pattern})" for pattern, _ in CONFESSION_PATTERNS),
    re.IGNORECASE,
)

_STUB_MESSAGES = {
    "pass": "{name}() has an empty body but is treated as implemented",
    "ellipsis": "{name}() is a `...` stub but is treated as implemented",
    "docstring": "{name}() has a docstring describing what it does, and no code that does it",
    "not_implemented": "{name}() raises NotImplementedError but is not marked abstract",
}


class PlaceholderCheck(Check):
    code = "VC010"
    label = "PLACEHOLDER"
    description = "Functions that were never actually written"
    severity = Severity.CRITICAL

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        for node in ctx.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            if is_abstract(node):
                continue

            kind = stub_kind(node)
            if kind is None:
                continue

            # A bare `pass` with no docstring in a tiny helper is usually a
            # deliberate no-op (signal handlers, __init__ overrides). Only flag
            # it when the function claims to do something.
            if kind == "pass" and not _claims_to_do_something(node):
                continue

            owner = enclosing_class(node)
            if owner is not None:
                # `def __getitem__(self): raise NotImplementedError` is how you
                # declare a protocol method unsupported. That is a decision,
                # not an unfinished job.
                if node.name.startswith("__") and node.name.endswith("__"):
                    continue
                # Python's informal abstract style: a base class raises
                # NotImplementedError and subclasses fill it in. Extremely
                # common in real code, and not a mistake.
                if ctx.index.is_override_point(node.name, owner.name):
                    continue
                if BASE_CLASS_NAME.search(owner.name):
                    continue

            yield self.finding(
                ctx,
                node,
                _STUB_MESSAGES[kind].format(name=node.name),
                suggestion=(
                    "Implement it, or mark it @abstractmethod so callers know "
                    "it is intentionally unfinished."
                ),
                # A method nobody overrides may still be a public extension
                # point for code we cannot see, so it is worth less certainty
                # than a plain function that simply was never written.
                severity=Severity.WARNING if owner is not None else Severity.CRITICAL,
            )


class ConfessionCheck(Check):
    code = "VC011"
    label = "MODEL CONFESSION"
    description = "Comments where the AI admits the code is not real"
    severity = Severity.CRITICAL

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        # Cheap reject: if no phrase appears anywhere in the file, there is
        # nothing a comment could contain either.
        if not _ANY_CONFESSION.search(ctx.source):
            return

        for lineno, comment in ctx.comments:
            for pattern, why in _COMPILED:
                if pattern.search(comment):
                    yield Finding(
                        path=ctx.path,
                        line=lineno,
                        column=0,
                        code=self.code,
                        label=self.label,
                        message=why,
                        severity=self.severity,
                        suggestion="Write the real implementation, or delete the comment and the code it excuses.",
                        snippet=ctx.line_text(lineno),
                    )
                    break


def _claims_to_do_something(node) -> bool:
    """Whether an empty function presents itself as doing real work."""
    from vibelint.checks._ast_utils import has_docstring

    if has_docstring(node):
        return True
    # A function that takes arguments and returns nothing but `pass` is
    # almost never a deliberate no-op.
    args = node.args
    return bool(args.args or args.posonlyargs or args.kwonlyargs) and not node.name.startswith("__")


