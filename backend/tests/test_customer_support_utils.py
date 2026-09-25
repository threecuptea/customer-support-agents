from fastapi.testclient import TestClient
import pytest

from models.model import OrderToReturn, ItemToReturn, CustomerContext, OrderRefundStatus, ReturnRefundDecision
from workflow.customer_support_utils import check_if_order_to_return_in_valid_state, get_return_refund_decision, \
    ORIGINAL_ORDER_FOR_RETURN_IS_NOT_DELIVERED, NOT_A_VALID_PRODUCT_ID, NOT_A_VALID_RETURN_QUANTITY
import uuid
from main import app
import logging

logging.basicConfig(level="INFO")
logger = logging.getLogger(__name__)



@pytest.fixture()
def client():
    # `with` triggers the FastAPI lifespan so app.state.support_graph is built.
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
    context: CustomerContext = CustomerContext(**data['customer_context'])
    original_order = context.latest_orders[0]
    with pytest.raises(ValueError, match=ORIGINAL_ORDER_FOR_RETURN_IS_NOT_DELIVERED):
        check_if_order_to_return_in_valid_state(return_order, original_order)

    email_addr = "manu.raju@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    data = resp.json()
    context: CustomerContext = CustomerContext(**data['customer_context'])
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
    context: CustomerContext = CustomerContext(**data['customer_context'])
    original_order = context.latest_orders[0]

    item = ItemToReturn(product_id= original_order.items[0].product_id, qty= 1)
    return_order = OrderToReturn(thread_id= str(uuid.uuid4()), items= [item])
        
    decision = get_return_refund_decision(return_order, original_order)
    assert decision.order_refund_status == expected_order_refund_status
     

        