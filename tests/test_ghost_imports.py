"""VC001 - imports of packages that do not exist."""

from conftest import codes, describe, lines_for

ONLY = ["VC001"]

# A name chosen so it cannot be on PyPI, in the stdlib, or on this machine.
GHOST = "quibblesnort_frobnicator_9000"


# -- true positives ------------------------------------------------------


def test_plain_import_of_nonexistent_package(scan_code):
    findings = scan_code("import %s\n" % GHOST, only=ONLY)
    assert codes(findings) == ["VC001"], describe(findings)
    assert lines_for(findings, "VC001") == [1]


def test_from_import_of_nonexistent_package(scan_code):
    findings = scan_code("from %s import parse\n" % GHOST, only=ONLY)
    assert codes(findings) == ["VC001"], describe(findings)


def test_dotted_import_of_nonexistent_package(scan_code):
    findings = scan_code("import %s.helpers\n" % GHOST, only=ONLY)
    assert codes(findings) == ["VC001"], describe(findings)


def test_each_ghost_import_is_reported_separately(scan_code):
    source = """
    import os
    import {0}
    import json
    from {0}_other import thing
    """.format(GHOST)
    findings = scan_code(source, only=ONLY)
    assert lines_for(findings, "VC001") == [2, 4], describe(findings)


def test_relative_import_of_missing_sibling_module(scan_code):
    findings = scan_code(
        {
            "pkg/__init__.py": "",
            "pkg/real.py": "VALUE = 1\n",
            "pkg/app.py": "from . import missing_module\n",
        },
        only=ONLY,
    )
    assert codes(findings) == ["VC001"], describe(findings)
    assert findings[0].path.name == "app.py"


def test_relative_import_of_missing_submodule(scan_code):
    findings = scan_code(
        {
            "pkg/__init__.py": "",
            "pkg/app.py": "from .nowhere import helper\n",
        },
        only=ONLY,
    )
    assert codes(findings) == ["VC001"], describe(findings)


# -- true negatives ------------------------------------------------------


def test_stdlib_imports_are_clean(scan_code):
    source = """
    import os
    import sys
    import json
    import asyncio
    from pathlib import Path
    from collections import OrderedDict
    from typing import Optional
    import xml.etree.ElementTree as ET
    """
    assert scan_code(source, only=ONLY) == []


def test_project_module_import_is_clean(scan_code):
    findings = scan_code(
        {
            "helpers.py": "def slugify(text):\n    return text.lower()\n",
            "app.py": "import helpers\n",
        },
        only=ONLY,
    )
    assert findings == [], describe(findings)


def test_from_project_module_import_is_clean(scan_code):
    findings = scan_code(
        {
            "helpers.py": "def slugify(text):\n    return text.lower()\n",
            "app.py": "from helpers import slugify\n",
        },
        only=ONLY,
    )
    assert findings == [], describe(findings)


def test_project_package_import_is_clean(scan_code):
    findings = scan_code(
        {
            "mypkg/__init__.py": "",
            "mypkg/core.py": "VALUE = 1\n",
            "app.py": "from mypkg.core import VALUE\n",
        },
        only=ONLY,
    )
    assert findings == [], describe(findings)


def test_relative_import_that_resolves_is_clean(scan_code):
    findings = scan_code(
        {
            "pkg/__init__.py": "",
            "pkg/real.py": "VALUE = 1\n",
            "pkg/app.py": "from . import real\nfrom .real import VALUE\n",
        },
        only=ONLY,
    )
    assert findings == [], describe(findings)


def test_optional_import_guarded_by_try_except_is_clean(scan_code):
    """Every compatibility shim in Python looks like this."""
    source = """
    try:
        import {0} as fastjson
    except ImportError:
        fastjson = None
    """.format(GHOST)
    findings = scan_code(source, only=ONLY)
    assert findings == [], describe(findings)


def test_optional_import_guarded_by_modulenotfounderror_is_clean(scan_code):
    source = """
    try:
        from {0} import speedups
    except ModuleNotFoundError:
        speedups = None
    """.format(GHOST)
    assert scan_code(source, only=ONLY) == []


def test_import_guarded_by_version_check_is_clean(scan_code):
    source = """
    import sys

    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import {0} as tomllib
    """.format(GHOST)
    findings = scan_code(source, only=ONLY)
    assert findings == [], describe(findings)


def test_import_guarded_by_type_checking_is_clean(scan_code):
    source = """
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from {0} import Client
    """.format(GHOST)
    assert scan_code(source, only=ONLY) == []


def test_star_import_from_real_module_is_clean(scan_code):
    findings = scan_code(
        {
            "helpers.py": "VALUE = 1\n",
            "app.py": "from helpers import *\n",
        },
        only=ONLY,
    )
    assert findings == [], describe(findings)


def test_declared_dependency_that_is_not_installed_is_clean(scan_code):
    """A requirement in requirements.txt is a setup problem, not a ghost."""
    findings = scan_code(
        {
            "requirements.txt": "%s>=1.2.0\nrequests\n" % GHOST,
            "app.py": "import %s\n" % GHOST,
        },
        only=ONLY,
    )
    assert findings == [], describe(findings)


def test_module_sitting_beside_the_scanned_file_is_clean(scan_code):
    findings = scan_code(
        {
            "srv/helpers.py": "VALUE = 1\n",
            "srv/app.py": "import helpers\n",
        },
        only=ONLY,
    )
    assert findings == [], describe(findings)


def test_ghost_import_suggests_a_close_real_name(scan_code):
    findings = scan_code("import jsonn\n", only=ONLY)
    assert codes(findings) == ["VC001"], describe(findings)
    assert "json" in (findings[0].suggestion or "")
