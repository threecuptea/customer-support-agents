import asyncio
import copy
import json
import time
import urllib.parse

import httpx
from fastapi.testclient import TestClient
from dotenv import load_dotenv
import pytest
from backend.models.slack_model import ReviewResponse
from adapters.slack_adapter import slack_client as slack_sdk_client
import slack_webhook
from memory import hitl_memory_key
from main import app as main_app
from slack_webhook import app as slack_app, parse_review_response, get_updated_refund_request, get_updated_summary, InvalidReviewPayload, signature_verifier
from models.customer_support_model import CustomerContext, Customer, ItemToReturn, OrderToReturn, RefundRequest, Order
from workflow.customer_support_utils import get_initial_return_refund_decision
from models.demo_data import get_demo_customer
import uuid

load_dotenv()


shared_thread_id = str(uuid.uuid4())

TEST_PAYLOAD = {'type': 'block_actions', 'user': {'id': 'U0BGP48TASV', 'username': 'threecuptea', 'name': 'threecuptea', 'team_id': 'T0BHFGFMTJL'}, 'api_app_id': 'A0BJ6CVPD5G', 'token': '5L436A90IncHzTU0swTWOPMS', 'container': {'type': 'message', 'message_ts': '1793835696.919579', 'channel_id': 'C0BGQUCRKV2', 'is_ephemeral': False}, 'trigger_id': '12510419155986.11593559741632.31ccd3c0cfcf08ee87d79ecf6bc813f1', 'team': {'id': 'T0BHFGFMTJL', 'domain': 'threecupteacom'}, 'enterprise': None, 'is_enterprise_install': False, 'channel': {'id': 'C0BGQUCRKV2', 'name': 'customer-support-review-dev'}, 'message': {'user': 'U0BJ8CRSTPB', 'type': 'message', 'ts': '1793835696.919579', 'bot_id': 'B0BJ07TG75H', 'app_id': 'A0BJ6CVPD5G', 'text': "CSR's review is required for the following return for refund request", 'team': 'T0BHFGFMTJL', 'blocks': [{'type': 'section', 'block_id': 'iZLgH', 'text': {'type': 'mrkdwn', 'text': "*CSR's review is required for the following return for refund request*\n\n*Refund request id:* 9999\n*Original order number:* 123458\n*Refund amount:* $569.74\n*Customer name:* Ms. Pamela Brown\n*Delivery date:* 2026-10-10\n*Return items:*\n    Cannondale Trail 3 Mountain Bike, REI, 1, ", 'verbatim': False}}, {'type': 'input', 'block_id': 'reason_input', 'label': {'type': 'plain_text', 'text': 'Reason (Optional):', 'emoji': True}, 'optional': True, 'dispatch_action': False, 'element': {'type': 'plain_text_input', 'action_id': 'reason_value', 'placeholder': {'type': 'plain_text', 'text': 'Elaborate the reason for your decision if needed...', 'emoji': True}, 'multiline': False, 'dispatch_action_config': {'trigger_actions_on': ['on_enter_pressed']}}}, {'type': 'actions', 'block_id': '9999', 'elements': [{'type': 'button', 'action_id': 'approve_action', 'text': {'type': 'plain_text', 'text': ':white_check_mark: Approve', 'emoji': True}, 'style': 'primary', 'value': 'approve'}, {'type': 'button', 'action_id': 'reject_action', 'text': {'type': 'plain_text', 'text': ':x: Reject', 'emoji': True}, 'style': 'danger', 'value': 'reject'}, {'type': 'button', 'action_id': 'flag_action', 'text': {'type': 'plain_text', 'text': ':warning: Flag', 'emoji': True}, 'value': 'flag'}]}]}, 'state': {'values': {'reason_input': {'reason_value': {'type': 'plain_text_input', 'value': 'It looks like a normal return for refund request'}}}}, 'response_url': 'https://hooks.slack.com/actions/T0BHFGFMTJL/12508636977350/N9BhFjdHdoNzt5qaUOG7fbWo', 'actions': [{'type': 'button', 'block_id': '9999', 'action_id': 'approve_action', 'text': {'type': 'plain_text', 'text': ':white_check_mark: Approve', 'emoji': True}, 'value': 'approve', 'style': 'primary', 'action_ts': '1793835785.140390'}]}


@pytest.fixture(scope="class")
def main_client():
    with TestClient(main_app) as test_client:
        yield test_client

@pytest.fixture(scope="class")
def slack_client():
    with TestClient(slack_app) as test_client:
        yield test_client


class SlackCalls(list):
    """The acknowledgements sent (list of (ReviewResponse, text)); `.replaces` holds the replace-original calls."""
    def __init__(self):
        super().__init__()
        self.acks: list[tuple[any, str]] = []
        self.replaces: list[tuple[str, RefundRequest]] = []
        self.block_id: str = ""


@pytest.fixture()
def fake_slack_calls(monkeypatch):
    """Replace the Slack acknowledgement and replace-original calls (real HTTP POSTs to hooks.slack.com) with recorders."""
    calls = SlackCalls()

    async def fake_ack(data, text=None):
        calls.acks.append((data, text))

    async def fake_replace(response_url, refund_request):
        calls.replaces.append((response_url, refund_request))

    def fake_post_message(channel, text, blocks):
        calls.block_id = blocks[2]["block_id"]

    monkeypatch.setattr(slack_webhook, "send_reply_text", fake_ack)
    monkeypatch.setattr(slack_webhook, "replace_original_message", fake_replace)
    monkeypatch.setattr(slack_sdk_client, "chat_postMessage", fake_post_message)
    return calls

def make_payload(block_id, action, reason) -> dict:
    """The captured Slack payload, re-pointed at `rr` (block_id carries rr id|order id|amount|name)."""
    payload = copy.deepcopy(TEST_PAYLOAD)
    payload["actions"][0]["block_id"] = block_id
    payload["actions"][0]["value"] = action
    payload["state"]["values"]["reason_input"]["reason_value"]["value"] = reason
    return payload


def signed_post(slack_client, payload=None, *, body=None, signature=None, timestamp=None):
    """POST the way Slack does: urlencoded form `payload=<json>`, signed with HMAC-SHA256 over `v0:<ts>:<body>`.
    The signature comes from the app's own SignatureVerifier (same signing secret), so the REAL endpoint is exercised."""
    if body is None:
        body = urllib.parse.urlencode({"payload": json.dumps(payload)})
    timestamp = timestamp or str(int(time.time()))
    if signature is None:
        signature = signature_verifier.generate_signature(timestamp=timestamp, body=body)
    return slack_client.post(
        "/webhook/slack/interactive",
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Signature": signature,
            "X-Slack-Request-Timestamp": timestamp,
        },
    )


def stored(redis_client, request_id) -> RefundRequest:
    return RefundRequest.model_validate_json(redis_client.get(f"rr:{request_id}"))

@pytest.mark.parametrize(
    "email_addr, requires_manual_approval_reason, notes_to_human_reviwer, action, reason",
    [
        ("pamela.brown@cnn.com", 
            "the request exceeds the automatic authorized refund amount.",
            None,
            "approve",
            "It looks like a normal return!!"
        ),
        ("wolf.blitzer@cnn.com", 
        "the request has passed the return window deadline.",
        "I missed the deadline because I traveled a lot due to the business reason.",
        "reject",
        "Sympathetic but cannot approve!!"
        ),
        ("dana.bash@cnn.com", 
        "the request includes a non-refundable item.",
        "I have never worn the bras I bought.",
        "flag",
        "I like her to take a picture of the item to prove it is unused."
        ),
    ]
)
def test_slack_e2e_flow(main_client, slack_client, fake_slack_calls, redis_client, email_addr, requires_manual_approval_reason, notes_to_human_reviwer, action, reason):
    resp = main_client.post("/api/auth", json={"email_addr": email_addr})
    context = CustomerContext(**resp.json()[1])
    target_order_id = context.latest_orders[0].order_id
    result_init = main_client.post(
            "/api/support/order/init",
            json={"customer_context": context.model_dump(mode= "json"), "order_number_provided": target_order_id},
    )
        # The premise to do any exchange_return_recommendation or return refund is to have ordr_number and target_order
    data = result_init.json()
    thread_id = data["thread_id"]
    target_order = Order(**data['target_order'])
    items = [{"product_id": item.product_id, "qty": item.number_units} for item in target_order.items]

    resp = main_client.post(
        "/api/support/return_refund/init",
        json={"thread_id": thread_id, "items": items})
    data = resp.json()
    assert data["rr_in_process"]
    rr_in_process = RefundRequest(**data.get("rr_in_process"))
    assert rr_in_process.status == "pending"
    
    resp = main_client.post(
        "/api/support/return_refund/process",
        json={"thread_id": thread_id, "notes_for_human_review_override": notes_to_human_reviwer}) # does send to Slack for manual review
    data = resp.json()
    rr_in_process = RefundRequest(**data.get("rr_in_process"))
    assert rr_in_process.requires_manual_approval_reason == requires_manual_approval_reason
    assert rr_in_process.notes_for_human_review_override == notes_to_human_reviwer
    assert rr_in_process.status == "wait_for_manual_review"
    assert stored(redis_client, rr_in_process.refund_request_id)
    
    block_id = fake_slack_calls.block_id
    assert block_id == str(rr_in_process.refund_request_id)
    payload = make_payload(block_id, action, reason)
    signed_post(slack_client, payload)
    assert fake_slack_calls.acks == []
    
    resp = main_client.get(f"/api/support/return_refund/{rr_in_process.refund_request_id}")
    rr1 = RefundRequest(**resp.json())
    assert rr1.status == f"manual_{action}"
    assert rr1.decision_reason == reason

    resp = main_client.get(f"/api/support/return_refund/by_order/{target_order.order_id}")
    rr_list = [RefundRequest(**datum) for datum in resp.json()]
    assert rr_list == [rr1]

    resp = main_client.post(
            "/api/support/return_refund/chat",
            json={"thread_id": thread_id, "user_conversation": "Hello"})
    data = resp.json()
    assert data["rr_in_process"]
    rr_in_process = RefundRequest(**data.get("rr_in_process"))
    assert rr_in_process.status == f"manual_{action}"
    assert rr_in_process.decision_reason == reason
    