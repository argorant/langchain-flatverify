"""LangChain tools for Flatverify email verification."""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool, BaseToolkit, ToolException
from langchain_core.utils import secret_from_env
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    SecretStr,
    model_validator,
)

from langchain_flatverify._client import (
    DEFAULT_BASE_URL,
    DONE,
    ENV_API_KEY,
    AsyncFlatverifyClient,
    FlatverifyClient,
    FlatverifyError,
    job_summary,
)
from langchain_flatverify._version import __version__

MAX_BULK_EMAILS = 200_000
USER_AGENT = f"langchain-flatverify/{__version__}"


class FlatverifyAPIWrapper(BaseModel):
    """Holds the API key and connection settings shared by the Flatverify tools.

    The key is read from ``FLATVERIFY_API_KEY`` unless passed as
    ``flatverify_api_key``. Create keys in the Flatverify app under API keys.
    """

    flatverify_api_key: SecretStr = Field(
        default_factory=secret_from_env(
            ENV_API_KEY,
            error_message=(
                f"Did not find a Flatverify API key. Set the {ENV_API_KEY} "
                "environment variable or pass flatverify_api_key."
            ),
        ),
    )
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 30.0
    max_retries: int = 3
    max_retry_wait: float = 30.0
    poll_interval: float = 3.0

    model_config = ConfigDict(extra="forbid")

    _client: FlatverifyClient | None = PrivateAttr(default=None)

    def _settings(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "max_retry_wait": self.max_retry_wait,
            "user_agent": USER_AGENT,
        }

    @property
    def client(self) -> FlatverifyClient:
        """Return a reusable synchronous client."""
        if self._client is None:
            self._client = FlatverifyClient(
                self.flatverify_api_key.get_secret_value(),
                **self._settings(),
            )
        return self._client

    def async_client(self) -> AsyncFlatverifyClient:
        """Return a new async client; close it with ``aclose()``."""
        return AsyncFlatverifyClient(
            self.flatverify_api_key.get_secret_value(),
            **self._settings(),
        )

    def collect_results(
        self,
        job_id: str,
        max_results: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return up to ``max_results`` rows and whether more exist."""
        rows: list[dict[str, Any]] = []
        for row in self.client.iter_results(job_id):
            if len(rows) >= max_results:
                return rows, True
            rows.append(row)
        return rows, False

    async def acollect_results(
        self,
        client: AsyncFlatverifyClient,
        job_id: str,
        max_results: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Async version of :meth:`collect_results`."""
        rows: list[dict[str, Any]] = []
        async for row in client.iter_results(job_id):
            if len(rows) >= max_results:
                return rows, True
            rows.append(row)
        return rows, False


class _FlatverifyBaseTool(BaseTool):
    """Shared setup: accepts ``flatverify_api_key`` or an ``api_wrapper``."""

    api_wrapper: FlatverifyAPIWrapper = Field(default_factory=FlatverifyAPIWrapper)
    handle_tool_error: bool = True

    @model_validator(mode="before")
    @classmethod
    def _build_wrapper(cls, data: Any) -> Any:
        if isinstance(data, dict) and "flatverify_api_key" in data:
            data = dict(data)
            key = data.pop("flatverify_api_key")
            if "api_wrapper" not in data:
                data["api_wrapper"] = FlatverifyAPIWrapper(flatverify_api_key=key)
        return data


class FlatverifyVerifyEmailInput(BaseModel):
    """Input for FlatverifyVerifyEmailTool."""

    email: str = Field(
        description="The email address to check, for example maya.chen@amazon.com.",
    )


class FlatverifyVerifyEmailTool(_FlatverifyBaseTool):
    """Check whether one email address can receive mail.

    Setup:
        Install ``langchain-flatverify`` and set ``FLATVERIFY_API_KEY``.

        .. code-block:: bash

            pip install -U langchain-flatverify
            export FLATVERIFY_API_KEY="fv_..."

    Instantiate:
        .. code-block:: python

            from langchain_flatverify import FlatverifyVerifyEmailTool

            tool = FlatverifyVerifyEmailTool()

    Invoke directly with args:
        .. code-block:: python

            tool.invoke({"email": "maya.chen@amazon.com"})

        .. code-block:: python

            {
                "email": "maya.chen@amazon.com",
                "status": "valid",
                "sub_status": "accepted",
                "reason": "...",
                "disposable": False,
                "role": False,
                "free": False,
                "catch_all": False,
            }
    """

    name: str = "flatverify_verify_email"
    description: str = (
        "Check whether one email address can receive mail. Input is a single "
        "email address. Returns status (valid, invalid, risky or unknown), "
        "sub_status with the reason (for example accepted, mailbox_not_found, "
        "catch_all, role_account or disposable) and true or false flags for "
        "disposable, role, free and catch_all addresses."
    )
    args_schema: type[BaseModel] = FlatverifyVerifyEmailInput

    def _run(
        self,
        email: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        try:
            return self.api_wrapper.client.verify(email)
        except FlatverifyError as exc:
            raise ToolException(str(exc)) from None

    async def _arun(
        self,
        email: str,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        client = self.api_wrapper.async_client()
        try:
            return await client.verify(email)
        except FlatverifyError as exc:
            raise ToolException(str(exc)) from None
        finally:
            await client.aclose()


class FlatverifyBulkVerifyInput(BaseModel):
    """Input for FlatverifyBulkVerifyTool."""

    emails: list[str] = Field(
        min_length=1,
        max_length=MAX_BULK_EMAILS,
        description=(
            "The email addresses to check, for example "
            '["j.ortiz@salesforce.com", "sam.lee@stripe.com"].'
        ),
    )
    name: str | None = Field(
        default=None,
        description="Optional label for the job, for example the list name.",
    )


class FlatverifyBulkVerifyTool(_FlatverifyBaseTool):
    """Check a list of email addresses as one job and wait for the results.

    Setup:
        Install ``langchain-flatverify`` and set ``FLATVERIFY_API_KEY``.

    Instantiate:
        .. code-block:: python

            from langchain_flatverify import FlatverifyBulkVerifyTool

            tool = FlatverifyBulkVerifyTool(wait_timeout=300, max_results=1000)

    Invoke directly with args:
        .. code-block:: python

            tool.invoke({"emails": ["j.ortiz@salesforce.com", "sam.lee@stripe.com"]})
    """

    name: str = "flatverify_bulk_verify"
    description: str = (
        "Check a list of email addresses as one job and wait for the results. "
        "Use this instead of calling the single address check many times. "
        "Duplicates and malformed entries are skipped. Returns counts per status "
        "(valid, invalid, risky, unknown) and one row per address with status, "
        "sub_status and flags. If the job is not finished within the wait time, "
        "returns the job_id so the results can be fetched later with "
        "flatverify_get_job."
    )
    args_schema: type[BaseModel] = FlatverifyBulkVerifyInput
    wait_timeout: float = 300.0
    """Seconds to wait for the job before returning its job_id."""
    max_results: int = 1000
    """Most result rows returned to the model in one call."""

    def _run(
        self,
        emails: list[str],
        name: str | None = None,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        client = self.api_wrapper.client
        try:
            started = client.verify_bulk(emails, name)
            job = client.wait_for_job(
                started["id"],
                timeout=self.wait_timeout,
                poll_interval=self.api_wrapper.poll_interval,
            )
            job["skipped"] = started.get("skipped", 0)
            if job.get("status") != DONE:
                return job_summary(job, None)
            rows, truncated = self.api_wrapper.collect_results(
                job["id"],
                self.max_results,
            )
            return job_summary(job, rows, truncated=truncated)
        except FlatverifyError as exc:
            raise ToolException(str(exc)) from None

    async def _arun(
        self,
        emails: list[str],
        name: str | None = None,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        client = self.api_wrapper.async_client()
        try:
            started = await client.verify_bulk(emails, name)
            job = await client.wait_for_job(
                started["id"],
                timeout=self.wait_timeout,
                poll_interval=self.api_wrapper.poll_interval,
            )
            job["skipped"] = started.get("skipped", 0)
            if job.get("status") != DONE:
                return job_summary(job, None)
            rows, truncated = await self.api_wrapper.acollect_results(
                client,
                job["id"],
                self.max_results,
            )
            return job_summary(job, rows, truncated=truncated)
        except FlatverifyError as exc:
            raise ToolException(str(exc)) from None
        finally:
            await client.aclose()


class FlatverifyGetJobInput(BaseModel):
    """Input for FlatverifyGetJobTool."""

    job_id: str = Field(description="The job_id returned by flatverify_bulk_verify.")


class FlatverifyGetJobTool(_FlatverifyBaseTool):
    """Get the status of a bulk job and, once it is done, its result rows.

    Instantiate:
        .. code-block:: python

            from langchain_flatverify import FlatverifyGetJobTool

            tool = FlatverifyGetJobTool()
            tool.invoke({"job_id": "8f14e45f-ceea-4e7a-9d3b-2f1c6a1b7e21"})
    """

    name: str = "flatverify_get_job"
    description: str = (
        "Get the status of a bulk email verification job by its job_id. When "
        "the job is done, also returns one row per address with status, "
        "sub_status and flags."
    )
    args_schema: type[BaseModel] = FlatverifyGetJobInput
    max_results: int = 1000
    """Most result rows returned to the model in one call."""

    def _run(
        self,
        job_id: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        try:
            job = self.api_wrapper.client.get_job(job_id)
            if job.get("status") != DONE:
                return job_summary(job, None)
            rows, truncated = self.api_wrapper.collect_results(
                job_id,
                self.max_results,
            )
            return job_summary(job, rows, truncated=truncated)
        except FlatverifyError as exc:
            raise ToolException(str(exc)) from None

    async def _arun(
        self,
        job_id: str,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> dict[str, Any]:
        client = self.api_wrapper.async_client()
        try:
            job = await client.get_job(job_id)
            if job.get("status") != DONE:
                return job_summary(job, None)
            rows, truncated = await self.api_wrapper.acollect_results(
                client,
                job_id,
                self.max_results,
            )
            return job_summary(job, rows, truncated=truncated)
        except FlatverifyError as exc:
            raise ToolException(str(exc)) from None
        finally:
            await client.aclose()


class FlatverifyToolkit(BaseToolkit):
    """All Flatverify tools sharing one API key.

    Instantiate:
        .. code-block:: python

            from langchain_flatverify import FlatverifyToolkit

            tools = FlatverifyToolkit().get_tools()
    """

    api_wrapper: FlatverifyAPIWrapper = Field(default_factory=FlatverifyAPIWrapper)

    @model_validator(mode="before")
    @classmethod
    def _build_wrapper(cls, data: Any) -> Any:
        if isinstance(data, dict) and "flatverify_api_key" in data:
            data = dict(data)
            key = data.pop("flatverify_api_key")
            if "api_wrapper" not in data:
                data["api_wrapper"] = FlatverifyAPIWrapper(flatverify_api_key=key)
        return data

    def get_tools(self) -> list[BaseTool]:
        """Return the single check, bulk check and job tools."""
        return [
            FlatverifyVerifyEmailTool(api_wrapper=self.api_wrapper),
            FlatverifyBulkVerifyTool(api_wrapper=self.api_wrapper),
            FlatverifyGetJobTool(api_wrapper=self.api_wrapper),
        ]
