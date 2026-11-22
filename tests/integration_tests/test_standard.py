"""LangChain standard integration tests, run against the mocked API."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from langchain_tests.integration_tests import ToolsIntegrationTests

from langchain_flatverify import (
    FlatverifyAPIWrapper,
    FlatverifyBulkVerifyTool,
    FlatverifyGetJobTool,
    FlatverifyVerifyEmailTool,
)
from tests.conftest import JOB_ID, TEST_KEY


def _wrapper() -> FlatverifyAPIWrapper:
    return FlatverifyAPIWrapper(flatverify_api_key=TEST_KEY, poll_interval=0)


class TestVerifyEmailToolIntegration(ToolsIntegrationTests):
    @property
    def tool_constructor(self) -> type[BaseTool]:
        return FlatverifyVerifyEmailTool

    @property
    def tool_constructor_params(self) -> dict[str, Any]:
        return {"api_wrapper": _wrapper()}

    @property
    def tool_invoke_params_example(self) -> dict[str, Any]:
        return {"email": "maya.chen@amazon.com"}


class TestBulkVerifyToolIntegration(ToolsIntegrationTests):
    @property
    def tool_constructor(self) -> type[BaseTool]:
        return FlatverifyBulkVerifyTool

    @property
    def tool_constructor_params(self) -> dict[str, Any]:
        return {"api_wrapper": _wrapper()}

    @property
    def tool_invoke_params_example(self) -> dict[str, Any]:
        return {"emails": ["j.ortiz@salesforce.com", "sam.lee@stripe.com"]}


class TestGetJobToolIntegration(ToolsIntegrationTests):
    @property
    def tool_constructor(self) -> type[BaseTool]:
        return FlatverifyGetJobTool

    @property
    def tool_constructor_params(self) -> dict[str, Any]:
        return {"api_wrapper": _wrapper()}

    @property
    def tool_invoke_params_example(self) -> dict[str, Any]:
        return {"job_id": JOB_ID}
