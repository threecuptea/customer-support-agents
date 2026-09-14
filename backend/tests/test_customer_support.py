import asyncio

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
import pytest

from main import app
from models.model import FAQMatchEvals
from workflow.customer_support import CustomerSupportAgent, ESCALATE_MESSAGE, FAQ_FUZZY_MATCH_SOURCE


@pytest.fixture()
def client():
    # `with` triggers the FastAPI lifespan so app.state.support_graph is built.
    with TestClient(app) as test_client:
        yield test_client


CUSTOMER_CONTEXT = {
    "customer_id": 1,
    "title": "Mr.",
    "first_name": "John",
    "last_name": "Doe",
    "email": "john@example.com",
    "latest_orders": [],
}


# --- Regression test for the CSA-8 bug: `general_faq_fuzz_match_node` used to
# instantiate `BaseMessage` directly, which raises a pydantic ValidationError
# (`type` field required) since BaseMessage has no concrete `type` discriminator.
# No pytest-asyncio plugin is installed, so these drive the coroutine with asyncio.run(). ---
def test_general_faq_fuzz_match_node_returns_ai_message():
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    state = {
        "general_inquiry": "What is your return policy?",
        "faq_match_evals": FAQMatchEvals(rapid_fuzz_partial_ratio_match_helpful=True, llm_semantic_match_helpful=False),
    }

    result = asyncio.run(agent.general_faq_fuzz_match_node(state))

    assert result["general_issue_resolved"] is True
    assert result["response"] == "We accept returns within 35 days of delivery for unused items"
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], AIMessage)
    assert result["messages"][0].content == result["response"]
    assert result["messages"][0].name == FAQ_FUZZY_MATCH_SOURCE


def test_general_faq_fuzz_match_node_escalates_on_low_confidence():
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    state = {
        "general_inquiry": "asdkjaslkdj not a real question",
        "faq_match_evals": FAQMatchEvals(rapid_fuzz_partial_ratio_match_helpful=True, llm_semantic_match_helpful=False),
    }

    result = asyncio.run(agent.general_faq_fuzz_match_node(state))

    assert result["general_issue_resolved"] is True
    assert result["response"] == ESCALATE_MESSAGE

def test_general_faq_llm_match_node_escalates_on_low_confidence():
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    state = {
        "general_inquiry": "What is your return policy?",
        "faq_match_evals": FAQMatchEvals(rapid_fuzz_partial_ratio_match_helpful=False, llm_semantic_match_helpful=True),
    }
    
    result = asyncio.run(agent.general_faq_llm_match_node(state))

    assert result["general_issue_resolved"] is True
    assert result["response"] == ESCALATE_MESSAGE


# --- End-to-end coverage for POST /api/support/general (also a regression test:
# the route used to call `GeneralSupportResponse(...)` with positional args, which
# pydantic BaseModel rejects). K. K, so the flow always escalates. ---
def test_general_support_endpoint_escalates_under_mock_llm(client):
    resp = client.post(
        "/api/support/general",
        json={"customer_context": CUSTOMER_CONTEXT, "general_inquiry": "What is your return policy?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["general_inquiry"] == "What is your return policy?"
    assert data["response"] == ESCALATE_MESSAGE


# --- Verifies multi-round thread continuity directly against the LangGraph checkpoint
# (via `aget_state`), not just the HTTP response: messages accumulate across rounds via
# the `add_messages` reducer, `summarize_node` prunes old messages back down via
# `RemoveMessage`, and it persists a running `summary` each time it fires. Under the
# mock LLM, `general_faq_eval_node` always escalates, which trips `_should_summarize`
# after every single round. ---
def test_general_support_thread_accumulates_and_summarizes(client):
    r1 = client.post(
        "/api/support/general",
        json={"customer_context": CUSTOMER_CONTEXT, "general_inquiry": "What is your return policy?"},
    )
    thread_id = r1.json()["thread_id"]

    graph = client.app.state.support_graph
    config = {"configurable": {"thread_id": thread_id}}
    state_after_r1 = asyncio.run(graph.aget_state(config))

    # summarize_node fired (general_issue_resolved=True trips _should_summarize) and
    # pruned everything but the 2 most recent messages -- there were only 2 to begin
    # with, so nothing is actually removed on this first round.
    assert len(state_after_r1.values["messages"]) == 2
    assert state_after_r1.values["messages"][0].content == "What is your return policy?"
    assert state_after_r1.values["messages"][1].content == ESCALATE_MESSAGE
    assert state_after_r1.values["summary"]

    r2 = client.post(
        "/api/support/general",
        json={
            "thread_id": thread_id,
            "customer_context": CUSTOMER_CONTEXT,
            "general_inquiry": "How long does delivery take?",
        },
    )
    assert r2.json()["thread_id"] == thread_id
    state_after_r2 = asyncio.run(graph.aget_state(config))

    # Round 2 appended the loaded-memory summary message, the new question, and the
    # new escalate reply on top of round 1's 2 messages (5 total) before summarize_node
    # pruned it back down to just the 2 most recent -- proving RemoveMessage actually
    # dropped the stale round-1 messages rather than letting the list grow unbounded.
    messages_after_r2 = state_after_r2.values["messages"]
    assert len(messages_after_r2) == 2
    assert messages_after_r2[0].content == "How long does delivery take?"
    assert messages_after_r2[1].content == ESCALATE_MESSAGE
    assert state_after_r2.values["summary"]
    assert state_after_r2.values["general_inquiry"] == "How long does delivery take?"
