"""VC050 - async calls with no await, VC051 - blocking calls inside async functions."""

import pytest

from conftest import codes, describe, lines_for

VC050 = ["VC050"]
VC051 = ["VC051"]


# =======================================================================
# VC050 - lost await
# =======================================================================


def test_async_call_with_discarded_result_is_flagged(scan_code):
    source = """
    async def refresh_cache():
        return 1


    async def main():
        refresh_cache()
    """
    findings = scan_code(source, only=VC050)
    assert codes(findings) == ["VC050"], describe(findings)
    assert lines_for(findings, "VC050") == [6]


def test_async_call_stored_but_never_awaited_is_flagged(scan_code):
    source = """
    async def fetch_orders():
        return []


    async def main():
        orders = fetch_orders()
        return len(orders)
    """
    findings = scan_code(source, only=VC050)
    assert codes(findings) == ["VC050"], describe(findings)
    assert lines_for(findings, "VC050") == [6]


def test_async_call_across_modules_is_flagged(scan_code):
    findings = scan_code(
        {
            "service.py": "async def fetch_orders():\n    return []\n",
            "app.py": (
                "from service import fetch_orders\n"
                "\n"
                "\n"
                "async def main():\n"
                "    fetch_orders()\n"
            ),
        },
        only=VC050,
    )
    assert codes(findings) == ["VC050"], describe(findings)
    assert findings[0].path.name == "app.py"


def test_async_call_from_sync_code_is_flagged(scan_code):
    source = """
    async def refresh_cache():
        return 1


    def warm_up():
        refresh_cache()
    """
    findings = scan_code(source, only=VC050)
    assert codes(findings) == ["VC050"], describe(findings)


# -- true negatives ------------------------------------------------------


def test_awaited_call_is_clean(scan_code):
    source = """
    async def fetch_orders():
        return []


    async def main():
        orders = await fetch_orders()
        return len(orders)
    """
    findings = scan_code(source, only=VC050)
    assert findings == [], describe(findings)


def test_coroutine_awaited_later_is_clean(scan_code):
    source = """
    async def fetch_orders():
        return []


    async def main():
        pending = fetch_orders()
        return await pending
    """
    findings = scan_code(source, only=VC050)
    assert findings == [], describe(findings)


def test_gather_consumes_the_coroutine(scan_code):
    source = """
    import asyncio


    async def fetch_orders():
        return []


    async def main():
        return await asyncio.gather(fetch_orders(), fetch_orders())
    """
    findings = scan_code(source, only=VC050)
    assert findings == [], describe(findings)


def test_gather_over_a_list_consumes_the_coroutine(scan_code):
    source = """
    import asyncio


    async def fetch_orders():
        return []


    async def main():
        return await asyncio.gather(*[fetch_orders(), fetch_orders()])
    """
    findings = scan_code(source, only=VC050)
    assert findings == [], describe(findings)


def test_create_task_consumes_the_coroutine(scan_code):
    source = """
    import asyncio


    async def fetch_orders():
        return []


    async def main():
        task = asyncio.create_task(fetch_orders())
        return await task
    """
    findings = scan_code(source, only=VC050)
    assert findings == [], describe(findings)


def test_asyncio_run_consumes_the_coroutine(scan_code):
    source = """
    import asyncio


    async def main():
        return 1


    if __name__ == "__main__":
        asyncio.run(main())
    """
    findings = scan_code(source, only=VC050)
    assert findings == [], describe(findings)


def test_sync_function_of_the_same_name_makes_it_ambiguous(scan_code):
    """A name that is `def` in one module and `async def` in another."""
    findings = scan_code(
        {
            "sync_impl.py": "def load():\n    return 1\n",
            "async_impl.py": "async def load():\n    return 1\n",
            "app.py": "def run(load):\n    return load()\n",
        },
        only=VC050,
    )
    assert findings == [], describe(findings)


def test_plain_sync_calls_are_clean(scan_code):
    source = """
    def compute(value):
        return value * 2


    def main():
        return compute(2)
    """
    assert scan_code(source, only=VC050) == []


# =======================================================================
# VC051 - blocking calls in async functions
# =======================================================================


@pytest.mark.parametrize(
    "call",
    [
        "time.sleep(1)",
        "requests.get('https://api.internal.corp')",
        "requests.post('https://api.internal.corp', json={})",
        "subprocess.run(['ls'])",
        "os.system('ls')",
        "urllib.request.urlopen('https://api.internal.corp')",
    ],
)
def test_blocking_calls_inside_async_are_flagged(scan_code, call):
    source = """
    import os
    import subprocess
    import time
    import urllib.request

    import requests


    async def handler():
        {0}
    """.format(call)
    findings = scan_code(source, only=VC051)
    assert codes(findings) == ["VC051"], describe(findings)
    assert lines_for(findings, "VC051") == [10]


def test_blocking_call_names_the_async_function(scan_code):
    source = """
    import time


    async def poll():
        time.sleep(5)
    """
    findings = scan_code(source, only=VC051)
    assert codes(findings) == ["VC051"], describe(findings)
    assert "poll" in findings[0].message


# -- true negatives ------------------------------------------------------


def test_blocking_call_in_sync_function_is_clean(scan_code):
    source = """
    import time


    def poll():
        time.sleep(5)
    """
    assert scan_code(source, only=VC051) == []


def test_async_sleep_is_clean(scan_code):
    source = """
    import asyncio


    async def poll():
        await asyncio.sleep(5)
    """
    assert scan_code(source, only=VC051) == []


def test_nested_sync_function_is_not_attributed_to_its_parent(scan_code):
    source = """
    import asyncio
    import time


    async def poll():
        def blocking_work():
            time.sleep(5)

        return await asyncio.to_thread(blocking_work)
    """
    findings = scan_code(source, only=VC051)
    assert findings == [], describe(findings)


def test_blocking_function_passed_to_an_executor_is_clean(scan_code):
    source = """
    import asyncio
    import time


    async def poll(loop):
        return await loop.run_in_executor(None, time.sleep, 5)
    """
    findings = scan_code(source, only=VC051)
    assert findings == [], describe(findings)


def test_async_http_client_is_clean(scan_code):
    source = """
    import httpx


    async def fetch(url):
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
        return response
    """
    findings = scan_code(source, only=VC051)
    assert findings == [], describe(findings)
