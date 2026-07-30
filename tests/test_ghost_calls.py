"""VC002 - calls to functions that do not exist, VC003 - calls to methods that do not."""

from conftest import codes, describe, lines_for

VC002 = ["VC002"]
VC003 = ["VC003"]


# =======================================================================
# VC002 - ghost function
# =======================================================================


def test_call_to_undefined_function(scan_code):
    source = """
    def handle(payload):
        return sanitise_payload_xyz(payload)
    """
    findings = scan_code(source, only=VC002)
    assert codes(findings) == ["VC002"], describe(findings)
    assert lines_for(findings, "VC002") == [2]
    assert "sanitise_payload_xyz" in findings[0].message


def test_call_to_function_that_exists_but_is_not_imported(scan_code):
    findings = scan_code(
        {
            "helpers.py": "def slugify(text):\n    return text.lower()\n",
            "app.py": "def route(title):\n    return slugify(title)\n",
        },
        only=VC002,
    )
    assert codes(findings) == ["VC002"], describe(findings)
    assert "helpers" in findings[0].message
    assert "from helpers import slugify" in (findings[0].suggestion or "")


def test_several_ghost_calls_are_all_reported(scan_code):
    source = """
    def run():
        a = first_ghost_helper()
        b = second_ghost_helper()
        return a, b
    """
    findings = scan_code(source, only=VC002)
    assert lines_for(findings, "VC002") == [2, 3], describe(findings)


# -- true negatives ------------------------------------------------------


def test_builtins_are_not_ghosts(scan_code):
    source = """
    def summarise(rows):
        total = sum(len(str(row)) for row in rows)
        print(total)
        return sorted(set(map(int, [1, 2])), reverse=bool(total))
    """
    assert scan_code(source, only=VC002) == []


def test_locally_defined_function_is_not_a_ghost(scan_code):
    source = """
    def double(value):
        return value * 2


    def run(value):
        return double(value)
    """
    assert scan_code(source, only=VC002) == []


def test_function_defined_later_in_the_file_is_not_a_ghost(scan_code):
    source = """
    def run(value):
        return double(value)


    def double(value):
        return value * 2
    """
    assert scan_code(source, only=VC002) == []


def test_imported_function_is_not_a_ghost(scan_code):
    source = """
    from json import dumps
    from os.path import join as path_join


    def render(payload, base):
        return path_join(base, dumps(payload))
    """
    assert scan_code(source, only=VC002) == []


def test_star_import_silences_the_check(scan_code):
    """A star import can bind anything, so we must not guess."""
    findings = scan_code(
        {
            "helpers.py": "VALUE = 1\n",
            "app.py": "from helpers import *\n\n\ndef run():\n    return whatever_it_brought_in()\n",
        },
        only=VC002,
    )
    assert findings == [], describe(findings)


def test_locally_assigned_callable_is_not_a_ghost(scan_code):
    source = """
    def run(rows):
        transform = lambda row: row
        return [transform(row) for row in rows]
    """
    assert scan_code(source, only=VC002) == []


def test_function_arguments_are_not_ghosts(scan_code):
    source = """
    def run(callback, *args, factory=None, **kwargs):
        factory()
        return callback(*args, **kwargs)
    """
    assert scan_code(source, only=VC002) == []


def test_class_and_exception_names_are_not_ghosts(scan_code):
    source = """
    class Widget:
        def __init__(self, size):
            self.size = size


    def build():
        try:
            return Widget(3)
        except ValueError as exc:
            return RuntimeError(str(exc))
    """
    assert scan_code(source, only=VC002) == []


def test_conditionally_defined_name_is_not_a_ghost(scan_code):
    source = """
    import os

    if os.name == "nt":
        def platform_root():
            return "C:/"
    else:
        def platform_root():
            return "/"


    def run():
        return platform_root()
    """
    assert scan_code(source, only=VC002) == []


def test_method_calls_are_not_handled_by_vc002(scan_code):
    source = """
    def run(session):
        return session.get_totally_made_up_thing()
    """
    assert scan_code(source, only=VC002) == []


def test_global_and_nested_definitions_are_not_ghosts(scan_code):
    source = """
    def configure():
        global _factory

        def _factory():
            return 1

        return _factory()
    """
    assert scan_code(source, only=VC002) == []


def test_walrus_bound_callable_is_not_a_ghost(scan_code):
    source = """
    def run(registry):
        if (handler := registry.get("x")) is not None:
            return handler()
        return None
    """
    assert scan_code(source, only=VC002) == []


# =======================================================================
# VC003 - ghost method on a project module
# =======================================================================


def test_call_to_missing_attribute_on_project_module(scan_code):
    findings = scan_code(
        {
            "helpers.py": "def slugify(text):\n    return text.lower()\n",
            "app.py": "import helpers\n\n\ndef run(title):\n    return helpers.format_date(title)\n",
        },
        only=VC003,
    )
    assert codes(findings) == ["VC003"], describe(findings)
    assert lines_for(findings, "VC003") == [5]
    assert "format_date" in findings[0].message


def test_ghost_method_suggests_a_close_real_name(scan_code):
    findings = scan_code(
        {
            "helpers.py": "def slugify(text):\n    return text.lower()\n",
            "app.py": "import helpers\n\n\ndef run(title):\n    return helpers.sluggify(title)\n",
        },
        only=VC003,
    )
    assert codes(findings) == ["VC003"], describe(findings)
    assert "slugify" in (findings[0].suggestion or "")


# -- true negatives ------------------------------------------------------


def test_existing_attribute_on_project_module_is_clean(scan_code):
    findings = scan_code(
        {
            "helpers.py": "CONSTANT = 1\n\n\ndef slugify(text):\n    return text.lower()\n",
            "app.py": "import helpers\n\n\ndef run(title):\n    return helpers.slugify(title)\n",
        },
        only=VC003,
    )
    assert findings == [], describe(findings)


def test_reexported_name_on_project_module_is_clean(scan_code):
    findings = scan_code(
        {
            "core.py": "def parse(text):\n    return text\n",
            "helpers.py": "from core import parse\n",
            "app.py": "import helpers\n\n\ndef run(text):\n    return helpers.parse(text)\n",
        },
        only=VC003,
    )
    assert findings == [], describe(findings)


def test_stdlib_module_attributes_are_never_flagged(scan_code):
    source = """
    import os
    import json


    def run(payload):
        os.makedirs("/tmp/x", exist_ok=True)
        return json.dumps(payload)
    """
    assert scan_code(source, only=VC003) == []


def test_third_party_module_attributes_are_never_flagged(scan_code):
    source = """
    import argparse


    def run():
        parser = argparse.ArgumentParser()
        parser.add_argument("--anything-at-all")
        return parser
    """
    assert scan_code(source, only=VC003) == []


def test_deeper_attribute_chains_are_not_judged(scan_code):
    """`helpers.client.send()` - `client` could be anything, so stay quiet."""
    findings = scan_code(
        {
            "helpers.py": "client = object()\n",
            "app.py": "import helpers\n\n\ndef run():\n    return helpers.client.send_now()\n",
        },
        only=VC003,
    )
    assert findings == [], describe(findings)


def test_star_import_silences_ghost_attributes(scan_code):
    findings = scan_code(
        {
            "helpers.py": "def slugify(text):\n    return text\n",
            "other.py": "VALUE = 1\n",
            "app.py": (
                "import helpers\n"
                "from other import *\n"
                "\n"
                "\n"
                "def run(title):\n"
                "    return helpers.format_date(title)\n"
            ),
        },
        only=VC003,
    )
    assert findings == [], describe(findings)


def test_method_name_used_elsewhere_in_project_is_not_a_ghost(scan_code):
    """If something in the project defines `.send()`, we cannot be sure."""
    findings = scan_code(
        {
            "mailer.py": "class Mailer:\n    def send(self, msg):\n        return msg\n",
            "helpers.py": "def slugify(text):\n    return text\n",
            "app.py": "import helpers\n\n\ndef run(msg):\n    return helpers.send(msg)\n",
        },
        only=VC003,
    )
    assert findings == [], describe(findings)
