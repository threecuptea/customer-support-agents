
from multiprocessing import context

import pytest
from fastapi.testclient import TestClient
from main import app
from models.customer_support_model import CustomerContext, Order, RefundRequest
import uuid
from workflow.customer_support_utils import get_initial_return_refund_decision


@pytest.fixture(scope="class")
def client():
    # `with` triggers the FastAPI lifespan so app.state.support_graph is built.
    with TestClient(app) as test_client:
        yield test_client


# `redis_client` fixture lives in conftest.py (dedicated test Redis DB, never the dev DB 0).

def test_retrieve_refund_requests_work_correctly(client, redis_client):
    email_addr = "manu.raju@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    customer_context = CustomerContext(**resp.json()[1])
    target_order_id = customer_context.latest_orders[0].order_id
    result_init = client.post(
            "/api/support/order/init",
            json={"customer_context": customer_context.model_dump(mode= "json"), "order_number_provided": target_order_id}
    )
    data = result_init.json()
    target_order: Order = Order(**data['target_order'])
    thread_id = data['thread_id']
    it = iter(target_order.items)
    item1 = next(it)
    resp = client.post(
            "/api/support/return_refund/init",
            json={"thread_id": thread_id, "items": [{"product_id": item1.product_id, "qty": item1.number_units}]})
    rr_in_process = RefundRequest(**resp.json()['rr_in_process'])
    assert rr_in_process is not None
    adapter = client.app.state.redis_adapter
    assert adapter is not None
    retrieved_rr: RefundRequest = client.portal.call(adapter.retrieve_refund_request, rr_in_process.refund_request_id)
    assert retrieved_rr is not None
    assert retrieved_rr.status == 'pending'

    
    
     
