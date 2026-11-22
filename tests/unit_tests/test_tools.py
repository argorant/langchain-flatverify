"""Behaviour tests for the Flatverify tools and client (mocked HTTP)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from langchain_core.messages import ToolMessage

from langchain_flatverify import (
    FlatverifyAPIWrapper,
    FlatverifyBulkVerifyTool,
    FlatverifyClient,
    FlatverifyError,
    FlatverifyGetJobTool,
    FlatverifyToolkit,
    FlatverifyVerifyEmailTool,
)
from tests.conftest import JOB_ID, ROWS, TEST_KEY, VALID_RESULT, job


def _wrapper(**kwargs: object) -> FlatverifyAPIWrapper:
    return FlatverifyAPIWrapper(
        flatverify_api_key=TEST_KEY,
        poll_interval=0,
        **kwargs,  # type: ignore[arg-type]
    )


def _error(status: int, code: str, *, retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return httpx.Response(
        status,
        json={"error": {"code": code, "message": f"{code} message"}},
        headers=headers,
    )


def test_verify_returns_result_and_sends_key(api: respx.MockRouter) -> None:
    tool = FlatverifyVerifyEmailTool(api_wrapper=_wrapper())
    result = tool.invoke({"email": "maya.chen@amazon.com"})
    assert result == VALID_RESULT
    request = api["verify"].calls.last.request
    assert request.headers["Authorization"] == f"Bearer {TEST_KEY}"
    assert request.headers["User-Agent"].startswith("langchain-flatverify/")
    assert json.loads(request.content) == {"email": "maya.chen@amazon.com"}


def test_verify_as_tool_call_returns_json_content() -> None:
    tool = FlatverifyVerifyEmailTool(api_wrapper=_wrapper())
    message = tool.invoke(
        {
            "name": tool.name,
            "args": {"email": "maya.chen@amazon.com"},
            "id": "call_1",
            "type": "tool_call",
        },
    )
    assert isinstance(message, ToolMessage)
    assert json.loads(str(message.content))["status"] == "valid"


def test_retries_rate_limited_then_succeeds(api: respx.MockRouter) -> None:
    api["verify"].side_effect = [
        _error(429, "rate_limited", retry_after="0"),
        httpx.Response(200, json=VALID_RESULT),
    ]
    tool = FlatverifyVerifyEmailTool(api_wrapper=_wrapper())
    assert tool.invoke({"email": "maya.chen@amazon.com"})["status"] == "valid"
    assert api["verify"].call_count == 2


def test_retries_busy_until_limit_then_reports_error(api: respx.MockRouter) -> None:
    api["verify"].mock(return_value=_error(503, "busy", retry_after="0"))
    tool = FlatverifyVerifyEmailTool(api_wrapper=_wrapper(max_retries=2))
    out = tool.invoke({"email": "maya.chen@amazon.com"})
    assert api["verify"].call_count == 3
    assert "503" in out
    assert "busy" in out


def test_too_many_jobs_is_not_retried(api: respx.MockRouter) -> None:
    api["bulk"].mock(return_value=_error(429, "too_many_jobs", retry_after="0"))
    tool = FlatverifyBulkVerifyTool(api_wrapper=_wrapper())
    out = tool.invoke({"emails": ["j.ortiz@salesforce.com"]})
    assert api["bulk"].call_count == 1
    assert "too_many_jobs" in out


def test_client_error_is_not_retried_and_hides_key(api: respx.MockRouter) -> None:
    api["verify"].mock(return_value=_error(401, "unauthorized"))
    tool = FlatverifyVerifyEmailTool(api_wrapper=_wrapper())
    out = tool.invoke({"email": "maya.chen@amazon.com"})
    assert api["verify"].call_count == 1
    assert "unauthorized" in out
    assert TEST_KEY not in out


def test_retry_wait_is_capped(
    api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []
    monkeypatch.setattr("langchain_flatverify._client.time.sleep", waits.append)
    api["verify"].side_effect = [
        _error(429, "rate_limited", retry_after="3600"),
        httpx.Response(200, json=VALID_RESULT),
    ]
    client = FlatverifyClient(TEST_KEY, max_retry_wait=5)
    assert client.verify("maya.chen@amazon.com")["status"] == "valid"
    assert waits == [5]


def test_network_error_becomes_flatverify_error(api: respx.MockRouter) -> None:
    api["verify"].side_effect = httpx.ConnectError("boom")
    client = FlatverifyClient(TEST_KEY)
    with pytest.raises(FlatverifyError, match="Could not reach"):
        client.verify("maya.chen@amazon.com")


def test_key_never_in_repr() -> None:
    wrapper = _wrapper()
    assert TEST_KEY not in repr(wrapper)
    assert TEST_KEY not in repr(wrapper.client)
    assert TEST_KEY not in repr(FlatverifyVerifyEmailTool(api_wrapper=wrapper))


def test_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLATVERIFY_API_KEY")
    with pytest.raises(ValueError, match="FLATVERIFY_API_KEY"):
        FlatverifyVerifyEmailTool()


def test_bulk_waits_and_returns_rows(api: respx.MockRouter) -> None:
    api["job"].side_effect = [
        httpx.Response(200, json=job("running")),
        httpx.Response(200, json=job("done")),
    ]
    tool = FlatverifyBulkVerifyTool(api_wrapper=_wrapper())
    out = tool.invoke(
        {
            "emails": [
                "j.ortiz@salesforce.com",
                "sam.lee@stripe.com",
                "info@shopify.com",
            ],
            "name": "Q4 leads",
        },
    )
    assert json.loads(api["bulk"].calls.last.request.content) == {
        "emails": ["j.ortiz@salesforce.com", "sam.lee@stripe.com", "info@shopify.com"],
        "name": "Q4 leads",
    }
    assert out["job_id"] == JOB_ID
    assert out["status"] == "done"
    assert out["counts"] == {"valid": 1, "invalid": 1, "risky": 1, "unknown": 0}
    assert out["skipped"] == 1
    assert out["results"] == ROWS
    assert out["results_truncated"] is False


def test_bulk_follows_result_pages(api: respx.MockRouter) -> None:
    api["results"].side_effect = [
        httpx.Response(200, json={"results": ROWS[:2], "next_after": 1}),
        httpx.Response(200, json={"results": ROWS[2:], "next_after": None}),
    ]
    tool = FlatverifyBulkVerifyTool(api_wrapper=_wrapper())
    out = tool.invoke({"emails": ["j.ortiz@salesforce.com"]})
    assert out["results"] == ROWS
    second = api["results"].calls[1].request.url.params
    assert second["after"] == "1"
    assert second["format"] == "json"


def test_bulk_truncates_rows(api: respx.MockRouter) -> None:
    tool = FlatverifyBulkVerifyTool(api_wrapper=_wrapper(), max_results=2)
    out = tool.invoke({"emails": ["j.ortiz@salesforce.com"]})
    assert len(out["results"]) == 2
    assert out["results_truncated"] is True


def test_bulk_returns_job_id_when_wait_ends(api: respx.MockRouter) -> None:
    api["job"].mock(return_value=httpx.Response(200, json=job("running")))
    tool = FlatverifyBulkVerifyTool(api_wrapper=_wrapper(), wait_timeout=0)
    out = tool.invoke({"emails": ["j.ortiz@salesforce.com"]})
    assert out["job_id"] == JOB_ID
    assert out["status"] == "running"
    assert "results" not in out
    assert "job_id" in out["message"]
    assert api["results"].call_count == 0


def test_bulk_rejects_empty_list() -> None:
    tool = FlatverifyBulkVerifyTool(api_wrapper=_wrapper())
    with pytest.raises(ValueError, match="emails"):
        tool.invoke({"emails": []})


def test_get_job_running_and_done(api: respx.MockRouter) -> None:
    tool = FlatverifyGetJobTool(api_wrapper=_wrapper())
    api["job"].mock(
        return_value=httpx.Response(200, json=job("waiting", waiting_reason="rate"))
    )
    running = tool.invoke({"job_id": JOB_ID})
    assert running["status"] == "waiting"
    assert running["waiting_reason"] == "rate"
    api["job"].mock(return_value=httpx.Response(200, json=job("done")))
    done = tool.invoke({"job_id": JOB_ID})
    assert done["results"] == ROWS


def test_get_job_not_found(api: respx.MockRouter) -> None:
    api["job"].mock(return_value=_error(404, "not_found"))
    out = FlatverifyGetJobTool(api_wrapper=_wrapper()).invoke({"job_id": JOB_ID})
    assert "not_found" in out


def test_client_account_and_iter_results() -> None:
    client = FlatverifyClient(TEST_KEY)
    assert client.get_account()["limits"]["per_minute"] == 50
    assert [r["email"] for r in client.iter_results(JOB_ID)] == [
        r["email"] for r in ROWS
    ]
    client.close()


def test_toolkit_shares_wrapper() -> None:
    toolkit = FlatverifyToolkit(flatverify_api_key=TEST_KEY)
    tools = toolkit.get_tools()
    assert [t.name for t in tools] == [
        "flatverify_verify_email",
        "flatverify_bulk_verify",
        "flatverify_get_job",
    ]
    assert all(t.api_wrapper is toolkit.api_wrapper for t in tools)  # type: ignore[attr-defined]


def test_descriptions_are_plain() -> None:
    for tool in FlatverifyToolkit().get_tools():
        text = tool.description.lower()
        assert "smtp" not in text
        assert chr(0x2014) not in text
        assert chr(0x2013) not in text


async def test_async_verify(api: respx.MockRouter) -> None:
    tool = FlatverifyVerifyEmailTool(api_wrapper=_wrapper())
    assert (await tool.ainvoke({"email": "maya.chen@amazon.com"}))["status"] == "valid"
    assert api["verify"].call_count == 1


async def test_async_retry_and_error(api: respx.MockRouter) -> None:
    api["verify"].side_effect = [
        _error(503, "busy", retry_after="0"),
        _error(402, "payment_required"),
    ]
    tool = FlatverifyVerifyEmailTool(api_wrapper=_wrapper())
    out = await tool.ainvoke({"email": "maya.chen@amazon.com"})
    assert "payment_required" in out
    assert api["verify"].call_count == 2


async def test_async_bulk_and_get_job(api: respx.MockRouter) -> None:
    api["job"].side_effect = [
        httpx.Response(200, json=job("queued")),
        httpx.Response(200, json=job("done")),
        httpx.Response(200, json=job("done")),
    ]
    bulk = FlatverifyBulkVerifyTool(api_wrapper=_wrapper(), max_results=1)
    out = await bulk.ainvoke({"emails": ["j.ortiz@salesforce.com"]})
    assert out["results"] == ROWS[:1]
    assert out["results_truncated"] is True
    got = await FlatverifyGetJobTool(api_wrapper=_wrapper()).ainvoke({"job_id": JOB_ID})
    assert got["status"] == "done"


async def test_async_bulk_not_finished(api: respx.MockRouter) -> None:
    api["job"].mock(return_value=httpx.Response(200, json=job("running")))
    bulk = FlatverifyBulkVerifyTool(api_wrapper=_wrapper(), wait_timeout=0)
    out = await bulk.ainvoke({"emails": ["j.ortiz@salesforce.com"]})
    assert out["status"] == "running"
    assert "results" not in out
