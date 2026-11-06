from fastapi.testclient import TestClient
from dotenv import load_dotenv
import pytest
import redis
import os
from slack_webhook import app, process_review_response, get_updated_refund_request_and_summary
from models.customer_support_model import CustomerContext, Customer, ItemToReturn, OrderToReturn, RefundRequest
from workflow.customer_support_utils import get_initial_return_refund_decision
from services.demo_data import get_demo_customer
import uuid
from datetime import datetime 

load_dotenv()

test_request_id = 9999
shared_thread_id = str(uuid.uuid4())
TEST_PAYLOAD = {'type': 'block_actions', 'user': {'id': 'U0BGP48TASV', 'username': 'threecuptea', 'name': 'threecuptea', 'team_id': 'T0BHFGFMTJL'}, 'api_app_id': 'A0BJ6CVPD5G', 'token': '5L436A90IncHzTU0swTWOPMS', 'container': {'type': 'message', 'message_ts': '1793835696.919579', 'channel_id': 'C0BGQUCRKV2', 'is_ephemeral': False}, 'trigger_id': '12510419155986.11593559741632.31ccd3c0cfcf08ee87d79ecf6bc813f1', 'team': {'id': 'T0BHFGFMTJL', 'domain': 'threecupteacom'}, 'enterprise': None, 'is_enterprise_install': False, 'channel': {'id': 'C0BGQUCRKV2', 'name': 'customer-support-review-dev'}, 'message': {'user': 'U0BJ8CRSTPB', 'type': 'message', 'ts': '1793835696.919579', 'bot_id': 'B0BJ07TG75H', 'app_id': 'A0BJ6CVPD5G', 'text': "CSR's review is required for the following return for refund request", 'team': 'T0BHFGFMTJL', 'blocks': [{'type': 'section', 'block_id': 'iZLgH', 'text': {'type': 'mrkdwn', 'text': "*CSR's review is required for the following return for refund request*\n\n*Refund request id:* 9999\n*Original order number:* 123458\n*Refund amount:* $569.74\n*Customer name:* Ms. Pamela Brown\n*Delivery date:* 2026-10-10\n*Return items:*\n    Cannondale Trail 3 Mountain Bike, REI, 1, ", 'verbatim': False}}, {'type': 'input', 'block_id': 'reason_input', 'label': {'type': 'plain_text', 'text': 'Reason (Optional):', 'emoji': True}, 'optional': True, 'dispatch_action': False, 'element': {'type': 'plain_text_input', 'action_id': 'reason_value', 'placeholder': {'type': 'plain_text', 'text': 'Elaborate the reason for your decision if needed...', 'emoji': True}, 'multiline': False, 'dispatch_action_config': {'trigger_actions_on': ['on_enter_pressed']}}}, {'type': 'actions', 'block_id': '06d216ee-9171-4a6a-b88a-2c638bd29969|9999|123458|569.74|Ms. Pamela Brown', 'elements': [{'type': 'button', 'action_id': 'approve_action', 'text': {'type': 'plain_text', 'text': ':white_check_mark: Approve', 'emoji': True}, 'style': 'primary', 'value': 'approve'}, {'type': 'button', 'action_id': 'reject_action', 'text': {'type': 'plain_text', 'text': ':x: Reject', 'emoji': True}, 'style': 'danger', 'value': 'reject'}, {'type': 'button', 'action_id': 'flag_action', 'text': {'type': 'plain_text', 'text': ':warning: Flag', 'emoji': True}, 'value': 'flag'}]}]}, 'state': {'values': {'reason_input': {'reason_value': {'type': 'plain_text_input', 'value': 'It looks like a normal return for refund request'}}}}, 'response_url': 'https://hooks.slack.com/actions/T0BHFGFMTJL/12508636977350/N9BhFjdHdoNzt5qaUOG7fbWo', 'actions': [{'type': 'button', 'block_id': '06d216ee-9171-4a6a-b88a-2c638bd29969|9999|123458|569.74|Ms. Pamela Brown', 'action_id': 'approve_action', 'text': {'type': 'plain_text', 'text': ':white_check_mark: Approve', 'emoji': True}, 'value': 'approve', 'style': 'primary', 'action_ts': '1793835785.140390'}]}


@pytest.fixture(scope="class")
def client():
    # `with` triggers the FastAPI lifespan so app.state.support_graph is built.
    with TestClient(app) as test_client:
        yield test_client

@pytest.fixture()
def redis_client():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis_client = redis.Redis.from_url(redis_url)
    yield redis_client
    # Cleanup after the test class is done
    try:
        redis_client.flushdb()
        redis_client.close()
    except Exception as e:
        print(f"Error cleaning up Redis client: {e}")

def test_process_review_response():
    review_response = process_review_response(TEST_PAYLOAD)
    assert review_response.thread_id == "06d216ee-9171-4a6a-b88a-2c638bd29969"
    assert review_response.action == "approve"  
    assert review_response.refund_request_id == 9999
    assert review_response.origin_order_id == 123458
    assert review_response.estimated_amount_refund_incl_tax == 569.74
    assert review_response.customer_name == "Ms. Pamela Brown"
    assert review_response.reason == "It looks like a normal return for refund request"
    assert review_response.decided_by == "threecuptea"
    assert review_response.decided_ts == 1793835696.919579 
    assert review_response.response_url == "https://hooks.slack.com/actions/T0BHFGFMTJL/12508636977350/N9BhFjdHdoNzt5qaUOG7fbWo"         
    
def test_slack_webhook_interaction(client, redis_client):
    email_addr = "pamela.brown@cnn.com"
    customer_context = CustomerContext(**get_demo_customer(email_addr)) # It does not use API and call workflow directly
    target_order = customer_context.latest_orders[0]
    
    customer: Customer = Customer(
            customer_id=customer_context.customer_id, title=customer_context.title, first_name=customer_context.first_name, last_name=customer_context.last_name, email=customer_context.email)
    items = [ItemToReturn(product_id=item.product_id, qty=item.number_units) for item in target_order.items]
    order_to_return = OrderToReturn(thread_id=shared_thread_id, items=items)
    temp_request, _ = get_initial_return_refund_decision(order_to_return, target_order, customer)
    temp_request.status = 'wait_for_manual_review'
    temp_request.requires_manual_approval = True
    temp_request.requires_manual_approval_reason = "the request exceeds the automatic authorized refund amount"

    temp_request.refund_request_id = test_request_id  # Assign the new key to the refund request
    redis_client.set(f"rr:{test_request_id}", temp_request.model_dump_json())

    resp = client.post("/webhook/slack/interactive/test", json=TEST_PAYLOAD)
    assert resp.status_code == 200 # Wait for the background task to complete

    review_response = process_review_response(TEST_PAYLOAD)
    updated_refund_request, _ = get_updated_refund_request_and_summary(temp_request, review_response)
    rr_json = redis_client.get(f"rr:{test_request_id}")  # Retrieve the updated refund request from Redis
    rr = RefundRequest.model_validate_json(rr_json)
    assert rr == updated_refund_request
    assert rr.status == "manual_approve"
    assert rr.decision_reason == review_response.reason
    assert rr.decided_by == review_response.decided_by
    tzinfo = temp_request.returned_order.original_delivery_date.tzinfo
    assert rr.decided_date == datetime.fromtimestamp(review_response.decided_ts, tz=tzinfo)
    assert rr.customer.customer_id == 32100

    # Retrieve the memory note for the user and verify its content
    result = client.app.state.store.get(("users", str(32100)), f"{review_response.thread_id}-hitl-{review_response.refund_request_id}")
    # why this one return empty? but client.app.state.store.get works.
    # result = asyncio.run(load_user_memory(client.app.state.store, 32100, limit=5))  # Assuming customer_id is 32100 for this test
    text= result.value.get("text", "") if result else ""
    assert "manual_approve" in text
    assert review_response.reason in text
    assert review_response.decided_by in text
    assert rr.decided_date.strftime('%Y-%m-%d %H:%M:%S') in text
    # Cleanup: Delete the memory note for the user after the test
    client.app.state.store.delete(("users", str(32100)), f"{review_response.thread_id}-hitl-{review_response.refund_request_id}") 
  