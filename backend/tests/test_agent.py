import pytest
from fastapi.testclient import TestClient
from main import app

@pytest.fixture()
def client():
    # `with` triggers the FastAPI lifespan so app.state.agent_graph is built.
    with TestClient(app) as test_client:
        yield test_client

# --- Helpers ----------------------------------------------------------------
def _sse(client, method, url, **kwargs):
    import json as _json

    events = []
    with client.stream(method, url, **kwargs) as response:
        for line in response.iter_lines():
            if line and line.startswith("data: "):
                events.append(_json.loads(line[6:]))
    return events

def test_agent_approve_completes(client):
    events = _sse(client, "POST", "/api/agent/start", json={"message": "research wind"})
    thread_id = next(e["thread_id"] for e in events if e["type"] == "thread")
    resumed = _sse(
        client,
        "POST",
        "/api/agent/decide",
        json={"thread_id": thread_id, "decisions": [{"type": "approve"}]},
    )
    state = next(e for e in resumed if e["type"] == "state")
    assert state["requires_input"] is False
    assert state["final_response"]


def test_agent_edit_tool_args(client):
    events = _sse(client, "POST", "/api/agent/start", json={"message": "research solar"})
    thread_id = next(e["thread_id"] for e in events if e["type"] == "thread")
    resumed = _sse(
        client,
        "POST",
        "/api/agent/decide",
        json={
            "thread_id": thread_id,
            "decisions": [
                {"type": "edit", "edited_action": {"name": "web_search", "args": {"query": "edited"}}}
            ],
        },
    )
    state = next(e for e in resumed if e["type"] == "state")
    assert state["requires_input"] is False
