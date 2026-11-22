"""LangChain standard unit tests for every Flatverify tool."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from langchain_tests.unit_tests import ToolsUnitTests

from langchain_flatverify import (
    FlatverifyBulkVerifyTool,
    FlatverifyGetJobTool,
    FlatverifyVerifyEmailTool,
)
from tests.conftest import JOB_ID, TEST_KEY


class TestVerifyEmailToolUnit(ToolsUnitTests):
    @property
    def tool_constructor(self) -> type[BaseTool]:
        return FlatverifyVerifyEmailTool

    @property
    def tool_constructor_params(self) -> dict[str, Any]:
        return {"flatverify_api_key": TEST_KEY}

    @property
    def tool_invoke_params_example(self) -> dict[str, Any]:
        return {"email": "maya.chen@amazon.com"}

    @property
    def init_from_env_params(
        self,
    ) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
        return (
            {"FLATVERIFY_API_KEY": "fv_from_env"},
            {},
            {"name": "flatverify_verify_email"},
        )


class TestBulkVerifyToolUnit(ToolsUnitTests):
    @property
    def tool_constructor(self) -> type[BaseTool]:
        return FlatverifyBulkVerifyTool

    @property
    def tool_constructor_params(self) -> dict[str, Any]:
        return {"flatverify_api_key": TEST_KEY}

    @property
    def tool_invoke_params_example(self) -> dict[str, Any]:
        return {"emails": ["j.ortiz@salesforce.com", "sam.lee@stripe.com"]}

    @property
    def init_from_env_params(
        self,
    ) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
        return (
            {"FLATVERIFY_API_KEY": "fv_from_env"},
            {},
            {"name": "flatverify_bulk_verify"},
        )


class TestGetJobToolUnit(ToolsUnitTests):
    @property
    def tool_constructor(self) -> type[BaseTool]:
        return FlatverifyGetJobTool

    @property
    def tool_constructor_params(self) -> dict[str, Any]:
        return {"flatverify_api_key": TEST_KEY}

    @property
    def tool_invoke_params_example(self) -> dict[str, Any]:
        return {"job_id": JOB_ID}
