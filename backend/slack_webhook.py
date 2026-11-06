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

from models.customer_support_model import RefundRequest
from models.slack_model import ReviewResponse
from adapters.slack_adapter import send_interactive_acknowledgement
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
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")
    
    logger.debug("Received Slack interactive payload: %s", data)
    interaction_type = data.get("type")
    if interaction_type != "block_actions":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported interaction type")

    actions = data.get("actions", [])
    if not actions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No human review action or action value found")
    
    review_response = process_review_response(data)
    background_tasks.add_task(send_interactive_acknowledgement, review_response)
    background_tasks.add_task(post_process_review_response, review_response)
    # The main difference is that asyncio.create_task() schedules a coroutine to run concurrently on the Python event loop immediately, 
    # whereas FastAPI's BackgroundTasks.add_task() queues a callable to run after the HTTP response has already been sent to the client.
    # Slack requires return a response within 3 seconds to avoid timeout errors.
    return {"status": "ok"}

@app.post("/webhook/slack/interactive/test", include_in_schema=False)
async def human_review_postback(data: dict[str, Any], request: Request):
    review_response = process_review_response(data)
    await post_process_review_response(review_response)

def process_review_response(data: dict[str, Any]) -> ReviewResponse:
    response_url = data.get("response_url", "")
    action_obj = data.get("actions", [])[0] # if we have action[0], we will definitively have its value and block_id
    action = action_obj.get("value")
    combo = action_obj.get("block_id").split("|")
    thread_id = combo[0] if combo else ""
    refund_request_id = int(combo[1]) if len(combo) > 1 else 0
    origin_order_id = int(combo[2]) if len(combo) > 2 else 0
    estimated_amount_refund_incl_tax = float(combo[3]) if len(combo) > 3 else 0.0
    customer_name = combo[4] if len(combo) > 4 else ""
    decided_by = data.get("user", {}).get("name") # Slack definitively provides the user's name and message ts
    decided_ts = float(data.get("message", {}).get("ts"))
    reason = data.get("state", {}).get("values", {}).get("reason_input", {}).get("reason_value", {}).get("value") # this is optional

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
    refund_request.decision_reason = review_response.reason
    refund_request.decided_by = review_response.decided_by
    tzinfo = refund_request.returned_order.original_delivery_date.tzinfo
    refund_request.decided_date = datetime.fromtimestamp(review_response.decided_ts, tz=tzinfo)
    
    summary= (f"Updating the refund request of ID: {refund_request.refund_request_id}, origin_order_id: {review_response.origin_order_id}, customer: {review_response.customer_name} with "
                            f"status: {refund_request.status}, "
                            f"decision_reason: {refund_request.decision_reason}, "
                            f"decided_by: {refund_request.decided_by}, "
                            f"decided_date: {refund_request.decided_date.strftime('%Y-%m-%d %H:%M:%S')}")
    return refund_request, summary

async def update_refund_request(refund_request: RefundRequest, summary: str) -> None:
    # Implement the logic to update the refund request based on the review response
    logger.info(summary)
    await app.state.redis_adapter.update_refund_request(refund_request.refund_request_id, refund_request)
    
async def log_review_updated_summary_into_memory(customer_id: str, review_response: ReviewResponse, summary: str) -> None:
    logger.info("log human review updated summary into memory for customer_id: %s, thread_id: %s", customer_id, f"{review_response.thread_id}-hitl-{review_response.refund_request_id}")
    # Have a different thread to avoid collision with workflow save_user_memory.  There can be multiple refund requests being processed in the same thread
    await save_user_memory(app.state.store, customer_id, f"{review_response.thread_id}-hitl-{review_response.refund_request_id}", summary)


async def post_process_review_response(review_response: ReviewResponse) -> None:
    existing_refund_request = await app.state.redis_adapter.retrieve_refund_request(review_response.refund_request_id)
    if existing_refund_request is None:
        # It won't be menaingful to return HTTP error here since the background task will run after sending status: 200 OK
        # Certainly, we don't want to return HTTP error to Slack here either 
        logger.error("Refund request not found for ID: %s", review_response.refund_request_id)
        return

    updated_refund_request, summary = get_updated_refund_request_and_summary(existing_refund_request, review_response)
    await update_refund_request(updated_refund_request, summary)
    await log_review_updated_summary_into_memory(updated_refund_request.customer.customer_id, review_response, summary)


        