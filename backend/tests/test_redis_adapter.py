
import asyncio
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from main import app
from models.customer_support_model import Customer, CustomerContext, Order, RefundRequest, ItemToReturn, OrderToReturn
from workflow.customer_support_utils import get_initial_return_refund_decision
import uuid
from models.demo_data import get_demo_customer
shared_thread_id = str(uuid.uuid4())

@pytest.fixture(scope="class")
def client():
    # `with` triggers the FastAPI lifespan so app.state.support_graph is built.
    with TestClient(app) as test_client:
        yield test_client

# `redis_client` fixture lives in conftest.py (dedicated test Redis DB, never the dev DB 0).

def test_retrieve_refund_requests_work_correctly(client, redis_client):
    """Test retrieve, insert, update refund requests in Redis adapter.
    This test covers:
    - Creating a refund request by a customer support agent (csa)
    - Retrieving the refund request from the Redis adapter
    - Processing the refund request
    - Creating another refund request by a customer support representative (csr)
    - Retrieving the refund request with and without the csa_only flag
    - update the refund request by the csr
    - retrieve the updated refund request by the csr
    - Also test retrieving refund requests by order with and without the csa_only flag
    """
    email_addr = "manu.raju@cnn.com"
    resp = client.post("/api/auth", json={"email_addr": email_addr})
    customer_context = CustomerContext(**resp.json()[1])
    customer: Customer = Customer(
                customer_id=customer_context.customer_id, title=customer_context.title, 
                first_name=customer_context.first_name, last_name=customer_context.last_name, email=customer_context.email)
    target_order_id = customer_context.latest_orders[0].order_id
    result_init = client.post(
            "/api/support/order/init",
            json={"customer_context": customer_context.model_dump(mode= "json"), "order_number_provided": target_order_id}
    )
    data = result_init.json()
    target_order: Order = Order(**data['target_order'])
    thread_id = data['thread_id']
    it = iter(target_order.items)
    # create a refund request by the customer support agent (csa)
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
    assert retrieved_rr.created_by == "csa"

    client.post(
                "/api/support/return_refund/process",
                json={"thread_id": thread_id, "turn_off_slack_integration_for_test": True})
    retrieved_rr: RefundRequest = client.portal.call(adapter.retrieve_refund_request, rr_in_process.refund_request_id)
    assert retrieved_rr is not None
    assert retrieved_rr.status == 'auto_approve'

    # create another refund request by the customer support representative (csr)
    item2 = next(it)
    order_to_return = OrderToReturn(thread_id=thread_id, items=[ItemToReturn(product_id=item2.product_id, qty=item2.number_units)
        ])
    rr_csr, _ = get_initial_return_refund_decision(order_to_return, target_order, customer)
    assert rr_csr is not None
    assert rr_csr.status == 'pending'
    rr_csr.created_by = "csr" # re-assign created_by to "csr"
    rr_csr_id = client.portal.call(adapter.insert_refund_request, rr_csr)
    # csa_only = False
    retrieved_rr_csr: RefundRequest = client.portal.call(adapter.retrieve_refund_request, rr_csr_id, False)
    assert retrieved_rr_csr is not None
    assert retrieved_rr_csr.status == 'pending'
    assert retrieved_rr_csr.created_by == "csr"
    # csa_only = True
    rr_csa_only: RefundRequest = client.portal.call(adapter.retrieve_refund_request, rr_csr_id, True)
    assert rr_csa_only is None

    rr_csr.status = 'manual_approve'
    rr_csr.decided_by = "threecuptea"
    tzinfo = rr_csr.returned_order.original_delivery_date.tzinfo
    rr_csr.decided_date = datetime.fromtimestamp(float(1794374624.0), tz=tzinfo)
    client.portal.call(adapter.update_refund_request, rr_csr_id, rr_csr)
    # csa_only = False
    retrieved_rr_csr: RefundRequest = client.portal.call(adapter.retrieve_refund_request, rr_csr_id, False)
    assert retrieved_rr_csr is not None
    assert retrieved_rr_csr.status == 'manual_approve'
    assert retrieved_rr_csr.decided_by == "threecuptea"
    assert retrieved_rr_csr.decided_date == rr_csr.decided_date
    # csa_only = False
    retrieved_rrs_by_order: list[RefundRequest] = client.portal.call(adapter.retrieve_refund_requests_by_order, target_order_id, False)
    assert retrieved_rrs_by_order is not None
    assert len(retrieved_rrs_by_order) == 2
    # csa_only = True
    retrieved_rrs_by_order_csa_only: list[RefundRequest] = client.portal.call(adapter.retrieve_refund_requests_by_order, target_order_id, True)
    assert retrieved_rrs_by_order_csa_only is not None
    assert len(retrieved_rrs_by_order_csa_only) == 1

test_request_id = 333

def seed_refund_request(redis_client, status="wait_for_manual_review", request_id=test_request_id) -> RefundRequest:
    email_addr = "pamela.brown@cnn.com"
    customer_context = CustomerContext(**get_demo_customer(email_addr)) # It does not use API and call workflow directly
    target_order = customer_context.latest_orders[0]
    customer: Customer = Customer(
            customer_id=customer_context.customer_id, title=customer_context.title, first_name=customer_context.first_name, last_name=customer_context.last_name, email=customer_context.email)
    items = [ItemToReturn(product_id=item.product_id, qty=item.number_units) for item in target_order.items]
    order_to_return = OrderToReturn(thread_id=shared_thread_id, items=items)
    temp_request, _ = get_initial_return_refund_decision(order_to_return, target_order, customer)
    temp_request.status = status
    temp_request.requires_manual_approval = True
    temp_request.requires_manual_approval_reason = "the request exceeds the automatic authorized refund amount"
    temp_request.refund_request_id = request_id
    redis_client.set(f"rr:{request_id}", temp_request.model_dump_json())
    return temp_request

def test_update_refund_request_if_status_concurrency(client, redis_client):
    """ Practice concurrency with updating refund requests if status changes """
    rr = seed_refund_request(redis_client)
    adapter = client.app.state.redis_adapter
    assert adapter is not None

    async def update_refund_request(i):
        return await adapter.update_refund_request_if_status(
            refund_request_id= rr.refund_request_id,
            expected_status= "wait_for_manual_review",
            updater=lambda rr: rr.model_copy(update={"status": "manual_approve", "decided_by": f"reviewer_{i}"})
        )
    
    async def race():
        return await asyncio.gather(*[update_refund_request(i) for i in range(1, 6)])
    
    results = client.portal.call(race)
    assert results is not None
    assert len(results) == 5
    outcome = [o for o, _ in results]
    assert outcome.count("updated") == 1
    assert outcome.count("status_mismatch") == 4




        


    



    

    
     
