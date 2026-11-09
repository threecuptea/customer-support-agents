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
from adapters.slack_adapter import send_interactive_acknowledgement, build_not_applied_text, replace_original_message
import logging

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from adapters.redis_adapter import RefundRequestRedisAdapter
from main import DATA_DIR, _resolve_db_path
from langgraph.store.memory import InMemoryStore
from memory import save_user_memory

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
        review_response = process_review_response(data)
    except InvalidReviewPayload as exc:
        # Malformed/forged payload: answer 400 instead of crashing with a 500 (Slack would retry a 500).
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


def process_review_response(data: dict[str, Any]) -> ReviewResponse:
    """Decode the Slack interactive payload. Raises InvalidReviewPayload for anything malformed."""
    try:
        action_obj = data["actions"][0]
        action = action_obj["value"]
        if action not in ALLOWED_ACTIONS:
            raise InvalidReviewPayload(f"unknown action: {action!r}")
        combo = action_obj["block_id"].split("|")
        thread_id = combo[0]
        refund_request_id = int(combo[1])
        origin_order_id = int(combo[2])
        estimated_amount_refund_incl_tax = float(combo[3])
        customer_name = "|".join(combo[4:])  # the name is last, so a '|' inside it is preserved
        decided_ts = float(data["message"]["ts"])
    except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
        raise InvalidReviewPayload(f"malformed payload: {exc!r}") from exc
    if not thread_id or refund_request_id <= 0:
        raise InvalidReviewPayload("missing thread id or refund request id")
    response_url = data.get("response_url", "")
    decided_by = data.get("user", {}).get("name")
    reason = data.get("state", {}).get("values", {}).get("reason_input", {}).get("reason_value", {}).get("value") # this is optional
    reason = (reason or "").strip()[:MAX_REASON_CHARS]  # RefundRequest.decision_reason is capped; never trust the length

    return ReviewResponse(
        response_url=response_url,
        thread_id=thread_id,
        refund_request_id=refund_request_id,
        origin_order_id=origin_order_id,
        estimated_amount_refund_incl_tax=estimated_amount_refund_incl_tax,
        customer_name=customer_name,
        action=action,
        reason=reason or "",
        decided_by=decided_by or "",
        decided_ts=decided_ts,
    )

def get_updated_refund_request_and_summary(refund_request: RefundRequest, review_response: ReviewResponse) -> tuple[RefundRequest, str]:
    refund_request.status = f'manual_{review_response.action}'
    # decision_reason has min_length=1: an empty string would make the stored JSON fail validation when read back
    refund_request.decision_reason = review_response.reason or None
    refund_request.decided_by = review_response.decided_by
    tzinfo = refund_request.returned_order.original_delivery_date.tzinfo
    refund_request.decided_date = datetime.fromtimestamp(review_response.decided_ts, tz=tzinfo)
    
    summary= (f"Updating the refund request of ID: {refund_request.refund_request_id}, origin_order_id: {review_response.origin_order_id}, customer: {review_response.customer_name} with "
                            f"status: {refund_request.status}, "
                            f"decision_reason: {refund_request.decision_reason or 'none given'}, "
                            f"decided_by: {refund_request.decided_by}, "
                            f"decided_date: {refund_request.decided_date.strftime('%Y-%m-%d %H:%M:%S')}")
    return refund_request, summary

async def log_review_updated_summary_into_memory(customer_id: str, review_response: ReviewResponse, summary: str) -> None:
    logger.info("log human review updated summary into memory for customer_id: %s, thread_id: %s", customer_id, f"{review_response.thread_id}-hitl-{review_response.refund_request_id}")
    # Have a different thread to avoid collision with workflow save_user_memory.  There can be multiple refund requests being processed in the same thread
    await save_user_memory(app.state.store, customer_id, f"{review_response.thread_id}-hitl-{review_response.refund_request_id}", summary)


async def post_process_review_response(review_response: ReviewResponse) -> tuple[str, RefundRequest | None]:
    """Apply the reviewer's decision. Returns (outcome, the stored refund request as it is now, or None).

    outcome: "updated" | "not_found" | "order_mismatch" | "status_mismatch".
    Only a request that is STILL `wait_for_manual_review` is changed, atomically (see
    RefundRequestRedisAdapter.update_refund_request_if_status), so a double press, a second reviewer or a Slack
    retry can never flip a request that is already decided, nor overwrite its decided_by/decided_date.
    """
    # It won't be meaningful to return an HTTP error from here: the background task runs after the 200 OK went out.
    adapter = app.state.redis_adapter
    existing = await adapter.retrieve_refund_request(review_response.refund_request_id)
    if existing is None:
        logger.error("Refund request not found for ID: %s", review_response.refund_request_id)
        return "not_found", None
    if existing.returned_order.origin_order_id != review_response.origin_order_id:
        # block_id is only trusted as a pointer; the stored request is the source of truth.
        logger.error("Refund request %s: order id in the Slack payload (%s) does not match the stored one (%s)",
                     review_response.refund_request_id, review_response.origin_order_id, existing.returned_order.origin_order_id)
        return "order_mismatch", existing

    summaries: list[str] = []

    def apply(refund_request: RefundRequest) -> RefundRequest:
        updated, summary = get_updated_refund_request_and_summary(refund_request, review_response)
        summaries.append(summary)
        return updated

    outcome, current = await adapter.update_refund_request_if_status(
        review_response.refund_request_id, "wait_for_manual_review", apply)
    if outcome != "updated":
        logger.warning("Ignored review %r of refund request %s: %s (current status: %s)",
                       review_response.action, review_response.refund_request_id, outcome, current.status if current else None)
        return outcome, current

    logger.info(summaries[-1])
    try:
        await log_review_updated_summary_into_memory(current.customer.customer_id, review_response, summaries[-1])
    except Exception:
        # The refund request is already updated; a memory-store failure must not undo or mask that.
        logger.exception("Could not log the human review of refund request %s into memory", review_response.refund_request_id)
    return "updated", current


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
        await send_interactive_acknowledgement(
            review_response, build_not_applied_text(review_response, outcome, current.status if current else None))


        