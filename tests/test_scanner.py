"""File discovery, suppression comments, syntax errors and the ScanResult shape."""

from halfbaked.finding import Severity
from halfbaked.indexer import discover_python_files, dotted_name_for
from halfbaked.scanner import scan

from conftest import code_set, codes, describe, lines_for, write_project

BARE_EXCEPT = """
def run():
    try:
        risky()
    except:
        pass
"""


# =======================================================================
# discovery
# =======================================================================


def test_scans_every_python_file_in_the_tree(scan_project):
    result = scan_project(
        {
            "a.py": BARE_EXCEPT,
            "pkg/b.py": BARE_EXCEPT,
            "pkg/sub/c.py": BARE_EXCEPT,
        },
        only=["VC030"],
    )
    assert result.files_scanned == 3
    assert {f.path.name for f in result.findings} == {"a.py", "b.py", "c.py"}


def test_non_python_files_are_ignored(scan_project):
    result = scan_project(
        {
            "a.py": BARE_EXCEPT,
            "notes.txt": "except: pass\n",
            "README.md": "```python\nexcept: pass\n```\n",
        },
        only=["VC030"],
    )
    assert result.files_scanned == 1


def test_vendor_and_cache_directories_are_skipped(scan_project):
    result = scan_project(
        {
            "src_app/real.py": BARE_EXCEPT,
            ".venv/lib/vendored.py": BARE_EXCEPT,
            "venv/lib/vendored.py": BARE_EXCEPT,
            "node_modules/pkg/thing.py": BARE_EXCEPT,
            "__pycache__/cached.py": BARE_EXCEPT,
            ".mypy_cache/x.py": BARE_EXCEPT,
            ".pytest_cache/y.py": BARE_EXCEPT,
            "build/generated.py": BARE_EXCEPT,
            "dist/generated.py": BARE_EXCEPT,
            ".git/hook.py": BARE_EXCEPT,
            "myapp.egg-info/meta.py": BARE_EXCEPT,
        },
        only=["VC030"],
    )
    assert result.files_scanned == 1
    assert [f.path.name for f in result.findings] == ["real.py"]


def test_discover_python_files_is_deterministic(tmp_path):
    write_project(
        tmp_path,
        {"b.py": "", "a.py": "", "pkg/z.py": "", "pkg/a.py": ""},
    )
    found = discover_python_files(tmp_path)
    assert found == sorted(found)


def test_scanning_a_single_file(scan_project):
    result = scan_project(
        {"a.py": BARE_EXCEPT, "b.py": BARE_EXCEPT},
        only=["VC030"],
        target="a.py",
    )
    assert result.files_scanned == 1
    assert [f.path.name for f in result.findings] == ["a.py"]


def test_scanning_a_subdirectory(scan_project):
    result = scan_project(
        {"a.py": BARE_EXCEPT, "pkg/b.py": BARE_EXCEPT},
        only=["VC030"],
        target="pkg",
    )
    assert result.files_scanned == 1
    assert [f.path.name for f in result.findings] == ["b.py"]


def test_skip_tests_excludes_test_files(scan_project):
    files = {
        "app.py": BARE_EXCEPT,
        "test_app.py": BARE_EXCEPT,
        "app_test.py": BARE_EXCEPT,
        "tests/test_deep.py": BARE_EXCEPT,
    }
    with_tests = scan_project(files, only=["VC030"], include_tests=True)
    assert with_tests.files_scanned == 4

    without_tests = scan_project(files, only=["VC030"], include_tests=False)
    assert without_tests.files_scanned == 1
    assert [f.path.name for f in without_tests.findings] == ["app.py"]


def test_dotted_name_collapses_init_and_strips_src(tmp_path):
    assert dotted_name_for(tmp_path / "pkg" / "__init__.py", tmp_path) == "pkg"
    assert dotted_name_for(tmp_path / "pkg" / "mod.py", tmp_path) == "pkg.mod"
    assert dotted_name_for(tmp_path / "src" / "pkg" / "mod.py", tmp_path) == "pkg.mod"


# =======================================================================
# suppression
# =======================================================================


def test_bare_noqa_suppresses_everything_on_the_line(scan_project):
    source = """
    def run():
        try:
            risky()
        except:  # noqa
            pass
    """
    result = scan_project(source, only=["VC030"])
    assert result.findings == []
    assert result.suppressed == 1


def test_halfbaked_ignore_suppresses_everything_on_the_line(scan_project):
    source = """
    def run():
        try:
            risky()
        except:  # halfbaked: ignore
            pass
    """
    result = scan_project(source, only=["VC030"])
    assert result.findings == []
    assert result.suppressed == 1


def test_former_vibelint_comment_still_suppresses(scan_project):
    """The tool was called vibelint before. Old suppressions must keep working.

    Suppression comments live in other people's source files. Quietly ceasing
    to honour one would resurrect a finding the author had already reviewed and
    decided to accept, which is the worst way for a rename to reach a user.
    """
    source = """
    def run():
        try:
            risky()
        except:  # vibelint: ignore
            pass
    """
    result = scan_project(source, only=["VC030"])
    assert result.findings == []
    assert result.suppressed == 1


def test_former_vibelint_comment_with_a_code_still_suppresses(scan_project):
    source = """
    def run():
        try:
            risky()
        except:  # vibelint: VC030
            pass
    """
    result = scan_project(source, only=["VC030"])
    assert result.findings == []
    assert result.suppressed == 1


def test_code_specific_noqa_suppresses_that_code(scan_project):
    source = """
    def run():
        try:
            risky()
        except:  # noqa: VC030
            pass
    """
    result = scan_project(source, only=["VC030"])
    assert result.findings == []
    assert result.suppressed == 1


def test_code_specific_halfbaked_comment_suppresses_that_code(scan_project):
    source = """
    def run():
        try:
            risky()
        except:  # halfbaked: VC030
            pass
    """
    result = scan_project(source, only=["VC030"])
    assert result.findings == []


def test_noqa_is_case_insensitive_about_codes(scan_project):
    source = """
    def run():
        try:
            risky()
        except:  # noqa: vc030
            pass
    """
    result = scan_project(source, only=["VC030"])
    assert result.findings == []


def test_noqa_for_a_different_code_does_not_suppress(scan_project):
    source = """
    def run():
        try:
            return compute()
        finally:
            return 0  # noqa: VC030
    """
    result = scan_project(source, only=["VC031"])
    assert codes(result.findings) == ["VC031"], describe(result.findings)
    assert result.suppressed == 0


def test_noqa_with_a_list_of_codes(scan_project):
    source = """
    def run():
        try:
            return compute()
        finally:
            return 0  # noqa: VC030, VC031
    """
    result = scan_project(source, only=["VC031"])
    assert result.findings == []


def test_suppression_only_applies_to_its_own_line(scan_project):
    source = """
    def run():
        try:
            risky()
        except:
            pass
        try:
            risky()
        except:  # noqa
            pass
    """
    result = scan_project(source, only=["VC030"])
    assert lines_for(result.findings, "VC030") == [4], describe(result.findings)
    assert result.suppressed == 1


def test_ordinary_comment_does_not_suppress(scan_project):
    source = """
    def run():
        try:
            risky()
        except:  # this is fine, honestly
            pass
    """
    result = scan_project(source, only=["VC030"])
    assert codes(result.findings) == ["VC030"], describe(result.findings)


# =======================================================================
# broken and empty files
# =======================================================================


def test_syntax_error_is_reported_as_vc000(scan_project):
    result = scan_project({"broken.py": "def run(:\n    pass\n"})
    assert codes(result.findings) == ["VC000"], describe(result.findings)
    assert result.findings[0].severity is Severity.CRITICAL
    # A file that fails to parse was still read and still produced a finding,
    # so it counts as scanned. Counting it as skipped made the summary claim
    # "1 flop - 1 of 0 files affected". `files_skipped` means unreadable.
    assert result.files_skipped == 0
    assert result.files_scanned == 1
    assert result.affected_files <= result.files_scanned


def test_a_broken_file_does_not_stop_the_rest_of_the_scan(scan_project):
    result = scan_project(
        {"broken.py": "def run(:\n    pass\n", "good.py": BARE_EXCEPT},
        only=None,
    )
    assert code_set(result.findings) >= {"VC000", "VC030"}
    # Both files were read: the broken one reported VC000, the good one was
    # checked normally. Neither was skipped - skipped means unreadable.
    assert result.files_scanned == 2
    assert result.files_skipped == 0


def test_empty_file_produces_no_findings(scan_project):
    result = scan_project({"empty.py": ""})
    assert result.findings == []
    assert result.files_scanned == 1
    assert result.files_skipped == 0


def test_whitespace_and_comment_only_file_is_clean(scan_project):
    result = scan_project({"header.py": "# module header\n\n\n"})
    assert result.findings == []
    assert result.files_scanned == 1


def test_docstring_only_module_is_clean(scan_project):
    result = scan_project({"pkg/__init__.py": '"""The package."""\n'})
    assert result.findings == []


# =======================================================================
# ScanResult
# =======================================================================


def test_result_root_is_the_scanned_directory(scan_project, project_root):
    result = scan_project({"a.py": "VALUE = 1\n"})
    assert result.root == project_root.resolve()


def test_result_root_for_a_single_file_is_its_parent(scan_project, project_root):
    result = scan_project({"pkg/a.py": "VALUE = 1\n"}, target="pkg/a.py")
    assert result.root == (project_root / "pkg").resolve()


def test_counts_cover_every_severity(scan_project):
    result = scan_project({"a.py": BARE_EXCEPT}, only=["VC030"])
    assert set(result.counts) == set(Severity)
    assert result.counts[Severity.CRITICAL] == 1


def test_worst_severity_is_none_when_clean(scan_project):
    result = scan_project({"a.py": "VALUE = 1\n"})
    assert result.worst_severity() is None


def test_worst_severity_picks_the_most_serious(scan_project):
    source = """
    URL = "https://api.example.com"


    def run():
        try:
            risky()
        except:
            pass
    """
    result = scan_project(source, only=["VC021", "VC030"])
    assert result.worst_severity() is Severity.CRITICAL


def test_sorted_findings_orders_by_severity_then_location(scan_project):
    source = """
    URL = "https://api.example.com"


    def run():
        try:
            risky()
        except:
            pass
    """
    result = scan_project(source, only=["VC021", "VC030"])
    ordered = result.sorted_findings()
    assert [f.code for f in ordered] == ["VC030", "VC021"]


def test_affected_files_counts_distinct_paths(scan_project):
    result = scan_project(
        {"a.py": BARE_EXCEPT, "b.py": BARE_EXCEPT, "c.py": "VALUE = 1\n"},
        only=["VC030"],
    )
    assert result.affected_files == 2
    assert result.files_scanned == 3


def test_findings_carry_snippet_and_suggestion(scan_project):
    result = scan_project({"a.py": BARE_EXCEPT}, only=["VC030"])
    finding = result.findings[0]
    assert finding.snippet == "except:"
    assert finding.suggestion
    assert finding.path.is_absolute()


def test_duration_is_recorded(scan_project):
    result = scan_project({"a.py": "VALUE = 1\n"})
    assert result.duration >= 0.0


def test_scanning_an_empty_directory_is_clean(tmp_path):
    result = scan(tmp_path)
    assert result.findings == []
    assert result.files_scanned == 0


def test_default_check_selection_is_used_when_none_given(scan_project):
    """`scan(path)` with no checks runs the whole catalogue."""
    result = scan_project({"a.py": BARE_EXCEPT}, only=None)
    assert "VC030" in code_set(result.findings)
