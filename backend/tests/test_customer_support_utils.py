import asyncio

from fastapi.testclient import TestClient
import pytest

from models.customer_support_model import Customer, Order, OrderToReturn, ItemToReturn, CustomerContext, OrderRefundStatus
from workflow.customer_support_utils import check_if_order_to_return_in_valid_state, get_initial_return_refund_decision, \
    ORIGINAL_ORDER_FOR_RETURN_IS_NOT_DELIVERED, NOT_A_VALID_PRODUCT_ID, NOT_A_VALID_RETURN_QUANTITY, group_memory
import uuid
from main import app
import logging
from memory import clean_user_memory
from datetime import datetime, UTC

logging.basicConfig(level="INFO")
logger = logging.getLogger(__name__)


@pytest.fixture(scope="class")
def client():
    # `with` triggers the FastAPI lifespan so main_app.state.support_graph is built.
    with TestClient(app) as test_client:
        yield test_client

def test_check_if_order_to_return_in_valid_state(client):
    with pytest.raises(ValueError):
        check_if_order_to_return_in_valid_state(None, None)

    item = ItemToReturn(product_id= "PRD-1031", qty= 3)
    return_order = OrderToReturn(thread_id= str(uuid.uuid4()), items= [item])
    with pytest.raises(ValueError):
        check_if_order_to_return_in_valid_state(return_order, None)

    email_addr = "jake.tapper@cnn.com" # in 'transit' status and no delivered_date
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    data = resp.json()
    context: CustomerContext = CustomerContext(**data[1])
    original_order = context.latest_orders[0]
    with pytest.raises(ValueError, match=ORIGINAL_ORDER_FOR_RETURN_IS_NOT_DELIVERED):
        check_if_order_to_return_in_valid_state(return_order, original_order)

    email_addr = "manu.raju@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    data = resp.json()
    context: CustomerContext = CustomerContext(**data[1])
    original_order = context.latest_orders[0] # in 'delivered' status
    # it has "PRD-1924", 1 unit. return_order has "PRD-1031" mis-match
    with pytest.raises(ValueError, match= NOT_A_VALID_PRODUCT_ID):
            check_if_order_to_return_in_valid_state(return_order, original_order)

    item = ItemToReturn(product_id= "PRD-1924", qty= 2)
    return_order.items = [item]
    with pytest.raises(ValueError, match= NOT_A_VALID_RETURN_QUANTITY):
        check_if_order_to_return_in_valid_state(return_order, original_order)

    item = ItemToReturn(product_id= "PRD-1924", qty= 1)
    return_order.items = [item]
    assert check_if_order_to_return_in_valid_state(return_order, original_order) == True


@pytest.mark.parametrize(
    "comment, email_addr, expected_order_refund_status",
    [
        ("The order is not in 'delivered' status", "jake.tapper@cnn.com", OrderRefundStatus.ORDER_INVALID_REFUNDABLE_STATE),
        ("The order exceeds amount threshold for auto approve", "pamela.brown@cnn.com", OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_DUE_TO_AMOUNT),
        ("Return a order exceeding its return windown", "wolf.blitzer@cnn.com", OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS),
        ("The order contains non refundable item", "dana.bash@cnn.com", OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS),
        ("The order matches auto approve criteria", "anderson.cooper@cnn.com", OrderRefundStatus.ORDER_AUTO_REFUNDABLE),
    ]
)    

def test_get_return_refund_decision_status(client, comment, email_addr, expected_order_refund_status):
    logging.info(comment)
    email_addr = email_addr
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    data = resp.json()
    customer_context = CustomerContext(**data[1])
    original_order = customer_context.latest_orders[0]
    customer: Customer = Customer(
            customer_id=customer_context.customer_id, title=customer_context.title, first_name=customer_context.first_name, last_name=customer_context.last_name, email=customer_context.email)

    item = ItemToReturn(product_id= original_order.items[0].product_id, qty= 1)
    return_order = OrderToReturn(thread_id= str(uuid.uuid4()), items= [item])
        
    _, decision = get_initial_return_refund_decision(return_order, original_order, customer)
    assert decision.order_refund_status == expected_order_refund_status


def test_group_memory(client):
    # indirect verify group_memory
    clean_user_memory(client.app.state.support_graph.store, 32108)
    resp = client.post("/api/auth", json={"email_addr": "memory.testing@cnn.com"})
    
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
    assert resp.status_code == 200

    resp_process = client.post(
                "/api/support/return_refund/process",
                json={"thread_id": thread_id, "turn_off_slack_integration_for_test": True})
    assert resp_process.status_code == 200

    graph = client.app.state.support_graph
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = asyncio.run(graph.aget_state(config))
    assert snapshot.values.get("summary") # store in the memory of the current thread. It's not part of history
    assert len(snapshot.values["messages"]) == 2 # recent conversation, keep the latest 2 after summarize_node
    assert not snapshot.values.get("history") # No any conversation of the previous thread
    assert not snapshot.values.get("human_reviews")
    # Simulate slack webhook postback
    text = "on 2026-11-05 19:24:05 UTC Updating the refund request of ID: 1 with status: manual_approve, decision_reason: It looks like a normal transaction., decided_by: threecuptea"
    client.app.state.support_graph.store.put(("users", str(32108)), "hitl-1",  {"text": text, "timestamp": datetime.now(UTC).timestamp()})

    resp = client.post(
            "/api/support/return_refund/chat",
            json={"thread_id": thread_id, "user_conversation": "Hello"})
    assert resp.status_code ==200
    snapshot = asyncio.run(graph.aget_state(config))
    # Adding hitl thread to memory store should reflect in the variable of human_reviews of the snapshot
    assert snapshot.values.get("human_reviews")
    assert text in snapshot.values["human_reviews"]

    # simulate logout and re-login so that we will get a new thread_id for the next conversation
    client.post("/api/auth/logout")

    resp = client.post("/api/auth", json={"email_addr": "memory.testing@cnn.com"})
        
    context = CustomerContext(**resp.json()[1])
    target_order_id = context.latest_orders[0].order_id
    result_init = client.post(
            "/api/support/order/init",
            json={"customer_context": context.model_dump(mode= "json"), "order_number_provided": target_order_id},
    )
    data = result_init.json()
    new_thread_id = data["thread_id"]
    config = {"configurable": {"thread_id": new_thread_id}}
    snapshot = asyncio.run(graph.aget_state(config))
    # order_init_static_response_node will summarize recent conversation
    assert snapshot.values.get("summary") # store in the current thread
    assert len(snapshot.values["messages"]) == 2 # recent conversation, keep the latest 2 after summarize_node
    assert snapshot.values.get("history") # history should have the conversation of the previous thread
    assert snapshot.values.get("human_reviews") # human_reviews should reflect the previous thread's human reviews
       
    clean_user_memory(client.app.state.support_graph.store, 32108)


    



    




    