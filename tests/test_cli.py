"""Exit codes, filtering flags and output formats."""

import io
import json

import pytest

from halfbaked.checks import CHECK_CLASSES, check_catalog, select_checks
from halfbaked.cli import EXIT_CLEAN, EXIT_FLOPS_FOUND, EXIT_USAGE_ERROR, main, print_catalog

from conftest import write_project

CLEAN = """
\"\"\"Small arithmetic helpers.\"\"\"


def add(a, b):
    \"\"\"Return the sum of a and b.\"\"\"
    return a + b


def multiply(a, b):
    \"\"\"Return the product of a and b.\"\"\"
    return a * b
"""

CRITICAL_SOURCE = """
def charge_customer(customer, amount):
    \"\"\"Charge the customer the given amount.\"\"\"
    pass
"""

WARNING_SOURCE = """
API_URL = "https://api.example.com/v1"
"""

NOTE_SOURCE = """
def run(rows):
    out = []
    for row in rows:
        try:
            out.append(int(row))
        except ValueError:
            continue
    return out
"""


@pytest.fixture
def make_project(tmp_path):
    def _make(files):
        write_project(tmp_path, files)
        return str(tmp_path)

    return _make


# =======================================================================
# exit codes
# =======================================================================


def test_clean_project_exits_zero(make_project, capsys):
    path = make_project({"app.py": CLEAN})
    assert main([path]) == EXIT_CLEAN
    assert "No flops found" in capsys.readouterr().out


def test_findings_exit_one(make_project, capsys):
    path = make_project({"app.py": CRITICAL_SOURCE})
    assert main([path, "--only", "VC010"]) == EXIT_FLOPS_FOUND
    assert "PLACEHOLDER" in capsys.readouterr().out


def test_fail_on_never_always_exits_zero(make_project, capsys):
    path = make_project({"app.py": CRITICAL_SOURCE})
    assert main([path, "--only", "VC010", "--fail-on", "never"]) == EXIT_CLEAN
    capsys.readouterr()


def test_fail_on_critical_ignores_warnings(make_project, capsys):
    path = make_project({"app.py": WARNING_SOURCE})
    assert main([path, "--only", "VC021", "--fail-on", "critical"]) == EXIT_CLEAN
    capsys.readouterr()


def test_fail_on_warning_catches_warnings(make_project, capsys):
    path = make_project({"app.py": WARNING_SOURCE})
    assert main([path, "--only", "VC021", "--fail-on", "warning"]) == EXIT_FLOPS_FOUND
    capsys.readouterr()


def test_default_fail_on_is_warning(make_project, capsys):
    path = make_project({"app.py": NOTE_SOURCE})
    # A note-level finding alone must not fail the default run.
    assert main([path, "--only", "VC030"]) == EXIT_CLEAN
    capsys.readouterr()


def test_fail_on_note_catches_notes(make_project, capsys):
    path = make_project({"app.py": NOTE_SOURCE})
    assert main([path, "--only", "VC030", "--fail-on", "note"]) == EXIT_FLOPS_FOUND
    capsys.readouterr()


def test_fail_on_critical_still_catches_criticals(make_project, capsys):
    path = make_project({"app.py": CRITICAL_SOURCE})
    assert main([path, "--only", "VC010", "--fail-on", "critical"]) == EXIT_FLOPS_FOUND
    capsys.readouterr()


def test_missing_path_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["/definitely/not/a/real/path/anywhere"])
    assert excinfo.value.code == EXIT_USAGE_ERROR


def test_only_and_ignore_cancelling_out_is_a_usage_error(make_project):
    path = make_project({"app.py": CLEAN})
    with pytest.raises(SystemExit) as excinfo:
        main([path, "--only", "VC010", "--ignore", "VC010"])
    assert excinfo.value.code == EXIT_USAGE_ERROR


def test_version_flag_exits_cleanly(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == EXIT_CLEAN


# =======================================================================
# filtering
# =======================================================================


def test_only_restricts_to_the_named_check(make_project, capsys):
    path = make_project({"app.py": CRITICAL_SOURCE + WARNING_SOURCE})
    main([path, "--only", "VC021", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert {f["code"] for f in payload["findings"]} == {"VC021"}


def test_only_is_repeatable(make_project, capsys):
    path = make_project({"app.py": CRITICAL_SOURCE + WARNING_SOURCE})
    main([path, "--only", "VC010", "--only", "VC021", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert {f["code"] for f in payload["findings"]} == {"VC010", "VC021"}


def test_ignore_removes_a_check(make_project, capsys):
    path = make_project({"app.py": CRITICAL_SOURCE + WARNING_SOURCE})
    main([path, "--ignore", "VC021", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert "VC021" not in {f["code"] for f in payload["findings"]}
    assert "VC010" in {f["code"] for f in payload["findings"]}


def test_check_codes_are_case_insensitive(make_project, capsys):
    path = make_project({"app.py": WARNING_SOURCE})
    main([path, "--only", "vc021", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert {f["code"] for f in payload["findings"]} == {"VC021"}


def test_skip_tests_excludes_test_files(make_project, capsys):
    path = make_project(
        {
            "app.py": CLEAN,
            "tests/test_theatre.py": "def test_nothing():\n    do_work()\n",
        }
    )
    assert main([path, "--only", "VC040"]) == EXIT_FLOPS_FOUND
    capsys.readouterr()
    assert main([path, "--only", "VC040", "--skip-tests"]) == EXIT_CLEAN
    capsys.readouterr()


def test_select_checks_returns_every_check_by_default():
    assert len(select_checks()) == len(CHECK_CLASSES) == 15


def test_select_checks_honours_enabled_and_disabled():
    assert [c.code for c in select_checks(enabled=["VC010"])] == ["VC010"]
    codes = [c.code for c in select_checks(disabled=["VC010"])]
    assert "VC010" not in codes and len(codes) == 14


# =======================================================================
# output
# =======================================================================


def test_json_output_shape(make_project, capsys):
    path = make_project({"app.py": CRITICAL_SOURCE})
    main([path, "--only", "VC010", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert set(payload) == {
        "root",
        "files_scanned",
        "files_skipped",
        "duration_seconds",
        "suppressed",
        "summary",
        "findings",
    }
    assert set(payload["summary"]) == {"critical", "warning", "note"}
    assert payload["files_scanned"] == 1
    assert payload["suppressed"] == 0

    finding = payload["findings"][0]
    assert set(finding) == {
        "path",
        "relative_path",
        "line",
        "column",
        "code",
        "label",
        "severity",
        "message",
        "suggestion",
        "snippet",
    }
    assert finding["code"] == "VC010"
    assert finding["label"] == "PLACEHOLDER"
    assert finding["severity"] == "critical"
    assert finding["relative_path"] == "app.py"
    assert finding["line"] == 1


def test_json_output_on_a_clean_project(make_project, capsys):
    path = make_project({"app.py": CLEAN})
    assert main([path, "--json"]) == EXIT_CLEAN
    payload = json.loads(capsys.readouterr().out)
    assert payload["findings"] == []
    assert payload["summary"] == {"critical": 0, "warning": 0, "note": 0}


def test_json_reports_suppressed_count(make_project, capsys):
    path = make_project(
        {"app.py": "def run():\n    try:\n        risky()\n    except:  # noqa\n        pass\n"}
    )
    main([path, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["suppressed"] >= 1


def test_text_output_has_no_ansi_when_no_color(make_project, capsys):
    path = make_project({"app.py": CRITICAL_SOURCE})
    main([path, "--only", "VC010", "--no-color"])
    assert "\033[" not in capsys.readouterr().out


def test_quiet_output_omits_snippets_and_suggestions(make_project, capsys):
    path = make_project({"app.py": CRITICAL_SOURCE})
    main([path, "--only", "VC010", "--quiet", "--no-color"])
    out = capsys.readouterr().out
    assert "PLACEHOLDER" in out
    assert "->" not in out


def test_text_output_names_the_file_and_line(make_project, capsys):
    path = make_project({"pkg/app.py": CRITICAL_SOURCE})
    main([path, "--only", "VC010", "--no-color"])
    out = capsys.readouterr().out
    assert "pkg/app.py" in out
    assert "charge_customer" in out


# =======================================================================
# --list
# =======================================================================


def test_list_exits_cleanly(capsys):
    assert main(["--list"]) == EXIT_CLEAN
    capsys.readouterr()


def test_list_writes_the_catalogue_to_stdout(capsys):
    main(["--list"])
    out = capsys.readouterr().out
    assert "VC001" in out
    assert "VC051" in out
    assert "15 checks" in out


def test_catalogue_describes_every_check():
    stream = io.StringIO()
    print_catalog(stream)
    text = stream.getvalue()

    catalog = check_catalog()
    assert len(catalog) == 15
    for code, check in catalog.items():
        assert code in text
        assert check.label in text
        assert check.description in text


def test_every_check_has_a_unique_code_label_and_description():
    catalog = check_catalog()
    assert sorted(catalog) == sorted({c.code for c in select_checks()})
    for check in catalog.values():
        assert check.code.startswith("VC")
        assert check.label
        assert check.description


def test_expected_codes_are_all_present():
    expected = {
        "VC001", "VC002", "VC003",
        "VC010", "VC011",
        "VC020", "VC021", "VC022",
        "VC030", "VC031",
        "VC040", "VC041", "VC042",
        "VC050", "VC051",
    }
    assert set(check_catalog()) == expected
