"""Tests for biscotti._builder_introspect."""
from __future__ import annotations

from biscotti._builder_introspect import introspect_builder


def test_simple_dict_get_with_defaults():
    def build(info):
        name = info.get("wine", "Unknown")
        producer = info.get("producer", "Unknown")
        return f"Wine: {name}\nProducer: {producer}"

    result = introspect_builder(build)
    assert result["variables"] == ["wine", "producer"], result["variables"]
    assert result["defaults"] == {"wine": "Unknown", "producer": "Unknown"}
    assert result["template"] == "Wine: {{wine}}\nProducer: {{producer}}"


def test_dict_get_no_default():
    def build(info):
        vintage = info.get("vintage")
        return f"Vintage: {vintage}"

    result = introspect_builder(build)
    assert result["variables"] == ["vintage"]
    assert result["template"] == "Vintage: {{vintage}}"


def test_subscript_access():
    def build(info):
        name = info["wine"]
        return f"Wine: {name}"

    result = introspect_builder(build)
    assert result["variables"] == ["wine"]
    assert result["template"] == "Wine: {{wine}}"


def test_format_spec_is_stripped():
    def build(info):
        name = info.get("wine", "Unknown")
        return f"Wine: {name!r}"

    result = introspect_builder(build)
    assert "{{wine}}" in result["template"]


def test_conditional_ifexp_picks_truthy_branch():
    def build(info):
        vintage = info.get("vintage", "")
        has_vintage = bool(vintage)
        vintage_line = f"\nVintage: {vintage}" if has_vintage else ""
        name = info.get("wine", "Unknown")
        return f"Wine: {name}{vintage_line}"

    result = introspect_builder(build)
    # Truthy branch wins → Vintage line included
    assert "Vintage: {{vintage}}" in result["template"]
    assert "Wine: {{wine}}" in result["template"]


def test_realistic_wine_builder():
    """A production-shape wine-prompt builder with 9 dict-get fields."""
    def _build_wine_prompt(wine_info, include_vintage_context=False):
        name        = wine_info.get("wine", "Unknown")
        vintage     = wine_info.get("vintage", "")
        producer    = wine_info.get("producer", "Unknown")
        varietal    = wine_info.get("varietal", "")
        color       = wine_info.get("color", "")
        region      = wine_info.get("region", "")
        subregion   = wine_info.get("subregion", "")
        country     = wine_info.get("country", "")
        appellation = wine_info.get("appellation", "")
        return f"""Write a portrait for this wine.

Wine: {name}
Vintage: {vintage}
Producer: {producer}
Varietal: {varietal}
Color: {color}
Region: {region}
Sub-region: {subregion}
Appellation: {appellation}
Country: {country}"""

    result = introspect_builder(_build_wine_prompt)
    for v in ["wine", "vintage", "producer", "varietal", "color", "region",
              "subregion", "country", "appellation"]:
        assert v in result["variables"], f"{v} missing from {result['variables']}"
        assert "{{" + v + "}}" in result["template"], f"{v} not in template"

    assert result["defaults"]["wine"] == "Unknown"
    assert result["defaults"]["producer"] == "Unknown"
    assert result["defaults"]["region"] == ""


def test_keys_only_fallback_for_unsupported_patterns():
    """Builders with loops or function calls fall back to keys-only mode."""
    def build(info):
        # Arithmetic on an extracted value → Approach A bails
        score_raw = info.get("score", 0)
        score = int(score_raw) * 10
        return f"Score: {score}"

    result = introspect_builder(build)
    assert "score" in result["variables"]
    # Template exists and references the var (exact rendering may vary by tier)
    assert "{{score}}" in result["template"] or "score" in result["template"]


def test_multiple_locals_from_same_dict():
    def build(info):
        a = info.get("a", "A")
        b = info.get("b", "B")
        c = info.get("c", "C")
        return f"{a}-{b}-{c}"

    result = introspect_builder(build)
    assert result["variables"] == ["a", "b", "c"]
    assert result["template"] == "{{a}}-{{b}}-{{c}}"


def test_signature_fallback_for_typed_positional_args():
    """Builders with typed positional args (no dict.get pattern) fall back
    to the function signature to extract variables."""
    def format_wine_notes(
        wine_name: str,
        vintage: int | None,
        current_notes: list,
        wine_type: str | None = None,
    ) -> str:
        parts = [f"Target — {wine_name}"]
        return "\n\n".join(parts)

    result = introspect_builder(format_wine_notes)
    assert set(result["variables"]) == {"wine_name", "vintage", "current_notes", "wine_type"}
    for v in ("wine_name", "vintage", "current_notes", "wine_type"):
        assert "{{" + v + "}}" in result["template"]
    # wine_type has default None → captured as ""
    assert result["defaults"]["wine_type"] == ""


def test_signature_fallback_captures_non_none_defaults():
    def build(name: str = "Anonymous", count: int = 3) -> str:
        return f"{name} × {count}"

    result = introspect_builder(build)
    assert set(result["variables"]) == {"name", "count"}
    assert result["defaults"]["name"] == "Anonymous"
    assert result["defaults"]["count"] == "3"


def test_signature_fallback_excludes_extras_kwargs():
    """Param names passed via extras= should not appear as variables — they're
    bind-time overrides, not user-facing inputs."""
    def build(wine_name: str, include_vintage: bool = False) -> str:
        return f"Name: {wine_name}"

    result = introspect_builder(build, extras={"include_vintage": True})
    assert "include_vintage" not in result["variables"]
    assert "wine_name" in result["variables"]


def test_dict_patterns_still_win_when_present():
    """When dict patterns are found, signature fallback is NOT used."""
    def build(info: dict) -> str:
        name = info.get("wine", "Unknown")
        return f"Wine: {name}"

    result = introspect_builder(build)
    # 'info' (the param name) should NOT leak into variables; only 'wine' (dict key)
    assert result["variables"] == ["wine"]
    assert "{{info}}" not in result["template"]
    assert "{{wine}}" in result["template"]
