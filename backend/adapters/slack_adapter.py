
import os
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import logging
from models.slack_model import ReviewResponse
from models.customer_support_model import RefundRequest
import httpx
from fastapi import HTTPException, status


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID_REVIEW_DEV = os.getenv("SLACK_CHANNEL_ID_REVIEW_DEV")

slack_client = WebClient(token=SLACK_BOT_TOKEN)


def build_interactive_blocks_payload(thread_id: str, refund_request: RefundRequest) -> list[any]:
    """
    Format a Slack interactive message for a refund request review.

    Args:
        thread_id (str): The Slack thread ID to which the message should be sent.
        refund_request (RefundRequest): The refund request to be reviewed.

    Returns:
        list: A list of dictionaries representing the Slack 'blocks' message.
    """
    notes_to_the_reviewer = f"*Notes to the reviewer:* {refund_request.notes_for_human_review_override}\n" if refund_request.notes_for_human_review_override else ""
    customer_name = f"{refund_request.customer.title} {refund_request.customer.first_name} {refund_request.customer.last_name}"
    return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*CSR's review is required for the following return for refund request*\n\n"
                    f"*Refund request id:* {refund_request.refund_request_id}\n*Original order number:* {refund_request.returned_order.origin_order_id}\n"
                    f"*Refund amount:* ${refund_request.returned_order.estimated_amount_refund_incl_tax}\n*Customer name:* {customer_name}\n*Delivery date:* {refund_request.returned_order.original_delivery_date.strftime('%Y-%m-%d')}\n"
                    f"{notes_to_the_reviewer}"
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
                "block_id": f"{thread_id}|{refund_request.refund_request_id}|{refund_request.returned_order.origin_order_id}|{refund_request.returned_order.estimated_amount_refund_incl_tax}|{customer_name}",
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


async def send_interactive_blocks_payload(thread_id: str, refund_request: RefundRequest) -> None:
    """Send an interactive blocks message to Slack for a return/ refund request review.

    Args:
        refund_request (RefundRequest): The refund request to be reviewed.
    """
    blocks = build_interactive_blocks_payload(thread_id, refund_request)
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


async def send_interactive_acknowledgement(data: ReviewResponse) -> None:
    """Send an interactive acknowledgement message to Slack for a return/ refund request review response.

    Args:
        data (ReviewResponse): The review response data containing the action and decision details.

    Returns:
        None
    """
    acknowledgement_text = build_acknowledgement_text(data)
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

    except httpx.HTTPStatusError as e:
        # Handle HTTP status errors (e.g., 4xx, 5xx responses)
        logger.error(f"Error sending review acknowledgement text: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to send review acknowledgement text, received status code: {e.response.status_code} with {e.response.text}")
    except httpx.HTTPError as e:
        # Handle other HTTP errors (e.g., network issues)
        logger.error(f"Error sending review acknowledgement text: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to send review acknowledgement text, received {e}")
