from fastapi.testclient import TestClient
import pytest
from main import app

# client = TestClient(app)
# IMPORTANT:I cannot use TestClient(app) as a global variable because it won't trigger the FastAPI lifespan context manager 
# without `with` clause as a context manager.  Tests would fail with AttributeError: 'FastAPI' object has no attribute 'state.approval_graph' 
# because the app.state.approval_graph was not never built. It's a very delicate error. 

@pytest.fixture()
def client():
    # `with` triggers the FastAPI lifespan so app.state.approval_graph is built.
    with TestClient(app) as test_client:
        yield test_client


# --- Approval workflow (draft → approve / edit / reject → send) ------------- 
def test_approval_start_drafts_and_pauses(client):
    start = client.post("/api/approval/start", json={"task": "Write a welcome email"})
    assert start.status_code == 200
    data = start.json()
    assert data['requires_input'] is True
    assert data['status'] == 'awaiting_review'
    assert data['draft']
    assert data['revision_count'] == 0    


def test_approval_approve_sends(client):
    thread_id = client.post("/api/approval/start", json={"task": "Write a note"}).json()["thread_id"]
    decide = client.post(
        "/api/approval/decide",
        json={"thread_id": thread_id, "action": "approve"},
    )
    assert decide.status_code == 200
    data = decide.json()
    assert data["requires_input"] is False
    assert data["status"] == "sent"
    assert data["final_output"]


def test_approval_edit_uses_user_content(client):
    thread_id = client.post("/api/approval/start", json={"task": "Write a note"}).json()["thread_id"]
    edited = "This is my hand-edited final version."
    decide = client.post(
        "/api/approval/decide",
        json={"thread_id": thread_id, "action": "edit", "content": edited},
    )
    assert decide.status_code == 200
    data = decide.json()
    assert data["status"] == "sent"
    assert data["final_output"] == edited


def test_approval_reject_redrafts_and_pauses_again(client):
    thread_id = client.post("/api/approval/start", json={"task": "Write a note"}).json()["thread_id"]
    decide = client.post(
        "/api/approval/decide",
        json={"thread_id": thread_id, "action": "reject", "feedback": "Make it shorter"},
    )
    assert decide.status_code == 200
    data = decide.json()
    # After a reject, the workflow go to 'drafter' node and  a new draft is produced and we pause for review again. 
    # "requires_input": is_interrupted = True,
    # "revision_count": state.get("revision_count", 0) + 1, was incremented by 1 in the 'human_review' of approval_workflow.py
    assert data["requires_input"] is True
    assert data["revision_count"] == 1
       