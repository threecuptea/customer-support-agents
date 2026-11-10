
import os
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import logging
from models.slack_model import ReviewResponse
from models.customer_support_model import RefundRequest, MAX_REASON_CHARS
import httpx
from dotenv import load_dotenv

SLACK_RESPONSE_URL_PREFIX = "https://hooks.slack.com/"


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

load_dotenv(override=True)
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID_REVIEW_DEV = os.getenv("SLACK_CHANNEL_ID_REVIEW_DEV")

slack_client = WebClient(token=SLACK_BOT_TOKEN)


def _customer_name(refund_request: RefundRequest) -> str:
    return f"{refund_request.customer.title} {refund_request.customer.first_name} {refund_request.customer.last_name}"


def _details_text(refund_request: RefundRequest, heading: str) -> str:
    """The request details shown in the review message, shared by the pending and the decided versions."""
    notes_to_the_reviewer = f"*Notes to the reviewer:* {refund_request.notes_for_human_review_override}\n" if refund_request.notes_for_human_review_override else ""
    return (f"{heading}\n\n"
            f"*Refund request id:* {refund_request.refund_request_id}\n*Original order number:* {refund_request.returned_order.origin_order_id}\n"
            f"*Refund amount:* ${refund_request.returned_order.estimated_amount_refund_incl_tax}\n*Customer name:* {_customer_name(refund_request)}\n*Delivery date:* {refund_request.returned_order.original_delivery_date.strftime('%Y-%m-%d')}\n"
            f"{notes_to_the_reviewer}"
            f"*Return items:*\n" + "\n".join([f"    {item.product_name}, {item.supplier_name}, {item.number_units}, {'NR' if item.nonrefundable_item else ''}" for item in refund_request.returned_order.items]))


# status -> (emoji, label) for the decided message; anything else falls back to the raw status.
_DECIDED_LABELS = {
    "manual_approve": ("✅", "Approved"),
    "manual_reject": ("❌", "Rejected"),
    "manual_flag": ("🚩", "Flagged"),
}


def build_decided_blocks_payload(refund_request: RefundRequest) -> list[dict]:
    """The review message AFTER a decision: same details, but no reason box and no buttons, plus the outcome.

    Slack replaces the original with this (replace_original), so a channel full of review messages shows at a
    glance which requests still have buttons (need attention) and which are done."""
    emoji, label = _DECIDED_LABELS.get(refund_request.status, ("ℹ️", f"Status: {refund_request.status}"))
    decided_date = refund_request.decided_date.strftime('%Y-%m-%d %H:%M:%S') if refund_request.decided_date else "—"
    outcome = f"{emoji} *{label}* by *{refund_request.decided_by or 'unknown'}* on {decided_date}"
    if refund_request.decision_reason:
        outcome += f"\n*Reason:* {refund_request.decision_reason}"
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": _details_text(refund_request, "*Return for refund request (reviewed)*")}},
        {"type": "section", "text": {"type": "mrkdwn", "text": outcome}},
        {"type": "divider"},  # visual end of this refund request in a busy channel
    ]


def build_interactive_blocks_payload(refund_request: RefundRequest) -> list[any]:
    """
    Format a Slack interactive message for a refund request review.

    Args:
        refund_request (RefundRequest): The refund request to be reviewed.

    Returns:
        list: A list of dictionaries representing the Slack 'blocks' message.
    """
    customer_name = _customer_name(refund_request)
    return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": _details_text(refund_request, "*CSR's review is required for the following return for refund request*")
                }
            },
            {
                "type": "input",
                "block_id": "reason_input",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "reason_value",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Elaborate the reason for your decision if needed..."
                    },
                    "multiline": False,
                    "max_length": MAX_REASON_CHARS
                },
                "label": {
                    "type": "plain_text",
                    "text": "Reason (Optional):"
                }
            },
            {
                "type": "actions",
                "block_id": f"{refund_request.refund_request_id}|{refund_request.returned_order.origin_order_id}|{refund_request.returned_order.estimated_amount_refund_incl_tax}|{customer_name}",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "✅ Approve"
                        },
                        "style": "primary",
                        "action_id": "approve_action",
                        "value": "approve"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "❌ Reject"
                        },
                        "style": "danger",
                        "action_id": "reject_action",
                        "value": "reject"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "⚠️ Flag"
                        },
                        "action_id": "flag_action",
                        "value": "flag"
                    }
                ]
            }
        ]


async def send_interactive_blocks_payload(refund_request: RefundRequest) -> None:
    """Send an interactive blocks message to Slack for a return/ refund request review.

    Args:
        refund_request (RefundRequest): The refund request to be reviewed.
    """
    blocks = build_interactive_blocks_payload(refund_request)
    logger.debug(f"Prepared interactive blocks payload: {blocks}")
    try:
        response = slack_client.chat_postMessage(
            channel=SLACK_CHANNEL_ID_REVIEW_DEV,
            text="CSR's review is required for the following return for refund request",
            blocks=blocks
        )
        logger.info(f"The return for refund review blocks message for ID: {refund_request.refund_request_id} was sent successfully to Slack  channel: 'customer-support-dev'")
    except SlackApiError as e:
        logger.error(f"Failed to send interactive blocks message to Slack: {e}")


def build_acknowledgement_text(data: ReviewResponse) -> str:
    """Build the acknowledgement text for a return/ refund request review response.

    Args:
        data (ReviewResponse): The review response data containing the action and decision details.

    Returns:
        str: The formatted acknowledgement text.
    """
    text = ""
    if data.action == "approve":
        text = (
            "✅ *The return/ refund request review status: Approved*\n"
            f"The request id: *{data.refund_request_id}* (origin order id: *{data.origin_order_id}*) of *${data.estimated_amount_refund_incl_tax}*\n"
            f"requested by *{data.customer_name}* was approved by *{data.decided_by}*\n"
        )
    elif data.action == "reject":
        text = (
            "❌ *The return/ refund request review status: Rejected*\n"
            f"The request id: *{data.refund_request_id}* (origin order id: *{data.origin_order_id}*) of *${data.estimated_amount_refund_incl_tax}*\n"
            f"requested by *{data.customer_name}* was rejected by *{data.decided_by}*\n"
        )
    elif data.action == "flag":
        text = (
            "🚩 *The return/ refund request review status: Flagged*\n"
            f"The request id: *{data.refund_request_id}* (origin order id: *{data.origin_order_id}*) of *${data.estimated_amount_refund_incl_tax}*\n"
            f"requested by *{data.customer_name}* was flagged by *{data.decided_by}*\n"
            "⚠️ Please review this invoice manually and follow up with the customer.\n"
        )
    optional_reason = f"*Reason:* {data.reason}\n" if data.reason else ""
    divider = "-------------------------------------------------------------------------------------------------\n"  
    return text + optional_reason + divider


def build_not_applied_text(data: ReviewResponse, outcome: str, current_status: str | None = None) -> str:
    """Acknowledgement for a button press that did NOT change the refund request (duplicate press, unknown id, ...)."""
    divider = "-------------------------------------------------------------------------------------------------\n"
    head = f"The request id: *{data.refund_request_id}* (origin order id: *{data.origin_order_id}*)"
    if outcome == "status_mismatch":
        text = (f"ℹ️ *No change made.* {head} is no longer waiting for a review "
                f"(current status: *{current_status}*). Your *{data.action}* from *{data.decided_by}* was ignored.\n")
    elif outcome == "not_found":
        text = f"⚠️ *No change made.* {head} was not found. Your *{data.action}* from *{data.decided_by}* was ignored.\n"
    elif outcome == "order_mismatch":
        text = f"⚠️ *No change made.* {head} does not match the stored request. Your *{data.action}* was ignored.\n"
    else:
        text = f"⚠️ *The review could not be recorded* for {head}. Please try again or contact support.\n"
    return text + divider


async def send_interactive_acknowledgement(data: ReviewResponse, text: str | None = None) -> None:
    """Send an interactive acknowledgement message to Slack for a return/ refund request review response.

    Best effort: this runs in a background task after Slack already got its 200, so there is nobody to
    raise an HTTP error to. Failures are logged and swallowed; they must never affect the refund update.

    Args:
        data (ReviewResponse): The review response data containing the action and decision details.
        text: optional replacement for the default acknowledgement text.

    Returns:
        None
    """
    if not data.response_url.startswith(SLACK_RESPONSE_URL_PREFIX):
        # response_url comes from the payload; only ever post to Slack itself (SSRF guard).
        logger.error("Refusing to post an acknowledgement to a non-Slack response_url")
        return
    acknowledgement_text = text if text is not None else build_acknowledgement_text(data)
    logger.debug(f"Prepared acknowledgement text: {acknowledgement_text}")
    try:
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            payload = {
            "response_type": "in_channel",
            "text": acknowledgement_text,
            "replace_original": False  # Purely acknowledgement, do not replace the original message
            }
            # The response_url dynamically generated responding to a specific interaction is different from the static webhook URL tied to the Slack Bot token 
            # after re-install into the Slack workspace for permission changes.  Therefore, we cannot use slack_client that send the acknowledge to the static webhook URL.
            logger.info("Sending an interactive acknowledgement to the response_url")
            response = await http_client.post(
                data.response_url,
                json=payload
            )
            response.raise_for_status()

    except httpx.HTTPError as e:
        # 4xx/5xx (e.g. expired response_url: 30 minutes or 5 uses) or network trouble
        logger.error(f"Error sending review acknowledgement text: {e}")


async def replace_original_message(response_url: str, refund_request: RefundRequest) -> None:
    """Replace the original review message (reason box + buttons) with the decided version (details + outcome).

    Uses the interaction's response_url with replace_original=True. Best effort like the acknowledgement:
    errors are logged and swallowed. Note a response_url allows 5 uses within 30 minutes; one press uses 2
    (this + the acknowledgement)."""
    if not response_url.startswith(SLACK_RESPONSE_URL_PREFIX):
        logger.error("Refusing to post to a non-Slack response_url")
        return
    payload = {
        "replace_original": True,
        "text": f"Return for refund request {refund_request.refund_request_id}: {refund_request.status}",  # notification/fallback text
        "blocks": build_decided_blocks_payload(refund_request),
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            response = await http_client.post(response_url, json=payload)
            response.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(f"Error replacing the original review message: {e}")
