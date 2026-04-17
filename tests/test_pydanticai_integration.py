"""
Tests for biscotti.pydanticai — register() and introspection helpers.
"""
import pytest
from pydantic import BaseModel
from pydantic_ai import Agent

from biscotti.pydanticai import (
    register,
    _extract_system_prompt,
    _extract_model_name,
    _extract_output_info,
    _extract_tools,
)
from biscotti.registry import get_agent, get_registry
from biscotti.runner import get_callable


class TestExtractSystemPrompt:
    def test_instructions_string(self):
        agent = Agent('test', instructions="You are helpful.")
        assert _extract_system_prompt(agent) == "You are helpful."

    def test_instructions_missing(self):
        agent = Agent('test')
        assert _extract_system_prompt(agent) == ""

    def test_system_prompt_decorator_static(self):
        agent = Agent('test')
        @agent.system_prompt
        def my_prompt() -> str:
            return "From decorator."
        prompt = _extract_system_prompt(agent)
        assert "From decorator." in prompt

    def test_combined_instructions_and_decorator(self):
        agent = Agent('test', instructions="Base instructions.")
        @agent.system_prompt
        def extra() -> str:
            return "Extra from decorator."
        prompt = _extract_system_prompt(agent)
        assert "Base instructions." in prompt
        assert "Extra from decorator." in prompt


class TestExtractModelName:
    def test_model_name(self):
        agent = Agent('test')
        name = _extract_model_name(agent)
        # test provider returns some model name
        assert isinstance(name, str)

    def test_no_model(self):
        agent = Agent()
        name = _extract_model_name(agent)
        assert name == ""


class TestExtractOutputInfo:
    def test_str_output(self):
        agent = Agent('test')
        info = _extract_output_info(agent)
        assert info["type"] == "str"
        assert info["schema"] is None

    def test_pydantic_model_output(self):
        class Summary(BaseModel):
            text: str
            score: float

        agent = Agent('test', output_type=Summary)
        info = _extract_output_info(agent)
        assert info["type"] == "Summary"
        assert info["schema"] is not None
        assert "text" in info["schema"]["properties"]
        assert "score" in info["schema"]["properties"]


class TestExtractTools:
    def test_function_tool(self):
        def search(query: str) -> str:
            """Search for information."""
            return "result"

        agent = Agent('test', tools=[search])
        tools = _extract_tools(agent)
        assert len(tools) >= 1
        tool_names = [t["name"] for t in tools]
        assert "search" in tool_names

    def test_no_tools(self):
        agent = Agent('test')
        tools = _extract_tools(agent)
        assert tools == []


class TestRegister:
    def test_register_basic(self):
        agent = Agent('test', instructions="Test prompt.")
        register(agent, name="test-agent")
        meta = get_agent("test-agent")
        assert meta is not None
        assert meta.name == "test-agent"
        assert meta.default_system_prompt == "Test prompt."

    def test_register_creates_callable(self):
        agent = Agent('test', instructions="Hello.")
        register(agent, name="callable-test")
        fn = get_callable("callable-test")
        assert fn is not None
        assert callable(fn)

    def test_register_with_description(self):
        agent = Agent('test')
        register(agent, name="desc-test", description="A test agent")
        meta = get_agent("desc-test")
        assert meta.description == "A test agent"

    def test_register_auto_detects_variables(self):
        agent = Agent('test', instructions="Hello {{name}}, you are {{role}}.")
        register(agent, name="var-test")
        meta = get_agent("var-test")
        assert "name" in meta.variables
        assert "role" in meta.variables

    def test_register_stores_pydanticai_metadata(self):
        agent = Agent('test', instructions="Test.")
        register(agent, name="meta-test")
        meta = get_agent("meta-test")
        assert hasattr(meta, '_pydanticai_agent')
        assert hasattr(meta, '_pydanticai_tools')
        assert hasattr(meta, '_pydanticai_output')
        assert meta._pydanticai_agent is agent

    def test_register_with_tools(self):
        def lookup(key: str) -> str:
            """Look up a value."""
            return "value"
        agent = Agent('test', tools=[lookup])
        register(agent, name="tools-test")
        meta = get_agent("tools-test")
        assert len(meta._pydanticai_tools) >= 1

    def test_register_with_output_type(self):
        class Result(BaseModel):
            answer: str
        agent = Agent('test', output_type=Result)
        register(agent, name="output-test")
        meta = get_agent("output-test")
        assert meta._pydanticai_output["type"] == "Result"
