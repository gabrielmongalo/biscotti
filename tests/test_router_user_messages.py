"""Task 10: API endpoints for UserMessageVersion CRUD."""
from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient
from pydantic_ai import Agent

from biscotti import Biscotti
from biscotti.pydanticai import register, _PENDING_SEEDS
from _builders_for_tests import wine_builder

os.environ.setdefault("OPENAI_API_KEY", "sk-test")


@pytest.fixture(autouse=True)
def _clear_pending():
    _PENDING_SEEDS.clear()
    yield
    _PENDING_SEEDS.clear()


@pytest.fixture
def client():
    a = Agent("openai:gpt-4o", instructions="sys")
    h = register(a, name="api-test-agent")
    h.user_prompt(wine_builder)

    bi = Biscotti(storage=":memory:")
    return TestClient(bi.app)


def test_list_user_message_versions_returns_seeded_v1(client):
    r = client.get("/api/agents/api-test-agent/user-message-versions")
    assert r.status_code == 200, r.text
    versions = r.json()
    assert len(versions) == 1
    assert versions[0]["version"] == 1
    assert "{{wine}}" in versions[0]["template"]
    assert versions[0]["status"] == "current"


def test_create_draft_user_message_version(client):
    r = client.post(
        "/api/agents/api-test-agent/user-message-versions",
        json={
            "agent_name": "api-test-agent",
            "template": "Wine: {{wine}} (edited by engineer)",
            "notes": "Tightened wording",
        },
    )
    assert r.status_code == 200, r.text
    v2 = r.json()
    assert v2["version"] == 2
    assert v2["status"] == "draft"
    assert "engineer" in v2["template"]


def test_promote_user_message_version(client):
    r = client.post(
        "/api/agents/api-test-agent/user-message-versions",
        json={"agent_name": "api-test-agent", "template": "new: {{wine}}"},
    )
    v2_id = r.json()["id"]

    r2 = client.post(
        f"/api/agents/api-test-agent/user-message-versions/{v2_id}/promote"
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "current"

    # v1 should now be archived
    r3 = client.get("/api/agents/api-test-agent/user-message-versions")
    versions = r3.json()
    statuses = {v["version"]: v["status"] for v in versions}
    assert statuses[2] == "current"
    assert statuses[1] == "archived"


def test_agent_endpoint_exposes_current_user_message(client):
    r = client.get("/api/agents/api-test-agent")
    assert r.status_code == 200
    data = r.json()
    assert data["current_user_message_version"] == 1
    assert "{{wine}}" in data["current_user_message_template"]
    assert "wine" in data["current_user_message_variables"]
    assert data["current_user_message_defaults"] == {"wine": "Unknown", "producer": "Unknown"}
    # Variables are unioned (sys prompt vars + user msg vars)
    assert "wine" in data["variables"]


def test_delete_non_current_version(client):
    r = client.post(
        "/api/agents/api-test-agent/user-message-versions",
        json={"agent_name": "api-test-agent", "template": "draft: {{x}}"},
    )
    v2_id = r.json()["id"]

    r2 = client.delete(
        f"/api/agents/api-test-agent/user-message-versions/{v2_id}"
    )
    assert r2.status_code == 200
    assert r2.json()["deleted"] is True


def test_cannot_delete_current_version(client):
    r = client.get("/api/agents/api-test-agent/user-message-versions")
    v1_id = r.json()[0]["id"]

    r2 = client.delete(f"/api/agents/api-test-agent/user-message-versions/{v1_id}")
    assert r2.status_code == 400
