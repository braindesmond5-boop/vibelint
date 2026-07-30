"""vibelint - find the mistakes AI leaves behind in your code.

Point it at a codebase, and it reports back like a test runner: every place
an AI assistant invented an API, left a placeholder, swallowed an error, or
wrote a test that can never fail.

Runs on the standard library alone. No API keys, no network, no AI required
to catch AI's mistakes.
"""

from vibelint.finding import Finding, Severity

__version__ = "0.1.1"
__all__ = ["Finding", "Severity", "__version__"]
