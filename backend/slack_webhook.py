from __future__ import annotations
import logging
import threading

from fastapi import FastAPI, HTTPException, Request, status, BackgroundTasks
from slack_sdk.signature import SignatureVerifier
import os
from dotenv import load_dotenv
from typing import Any, AsyncGenerator
import json
from datetime import datetime

from models.customer_support_model import RefundRequest, MAX_REASON_CHARS
from models.slack_model import ReviewResponse
from adapters.slack_adapter import build_not_applied_text, replace_original_message, send_reply_text, customer_name
import logging

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from adapters.redis_adapter import RefundRequestRedisAdapter
from paths import DATA_DIR, resolve_db_path as _resolve_db_path
from langgraph.store.memory import InMemoryStore
from memory import save_user_memory, hitl_memory_key
from text_safety import clean_free_text

load_dotenv(override=True)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Connect to Redis for refund request cache so that both main.py and slack_webhook.py can access the same refund request processing state."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    app.state.redis_adapter = RefundRequestRedisAdapter(redis_url=redis_url)
    await app.state.redis_adapter.connect()

    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true" # we are using demo mode in dev environment.
    store_db = _resolve_db_path(os.getenv("STORE_DB"))
    connection_url = os.getenv("CONNECTION_URL")
    if demo_mode and store_db:
        with threading.Lock():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        # We are not persisting any business entities in demo_mode (local)
        from langgraph.store.sqlite.aio import AsyncSqliteStore           
        async with AsyncSqliteStore.from_conn_string(store_db) as store:
            app.state.store = store
            yield 
    elif not demo_mode and connection_url:    
        from langgraph.store.postgres import AsyncPostgresStore
            # not testing the connection here in production
        async with AsyncPostgresStore.from_conn_string(f'{connection_url}/store') as store:
            app.state.store = store
            yield
    else:
        logger.info("Using in-memory MemorySaver and InMemoryStore")
        store = InMemoryStore()
        app.state.store = store
        yield
    await app.state.redis_adapter.disconnect()

app = FastAPI(lifespan=lifespan)


signature_verifier = SignatureVerifier(signing_secret=os.environ["SLACK_SIGNING_SECRET"])

# We can deploy this FastAPI app separately (in a different port) to handle Slack integration

@app.get("/webhook/slack/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/slack/interactive")
async def human_review_postback(request: Request, background_tasks: BackgroundTasks):
    # payload: str = Form(...), This will parse form data from request body.  Therefore, cannot call reuest.body() again.
    # The RuntimeError: Stream consumed error in frameworks like FastAPI or Starlette happens when you try to read request.body() more than once.
    logger.info(f"Received Slack interactive payload")
    body = await request.body()
    signature = request.headers.get("X-Slack-Signature")
    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    
    if not signature_verifier.is_valid(body=body, signature=signature, timestamp=timestamp):
         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid request signature")
    form_data = await request.form()
    
    try:
        data: dict[str, Any] = json.loads(form_data.get("payload"))
    except (json.JSONDecodeError, TypeError):  # TypeError: no `payload` form field
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")
    if not isinstance(data, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    interaction_type = data.get("type")
    if interaction_type != "block_actions":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported interaction type")

    actions = data.get("actions", [])
    if not actions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No human review action or action value found")
    
    try:
        review_response = parse_review_response(data)
    except InvalidReviewPayload as exc:
        # Malformed/forged payload: answer 400 (bad request) instead of crashing with a 500 (Slack would retry a 500).
        # HTTP 400 is a client-side error.  Slack know that the client sent a malformed request and client need to correct and re-send
        # Slack will not retry the request when receiving a 400 response.
        # HTTP 500 is a server-side error.  Slack will retry the request when receiving a 500 response.
        logger.warning("Rejected malformed Slack interactive payload: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid review payload")
    # One background task, in a fixed order: update the refund request FIRST, acknowledge SECOND.
    # (BackgroundTasks stops at the first task that raises, so a failing acknowledgement used to cancel the update.)
    # The main difference is that asyncio.create_task() schedules a coroutine to run concurrently on the Python event loop immediately,
    # whereas FastAPI's BackgroundTasks.add_task() queues a callable to run after the HTTP response has already been sent to the client.
    # Slack requires return a response within 3 seconds to avoid timeout errors.
    background_tasks.add_task(handle_review_response, review_response)
    return {"status": "ok"}


class InvalidReviewPayload(ValueError):
    pass


ALLOWED_ACTIONS = ("approve", "reject", "flag")


def parse_review_response(data: dict[str, Any]) -> ReviewResponse:
    """Decode the Slack interactive payload. Raises InvalidReviewPayload for anything malformed."""
    try:
        action_obj = data["actions"][0]
        action = action_obj["value"]
        if action not in ALLOWED_ACTIONS:
            raise InvalidReviewPayload(f"unknown action: {action!r}")
        refund_request_id = int(action_obj["block_id"])
        decided_ts = float(data["message"]["ts"])
    except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
        raise InvalidReviewPayload(f"malformed payload: {exc!r}") from exc
    if refund_request_id <= 0:
        raise InvalidReviewPayload("missing refund request id")
    response_url = data.get("response_url", "")
    decided_by = data.get("user", {}).get("name")
    reason = data.get("state", {}).get("values", {}).get("reason_input", {}).get("reason_value", {}).get("value") # this is optional
    reason = clean_free_text(reason, MAX_REASON_CHARS)  # capped (RefundRequest.decision_reason), no control/invisible chars, one line

    return ReviewResponse(
        response_url=response_url,
        refund_request_id=refund_request_id,
        action=action,
        reason=reason or "",
        decided_by=decided_by or "",
        decided_ts=decided_ts,
    )

def get_updated_refund_request(refund_request: RefundRequest, review_response: ReviewResponse) -> RefundRequest:
    refund_request.status = f'manual_{review_response.action}'
    # decision_reason has min_length=1: an empty string would make the stored JSON fail validation when read back
    refund_request.decision_reason = review_response.reason or None
    refund_request.decided_by = review_response.decided_by
    tzinfo = refund_request.returned_order.original_delivery_date.tzinfo
    refund_request.decided_date = datetime.fromtimestamp(review_response.decided_ts, tz=tzinfo)
    
    return refund_request

def get_updated_summary(updated_rr: RefundRequest) -> str:
    return (f"Updating the refund request of ID: {updated_rr.refund_request_id}, origin_order_id: {updated_rr.returned_order.origin_order_id}, customer: {customer_name(updated_rr)} with "
                            f"status: {updated_rr.status}, "
                            f"decision_reason: {(chr(34) + updated_rr.decision_reason + chr(34)) if updated_rr.decision_reason else 'none given'}, "
                            f"decided_by: {updated_rr.decided_by}, "
                            f"decided_date: {updated_rr.decided_date.strftime('%Y-%m-%d %H:%M:%S')}")

async def log_review_updated_summary_into_memory(customer_id: str, review_response: ReviewResponse, summary: str) -> None:
    key = hitl_memory_key(review_response.refund_request_id)
    logger.info("log human review updated summary into memory for customer_id: %s, key: %s", customer_id, key)
    # A key of its own (hitl-<refund_request_id>, unique per refund request) avoids collision with the workflow's per-thread
    # save_user_memory keys; nothing from the Slack payload but the (validated) refund request id goes into it.
    await save_user_memory(app.state.store, customer_id, key, summary)


async def post_process_review_response(review_response: ReviewResponse) -> tuple[str, RefundRequest | None]:
    """Apply the reviewer's decision. Returns (outcome, the stored refund request as it is now, or None).

    outcome: "updated" | "not_found" |  "status_mismatch".
    Only a request that is STILL `wait_for_manual_review` is changed, atomically (see
    RefundRequestRedisAdapter.update_refund_request_if_status), so a double press, a second reviewer or a Slack
    retry can never flip a request that is already decided, nor overwrite its decided_by/decided_date.
    """
    # ReviewResponse should only carry refund_request_id and the action taken by the reviewer. The source of truth for the refund request details is the stored RefundRequest object.
    # We should not need retrieve_refund_request here, adapter.update_refund_request_if_status will handle the check anyway
    def apply(refund_request: RefundRequest) -> RefundRequest:
        return get_updated_refund_request(refund_request, review_response)
    adapter = app.state.redis_adapter
    outcome, updated_rr = await adapter.update_refund_request_if_status(
        review_response.refund_request_id, "wait_for_manual_review", apply)
    if outcome != "updated":
        logger.warning("Ignored review %r of refund request %s: %s (current status: %s)",
                       review_response.action, review_response.refund_request_id, outcome, updated_rr.status if updated_rr else None)
        return outcome, updated_rr
    # Log the summary of the updated refund request
    summary= get_updated_summary(updated_rr)
    logger.info(summary)
    try:
        await log_review_updated_summary_into_memory(updated_rr.customer.customer_id, review_response, summary)
    except Exception:
        # The refund request is already updated; a memory-store failure must not undo or mask that.
        logger.exception("Could not log the human review of refund request %s into memory", review_response.refund_request_id)
    return "updated", updated_rr


async def handle_review_response(review_response: ReviewResponse) -> None:
    """Background task: update the refund request first, then tell Slack what happened.

    1. If the request is decided (by this press, or by an earlier one), replace the original message - details
       without the reason box and buttons, plus the outcome - so reviewed requests stand out from pending ones.
    2. No separate acknowledgement for a successful decision (the replaced message already says it). If nothing
       changed (duplicate/late press, unknown request, ...), post the "No change made" explanation."""
    try:
        outcome, current = await post_process_review_response(review_response)
    except Exception:
        logger.exception("Could not apply the review of refund request %s", review_response.refund_request_id)
        outcome, current = "error", None
    if outcome in ("updated", "status_mismatch") and current is not None:
        # status_mismatch: this press lost the race / was a duplicate, but the message may still show stale buttons
        await replace_original_message(review_response.response_url, current)
    if outcome != "updated":
        await send_reply_text(
            review_response, build_not_applied_text(review_response, outcome, current.status if current else None))


        