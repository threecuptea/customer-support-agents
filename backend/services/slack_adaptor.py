
import os
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import logging
from backend.models.slack_model import ReviewResponse
from models.customer_support_model import RefundRequest


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID_REVIEW_DEV = os.getenv("SLACK_CHANNEL_ID_REVIEW_DEV")

client = WebClient(token=SLACK_BOT_TOKEN)


def build_interactive_blocks_payload(refund_request: RefundRequest) -> list[any]:
    """
    Format a Slack interactive message for a refund request review.

    Args:
        refund_request (RefundRequest): The refund request to be reviewed.
        thread_id (str): The Slack thread ID to which the message should be sent.

    Returns:
        list: A list of dictionaries representing the Slack 'blocks' message.
    """
    customer_name = f"{refund_request.customer.title} {refund_request.customer.first_name} {refund_request.customer.last_name}"
    return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*CSR's review is required for the following return for refund request*\n\n"
                    f"*Refund request id:* {refund_request.refund_request_id}\n*Original order number:* {refund_request.returned_order.origin_order_id}\n"
                    f"*Refund amount:* ${refund_request.returned_order.estimated_amount_refund_incl_tax}\n*Customer name:* {customer_name}\n*Delivery date:* {refund_request.returned_order.original_delivery_date}\n"
                    f"*Return items:*\n" + "\n".join([f"    {item.product_name}, {item.supplier_name}, {item.number_units}, {'NR' if item.nonrefundable_item else ''}" for item in refund_request.returned_order.items])
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
                    "multiline": False
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
        thread_id (str): The thread ID associated with the refund request to be encoded in the block_id of the interactive message.

    Returns:
        None
    """
    try:
        response = client.chat_postMessage(
            channel=SLACK_CHANNEL_ID_REVIEW_DEV,
            text="Return/ refund request review interactive message",
            blocks=build_interactive_blocks_payload(refund_request),
        )
        logger.info(f"The review interactive blocks message was sent successfully! TS: {response['ts']}")

    except SlackApiError as e:
        # Handle api errors (e.g., missing scope, invalid channel ID)
        logger.error(f"Error sending review interactive blocks message: {e.response['error']}")


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
            "⚠️ *The return/ refund request review status: Flagged*\n"
            f"The request id: *{data.refund_request_id}* (origin order id: *{data.origin_order_id}*) of *${data.estimated_amount_refund_incl_tax}*\n"
            f"requested by *{data.customer_name}* was flagged by *{data.decided_by}*\n"
        )
    optional_reason = f"*Reason:* {data.reason}\n" if data.reason else ""
    divider = "-------------------------------------------------------------------------------------------------\n"  
    return text + optional_reason + divider


async def send_interactive_acknowledgement(data: ReviewResponse) -> None:
    """Send an interactive acknowledgement message to Slack for a return/ refund request review response.

    Args:
        data (ReviewResponse): The review response data containing the action and decision details.

    Returns:
        None
    """
    try:
        response = client.chat_postMessage(
            channel=SLACK_CHANNEL_ID_REVIEW_DEV,
            text=build_acknowledgement_text(data),   
        )
        logger.info(f"The review acknowledgement text was sent successfully! TS: {response['ts']}")

    except SlackApiError as e:
        # Handle api errors (e.g., missing scope, invalid channel ID)
        logger.error(f"Error sending review acknowledgement text: {e.response['error']}")