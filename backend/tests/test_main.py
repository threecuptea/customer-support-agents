"""Tests for the LangGraph interrupt workflow API.

Run with: USE_MOCK_LLM=true python -m pytest -v
The mock model keeps these tests fast and offline (no API keys required).
"""

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("USE_MOCK_LLM", "true")

from main import app


@pytest.fixture()
def client():
    # `with` triggers the FastAPI lifespan so app.state.graph is built.
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# --- Helpers ----------------------------------------------------------------
def _sse(client, method, url, **kwargs):
    import json as _json

    events = []
    with client.stream(method, url, **kwargs) as response:
        for line in response.iter_lines():
            if line and line.startswith("data: "):
                events.append(_json.loads(line[6:]))
    return events


# --- Approval workflow ------------------------------------------------------
def test_approval_start_drafts_and_pauses(client):
    start = client.post("/approval/start", json={"task": "Write a welcome email"})
    assert start.status_code == 200
    data = start.json()
    assert data['requires_input'] is True
    assert data['status'] == 'awaiting_review'
    assert data['draft']
    assert data['revision_count'] == 0    


def test_approval_approve_sends(client):
    thread_id = client.post("/approval/start", json={"task": "Write a note"}).json()["thread_id"]
    decide = client.post(
        "/approval/decide",
        json={"thread_id": thread_id, "action": "approve"},
    )
    assert decide.status_code == 200
    data = decide.json()
    assert data["requires_input"] is False
    assert data["status"] == "sent"
    assert data["final_output"]


def test_approval_edit_uses_user_content(client):
    thread_id = client.post("/approval/start", json={"task": "Write a note"}).json()["thread_id"]
    edited = "This is my hand-edited final version."
    decide = client.post(
        "/approval/decide",
        json={"thread_id": thread_id, "action": "edit", "content": edited},
    )
    assert decide.status_code == 200
    data = decide.json()
    assert data["status"] == "sent"
    assert data["final_output"] == edited


def test_approval_reject_redrafts_and_pauses_again(client):
    thread_id = client.post("/approval/start", json={"task": "Write a note"}).json()["thread_id"]
    decide = client.post(
        "/approval/decide",
        json={"thread_id": thread_id, "action": "reject", "feedback": "Make it shorter"},
    )
    assert decide.status_code == 200
    data = decide.json()
    # After a reject, the workflow go to 'drafter' node and  a new draft is produced and we pause for review again. 
    # "requires_input": is_interrupted = True,
    # "revision_count": state.get("revision_count", 0) + 1, was incremented by 1 in the 'human_review' of approval_workflow.py
    assert data["requires_input"] is True
    assert data["revision_count"] == 1


# --- Agent engine (create_agent + HITL middleware) --------------------------
def test_agent_start_pauses_for_tool_approval(client):
    events = _sse(client, "POST", "/agent/start", json={"message": "research fuel cells"})
    assert any(e["type"] == "thread" for e in events)
    state = next(e for e in events if e["type"] == "state")
    assert state["requires_input"] is True
    assert state["tool_requests"][0]["name"] == "web_search"
    assert "approve" in state["allowed"] and "edit" in state["allowed"]


def test_agent_approve_completes(client):
    events = _sse(client, "POST", "/agent/start", json={"message": "research wind"})
    thread_id = next(e["thread_id"] for e in events if e["type"] == "thread")
    resumed = _sse(
        client,
        "POST",
        "/agent/decide",
        json={"thread_id": thread_id, "decisions": [{"type": "approve"}]},
    )
    state = next(e for e in resumed if e["type"] == "state")
    assert state["requires_input"] is False
    assert state["final_response"]


def test_agent_edit_tool_args(client):
    events = _sse(client, "POST", "/agent/start", json={"message": "research solar"})
    thread_id = next(e["thread_id"] for e in events if e["type"] == "thread")
    resumed = _sse(
        client,
        "POST",
        "/agent/decide",
        json={
            "thread_id": thread_id,
            "decisions": [
                {"type": "edit", "edited_action": {"name": "web_search", "args": {"query": "edited"}}}
            ],
        },
    )
    state = next(e for e in resumed if e["type"] == "state")
    assert state["requires_input"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
