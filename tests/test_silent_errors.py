"""VC030 - errors caught and thrown away, VC031 - return/break inside finally."""

from conftest import codes, describe, lines_for, severities

VC030 = ["VC030"]
VC031 = ["VC031"]


# =======================================================================
# VC030 - silent failure
# =======================================================================


def test_bare_except_with_pass_is_critical(scan_code):
    source = """
    def run():
        try:
            risky()
        except:
            pass
    """
    findings = scan_code(source, only=VC030)
    assert codes(findings) == ["VC030"], describe(findings)
    assert lines_for(findings, "VC030") == [4]
    assert severities(findings, "VC030")[0].label == "critical"


def test_bare_except_with_a_body_is_still_flagged(scan_code):
    source = """
    import logging


    def run():
        try:
            risky()
        except:
            logging.warning("failed")
    """
    findings = scan_code(source, only=VC030)
    assert codes(findings) == ["VC030"], describe(findings)
    assert severities(findings, "VC030")[0].label == "warning"


def test_broad_except_with_pass_is_flagged(scan_code):
    source = """
    def run():
        try:
            risky()
        except Exception:
            pass
    """
    findings = scan_code(source, only=VC030)
    assert codes(findings) == ["VC030"], describe(findings)
    assert severities(findings, "VC030")[0].label == "warning"


def test_specific_except_with_pass_is_flagged(scan_code):
    source = """
    def run(raw):
        try:
            return int(raw)
        except ValueError:
            pass
    """
    findings = scan_code(source, only=VC030)
    assert codes(findings) == ["VC030"], describe(findings)


def test_except_with_continue_is_only_a_note(scan_code):
    source = """
    def run(rows):
        out = []
        for row in rows:
            try:
                out.append(int(row))
            except ValueError:
                continue
        return out
    """
    findings = scan_code(source, only=VC030)
    assert codes(findings) == ["VC030"], describe(findings)
    assert severities(findings, "VC030")[0].label == "note"


def test_swallowing_baseexception_is_flagged(scan_code):
    source = """
    def run():
        try:
            risky()
        except BaseException:
            pass
    """
    findings = scan_code(source, only=VC030)
    assert codes(findings) == ["VC030"], describe(findings)


def test_swallowing_keyboardinterrupt_is_flagged(scan_code):
    source = """
    def run():
        try:
            risky()
        except KeyboardInterrupt:
            pass
    """
    findings = scan_code(source, only=VC030)
    assert codes(findings) == ["VC030"], describe(findings)


def test_swallowing_systemexit_is_flagged(scan_code):
    source = """
    def run():
        try:
            risky()
        except SystemExit:
            pass
    """
    findings = scan_code(source, only=VC030)
    assert codes(findings) == ["VC030"], describe(findings)


def test_every_swallowing_handler_is_reported(scan_code):
    source = """
    def run():
        try:
            risky()
        except ValueError:
            pass
        except KeyError:
            pass
    """
    findings = scan_code(source, only=VC030)
    assert lines_for(findings, "VC030") == [4, 6], describe(findings)


# -- true negatives ------------------------------------------------------


def test_handled_exception_is_clean(scan_code):
    source = """
    import logging

    log = logging.getLogger(__name__)


    def run(raw):
        try:
            return int(raw)
        except ValueError as exc:
            log.warning("bad value %r: %s", raw, exc)
            return 0
    """
    findings = scan_code(source, only=VC030)
    assert findings == [], describe(findings)


def test_reraising_is_clean(scan_code):
    source = """
    def run():
        try:
            risky()
        except OSError:
            cleanup()
            raise
    """
    findings = scan_code(source, only=VC030)
    assert findings == [], describe(findings)


def test_chained_reraise_is_clean(scan_code):
    source = """
    def run(raw):
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("bad input") from exc
    """
    findings = scan_code(source, only=VC030)
    assert findings == [], describe(findings)


def test_fallback_import_is_clean(scan_code):
    source = """
    try:
        import ujson as json
    except ImportError:
        import json
    """
    findings = scan_code(source, only=VC030)
    assert findings == [], describe(findings)


def test_try_else_finally_with_real_work_is_clean(scan_code):
    source = """
    def run(path, opener):
        handle = opener(path)
        try:
            data = handle.read()
        except OSError as exc:
            raise RuntimeError(path) from exc
        else:
            return data
        finally:
            handle.close()
    """
    findings = scan_code(source, only=VC030)
    assert findings == [], describe(findings)


def test_keyboardinterrupt_handled_properly_is_clean(scan_code):
    """Catching Ctrl-C to exit cleanly is the correct way to write a CLI."""
    source = """
    import sys


    def main():
        try:
            run_forever()
        except KeyboardInterrupt:
            sys.stderr.write("interrupted\\n")
            sys.exit(130)
    """
    findings = scan_code(source, only=VC030)
    assert findings == [], describe(findings)


def test_keyboardinterrupt_reraised_is_clean(scan_code):
    source = """
    def main():
        try:
            run_forever()
        except KeyboardInterrupt:
            shutdown()
            raise
    """
    findings = scan_code(source, only=VC030)
    assert findings == [], describe(findings)


def test_systemexit_reraised_after_cleanup_is_clean(scan_code):
    source = """
    def main():
        try:
            run()
        except SystemExit:
            flush_logs()
            raise
    """
    findings = scan_code(source, only=VC030)
    assert findings == [], describe(findings)


# =======================================================================
# VC031 - return / break inside finally
# =======================================================================


def test_return_in_finally_is_flagged(scan_code):
    source = """
    def run():
        try:
            return compute()
        finally:
            return 0
    """
    findings = scan_code(source, only=VC031)
    assert codes(findings) == ["VC031"], describe(findings)
    assert lines_for(findings, "VC031") == [5]


def test_break_in_finally_is_flagged(scan_code):
    source = """
    def run(rows):
        for row in rows:
            try:
                process(row)
            finally:
                break
    """
    findings = scan_code(source, only=VC031)
    assert codes(findings) == ["VC031"], describe(findings)
    assert lines_for(findings, "VC031") == [6]


def test_conditional_return_in_finally_is_flagged(scan_code):
    source = """
    def run(flag):
        try:
            return compute()
        finally:
            if flag:
                return None
    """
    findings = scan_code(source, only=VC031)
    assert codes(findings) == ["VC031"], describe(findings)


# -- true negatives ------------------------------------------------------


def test_cleanup_only_finally_is_clean(scan_code):
    source = """
    def run(handle):
        try:
            return handle.read()
        finally:
            handle.close()
    """
    findings = scan_code(source, only=VC031)
    assert findings == [], describe(findings)


def test_return_in_try_body_is_clean(scan_code):
    source = """
    def run(handle):
        try:
            return handle.read()
        except OSError:
            return None
        finally:
            handle.close()
    """
    findings = scan_code(source, only=VC031)
    assert findings == [], describe(findings)


def test_try_without_finally_is_clean(scan_code):
    source = """
    def run(rows):
        for row in rows:
            try:
                return process(row)
            except KeyError:
                break
        return None
    """
    findings = scan_code(source, only=VC031)
    assert findings == [], describe(findings)


def test_return_inside_a_nested_function_in_finally_is_clean(scan_code):
    """The `return` belongs to the closure, not to the finally block."""
    source = """
    def run(registry):
        try:
            return compute()
        finally:
            def _later():
                return 1

            registry.append(_later)
    """
    findings = scan_code(source, only=VC031)
    assert findings == [], describe(findings)


def test_continue_in_finally_is_not_reported_as_return(scan_code):
    source = """
    def run(rows):
        for row in rows:
            try:
                process(row)
            finally:
                pass
        return None
    """
    findings = scan_code(source, only=VC031)
    assert findings == [], describe(findings)
