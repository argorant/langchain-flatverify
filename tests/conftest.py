"""Shared fixtures: every test runs against a mocked Flatverify API."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx

BASE_URL = "https://app.flatverify.com/api/v1"
TEST_KEY = "fv_test_0123456789abcdef"
JOB_ID = "8f14e45f-ceea-4e7a-9d3b-2f1c6a1b7e21"

VALID_RESULT: dict[str, Any] = {
    "email": "maya.chen@amazon.com",
    "status": "valid",
    "sub_status": "accepted",
    "reason": "The address can receive mail.",
    "disposable": False,
    "role": False,
    "free": False,
    "catch_all": False,
}

ROWS: list[dict[str, Any]] = [
    {**VALID_RESULT, "email": "j.ortiz@salesforce.com"},
    {
        **VALID_RESULT,
        "email": "sam.lee@stripe.com",
        "status": "invalid",
        "sub_status": "mailbox_not_found",
        "reason": "The mailbox does not exist.",
    },
    {
        **VALID_RESULT,
        "email": "info@shopify.com",
        "status": "risky",
        "sub_status": "role_account",
        "reason": "A shared role address.",
        "role": True,
    },
]


def job(status: str = "done", **extra: Any) -> dict[str, Any]:
    done = status == "done"
    body: dict[str, Any] = {
        "id": JOB_ID,
        "name": None,
        "source": "api",
        "status": status,
        "waiting_reason": None,
        "total": 3,
        "processed": 3 if done else 1,
        "counts": {"valid": 1, "invalid": 1, "risky": 1, "unknown": 0}
        if done
        else {"valid": 1, "invalid": 0, "risky": 0, "unknown": 0},
        "created_at": "2026-11-22T10:00:00.000Z",
        "finished_at": "2026-11-22T10:00:09.000Z" if done else None,
    }
    body.update(extra)
    return body


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLATVERIFY_API_KEY", TEST_KEY)


@pytest.fixture(autouse=True)
def api() -> Iterator[respx.MockRouter]:
    """Mock every Flatverify route; unmatched requests fail the test."""
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        router.post("/verify", name="verify").mock(
            return_value=httpx.Response(200, json=VALID_RESULT),
        )
        router.post("/verify/bulk", name="bulk").mock(
            return_value=httpx.Response(202, json={**job("queued"), "skipped": 1}),
        )
        router.get(f"/jobs/{JOB_ID}", name="job").mock(
            return_value=httpx.Response(200, json=job("done")),
        )
        router.get(f"/jobs/{JOB_ID}/results", name="results").mock(
            return_value=httpx.Response(
                200, json={"results": ROWS, "next_after": None}
            ),
        )
        router.get("/account", name="account").mock(
            return_value=httpx.Response(
                200,
                json={
                    "plan": "growth",
                    "limits": {"per_minute": 50},
                    "usage": {"today": 12, "this_minute": 0},
                    "free_checks_left": 0,
                },
            ),
        )
        yield router
