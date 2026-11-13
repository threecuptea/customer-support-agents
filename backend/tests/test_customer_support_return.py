import asyncio

from dotenv import load_dotenv
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ChatMessage, HumanMessage

import pytest

from main import app
from models.demo_data import get_demo_customer
from models.customer_support_model import Customer, Order, CustomerContext, ExchangeOrReturnInput, ExchangeReturnReason, ExchangeReturnRefundAction, ESCALATE_REASON, \
    ReturnRefundInitialDecision, RefundRequest, OrderRefundStatus, OrderToReturn, ItemToReturn, ReturnRefundStructuredOutput
from workflow.customer_support import SOURCE_RETURN_REFUND_CHAT, CustomerSupportAgent, ROLE_FUNCTION, ROLE_AGENT, SOURCE_EXCHANGE_RETURN_REASON, \
    PREFIX_NEED_EXPEDIT_REPLACEMENT, PREFIX_RCVD_DAMAGED_PRODUCT, PREFIX_RCVD_WRONG_ITEM, PREFIX_FOUND_BETTER_PRICE, ESCALATE_MESSAGE, SOURCE_RETURN_REFUND_PROCESS
from workflow.customer_support_utils import get_initial_return_refund_decision
import uuid

load_dotenv(override=True)

shared_thread_id = str(uuid.uuid4())
shared_order_id = 12462


@pytest.fixture(scope="class")
def client():
    # `with` triggers the FastAPI lifespan so app.state.support_graph is built.
    with TestClient(app) as test_client:
        yield test_client

# `redis_client` fixture lives in conftest.py (dedicated test Redis DB, never the dev DB 0).


@pytest.mark.parametrize(
    "reason_option, expected_action",
    [
        (ExchangeReturnReason.DAMAGED_DEFECTIVE_OR_MISSING_PARTS, ExchangeReturnRefundAction.EXPEDITE_EXCHANGE),
        (ExchangeReturnReason.WRONG_ITEM_SHIPPED, ExchangeReturnRefundAction.EXPEDITE_EXCHANGE), 
        (ExchangeReturnReason.BETTER_PRICE_FOUND, ExchangeReturnRefundAction.PARTIAL_REFUND),
        (ExchangeReturnReason.WRONG_SIZE_OR_FIT, ExchangeReturnRefundAction.EXCHANGE),
        (ExchangeReturnReason.DIFFERENT_COLOR_OR_STYLE, ExchangeReturnRefundAction.EXCHANGE),
        (ExchangeReturnReason.NOT_MATCH_DESCRIPTION_OR_PHOTO, ExchangeReturnRefundAction.RETURN),
        (ExchangeReturnReason.DIFFICULT_TO_ASSEMBLY, ExchangeReturnRefundAction.RETURN),
        (ExchangeReturnReason.CHANGED_MIND_OR_IMPULSE_BUY, ExchangeReturnRefundAction.RETURN),
        (ExchangeReturnReason.LATE_DELIVERY_NO_LONGER_NEEDED, ExchangeReturnRefundAction.RETURN),
        (None, ExchangeReturnRefundAction.RETURN)
    ]
)
def test_get_recommended_action(reason_option, expected_action):
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    input = None
    if reason_option:
        input = ExchangeOrReturnInput(thread_id= shared_thread_id, reason_option= reason_option)
    assert agent.get_recommended_action(input) == (reason_option, expected_action)


@pytest.mark.parametrize(
    "reason_option, in_response, in_escalation_message, special_exchange_handling",
        [
            (ExchangeReturnReason.DAMAGED_DEFECTIVE_OR_MISSING_PARTS, 
             f'{PREFIX_RCVD_DAMAGED_PRODUCT} and {PREFIX_NEED_EXPEDIT_REPLACEMENT}', 
             ESCALATE_REASON.HELP_EXPEDITE_EXCHANGE_FOR_DEFECTIVE_WRONG_ITEM, True),
            (ExchangeReturnReason.WRONG_ITEM_SHIPPED, 
             f'{PREFIX_RCVD_WRONG_ITEM} and {PREFIX_NEED_EXPEDIT_REPLACEMENT}', 
             ESCALATE_REASON.HELP_EXPEDITE_EXCHANGE_FOR_DEFECTIVE_WRONG_ITEM, True),
            (ExchangeReturnReason.BETTER_PRICE_FOUND, 
             PREFIX_FOUND_BETTER_PRICE, 
             ESCALATE_REASON.HELP_DECIDE_IF_PRICE_MATCH_WITH_COMPETITOR, False), 
            (ExchangeReturnReason.WRONG_SIZE_OR_FIT, "We recommend 'exchange' since you want a different size, color or style.", None, False),
            (ExchangeReturnReason.NOT_MATCH_DESCRIPTION_OR_PHOTO, "We recommend 'Return' based upon the reason you provided.", None, False),
        ]
)    
def test_api_invoke_exchange_return_recommendation(client, reason_option, in_response, in_escalation_message, special_exchange_handling):
    email_addr = "anderson.cooper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    context = CustomerContext(**resp.json()[1])
    target_order_id = context.latest_orders[0].order_id
    result_init = client.post(
        "/api/support/order/init",
        json={"customer_context": context.model_dump(mode= "json"), "order_number_provided": target_order_id}
    )
    # The premise to do any exchange_return_recommendation or return refund is to have ordr_number and target_order
    thread_id = result_init.json()["thread_id"]
    result_recommend = client.post(
        "/api/support/exchange_return/recommend",
        json={"thread_id": thread_id, "reason_option": reason_option})
    data = result_recommend.json()
    assert data["thread_id"] == thread_id
    assert in_response in data["response"]
    assert data["special_exchange_handling"] == special_exchange_handling

    graph = client.app.state.support_graph
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = asyncio.run(graph.aget_state(config))
    assert snapshot.values.get("summary")
    assert len(snapshot.values["messages"]) == 2
    messages = snapshot.values["messages"]
    assert isinstance(messages[-1], ChatMessage)
    chat_message = messages[-1]
    assert chat_message.role == ROLE_AGENT
    assert chat_message.additional_kwargs["source"] == SOURCE_EXCHANGE_RETURN_REASON
    assert in_response in chat_message.content
    escalation_reason = snapshot.values.get("escalation_reason")
    if in_escalation_message:
        assert in_escalation_message in escalation_reason
    else:
        assert not escalation_reason   
    
        
@pytest.mark.parametrize(
    "email_addr, expected_order_refund_status, in_response",
    [
        ("anderson.cooper@cnn.com", OrderRefundStatus.ORDER_AUTO_REFUNDABLE, 
        "Congratulations!! It's in my authority to approve your request."),
        ("pamela.brown@cnn.com", OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_DUE_TO_AMOUNT,
         "It's not in my authority to approve your request because the refund amount before tax has exceeded my authorized amount threshold: $500."),
        ("wolf.blitzer@cnn.com", OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS, 
        "I am sorry that I have to reject your return refund request because your request come too late and has passed 35 days of the return window deadline."
        ),
        ("dana.bash@cnn.com", OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS, 
        "I am sorry that I have to reject your return refund request because you are trying to return a non-refundable item."),
    ]
)    
def test_api_invoke_return_refund_init_workflow(client, email_addr, expected_order_refund_status, in_response):
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    context = CustomerContext(**resp.json()[1])
    target_order_id = context.latest_orders[0].order_id
    result_init = client.post(
        "/api/support/order/init",
        json={"customer_context": context.model_dump(mode= "json"), "order_number_provided": target_order_id},
    )
    # The premise to do any exchange_return_recommendation or return refund is to have ordr_number and target_order
    data = result_init.json()
    thread_id = data["thread_id"]
    target_order: Order = Order(**data['target_order'])
    
    items = [{"product_id": item.product_id, "qty": item.number_units} for item in target_order.items]

    resp = client.post(
        "/api/support/return_refund/init",
        json={"thread_id": thread_id, "items": items})
    data = resp.json()
    assert in_response in data["response"]

    assert data["initial_return_refund_decision"]
    initial_decision: ReturnRefundInitialDecision = ReturnRefundInitialDecision(**data["initial_return_refund_decision"])
    assert initial_decision.order_refund_status == expected_order_refund_status
    
    assert data["rr_in_process"]
    refund_request = RefundRequest(**data["rr_in_process"])
    assert refund_request.status == "pending"
    return_order = refund_request.returned_order
    assert return_order.origin_order_id == target_order.order_id
    assert return_order.original_delivery_date == target_order.delivery_date
    assert return_order.estimated_amount_refund_incl_tax == target_order.total_amount_incl_tax
    assert return_order.tax_applied_rate == target_order.tax_applied_rate
    assert return_order.status == "pending"
    assert len(return_order.items) == len(items)
    for i, item in enumerate(return_order.items):
        assert item.product_id == items[i]["product_id"]
        assert item.number_units == items[i]["qty"]
    assert not data["rr_being_processed"]    

    graph = client.app.state.support_graph
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = asyncio.run(graph.aget_state(config))
    assert snapshot.values.get("summary")
    assert len(snapshot.values["messages"]) == 2
    messages = snapshot.values["messages"]
    assert isinstance(messages[-1], ChatMessage)
    chat_message = messages[-1]
    assert chat_message.role == ROLE_FUNCTION
    assert chat_message.content == expected_order_refund_status.value

    
def test_api_invoke_return_refund_init_workflow_error(client):
    email_addr = "jake.tapper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    context = CustomerContext(**resp.json()[1])
    target_order_id = context.latest_orders[0].order_id
    result_init = client.post(
        "/api/support/order/init",
        json={"customer_context": context.model_dump(mode= "json"), "order_number_provided": target_order_id}
    )
    # The premise to do any exchange_return_recommendation or return refund is to have ordr_number and target_order
    data = result_init.json()
    thread_id = data["thread_id"]
    target_order: Order = Order(**data['target_order'])
    assert not target_order.delivery_date
    assert target_order.status != "delivered"
    
    items = [{"product_id": item.product_id, "qty": item.number_units} for item in target_order.items]
    resp = client.post(
            "/api/support/return_refund/init",
            json={"thread_id": thread_id, "items": items})
    assert resp.status_code == 400 
    
        
def test_routes_return():
    agent = CustomerSupportAgent(checkpointer=None, store=None)
    state = {
       "support_category": "exchange_or_return",
    }
    assert agent.route_branch(state) == "exchange_or_return"
    order_to_return = OrderToReturn(thread_id= shared_thread_id, items= [ItemToReturn(product_id= "PRD-001", qty=1)])
    state = {
        "support_category": "return_refund",
        "order_to_return": order_to_return,
        "initial_return_refund_decision": None,
        "proceed_to_process_return_refund": False, 
        "desire_to_chat_return_refund":False,
        "request_human_review_return_refund": False,
        "notes_for_human_review_override": None,
        "rr_id_in_process": 0,
        "rr_being_processed": False,
    }
    assert agent.route_branch(state) == "return_refund_init"
    initial_decision = ReturnRefundInitialDecision(order_refund_status= OrderRefundStatus.ORDER_AUTO_REFUNDABLE)
    state.update({"initial_return_refund_decision": initial_decision, "proceed_to_process_return_refund": True})
    assert agent.route_branch(state) == "return_refund_process"
    # When the customer does not want to process instead want to chat
    state.update({"desire_to_chat_return_refund": True, "proceed_to_process_return_refund": False})
    assert agent.route_branch(state) == "return_refund_chat"
    # when the customer want to chat after processing 
    state.update({"desire_to_chat_return_refund": True, "proceed_to_process_return_refund": True, "rr_being_processed": True})
    assert agent.route_branch(state) == "return_refund_chat"
    # Finish processing, does not want to chat
    state.update({"desire_to_chat_return_refund": False, "proceed_to_process_return_refund": True, "rr_being_processed": True})
    assert agent.route_branch(state) == "return_refund_done_or_unknown"
    # Does not want to process, does not want to chat, what can we do? Nothing
    state.update({"desire_to_chat_return_refund": False, "proceed_to_process_return_refund": False, "rr_being_processed": False})
    assert agent.route_branch(state) == "return_refund_done_or_unknown"


@pytest.mark.parametrize(
    "email_addr, expected_order_refund_status, in_response, request_status, decided_by, decision_reason, requires_manual_approval, requires_manual_approval_reason",
    [
        ("anderson.cooper@cnn.com", OrderRefundStatus.ORDER_AUTO_REFUNDABLE, 
        "You would receive a confirmation email with instructions on how and where to send your package.", "auto_approve", "Agent", None, False, None
        ),
        ("pamela.brown@cnn.com", OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_DUE_TO_AMOUNT,
         "You would receive an email of a human review result regarding to your refund request shortly.",
         "wait_for_manual_review", None, None, True, "the request exceeds the automatic authorized refund amount."
        ),
        ("wolf.blitzer@cnn.com", OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS,
        "You would receive a rejection email and detail the underlined reason.",
        "auto_reject", "Agent", "the request has passed the return window deadline.", False, None
        ),
        ("dana.bash@cnn.com", OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS,
        "You would receive a rejection email and detail the underlined reason.",
        "auto_reject", "Agent", "the request includes a non-refundable item.", False, None
        ),
    ]
)

def test_api_invoke_return_refund_process_workflow(client, redis_client, email_addr, expected_order_refund_status, in_response, request_status,
                                               decided_by, decision_reason, requires_manual_approval, requires_manual_approval_reason):
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    context = CustomerContext(**resp.json()[1])
    target_order_id = context.latest_orders[0].order_id
    result_init = client.post(
        "/api/support/order/init",
        json={"customer_context": context.model_dump(mode= "json"), "order_number_provided": target_order_id},
    )
    # The premise to do any exchange_return_recommendation or return refund is to have ordr_number and target_order
    data = result_init.json()
    thread_id = data["thread_id"]
    target_order: Order = Order(**data['target_order'])
    
    items = [{"product_id": item.product_id, "qty": item.number_units} for item in target_order.items]

    resp = client.post(
        "/api/support/return_refund/init",
        json={"thread_id": thread_id, "items": items})
    data = resp.json()

    assert data["initial_return_refund_decision"]
    initial_decision: ReturnRefundInitialDecision = ReturnRefundInitialDecision(**data["initial_return_refund_decision"])
    assert initial_decision.order_refund_status == expected_order_refund_status

    assert data["rr_in_process"]
    rr_in_process = RefundRequest(**data.get("rr_in_process"))
    rr_json = redis_client.get(f"rr:{rr_in_process.refund_request_id}")
    assert rr_in_process == RefundRequest.model_validate_json(rr_json)
    assert rr_in_process.status == "pending"

    assert not data["rr_being_processed"]

    resp_process = client.post(
            "/api/support/return_refund/process",
            json={"thread_id": thread_id, "turn_off_slack_integration_for_test": True})
    assert resp_process.status_code == 200
    data = resp_process.json()
    assert in_response in data["response"]

    assert data["rr_in_process"]
    rr_in_process = RefundRequest(**data.get("rr_in_process"))
    # I tried to use asyncio.run(redis_adapter.retrieve_refund_request...) and 
    # got RuntimeError: Future <Future pending> attached to a different loop
    # Because await app.state.redis_adapter.connect() in lifespan has already started an event loop, we cannot use asyncio.run() to start another event loop here.
    # I tried to use async client and async test function so that I can use await instead to avoid the above issue and I got fixture-related errors.
    # Therefore, I settle to use sync redis client here from fixture and clean up keys after each test.
    # I can use get /api/support/return_refund/{refund_request_id} call instead.  However, I still need to pass in redis_client so that I can clean up.
    rr_json = redis_client.get(f"rr:{rr_in_process.refund_request_id}")
    assert rr_in_process == RefundRequest.model_validate_json(rr_json)
    assert rr_in_process.status == request_status
    if decided_by:
        assert rr_in_process.decided_by == decided_by
    if decision_reason:
        assert rr_in_process.decision_reason == decision_reason
    assert rr_in_process.requires_manual_approval == requires_manual_approval
    if requires_manual_approval_reason:
        assert rr_in_process.requires_manual_approval_reason == requires_manual_approval_reason

    assert data["rr_being_processed"]
    # retired fields must not come back in the API contract
    assert "refund_request_to_process" not in data
    assert "assigned_refund_request_id" not in data

    graph = client.app.state.support_graph
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = asyncio.run(graph.aget_state(config))
    assert snapshot.values.get("summary")
    assert len(snapshot.values["messages"]) == 2
    messages = snapshot.values["messages"]
    assert isinstance(messages[-1], ChatMessage)
    chat_message = messages[-1]
    assert chat_message.role == ROLE_AGENT
    assert chat_message.additional_kwargs["source"] == SOURCE_RETURN_REFUND_PROCESS

    # A refund request is processed exactly once: a second /process call for the same
    resp_process_again = client.post(
            "/api/support/return_refund/process",
            json={"thread_id": thread_id, "turn_off_slack_integration_for_test": True})
    assert resp_process_again.status_code == 400

@pytest.mark.parametrize(
    "email_addr, expected_order_refund_status, in_response, requires_manual_approval_reason, notes_to_human_reviwer",
    [
        ("wolf.blitzer@cnn.com", OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS,
        "You would receive an email of a human review result regarding to your refund request shortly.",
        "the request has passed the return window deadline.",
        "I missed the deadline because I traveled a lot due to the business reason."
        ),
        ("dana.bash@cnn.com", OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS,
        "You would receive an email of a human review result regarding to your refund request shortly.",
        "the request includes a non-refundable item.",
        "I have never worn the bras I bought."
        ),
    ]
)
def test_api_invoke_return_refund_process_workflow_human_override(client, redis_client, email_addr, expected_order_refund_status, in_response,
                                                              requires_manual_approval_reason, notes_to_human_reviwer):
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    context = CustomerContext(**resp.json()[1])
    target_order_id = context.latest_orders[0].order_id
    result_init = client.post(
        "/api/support/order/init",
        json={"customer_context": context.model_dump(mode= "json"), "order_number_provided": target_order_id},
    )
    # The premise to do any exchange_return_recommendation or return refund is to have ordr_number and target_order
    data = result_init.json()
    thread_id = data["thread_id"]
    target_order: Order = Order(**data['target_order'])

    items = [{"product_id": item.product_id, "qty": item.number_units} for item in target_order.items]

    resp = client.post(
        "/api/support/return_refund/init",
        json={"thread_id": thread_id, "items": items})
    data = resp.json()

    assert data["initial_return_refund_decision"]
    initial_decision: ReturnRefundInitialDecision = ReturnRefundInitialDecision(**data["initial_return_refund_decision"])
    assert initial_decision.order_refund_status == expected_order_refund_status
    assert data["rr_in_process"]
    rr_in_process = RefundRequest(**data.get("rr_in_process"))
    rr_json = redis_client.get(f"rr:{rr_in_process.refund_request_id}")
    assert rr_in_process == RefundRequest.model_validate_json(rr_json)
    assert rr_in_process.status == "pending"

    assert not data["rr_being_processed"]

    resp_process = client.post(
            "/api/support/return_refund/process",
            json={"thread_id": thread_id, "notes_for_human_review_override": notes_to_human_reviwer, "turn_off_slack_integration_for_test": True})
    assert resp_process.status_code == 200
    data = resp_process.json()
    assert in_response in data["response"]

    assert data["rr_in_process"]
    rr_in_process = RefundRequest(**data.get("rr_in_process"))
    rr_json = redis_client.get(f"rr:{rr_in_process.refund_request_id}")
    assert rr_in_process == RefundRequest.model_validate_json(rr_json)
    assert rr_in_process.status == "wait_for_manual_review"
    assert not rr_in_process.decided_by
    assert rr_in_process.requires_manual_approval == True
    assert rr_in_process.requires_manual_approval_reason == requires_manual_approval_reason
    assert rr_in_process.notes_for_human_review_override == notes_to_human_reviwer

    assert data["rr_being_processed"]

def test_api_invoke_return_refund_process_or_chat_workflow_error(client):
    email_addr = "jake.tapper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    context = CustomerContext(**resp.json()[1])
    target_order_id = context.latest_orders[0].order_id
    result_init = client.post(
        "/api/support/order/init",
        json={"customer_context": context.model_dump(mode= "json"), "order_number_provided": target_order_id}
    )
    # The premise to do any exchange_return_recommendation or return refund is to have ordr_number and target_order
    data = result_init.json()
    thread_id = data["thread_id"]
    target_order: Order = Order(**data['target_order'])
    assert not target_order.delivery_date
    assert target_order.status != "delivered"
    
    items = [{"product_id": item.product_id, "qty": item.number_units} for item in target_order.items]
    resp = client.post(
            "/api/support/return_refund/init",
            json={"thread_id": thread_id, "items": items})
    assert resp.status_code == 400
    resp = client.post(
            "/api/support/return_refund/process",
            json={"thread_id": thread_id, "turn_off_slack_integration_for_test": True})
    assert resp.status_code == 400

    resp = client.post(
                "/api/support/return_refund/chat",
                json={"thread_id": thread_id, "user_conversation": "Hello"})
    assert resp.status_code == 400


def test_api_invoke_return_refund_chat_workflow(client, redis_client):
    # redis client can help cleanup 
    email_addr = "sonya_ling1947@yahoo.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    context = CustomerContext(**resp.json()[1])
    target_order_id = context.latest_orders[1].order_id
    result_init = client.post(
        "/api/support/order/init",
        json={"customer_context": context.model_dump(mode= "json"), "order_number_provided": target_order_id}
    )
    # The premise to do any exchange_return_recommendation or return refund is to have ordr_number and target_order
    data = result_init.json()
    thread_id = data["thread_id"]
    target_order: Order = Order(**data['target_order'])
    items = [{"product_id": item.product_id, "qty": item.number_units} for item in target_order.items]
    resp = client.post(
        "/api/support/return_refund/init",
        json={"thread_id": thread_id, "items": items})
        
    resp = client.post(
        "/api/support/return_refund/chat",
        json={"thread_id": thread_id, "user_conversation": "Hello"})
    assert resp.status_code ==200
    data = resp.json()
    assert not data["request_human_review_return_refund"]

    # Mock LLM always returns None for with_structured_output, so return_refund_chat_node
    # must fall back to an escalate response rather than the "" it used to return, and must
    # not stomp request_human_review_return_refund back to False once it's already True.
    assert data["response"]
    assert ESCALATE_MESSAGE in data["response"]

    graph = client.app.state.support_graph
    config = {"configurable": {"thread_id": thread_id}}
    asyncio.run(graph.aupdate_state(config, {"request_human_review_return_refund": True}))
    resp = client.post(
        "/api/support/return_refund/chat",
        json={"thread_id": thread_id, "user_conversation": "Please let a human review this"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["request_human_review_return_refund"]


def test_request_human_review_for_return_refund_chat_with_fake_llm():
    question = "Yes, please initialize a human review for my return refund request"
    response = "Please input why you think that the request should be approved in the 'notes to reviewer' input field, then press 'Process the request'"
    output = ReturnRefundStructuredOutput(
        response=response,
        request_human_review_return_refund=True,
    )
    class _FakeReturnRefundChatLLM:
        async def ainvoke(self, messages):
            return output
        
    email_addr = "wolf.blitzer@cnn.com"
    customer_context = CustomerContext(**get_demo_customer(email_addr)) # It does not use API and call workflow directly
    target_order = customer_context.latest_orders[0]
    customer: Customer = Customer(
            customer_id=customer_context.customer_id, title=customer_context.title, first_name=customer_context.first_name, last_name=customer_context.last_name, email=customer_context.email)
    items = [ItemToReturn(product_id=item.product_id, qty=item.number_units) for item in target_order.items]
    order_to_return = OrderToReturn(thread_id=shared_thread_id, items=items)
    refund_request, initial_decision = get_initial_return_refund_decision(order_to_return, target_order, customer)
    refund_request.refund_request_id = 1001
    class _FakeRedisAdapter:
            async def retrieve_refund_request(self, refund_request_id: int) -> RefundRequest | None:
                return refund_request

    state = {
        "messages": [HumanMessage(content=question)],
        "order_number_provided": target_order.order_id,
        "target_order": target_order,
        "rr_id_in_process": 1001,
        "initial_return_refund_decision": initial_decision,
    }
    agent = CustomerSupportAgent(checkpointer=None, store=None, redis_adapter=_FakeRedisAdapter())
    agent.return_refund_llm = _FakeReturnRefundChatLLM()
    result = asyncio.run(agent.return_refund_chat_node(state))
    assert result["response"] == response
    assert ESCALATE_MESSAGE not in result["response"]
    assert isinstance(result["messages"][0], AIMessage)
    message: AIMessage = result["messages"][0]
    assert message.additional_kwargs["source"] == SOURCE_RETURN_REFUND_CHAT
    assert message.content == response
    assert result["request_human_review_return_refund"]

def test_api_refund_request_get(client, redis_client):
    # redis client can help cleanup Redis cache after each test.
    email_addr = "manu.raju@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    context = CustomerContext(**resp.json()[1])
    target_order_id = context.latest_orders[0].order_id
    result_init = client.post(
        "/api/support/order/init",
        json={"customer_context": context.model_dump(mode= "json"), "order_number_provided": target_order_id}
    )
    # The premise to do any exchange_return_recommendation or return refund is to have ordr_number and target_order
    data = result_init.json()
    thread_id = data["thread_id"]
    target_order: Order = Order(**data['target_order'])

    # One order has two refund requests
    item1 = next(({"product_id": item.product_id, "qty": item.number_units} for item in target_order.items), None)
    if item1 is None:
        pytest.fail("No item found in the target order")
    resp = client.post(
        "/api/support/return_refund/init",
        json={"thread_id": thread_id, "items": [item1]})
    assert resp.status_code == 200
    assert "rr_in_process" in resp.json()
    rr_in_process = RefundRequest(**resp.json()["rr_in_process"])
    rr_id_1 = rr_in_process.refund_request_id
    resp = client.get(f"/api/support/return_refund/{rr_id_1}")
    assert resp.status_code == 200
    rr1 = RefundRequest(**resp.json())
    assert rr1 == rr_in_process
    assert rr1.refund_request_id == rr_id_1
    assert rr1.returned_order.items[0].product_id == target_order.items[0].product_id
    assert rr1.returned_order.items[0].product_id == item1["product_id"]
    assert rr1.returned_order.items[0].number_units == item1["qty"]

    # One CSA refund request per order: re-running /init while the request is still `pending` adopts it
    # (same id, same items, no orphan), whatever items the second call carries.
    assert rr1.initial_decision is not None  # audit record of what the customer was told
    item2 = next(({"product_id": item.product_id, "qty": item.number_units} for item in target_order.items if item.product_id != item1["product_id"]), None)
    if item2 is None:
        pytest.fail("No item found in the target order")
    resp = client.post(
            "/api/support/return_refund/init",
            json={"thread_id": thread_id, "items": [item2]})
    assert resp.status_code == 200
    rr_again = RefundRequest(**resp.json()["rr_in_process"])
    assert rr_again == rr1
    assert resp.json()["initial_return_refund_decision"]["order_refund_status"] == rr1.initial_decision.value

    resp = client.get(f"/api/support/return_refund/by_order/{target_order.order_id}")
    assert resp.status_code == 200
    rr_list = [RefundRequest(**datum) for datum in resp.json()]
    assert rr_list == [rr1]

    # Once processed, the agent creates no other request for this order: 400, and still only one in Redis.
    resp = client.post(
            "/api/support/return_refund/process",
            json={"thread_id": thread_id, "turn_off_slack_integration_for_test": True})
    assert resp.status_code == 200
    resp = client.post(
            "/api/support/return_refund/init",
            json={"thread_id": thread_id, "items": [item2]})
    assert resp.status_code == 400
    assert "contact a customer-support representative" in resp.json()["detail"]
    resp = client.get(f"/api/support/return_refund/by_order/{target_order.order_id}")
    assert len(resp.json()) == 1


def _start_return_refund(client, email_addr="manu.raju@cnn.com"):
    """Sign in as `email_addr`, init an order and a return/refund; returns (thread_id, RefundRequest, order_id)."""
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    context = CustomerContext(**resp.json()[1])
    result_init = client.post(
        "/api/support/order/init",
        json={"customer_context": context.model_dump(mode="json"), "order_number_provided": context.latest_orders[0].order_id})
    data = result_init.json()
    target_order = Order(**data["target_order"])
    item = {"product_id": target_order.items[0].product_id, "qty": target_order.items[0].number_units}
    resp = client.post("/api/support/return_refund/init", json={"thread_id": data["thread_id"], "items": [item]})
    assert resp.status_code == 200
    return data["thread_id"], RefundRequest(**resp.json()["rr_in_process"]), target_order.order_id


def test_refund_request_gets_are_limited_to_the_owner(client, redis_client):
    _, rr, order_id = _start_return_refund(client, "manu.raju@cnn.com")
    assert client.get(f"/api/support/return_refund/{rr.refund_request_id}").json()["refund_request_id"] == rr.refund_request_id
    assert [r["refund_request_id"] for r in client.get(f"/api/support/return_refund/by_order/{order_id}").json()] == [rr.refund_request_id]

    # Another signed-in customer (same client: signing in replaces the session) must not see it. Not-owned looks exactly like missing.
    other = client.post("/api/auth", json={"email_addr": "pamela.brown@cnn.com"})
    assert other.status_code == 200
    resp = client.get(f"/api/support/return_refund/{rr.refund_request_id}")
    assert resp.status_code == 200 and resp.json() is None
    assert client.get(f"/api/support/return_refund/9999999").json() is None  # identical to an id that does not exist
    assert client.get(f"/api/support/return_refund/by_order/{order_id}").json() == []


def test_refund_request_gets_require_sign_in(client, redis_client):
    client.post("/api/auth/logout")
    assert client.get("/api/support/return_refund/1").status_code in (401, 403)
    assert client.get("/api/support/return_refund/by_order/1").status_code in (401, 403)


def test_process_and_chat_return_400_when_the_refund_request_vanished_from_redis(client, redis_client):
    thread_id, rr, _ = _start_return_refund(client)
    redis_client.delete(f"rr:{rr.refund_request_id}")  # Redis flushed/restarted; the sqlite checkpoint still points at it
    resp = client.post("/api/support/return_refund/process", json={"thread_id": thread_id, "turn_off_slack_integration_for_test": True})
    assert resp.status_code == 400
    resp = client.post("/api/support/return_refund/chat", json={"thread_id": thread_id, "user_conversation": "hello?"})
    assert resp.status_code == 400


def test_chat_response_carries_the_latest_refund_request(client, redis_client):
    """/chat returns rr_in_process like /init and /process, re-read from Redis after the graph ran, so a status
    changed behind our back (the Slack webhook) shows up on the very next chat reply."""
    thread_id, rr, _ = _start_return_refund(client)
    resp = client.post("/api/support/return_refund/chat", json={"thread_id": thread_id, "user_conversation": "hello?"})
    assert resp.status_code == 200
    assert resp.json()["rr_in_process"]["refund_request_id"] == rr.refund_request_id
    assert resp.json()["rr_in_process"]["status"] == "pending"

    stored = RefundRequest.model_validate_json(redis_client.get(f"rr:{rr.refund_request_id}"))
    stored.status = "manual_approve"
    redis_client.set(f"rr:{rr.refund_request_id}", stored.model_dump_json())
    resp = client.post("/api/support/return_refund/chat", json={"thread_id": thread_id, "user_conversation": "any news?"})
    assert resp.json()["rr_in_process"]["status"] == "manual_approve"


def test_init_rejects_duplicate_rows_that_together_exceed_the_ordered_units(client, redis_client):
    resp = client.post("/api/auth", json={"email_addr": "manu.raju@cnn.com"})
    context = CustomerContext(**resp.json()[1])
    data = client.post(
        "/api/support/order/init",
        json={"customer_context": context.model_dump(mode="json"), "order_number_provided": context.latest_orders[0].order_id}).json()
    item = Order(**data["target_order"]).items[0]
    rows = [{"product_id": item.product_id, "qty": item.number_units}] * 2  # each row is fine, together they are double
    resp = client.post("/api/support/return_refund/init", json={"thread_id": data["thread_id"], "items": rows})
    assert resp.status_code == 400
