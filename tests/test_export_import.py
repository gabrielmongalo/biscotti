"""
tests/test_export_import.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for the export/import endpoints.
"""
import pytest
import pytest_asyncio
import httpx

from biscotti import Biscotti
from biscotti.registry import register_agent
from biscotti.models import AgentMeta, PromptVersionCreate, TestCaseCreate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def docs():
    d = Biscotti(storage=":memory:")
    await d.__aenter__()
    register_agent(AgentMeta(
        name="export_test_agent",
        default_system_prompt="You are helpful. Topic: {{topic}}",
    ))
    yield d
    await d.__aexit__(None, None, None)


@pytest_asyncio.fixture
async def seeded_docs(docs: Biscotti):
    """docs fixture with pre-seeded versions, test cases, and settings."""
    store = docs.store

    await store.create_prompt_version(PromptVersionCreate(
        agent_name="export_test_agent",
        system_prompt="You are a chef. Ingredients: {{ingredients}}",
        notes="first version",
        created_by="tester",
    ))
    await store.create_prompt_version(PromptVersionCreate(
        agent_name="export_test_agent",
        system_prompt="You are a pastry chef. Ingredients: {{ingredients}}",
        notes="second version",
        created_by="tester",
    ))

    await store.upsert_test_case(TestCaseCreate(
        agent_name="export_test_agent",
        name="quick dinner",
        user_message="Suggest a quick dinner",
        variable_values={"ingredients": "chicken, rice"},
    ))
    await store.upsert_test_case(TestCaseCreate(
        agent_name="export_test_agent",
        name="dessert",
        user_message="Suggest a dessert",
        variable_values={"ingredients": "chocolate, cream"},
    ))

    await store.update_agent_settings(
        "export_test_agent",
        judge_criteria="- Uses ingredients\n- Is creative",
        judge_model="openai:gpt-4o",
    )

    return docs


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_returns_correct_structure(seeded_docs: Biscotti):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=seeded_docs.app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/agents/export_test_agent/export")

    assert resp.status_code == 200
    data = resp.json()

    assert data["agent_name"] == "export_test_agent"
    assert "exported_at" in data
    assert len(data["versions"]) == 2
    assert len(data["test_cases"]) == 2
    assert data["settings"]["judge_criteria"] == "- Uses ingredients\n- Is creative"
    assert data["settings"]["judge_model"] == "openai:gpt-4o"

    # Check Content-Disposition header
    assert "attachment" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_export_unknown_agent(docs: Biscotti):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=docs.app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/agents/nonexistent_agent/export")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_import_creates_versions_and_test_cases(docs: Biscotti):
    bundle = {
        "agent_name": "export_test_agent",
        "versions": [
            {
                "system_prompt": "You are a baker. Items: {{items}}",
                "variables": ["items"],
                "notes": "imported v1",
                "created_by": "import",
            },
        ],
        "test_cases": [
            {
                "name": "bread",
                "user_message": "Make me bread",
                "variable_values": {"items": "flour, water"},
            },
        ],
        "settings": {
            "judge_criteria": "- Follows recipe",
            "judge_model": "anthropic:claude-sonnet-4-6",
            "coach_enabled": True,
        },
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=docs.app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/agents/export_test_agent/import", json=bundle
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["versions_imported"] == 1
    assert data["test_cases_imported"] == 1

    # Verify data was actually persisted (there may be an auto-seeded version too)
    versions = await docs.store.list_versions("export_test_agent")
    imported = [v for v in versions if "baker" in v.system_prompt]
    assert len(imported) == 1

    test_cases = await docs.store.list_test_cases("export_test_agent")
    assert len(test_cases) == 1
    assert test_cases[0].name == "bread"

    settings = await docs.store.get_agent_settings("export_test_agent")
    assert settings.judge_criteria == "- Follows recipe"


@pytest.mark.asyncio
async def test_import_unknown_agent(docs: Biscotti):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=docs.app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/agents/nonexistent_agent/import", json={"versions": [], "test_cases": []}
        )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Round-trip test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_round_trip_export_import(seeded_docs: Biscotti):
    """Export from one agent, import into the same agent after clearing, verify consistency."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=seeded_docs.app), base_url="http://test"
    ) as client:
        # Export
        export_resp = await client.get("/api/agents/export_test_agent/export")
        assert export_resp.status_code == 200
        bundle = export_resp.json()

    # Register a second agent to import into
    register_agent(AgentMeta(
        name="import_target_agent",
        default_system_prompt="You are helpful.",
    ))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=seeded_docs.app), base_url="http://test"
    ) as client:
        # Import into the target agent
        import_resp = await client.post(
            "/api/agents/import_target_agent/import", json=bundle
        )
        assert import_resp.status_code == 200
        result = import_resp.json()
        assert result["versions_imported"] == 2
        assert result["test_cases_imported"] == 2

    # Verify the imported data matches
    store = seeded_docs.store
    versions = await store.list_versions("import_target_agent")
    assert len(versions) == 2

    test_cases = await store.list_test_cases("import_target_agent")
    assert len(test_cases) == 2
    tc_names = {tc.name for tc in test_cases}
    assert tc_names == {"quick dinner", "dessert"}

    settings = await store.get_agent_settings("import_target_agent")
    assert settings.judge_criteria == "- Uses ingredients\n- Is creative"
    assert settings.judge_model == "openai:gpt-4o"
