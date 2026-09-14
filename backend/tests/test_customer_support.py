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
