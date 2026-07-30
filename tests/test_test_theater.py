"""VC040 tests that assert nothing, VC041 assertions on literals, VC042 mock tautologies."""

from conftest import codes, describe, lines_for

VC040 = ["VC040"]
VC041 = ["VC041"]
VC042 = ["VC042"]

TEST_FILE = "tests/test_orders.py"


def in_test_file(source):
    return {TEST_FILE: source}


# =======================================================================
# VC040 - tests that cannot fail
# =======================================================================


def test_test_without_any_assertion_is_flagged(scan_code):
    source = """
    def test_create_order():
        order = build_order(items=[1, 2])
        save(order)
    """
    findings = scan_code(in_test_file(source), only=VC040)
    assert codes(findings) == ["VC040"], describe(findings)
    assert lines_for(findings, "VC040") == [1]


def test_each_silent_test_is_reported(scan_code):
    source = """
    def test_one():
        do_work()


    def test_two():
        assert do_work() == 1


    def test_three():
        do_work()
    """
    findings = scan_code(in_test_file(source), only=VC040)
    assert lines_for(findings, "VC040") == [1, 9], describe(findings)


def test_async_test_without_assertion_is_flagged(scan_code):
    source = """
    async def test_fetch():
        result = await fetch()
        print(result)
    """
    findings = scan_code(in_test_file(source), only=VC040)
    assert codes(findings) == ["VC040"], describe(findings)


# -- true negatives ------------------------------------------------------


def test_plain_assert_satisfies_the_check(scan_code):
    source = """
    def test_total():
        order = build_order()
        assert order.total == 10
    """
    findings = scan_code(in_test_file(source), only=VC040)
    assert findings == [], describe(findings)


def test_unittest_style_assertions_satisfy_the_check(scan_code):
    source = """
    import unittest


    class OrderTests(unittest.TestCase):
        def test_total(self):
            order = build_order()
            self.assertEqual(order.total, 10)

        def test_empty(self):
            self.assertFalse(build_order().items)
    """
    findings = scan_code(in_test_file(source), only=VC040)
    assert findings == [], describe(findings)


def test_pytest_raises_satisfies_the_check(scan_code):
    source = """
    import pytest


    def test_rejects_negative():
        with pytest.raises(ValueError):
            build_order(total=-1)
    """
    findings = scan_code(in_test_file(source), only=VC040)
    assert findings == [], describe(findings)


def test_mock_assertion_helper_satisfies_the_check(scan_code):
    source = """
    def test_sends_email(mailer):
        notify(mailer)
        mailer.send.assert_called_once_with("hi")
    """
    findings = scan_code(in_test_file(source), only=VC040)
    assert findings == [], describe(findings)


def test_shared_verification_helper_satisfies_the_check(scan_code):
    source = """
    def check_order(order):
        assert order.total > 0


    def test_total():
        check_order(build_order())
    """
    findings = scan_code(in_test_file(source), only=VC040)
    assert findings == [], describe(findings)


def test_fixtures_are_not_tests(scan_code):
    source = """
    import pytest


    @pytest.fixture
    def test_client():
        return object()
    """
    findings = scan_code(in_test_file(source), only=VC040)
    assert findings == [], describe(findings)


def test_helper_functions_are_not_tests(scan_code):
    source = """
    def build_order(**kwargs):
        return kwargs


    def test_total():
        assert build_order(total=1)["total"] == 1
    """
    findings = scan_code(in_test_file(source), only=VC040)
    assert findings == [], describe(findings)


def test_empty_test_body_is_left_to_vc010(scan_code):
    source = """
    def test_not_written_yet():
        \"\"\"Cover the refund path.\"\"\"
    """
    findings = scan_code(in_test_file(source), only=VC040)
    assert findings == [], describe(findings)


def test_non_test_files_are_not_checked_for_assertions(scan_code):
    source = """
    def test_connection(client):
        client.ping()
    """
    findings = scan_code({"app/health.py": source}, only=VC040)
    assert findings == [], describe(findings)


# =======================================================================
# VC041 - assertions that are true by construction
# =======================================================================


def test_assert_true_literal_is_flagged(scan_code):
    source = """
    def test_thing():
        do_work()
        assert True
    """
    findings = scan_code(in_test_file(source), only=VC041)
    assert codes(findings) == ["VC041"], describe(findings)
    assert lines_for(findings, "VC041") == [3]


def test_assert_literal_comparison_is_flagged(scan_code):
    source = """
    def test_thing():
        assert 1 == 1
    """
    findings = scan_code(in_test_file(source), only=VC041)
    assert codes(findings) == ["VC041"], describe(findings)


def test_assert_non_empty_string_is_flagged(scan_code):
    source = """
    def test_thing():
        assert "ok"
    """
    findings = scan_code(in_test_file(source), only=VC041)
    assert codes(findings) == ["VC041"], describe(findings)


def test_assert_non_empty_literal_container_is_flagged(scan_code):
    source = """
    def test_thing():
        assert [1, 2]
    """
    findings = scan_code(in_test_file(source), only=VC041)
    assert codes(findings) == ["VC041"], describe(findings)


def test_assert_equal_of_identical_literals_is_flagged(scan_code):
    source = """
    import unittest


    class Tests(unittest.TestCase):
        def test_thing(self):
            self.assertEqual(1, 1)
    """
    findings = scan_code(in_test_file(source), only=VC041)
    assert codes(findings) == ["VC041"], describe(findings)


def test_assert_true_call_with_literal_is_flagged(scan_code):
    source = """
    import unittest


    class Tests(unittest.TestCase):
        def test_thing(self):
            self.assertTrue(True)
    """
    findings = scan_code(in_test_file(source), only=VC041)
    assert codes(findings) == ["VC041"], describe(findings)


# -- true negatives ------------------------------------------------------


def test_assertions_on_real_values_are_clean(scan_code):
    source = """
    def test_total():
        order = build_order()
        assert order.total == 10
        assert order.items
        assert order.status != "draft"
        assert len(order.items) == 2
    """
    findings = scan_code(in_test_file(source), only=VC041)
    assert findings == [], describe(findings)


def test_assert_false_literal_comparison_is_clean(scan_code):
    """`assert 1 == 2` fails every time - noisy, but not a fake pass."""
    source = """
    def test_thing():
        assert 1 == 2
    """
    findings = scan_code(in_test_file(source), only=VC041)
    assert findings == [], describe(findings)


def test_unittest_assert_equal_on_real_values_is_clean(scan_code):
    source = """
    import unittest


    class Tests(unittest.TestCase):
        def test_thing(self):
            self.assertEqual(compute(), 42)
            self.assertTrue(compute())
    """
    findings = scan_code(in_test_file(source), only=VC041)
    assert findings == [], describe(findings)


def test_isinstance_assertion_is_clean(scan_code):
    source = """
    def test_type():
        assert isinstance(build_order(), dict)
    """
    findings = scan_code(in_test_file(source), only=VC041)
    assert findings == [], describe(findings)


def test_constant_assert_in_production_code_is_not_flagged(scan_code):
    """`assert True` outside a test file is not test theater."""
    source = """
    def run():
        assert True
        return 1
    """
    findings = scan_code({"app/service.py": source}, only=VC041)
    assert findings == [], describe(findings)


# =======================================================================
# VC042 - tests that only assert on their own mocks
# =======================================================================


def test_assertion_on_a_mock_return_value_is_flagged(scan_code):
    source = """
    from unittest.mock import MagicMock


    def test_charge():
        client = MagicMock()
        client.charge.return_value = {"status": "ok"}
        result = client.charge(100)
        assert result["status"] == "ok"
    """
    findings = scan_code(in_test_file(source), only=VC042)
    assert codes(findings) == ["VC042"], describe(findings)
    assert lines_for(findings, "VC042") == [4]


def test_assertion_on_a_mock_fixture_only_is_flagged(scan_code):
    source = """
    def test_lookup(mock_db):
        mock_db.fetch.return_value = 7
        assert mock_db.fetch() == 7
    """
    findings = scan_code(in_test_file(source), only=VC042)
    assert codes(findings) == ["VC042"], describe(findings)


def test_chained_mock_derived_value_is_flagged(scan_code):
    source = """
    from unittest.mock import MagicMock


    def test_chain():
        client = MagicMock()
        raw = client.get("/orders")
        parsed = raw.json()
        assert parsed["ok"]
    """
    findings = scan_code(in_test_file(source), only=VC042)
    assert codes(findings) == ["VC042"], describe(findings)


# -- true negatives ------------------------------------------------------


def test_mock_passed_into_real_code_is_clean(scan_code):
    """This is exactly the test we want people writing."""
    source = """
    def test_process(mock_db):
        mock_db.fetch.return_value = [1, 2, 3]
        result = process(mock_db)
        assert result.total == 6
    """
    findings = scan_code(in_test_file(source), only=VC042)
    assert findings == [], describe(findings)


def test_test_without_mocks_is_clean(scan_code):
    source = """
    def test_total():
        order = build_order()
        assert order.total == 10
    """
    findings = scan_code(in_test_file(source), only=VC042)
    assert findings == [], describe(findings)


def test_mock_used_only_for_call_verification_is_clean(scan_code):
    source = """
    from unittest.mock import MagicMock


    def test_notifies():
        mailer = MagicMock()
        notify(mailer, "hi")
        mailer.send.assert_called_once_with("hi")
    """
    findings = scan_code(in_test_file(source), only=VC042)
    assert findings == [], describe(findings)


def test_mixed_assertions_are_clean(scan_code):
    source = """
    def test_process(mock_db):
        mock_db.fetch.return_value = [1, 2]
        result = process(mock_db)
        assert mock_db.fetch.called
        assert result.total == 3
    """
    findings = scan_code(in_test_file(source), only=VC042)
    assert findings == [], describe(findings)


def test_patch_context_manager_with_real_assertion_is_clean(scan_code):
    source = """
    from unittest.mock import patch


    def test_uses_clock():
        with patch("app.clock.now") as fake_now:
            fake_now.return_value = 0
            result = compute_age(born=0)
        assert result == 0
    """
    findings = scan_code(in_test_file(source), only=VC042)
    assert findings == [], describe(findings)


def test_mock_tautology_not_checked_outside_test_files(scan_code):
    source = """
    from unittest.mock import MagicMock


    def test_charge():
        client = MagicMock()
        result = client.charge(1)
        assert result
    """
    findings = scan_code({"app/demo.py": source}, only=VC042)
    assert findings == [], describe(findings)
