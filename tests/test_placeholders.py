"""VC010 - functions that were never written, VC011 - comments where the model confesses."""

import pytest

from conftest import codes, describe, lines_for, messages

VC010 = ["VC010"]
VC011 = ["VC011"]


# =======================================================================
# VC010 - placeholder implementations
# =======================================================================


def test_documented_function_with_empty_body(scan_code):
    source = """
    def charge_customer(customer, amount):
        \"\"\"Charge the customer the given amount.\"\"\"
        pass
    """
    findings = scan_code(source, only=VC010)
    assert codes(findings) == ["VC010"], describe(findings)
    assert lines_for(findings, "VC010") == [1]


def test_ellipsis_stub(scan_code):
    source = """
    def transform(record):
        ...
    """
    findings = scan_code(source, only=VC010)
    assert codes(findings) == ["VC010"], describe(findings)


def test_docstring_only_body(scan_code):
    source = """
    def compute_tax(order):
        \"\"\"Return the tax owed on an order.\"\"\"
    """
    findings = scan_code(source, only=VC010)
    assert codes(findings) == ["VC010"], describe(findings)
    assert "docstring" in findings[0].message


def test_not_implemented_error_outside_any_class(scan_code):
    source = """
    def export_report(rows):
        raise NotImplementedError
    """
    findings = scan_code(source, only=VC010)
    assert codes(findings) == ["VC010"], describe(findings)


def test_empty_body_with_arguments(scan_code):
    source = """
    def send_email(to, subject, body):
        pass
    """
    findings = scan_code(source, only=VC010)
    assert codes(findings) == ["VC010"], describe(findings)


def test_async_stub_is_flagged(scan_code):
    source = """
    async def fetch_orders(customer_id):
        \"\"\"Fetch every order for a customer.\"\"\"
        ...
    """
    findings = scan_code(source, only=VC010)
    assert codes(findings) == ["VC010"], describe(findings)


def test_each_stub_reported_once(scan_code):
    source = """
    def first(a):
        \"\"\"Do the first thing.\"\"\"
        pass


    def second(a):
        ...


    def third(a):
        return a
    """
    findings = scan_code(source, only=VC010)
    assert lines_for(findings, "VC010") == [1, 6], describe(findings)


# -- true negatives ------------------------------------------------------


def test_real_implementation_is_clean(scan_code):
    source = """
    def compute_total(items):
        \"\"\"Return the total price of every item.\"\"\"
        total = 0
        for item in items:
            total += item.price
        return total
    """
    assert scan_code(source, only=VC010) == []


def test_abstractmethod_is_not_a_placeholder(scan_code):
    source = """
    from abc import ABC, abstractmethod


    class Repository(ABC):
        @abstractmethod
        def get(self, key):
            \"\"\"Return the stored value.\"\"\"
            raise NotImplementedError

        @abstractmethod
        def put(self, key, value):
            ...
    """
    findings = scan_code(source, only=VC010)
    assert findings == [], describe(findings)


def test_abc_subclass_methods_are_not_placeholders(scan_code):
    source = """
    from abc import ABC


    class Storage(ABC):
        def read(self, key):
            raise NotImplementedError

        def write(self, key, value):
            raise NotImplementedError
    """
    findings = scan_code(source, only=VC010)
    assert findings == [], describe(findings)


def test_abcmeta_metaclass_is_not_a_placeholder(scan_code):
    source = """
    import abc


    class Storage(metaclass=abc.ABCMeta):
        def read(self, key):
            raise NotImplementedError
    """
    findings = scan_code(source, only=VC010)
    assert findings == [], describe(findings)


def test_protocol_methods_are_not_placeholders(scan_code):
    source = """
    from typing import Protocol


    class Serialiser(Protocol):
        def dump(self, value):
            ...

        def load(self, raw):
            raise NotImplementedError
    """
    findings = scan_code(source, only=VC010)
    assert findings == [], describe(findings)


def test_generic_protocol_methods_are_not_placeholders(scan_code):
    """`class Store(Protocol[T])` is still a Protocol, subscript and all."""
    source = """
    from typing import Protocol, TypeVar

    T = TypeVar("T")


    class Store(Protocol[T]):
        def get(self, key: str) -> T:
            ...

        def put(self, key: str, value: T) -> None:
            raise NotImplementedError
    """
    findings = scan_code(source, only=VC010)
    assert findings == [], describe(findings)


def test_generic_abc_methods_are_not_placeholders(scan_code):
    """`class Store(ABC, Generic[T])` - the ABC base is still right there."""
    source = """
    from abc import ABC, abstractmethod
    from typing import Generic, TypeVar

    T = TypeVar("T")


    class Store(ABC, Generic[T]):
        @abstractmethod
        def get(self, key: str) -> T:
            raise NotImplementedError
    """
    findings = scan_code(source, only=VC010)
    assert findings == [], describe(findings)


def test_typing_overload_stubs_are_not_placeholders(scan_code):
    source = """
    from typing import overload


    @overload
    def parse(value: int) -> int:
        ...


    @overload
    def parse(value: str) -> str:
        ...


    def parse(value):
        return value
    """
    findings = scan_code(source, only=VC010)
    assert findings == [], describe(findings)


def test_deliberate_no_op_is_not_a_placeholder(scan_code):
    source = """
    def noop():
        pass
    """
    assert scan_code(source, only=VC010) == []


def test_dunder_override_with_pass_is_not_a_placeholder(scan_code):
    source = """
    class Silent:
        def __init__(self, stream):
            pass
    """
    assert scan_code(source, only=VC010) == []


def test_empty_exception_class_is_not_a_placeholder(scan_code):
    source = """
    class ConfigError(Exception):
        pass


    class MissingKey(ConfigError):
        \"\"\"Raised when a key is absent.\"\"\"
    """
    assert scan_code(source, only=VC010) == []


def test_body_that_only_looks_short_is_clean(scan_code):
    source = """
    def identity(value):
        \"\"\"Return the value unchanged.\"\"\"
        return value
    """
    assert scan_code(source, only=VC010) == []


def test_abstract_base_class_without_abc_is_not_a_placeholder(scan_code):
    """The oldest interface idiom in Python: a plain base that refuses to run.

    `raise NotImplementedError` in a class that exists to be subclassed is a
    deliberate contract, not an unfinished function.
    """
    source = """
    class BaseHandler:
        \"\"\"Subclasses must implement handle().\"\"\"

        def handle(self, event):
            raise NotImplementedError("subclasses must implement handle()")
    """
    findings = scan_code(source, only=VC010)
    assert findings == [], describe(findings)


# =======================================================================
# VC011 - model confessions in comments
# =======================================================================


@pytest.mark.parametrize(
    "comment",
    [
        "# In a real implementation, this would call the payment gateway",
        "# In a real application you would persist this",
        "# In production, you'd use a proper database here",
        "# This is a simplified version of the algorithm",
        "# Using a mock implementation for now",
        "# For demonstration purposes only",
        "# Replace this with your actual API key",
        "# Add your own logic here",
        "# Actual implementation would go here",
        "# Handle this error properly later",
    ],
)
def test_confession_comments_are_flagged(scan_code, comment):
    source = "def run(value):\n    %s\n    return value\n" % comment
    findings = scan_code(source, only=VC011)
    assert codes(findings) == ["VC011"], describe(findings)
    assert lines_for(findings, "VC011") == [2]


def test_confession_reports_the_comment_line_not_the_function(scan_code):
    source = """
    def run(value):
        total = value * 2
        # In a real implementation, this would be rounded properly
        return total
    """
    findings = scan_code(source, only=VC011)
    assert lines_for(findings, "VC011") == [3], describe(findings)


def test_one_finding_per_confession_line(scan_code):
    source = """
    # In a real implementation this would be cached
    VALUE = 1
    # For demonstration purposes only
    OTHER = 2
    """
    findings = scan_code(source, only=VC011)
    assert lines_for(findings, "VC011") == [1, 3], describe(findings)


def test_a_line_is_reported_once_even_if_two_patterns_match(scan_code):
    source = """
    # In a real implementation, replace this with your actual client
    VALUE = 1
    """
    findings = scan_code(source, only=VC011)
    assert codes(findings) == ["VC011"], describe(findings)


# -- true negatives ------------------------------------------------------


def test_ordinary_comments_are_clean(scan_code):
    source = """
    # Compute the running checksum for each chunk.
    # The buffer is deliberately reused to avoid churn.
    def checksum(chunks):
        total = 0
        for chunk in chunks:  # cheap, no allocation
            total ^= hash(chunk)
        return total
    """
    findings = scan_code(source, only=VC011)
    assert findings == [], describe(findings)


def test_todo_and_fixme_are_deliberately_not_confessions(scan_code):
    """Humans write these constantly and every other linter reports them.

    See the note beside `CONFESSION_PATTERNS`: they are excluded on purpose so
    the findings that are specific to generated code are not buried.
    """
    source = """
    # TODO: implement retry handling
    # TODO(alice): revisit once the migration lands
    # FIXME: this drops the last row
    VALUE = 1
    """
    findings = scan_code(source, only=VC011)
    assert findings == [], describe(findings)


def test_prose_in_a_docstring_is_not_a_confession(scan_code):
    source = '''
    def parse(text):
        """Parse the text.

        In a real application you would validate the encoding first, but
        callers already do that for us.
        """
        return text.strip()
    '''
    findings = scan_code(source, only=VC011)
    assert findings == [], describe(findings)


def test_string_literal_is_not_a_confession(scan_code):
    source = """
    MESSAGE = "in a real implementation this would be translated"
    """
    findings = scan_code(source, only=VC011)
    assert findings == [], describe(findings)


def test_url_fragment_is_not_a_confession(scan_code):
    """A `#` inside a string is a URL fragment, not a comment."""
    source = """
    DOCS = "https://docs.internal.corp/runbook#fixme-section"
    """
    findings = scan_code(source, only=VC011)
    assert findings == [], describe(findings)


def test_word_fixme_inside_an_identifier_is_not_a_confession(scan_code):
    source = """
    # the fixmethod helper normalises legacy rows
    def fixmethod(row):
        return row
    """
    findings = scan_code(source, only=VC011)
    assert findings == [], describe(findings)
