"""Tests for biscotti._scaffolds — provider-specific app.py templates."""
from biscotti._scaffolds import render_scaffold, PROVIDERS


def test_providers_list_contains_expected():
    assert set(PROVIDERS) == {"anthropic", "openai", "pydanticai", "other"}


def test_render_anthropic_contains_agent_name():
    out = render_scaffold("anthropic", agent_name="recipe agent", model="claude-sonnet-4-6")
    assert "recipe_agent" in out          # snake_cased function name
    assert '"recipe agent"' in out        # original name in decorator
    assert "claude-sonnet-4-6" in out
    assert "AsyncAnthropic" in out


def test_render_openai_contains_agent_name():
    out = render_scaffold("openai", agent_name="my agent", model="gpt-4o")
    assert "my_agent" in out
    assert '"my agent"' in out
    assert "gpt-4o" in out
    assert "AsyncOpenAI" in out


def test_render_pydanticai_contains_agent_name():
    out = render_scaffold("pydanticai", agent_name="chat agent", model="openai:gpt-4o")
    assert "chat_agent" in out
    assert '"chat agent"' in out
    assert "openai:gpt-4o" in out
    assert "pydantic_ai" in out


def test_render_other_contains_agent_name():
    out = render_scaffold("other", agent_name="my agent", model="")
    assert "my_agent" in out
    assert '"my agent"' in out
    assert "# TODO" in out


def test_render_snake_cases_agent_name():
    out = render_scaffold("anthropic", agent_name="My Cool Agent", model="claude-haiku-4-5")
    assert "my_cool_agent" in out
    assert '"My Cool Agent"' in out


def test_render_unknown_provider_raises():
    import pytest
    with pytest.raises(ValueError, match="Unknown provider"):
        render_scaffold("groq", agent_name="x", model="y")


def test_rendered_file_is_valid_python():
    import ast
    models = {
        "anthropic": "claude-sonnet-4-6",
        "openai": "gpt-4o",
        "pydanticai": "openai:gpt-4o",
        "other": "",
    }
    for provider in PROVIDERS:
        out = render_scaffold(provider, agent_name="test agent", model=models[provider])
        ast.parse(out)  # raises SyntaxError if invalid
