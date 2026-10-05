import asyncio

from fastapi.testclient import TestClient
from langchain_core.messages import ChatMessage

import pytest

from main import app
from models.model import Order, CustomerContext, ExchangeOrReturnInput, ExchangeReturnReason, ExchangeReturnRefundAction, ESCALATE_REASON, \
    ReturnRefundInitialDecision, RefundRequest, OrderRefundStatus, OrderToReturn, ItemToReturn
from workflow.customer_support import CustomerSupportAgent, ROLE_FUNCTION, ROLE_AGENT, SOURCE_EXCHANGE_RETURN_REASON, SOURCE_RETURN_REFUND_PROCESS, \
    PREFIX_NEED_EXPEDIT_REPLACEMENT, PREFIX_RCVD_DAMAGED_PRODUCT, PREFIX_RCVD_WRONG_ITEM, PREFIX_FOUND_BETTER_PRICE
from workflow.return_refund_utils import refund_requests_processing_dict
import uuid

shared_thread_id = str(uuid.uuid4())
shared_order_id = 12462

@pytest.fixture()
def client():
    # `with` triggers the FastAPI lifespan so app.state.support_graph is built.
    with TestClient(app) as test_client:
        yield test_client


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
    "reason_option, in_response, in_escalation_message",
        [
            (ExchangeReturnReason.DAMAGED_DEFECTIVE_OR_MISSING_PARTS, 
             f'{PREFIX_RCVD_DAMAGED_PRODUCT} and {PREFIX_NEED_EXPEDIT_REPLACEMENT}', 
             ESCALATE_REASON.HELP_EXPEDITE_EXCHANGE_FOR_DEFECTIVE_WRONG_ITEM),
            (ExchangeReturnReason.WRONG_ITEM_SHIPPED, 
             f'{PREFIX_RCVD_WRONG_ITEM} and {PREFIX_NEED_EXPEDIT_REPLACEMENT}', 
             ESCALATE_REASON.HELP_EXPEDITE_EXCHANGE_FOR_DEFECTIVE_WRONG_ITEM),
            (ExchangeReturnReason.BETTER_PRICE_FOUND, 
             PREFIX_FOUND_BETTER_PRICE, 
             ESCALATE_REASON.HELP_DECIDE_IF_PRICE_MATCH_WITH_COMPETITOR), 
            (ExchangeReturnReason.WRONG_SIZE_OR_FIT, "We recommend 'exchange' since you want a different size, color or style.", None),
            (ExchangeReturnReason.NOT_MATCH_DESCRIPTION_OR_PHOTO, "We recommend 'Return' based upon the reason you provided.", None),
        ]
)    
def test_invoke_exchange_return_recommendation(client, reason_option, in_response, in_escalation_message):
    email_addr = "anderson.cooper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    context: CustomerContext = CustomerContext(**data['customer_context'])
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

    graph = client.app.state.support_graph
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = asyncio.run(graph.aget_state(config))
    assert snapshot.values.get("summary")
    assert len(snapshot.values["messages"]) == 2
    messages = snapshot.values["messages"]
    isinstance(messages[-1], ChatMessage)
    chat_message = messages[-1]
    assert chat_message.role == ROLE_AGENT
    assert chat_message.additional_kwargs["source"] == SOURCE_EXCHANGE_RETURN_REASON
    assert in_response in chat_message.content
    escalation_reason = snapshot.values.get("escalation_reason")
    if in_escalation_message:
        in_escalation_message in escalation_reason
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
def test_invoke_return_refund_init_workflow(client, email_addr, expected_order_refund_status, in_response):
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    context: CustomerContext = CustomerContext(**data['customer_context'])
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

    assert data["refund_request_to_process"]
    refund_request = RefundRequest(**data["refund_request_to_process"])
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

    graph = client.app.state.support_graph
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = asyncio.run(graph.aget_state(config))
    assert snapshot.values.get("summary")
    assert len(snapshot.values["messages"]) == 2
    messages = snapshot.values["messages"]
    isinstance(messages[-1], ChatMessage)
    chat_message = messages[-1]
    assert chat_message.role == ROLE_FUNCTION
    assert chat_message.content == expected_order_refund_status.value    

    
def test_invoke_return_refund_init_workflow_error(client):
    email_addr = "jake.tapper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    context: CustomerContext = CustomerContext(**data['customer_context'])
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
        "refund_request_to_process": None,
        "proceed_to_process_return_refund": False, 
        "assigned_refund_request_id":0,
        "desire_to_chat_return_refund":False,
        "request_human_review_return_refund": False,
        "notes_for_human_review_override": None,
    }
    assert agent.route_branch(state) == "return_refund_init"
    initial_decision = ReturnRefundInitialDecision(order_refund_status= OrderRefundStatus.ORDER_AUTO_REFUNDABLE)
    # We should have "refund_request_to_process".  However, invoke_return_refund_process_workflow has already protected it
    state.update({"initial_return_refund_decision": initial_decision, "proceed_to_process_return_refund": True})
    assert agent.route_branch(state) == "return_refund_process"
    # When the customer does not want to process instead want to chat
    state.update({"desire_to_chat_return_refund": True, "proceed_to_process_return_refund": False})
    assert agent.route_branch(state) == "return_refund_chat"
    # when the customer want to chat after processing 
    state.update({"desire_to_chat_return_refund": True, "proceed_to_process_return_refund": True, "assigned_refund_request_id": 1001})
    assert agent.route_branch(state) == "return_refund_chat"
    # Finish processing, does not want to chat
    state.update({"desire_to_chat_return_refund": False, "proceed_to_process_return_refund": True, "assigned_refund_request_id": 1001})
    assert agent.route_branch(state) == "return_refund_done_or_unknown"
    # Does not want to process, does not want to chat, what can we do? Nothing
    state.update({"desire_to_chat_return_refund": False, "proceed_to_process_return_refund": False, "assigned_refund_request_id": 0})
    assert agent.route_branch(state) == "return_refund_done_or_unknown"


@pytest.mark.parametrize(
    "email_addr, expected_order_refund_status, in_response, request_status, decided_by, decision_reason, requires_manual_approval, requires_manual_approval_reason",
    [
        ("anderson.cooper@cnn.com", OrderRefundStatus.ORDER_AUTO_REFUNDABLE, 
        "You would receive a confirmation email with instructions on how and where to send your package.", "auto_approve", "Agent", None, False, None
        ),
        ("pamela.brown@cnn.com", OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_DUE_TO_AMOUNT,
         "You would receive an email of a human review result regarding to your refund request shortly.",
         "wait_for_manual_review", None, None, True, "the request exceeds the automatic authorized refund amount"
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
def test_invoke_return_refund_process_workflow_(client, email_addr, expected_order_refund_status, in_response, request_status, 
                                               decided_by, decision_reason, requires_manual_approval, requires_manual_approval_reason):
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    context: CustomerContext = CustomerContext(**data['customer_context'])
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
    initial_decision.order_refund_status == expected_order_refund_status

    resp_process = client.post(
            "/api/support/return_refund/process",
            json={"thread_id": thread_id})
    assert resp_process.status_code == 200
    data = resp_process.json()
    assert in_response in data["response"]
    assert data["assigned_refund_request_id"]
    assigned_refund_request_id = data["assigned_refund_request_id"]
    assert assigned_refund_request_id in refund_requests_processing_dict
    refund_request_to_process = RefundRequest(**data.get("refund_request_to_process"))
    # print(refund_request_to_process)
    assert refund_request_to_process == refund_requests_processing_dict[assigned_refund_request_id]
    assert refund_request_to_process.status == request_status
    if decided_by:
        assert refund_request_to_process.decided_by == decided_by
    if decision_reason:
        refund_request_to_process.decision_reason
    assert refund_request_to_process.requires_manual_approval == requires_manual_approval
    if requires_manual_approval_reason:
        assert refund_request_to_process.requires_manual_approval_reason == requires_manual_approval_reason

    graph = client.app.state.support_graph
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = asyncio.run(graph.aget_state(config))
    assert snapshot.values.get("summary")
    assert len(snapshot.values["messages"]) == 2
    messages = snapshot.values["messages"]
    isinstance(messages[-1], ChatMessage)
    chat_message = messages[-1]
    assert chat_message.role == ROLE_AGENT
    assert chat_message.additional_kwargs["source"] == SOURCE_RETURN_REFUND_PROCESS     


@pytest.mark.parametrize(
    "email_addr, expected_order_refund_status, in_response, request_status, requires_manual_approval_reason, notes_to_human_reviwer", 
    [
        ("wolf.blitzer@cnn.com", OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS,
        "You would receive an email of a human review result regarding to your refund request shortly.",
        "wait_for_manual_review", "the request has passed the return window deadline.", 
        "I missed the deadline because I traveled a lot due to the business reason."
        ),
        ("dana.bash@cnn.com", OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS,
        "You would receive an email of a human review result regarding to your refund request shortly.",
        "wait_for_manual_review", "the request includes a non-refundable item.", 
        "I have never worn the bras I bought."
        ),
    ]
)
def test_invoke_return_refund_process_workflow_human_override(client, email_addr, expected_order_refund_status, in_response, request_status, 
                                                              requires_manual_approval_reason, notes_to_human_reviwer):
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    context: CustomerContext = CustomerContext(**data['customer_context'])
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
    initial_decision.order_refund_status == expected_order_refund_status

    resp_process = client.post(
            "/api/support/return_refund/process",
            json={"thread_id": thread_id, "notes_for_human_review_override": notes_to_human_reviwer})
    assert resp_process.status_code == 200
    data = resp_process.json()
    assert in_response in data["response"]
    assert data["assigned_refund_request_id"]
    assigned_refund_request_id = data["assigned_refund_request_id"]
    assert assigned_refund_request_id in refund_requests_processing_dict
    refund_request_to_process = RefundRequest(**data.get("refund_request_to_process"))
    # print(refund_request_to_process)
    assert refund_request_to_process == refund_requests_processing_dict[assigned_refund_request_id]
    assert refund_request_to_process.status == request_status
    assert not refund_request_to_process.decided_by
    assert refund_request_to_process.requires_manual_approval == True
    assert refund_request_to_process.requires_manual_approval_reason == requires_manual_approval_reason
    assert refund_request_to_process.notes_for_human_review_override == notes_to_human_reviwer


def test_invoke_return_refund_process_or_chat_workflow_error(client):
    email_addr = "jake.tapper@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    context: CustomerContext = CustomerContext(**data['customer_context'])
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
    # If the refund_request_to_process is None, both "Process the request" and "I like to chat" should be disabled
    resp = client.post(
            "/api/support/return_refund/process",
            json={"thread_id": thread_id})
    assert resp.status_code == 400

    resp = client.post(
                "/api/support/return_refund/chat",
                json={"thread_id": thread_id, "user_conversation": "Hello"})
    assert resp.status_code == 400


def test_invoke_return_refund_chat_workflow(client):
    email_addr = "sonya_ling1947@yahoo.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    assert resp.status_code == 200
    data = resp.json()
    context: CustomerContext = CustomerContext(**data['customer_context'])
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
    
