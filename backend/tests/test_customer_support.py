import asyncio

from fastapi.testclient import TestClient
from langchain_core.messages import ChatMessage

import pytest

from main import app
from models.model import FAQMatchEvals, Order, CustomerContext
from workflow.customer_support import CustomerSupportAgent, ESCALATE_MESSAGE, FUNCTION_FAQ_FUZZY_MATCH, SOURCE_FAQ_FUZZY_MATCH, SOURCE_FAQ_LLM_MATCH, \
    SOURCE_FAQ_LLM_EVALS, ROLE_FUNCTION_CALL, ROLE_AGENT, FAQ_MATCH_THRESHOLD, SYSTEM_ERROR_MESSAGE, SOURCE_ORDER_RETRIEVAL
from langchain_core.messages import HumanMessage
from datetime import datetime
from zoneinfo import ZoneInfo

_zoneinfo = ZoneInfo("America/New_York")

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
def test_general_faq_fuzz_match_node_returns_chat_message():
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    state = {
        "general_inquiry": "What is your return policy?",
        "faq_match_evals": FAQMatchEvals(rapid_fuzz_partial_ratio_match_helpful=True, llm_semantic_match_helpful=False),
    }

    result = asyncio.run(agent.general_faq_fuzz_match_node(state))

    assert result["general_issue_resolved"] is True
    assert result["response"] == "We accept returns within 35 days of delivery for unused items"
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], ChatMessage)
    assert result["messages"][0].content == result["response"]
    assert result["messages"][0].role == ROLE_FUNCTION_CALL
    assert result["messages"][0].name == FUNCTION_FAQ_FUZZY_MATCH
    assert result["messages"][0].additional_kwargs['faq_match_result']
    assert result["messages"][0].additional_kwargs['faq_match_result'].confidence_score > FAQ_MATCH_THRESHOLD


def test_general_faq_fuzz_match_node_escalates_on_low_confidence():
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    state = {
        "general_inquiry": "asdkjaslkdj not a real question",
        "faq_match_evals": FAQMatchEvals(rapid_fuzz_partial_ratio_match_helpful=True, llm_semantic_match_helpful=False),
    }

    result = asyncio.run(agent.general_faq_fuzz_match_node(state))

    assert result["general_issue_resolved"] is True
    assert ESCALATE_MESSAGE in result["response"]
    assert result["messages"][0].role == ROLE_AGENT
    assert result["messages"][0].additional_kwargs['source'] == SOURCE_FAQ_FUZZY_MATCH
    

def test_general_faq_llm_match_node_escalates_on_low_confidence():
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    state = {
        "general_inquiry": "asdkjaslkdj not a real question",
        "faq_match_evals": FAQMatchEvals(rapid_fuzz_partial_ratio_match_helpful=False, llm_semantic_match_helpful=True),
    }
    # It comes from mocked llm issue
    result = asyncio.run(agent.general_faq_llm_match_node(state))

    assert result["general_issue_resolved"] is True
    assert ESCALATE_MESSAGE in result["response"]
    assert result["messages"][0].role == ROLE_AGENT
    assert result["messages"][0].additional_kwargs['source'] == SOURCE_FAQ_LLM_MATCH

def test_general_faq_llm_evals_node_directly_escalates():
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    state = {
        "messages": [HumanMessage(content="asdkjaslkdj not a real question")],
        "general_inquiry": "asdkjaslkdj not a real question",
    }
    # It comes from mocked llm issue
    result = asyncio.run(agent.general_faq_eval_node(state))

    assert result["general_issue_resolved"] is True
    assert ESCALATE_MESSAGE in result["response"]
    assert result["messages"][0].role == ROLE_AGENT
    assert result["messages"][0].additional_kwargs['source'] == SOURCE_FAQ_LLM_EVALS



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
    # It comes from mocked llm issue, always negative
    assert ESCALATE_MESSAGE in data["response"]
    assert data["thread_id"]
    

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
    assert ESCALATE_MESSAGE in state_after_r1.values["messages"][1].content
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
    assert ESCALATE_MESSAGE in messages_after_r2[1].content
    assert state_after_r2.values["summary"]
    assert state_after_r2.values["general_inquiry"] == "How long does delivery take?"

def test_order_init_succeed(client):
    email_addr = "anderson.cooper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    context: CustomerContext = CustomerContext(**data['customer_context'])
    target_order_id = context.latest_orders[0].order_id
    assert context.email == email_addr
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    state = {
        "customer_context": context,
        "order_number_provided": target_order_id
    }
    result = asyncio.run(agent.order_init_chat_node(state))
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], ChatMessage)
    assert result["messages"][0].role == ROLE_AGENT
    assert result["target_order"]
    order: Order = result["target_order"]
    assert order.order_id == target_order_id
    assert order.status == 'delivered'
    assert result["response"]
    phrase = f"in '{order.status}' status" 
    assert phrase in result["response"]
    assert phrase in result["messages"][0].content

    update_order = context.latest_orders[0]
    update_order.status = 'transit'
    result = asyncio.run(agent.order_init_chat_node(state))
    order: Order = result["target_order"]
    assert order.status == update_order.status
    phrase = f"in '{order.status}' status" 
    assert phrase in result["response"]
    assert phrase in result["messages"][0].content

    update_order = context.latest_orders[0]
    update_order.status = 'pending'
    result = asyncio.run(agent.order_init_chat_node(state))
    order: Order = result["target_order"]
    assert order.status == update_order.status
    phrase = f"in '{order.status}' status" 
    assert phrase in result["response"]
    assert phrase in result["messages"][0].content

def test_order_init_fail(client):
    email_addr = "anderson.cooper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    context: CustomerContext = CustomerContext(**data['customer_context'])
    target_order_id = context.latest_orders[0].order_id
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    state = {
        "customer_context": context,
        "order_number_provided": target_order_id + 1
    }
    result = asyncio.run(agent.order_init_chat_node(state))
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], ChatMessage)
    assert result["response"] == SYSTEM_ERROR_MESSAGE
    assert result["messages"][0].role == ROLE_AGENT
    assert result["messages"][0].additional_kwargs['source'] == SOURCE_ORDER_RETRIEVAL

    
def test_routes(client):
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    state = {
       "support_category": "general/ others",
    }
    assert agent.route_branch(state) == "general_faq"
    state = {
           "summarize_on_exit": True,
    }
    assert agent.route_branch(state) == "summarize_node"
    state = {
        "support_category": "order_inquery",
        "order_number_provided": 123464,
        "target_order": None,
    }
    route = agent.route_branch(state)
    assert route == "order_init"

    email_addr = "anderson.cooper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    context: CustomerContext = CustomerContext(**data['customer_context'])

    state = {
        "support_category": "order_inquery",
        "order_number_provided": 123464,
        "target_order": context.latest_orders[0],
        }
    assert agent.route_branch(state) == "order_init_done"
    

def test_invoke_order_init_and_continue(client):
    email_addr = "anderson.cooper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    context: CustomerContext = CustomerContext(**data['customer_context'])
    target_order_id = context.latest_orders[0].order_id
    # I got into Object of type CustomerContext is not JSON serializable error. 
    # I must use Pydantic's built-in serialization methods rather than Python's standard json.dumps()
    # Native Pydantic dict conversion
    result_init = client.post(
        "/api/support/order/init",
        json={"customer_context": context.model_dump(mode= "json"), "order_number_provided": target_order_id},
    )
    
    thread_id = result_init.json()["thread_id"]
    graph = client.app.state.support_graph
    config = {"configurable": {"thread_id": thread_id}}
    snapshot_init = asyncio.run(graph.aget_state(config))
    assert len(snapshot_init.values["messages"]) == 2
    message_0 = snapshot_init.values["messages"][0]
    assert isinstance(message_0, HumanMessage)
    assert message_0.content == f"Order inquiry: {target_order_id}"
    message_1 = snapshot_init.values["messages"][1]
    assert isinstance(message_1, ChatMessage)
    assert message_1.role == ROLE_AGENT
    assert f"in 'delivered' status" in message_1.content
    assert f"in 'delivered' status" in snapshot_init.values["response"]
    assert snapshot_init.values["target_order"]
    assert snapshot_init.values["summary"]

    #TODO how can we improve LLM to make it more useful in unit tests.
    # Will get {'detail': "Error continuing customer-support order_inquery: 'NoneType' object has no attribute 'escalate'"} because
    # mock LLM return order_output: OrderStructuredOutput  None
    """
    result_continue = client.post(
        "/api/support/order/continue",
        json={"thread_id": thread_id, "user_conversation": "The Earbuds are not in high-quality as expected. I like to return and get the refund"},
    )
    """



        







    







            
    
