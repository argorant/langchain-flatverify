"""Small sync and async HTTP clients for the Flatverify REST API."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://app.flatverify.com/api/v1"
ENV_API_KEY = "FLATVERIFY_API_KEY"
DONE = "done"


class FlatverifyError(Exception):
    """Raised when the Flatverify API returns an error or cannot be reached."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        """Create the error with the HTTP status and the API error code."""
        super().__init__(message)
        self.status_code = status_code
        self.code = code

    def __str__(self) -> str:
        """Return a short, agent readable description."""
        message = super().__str__()
        if self.status_code is None:
            return message
        return f"Flatverify API error {self.status_code} ({self.code}): {message}"


def _error_from(response: httpx.Response) -> FlatverifyError:
    code = "error"
    message = response.reason_phrase or "Request failed"
    try:
        body = response.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            code = str(err.get("code") or code)
            message = str(err.get("message") or message)
    except ValueError:
        pass
    return FlatverifyError(message, status_code=response.status_code, code=code)


def _retry_after(response: httpx.Response, attempt: int, max_wait: float) -> float:
    raw = response.headers.get("Retry-After")
    try:
        wait = float(raw) if raw is not None else float(2**attempt)
    except ValueError:
        wait = float(2**attempt)
    return max(0.0, min(wait, max_wait))


def _is_retryable(response: httpx.Response) -> bool:
    if response.status_code == 503:
        return True
    if response.status_code == 429:
        # too_many_jobs means five lists are open; waiting a few seconds won't fix it.
        return _error_from(response).code != "too_many_jobs"
    return False


def _headers(api_key: str, user_agent: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": user_agent,
    }


def _bulk_body(emails: Sequence[str], name: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {"emails": list(emails)}
    if name:
        body["name"] = name
    return body


def _page_params(after: int | None) -> dict[str, Any]:
    params: dict[str, Any] = {"format": "json"}
    if after is not None:
        params["after"] = after
    return params


class FlatverifyClient:
    """Synchronous Flatverify API client.

    Retries 429 rate_limited and 503 busy responses after the Retry-After delay,
    up to ``max_retries`` times. Other errors raise :class:`FlatverifyError`.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 3,
        max_retry_wait: float = 30.0,
        user_agent: str = "flatverify-python-tools/1.0.0",
    ) -> None:
        """Create a client. The API key is sent as a Bearer token."""
        if not api_key:
            msg = f"Missing Flatverify API key. Set {ENV_API_KEY} or pass api_key."
            raise FlatverifyError(msg)
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._max_retry_wait = max_retry_wait
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers=_headers(api_key, user_agent),
        )

    def __repr__(self) -> str:
        """Never include the API key."""
        return f"FlatverifyClient(base_url={self._base_url!r})"

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        attempt = 0
        while True:
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                msg = f"Could not reach the Flatverify API: {type(exc).__name__}"
                raise FlatverifyError(msg) from None
            if response.is_success:
                return response.json()
            if _is_retryable(response) and attempt < self._max_retries:
                time.sleep(_retry_after(response, attempt, self._max_retry_wait))
                attempt += 1
                continue
            raise _error_from(response)

    def verify(self, email: str) -> dict[str, Any]:
        """Verify one email address and return the result."""
        return self._request("POST", "/verify", json={"email": email})

    def verify_bulk(
        self,
        emails: Sequence[str],
        name: str | None = None,
    ) -> dict[str, Any]:
        """Start a bulk job. Returns the job object plus ``skipped``."""
        return self._request("POST", "/verify/bulk", json=_bulk_body(emails, name))

    def get_job(self, job_id: str) -> dict[str, Any]:
        """Return the job object for ``job_id``."""
        return self._request("GET", f"/jobs/{job_id}")

    def get_results_page(
        self,
        job_id: str,
        after: int | None = None,
    ) -> dict[str, Any]:
        """Return one page of up to 1,000 results and ``next_after``."""
        return self._request(
            "GET",
            f"/jobs/{job_id}/results",
            params=_page_params(after),
        )

    def iter_results(self, job_id: str) -> Iterator[dict[str, Any]]:
        """Yield every result row of a job, page by page."""
        after: int | None = None
        while True:
            page = self.get_results_page(job_id, after)
            yield from page.get("results") or []
            after = page.get("next_after")
            if after is None:
                return

    def wait_for_job(
        self,
        job_id: str,
        *,
        timeout: float = 300.0,
        poll_interval: float = 3.0,
    ) -> dict[str, Any]:
        """Poll until the job is done or ``timeout`` seconds pass.

        Returns the latest job object either way; check ``status``.
        """
        deadline = time.monotonic() + timeout
        while True:
            job = self.get_job(job_id)
            if job.get("status") == DONE or time.monotonic() >= deadline:
                return job
            time.sleep(poll_interval)

    def get_account(self) -> dict[str, Any]:
        """Return plan, speed limit, usage and free checks left."""
        return self._request("GET", "/account")


class AsyncFlatverifyClient:
    """Asynchronous Flatverify API client with the same retry rules."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 3,
        max_retry_wait: float = 30.0,
        user_agent: str = "flatverify-python-tools/1.0.0",
    ) -> None:
        """Create an async client. The API key is sent as a Bearer token."""
        if not api_key:
            msg = f"Missing Flatverify API key. Set {ENV_API_KEY} or pass api_key."
            raise FlatverifyError(msg)
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._max_retry_wait = max_retry_wait
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers=_headers(api_key, user_agent),
        )

    def __repr__(self) -> str:
        """Never include the API key."""
        return f"AsyncFlatverifyClient(base_url={self._base_url!r})"

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        attempt = 0
        while True:
            try:
                response = await self._http.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                msg = f"Could not reach the Flatverify API: {type(exc).__name__}"
                raise FlatverifyError(msg) from None
            if response.is_success:
                return response.json()
            if _is_retryable(response) and attempt < self._max_retries:
                await asyncio.sleep(
                    _retry_after(response, attempt, self._max_retry_wait),
                )
                attempt += 1
                continue
            raise _error_from(response)

    async def verify(self, email: str) -> dict[str, Any]:
        """Verify one email address and return the result."""
        return await self._request("POST", "/verify", json={"email": email})

    async def verify_bulk(
        self,
        emails: Sequence[str],
        name: str | None = None,
    ) -> dict[str, Any]:
        """Start a bulk job. Returns the job object plus ``skipped``."""
        return await self._request(
            "POST",
            "/verify/bulk",
            json=_bulk_body(emails, name),
        )

    async def get_job(self, job_id: str) -> dict[str, Any]:
        """Return the job object for ``job_id``."""
        return await self._request("GET", f"/jobs/{job_id}")

    async def get_results_page(
        self,
        job_id: str,
        after: int | None = None,
    ) -> dict[str, Any]:
        """Return one page of up to 1,000 results and ``next_after``."""
        return await self._request(
            "GET",
            f"/jobs/{job_id}/results",
            params=_page_params(after),
        )

    async def iter_results(self, job_id: str) -> AsyncIterator[dict[str, Any]]:
        """Yield every result row of a job, page by page."""
        after: int | None = None
        while True:
            page = await self.get_results_page(job_id, after)
            for row in page.get("results") or []:
                yield row
            after = page.get("next_after")
            if after is None:
                return

    async def wait_for_job(
        self,
        job_id: str,
        *,
        timeout: float = 300.0,
        poll_interval: float = 3.0,
    ) -> dict[str, Any]:
        """Poll until the job is done or ``timeout`` seconds pass."""
        deadline = time.monotonic() + timeout
        while True:
            job = await self.get_job(job_id)
            if job.get("status") == DONE or time.monotonic() >= deadline:
                return job
            await asyncio.sleep(poll_interval)

    async def get_account(self) -> dict[str, Any]:
        """Return plan, speed limit, usage and free checks left."""
        return await self._request("GET", "/account")


def job_summary(
    job: dict[str, Any],
    rows: list[dict[str, Any]] | None,
    *,
    truncated: bool = False,
) -> dict[str, Any]:
    """Shape a job and its result rows into a compact dict for an agent."""
    out: dict[str, Any] = {
        "job_id": job.get("id"),
        "status": job.get("status"),
        "total": job.get("total"),
        "processed": job.get("processed"),
        "counts": job.get("counts"),
    }
    if "skipped" in job:
        out["skipped"] = job["skipped"]
    if job.get("status") == DONE and rows is not None:
        out["results"] = rows
        out["results_truncated"] = truncated
    else:
        if job.get("waiting_reason"):
            out["waiting_reason"] = job["waiting_reason"]
        out["message"] = (
            "The job is not finished yet. Fetch the results later with this job_id."
        )
    return out
