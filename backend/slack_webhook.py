import logging

from fastapi import FastAPI, HTTPException, Request, Form, status
from slack_sdk.signature import SignatureVerifier
import os
from dotenv import load_dotenv
from typing import Any
import json
from zoneinfo import ZoneInfo
from datetime import datetime

from traitlets import This
from models.slack_model import ReviewResponse
from services.slack_adaptor import send_interactive_acknowledgement
from workflow.return_refund_utils import refund_requests_processing_dict
import logging

load_dotenv(override=True)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


app = FastAPI()


signature_verifier = SignatureVerifier(signing_secret=os.environ["SLACK_SIGNING_SECRET"])

# We can deploy this FastAPI app separately (in a different port) to handle Slack integration

@app.get("/webhook/slack/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/slack/interactive")
async def human_review_postback(request: Request):
    # payload: str = Form(...), This will parse form data from request body.  Therefore, cannot call reuest.body() again.
    # The RuntimeError: Stream consumed error in frameworks like FastAPI or Starlette happens when you try to read request.body() more than once.
    body = await request.body()
    signature = request.headers.get("X-Slack-Signature")
    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    
    if not signature_verifier.is_valid(body=body, signature=signature, timestamp=timestamp):
         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid request signature")
    form_data = await request.form()
    
    try:
        data: dict[str, Any] = json.loads(form_data.get("payload"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")
    
    interaction_type = data.get("type")
    if interaction_type != "block_actions":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported interaction type")

    actions = data.get("actions", [])
    if not actions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No human review action or action value found")
    review_response = process_review_response(data)
    await update_refund_request(review_response)
    await send_interactive_acknowledgement(review_response)

    return {"status": "ok"}


def process_review_response(data: dict[str, Any]) -> ReviewResponse:
    action_obj = data.get("actions", [])[0] # if we have action[0], we will definitively have its value and block_id
    action = action_obj.get("value")
    combo = action_obj.get("block_id").split("|")
    refund_request_id = int(combo[0]) if combo else 0
    origin_order_id = int(combo[1]) if len(combo) > 1 else 0
    estimated_amount_refund_incl_tax = float(combo[2]) if len(combo) > 2 else 0.0
    customer_name = combo[3] if len(combo) > 3 else ""
    decided_by = data.get("user", {}).get("name") # Slack definitively provides the user's name and message ts
    decided_ts = float(data.get("message", {}).get("ts"))
    reason = data.get("state", {}).get("values", {}).get("reason_input", {}).get("reason_value", {}).get("value") # this is optional

    return ReviewResponse(
        refund_request_id=refund_request_id,
        origin_order_id=origin_order_id,
        estimated_amount_refund_incl_tax=estimated_amount_refund_incl_tax,
        customer_name=customer_name,
        action=action,
        reason=reason or "",
        decided_by=decided_by or "",
        decided_ts=decided_ts,
    )

async def update_refund_request(review_response: ReviewResponse) -> None:
    # Implement the logic to update the refund request based on the review response
    refund_request = refund_requests_processing_dict.get(review_response.refund_request_id)
    if refund_request:
        refund_request.status = f'manual_{review_response.action}'
        refund_request.decision_reason = review_response.reason
        refund_request.decided_by = review_response.decided_by
        tzinfo = refund_request.returned_order.original_delivery_date.tzinfo
        refund_request.decided_date = datetime.fromtimestamp(review_response.decided_ts, tz=tzinfo)
    else:
        # Only if we shutdown the server before processing the review response
        logger.error(f"Refund request not found for ID: {review_response.refund_request_id}")
        