from __future__ import annotations

from fastapi import Request, HTTPException
import os
from langchain_core.messages import HumanMessage
from models.customer_support_model import ExchangeOrReturnOutput, GeneralSupportRequest, OrderInitRequest, OrderInitResponse, \
    GenericChatInput, SummarizeOnExit, OrderToReturn, Order, ExchangeOrReturnInput, GenericResponse, InitialReturnRefundResponse, RefundRequest, \
    ReturnRefundProcessRequest, ReturnRefundProcessResponse, ReturnRefundChatResponse
from services.ownership import check_context_owner, check_thread_owner, owns_refund_request, session_email
import uuid
import logging
from workflow.customer_support_utils import check_if_order_to_return_in_valid_state, group_memory


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

integrate_slack = os.getenv("INTEGRATE_SLACK", "false").lower() == "true"


async def invoke_general_support_workflow(support: GeneralSupportRequest, request: Request) -> GenericResponse:
    graph = request.app.state.support_graph
    check_context_owner(request, support.customer_context)
    if support.thread_id:
        await check_thread_owner(graph, support.thread_id, request)
    thread_id = support.thread_id if support.thread_id else str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {
            "messages": [HumanMessage(content= support.general_inquiry)],
            "customer_context": support.customer_context,
            "support_category": "general/ others",
            "general_inquiry": support.general_inquiry,
            "escalation_reason": None,
            "faq_match_evals": None,
            "general_issue_resolved": False,
            "summarize_on_exit": False,
    }
    # {history, human_reviews}
    memory_dict = await group_memory(store= graph.store, user_id= support.customer_context.customer_id, thread_id= support.thread_id)
    # Remove history as SystemMessage so that summary won't include history
    if memory_dict:
        initial_state.update(memory_dict)
    try:
        customer_support_state  = await graph.ainvoke(initial_state, config)
        return GenericResponse(
           thread_id=thread_id,
           response=customer_support_state["response"],
        )

    except Exception as exc:
        error_msg = "Error starting customer-support general-inquiry"
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=f"{error_msg}: {exc}")
    
async def invoke_order_init_workflow(support: OrderInitRequest, request: Request) -> OrderInitResponse:
    graph = request.app.state.support_graph
    check_context_owner(request, support.customer_context)
    if support.thread_id:
        await check_thread_owner(graph, support.thread_id, request)
    thread_id = support.thread_id if support.thread_id else str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    # We can add "human_escalates" later. history is pretty steady. However, external human_reviews and human_escalates can come any time.
    memory_dict = await group_memory(store= graph.store, user_id= support.customer_context.customer_id, thread_id= support.thread_id)
    # Remove history as SystemMessage so that summary won't include history
    initial_state = {
            "messages": [HumanMessage(content= f"Order inquiry: {support.order_number_provided}")],
            "customer_context": support.customer_context,
            "support_category": "order_inquery",
            "order_number_provided": support.order_number_provided,
            "target_order": None,
            "order_is_revisit": False,
            "order_has_refund_request": False,
            "order_issue_escalated": False,
            "order_issue_resolved": False,
            "order_turns": 0,
            "order_prior_topic": None,
            "escalation_reason": None,
            "summarize_on_exit": False,
    }
    if memory_dict:
        initial_state.update(memory_dict)
    try:
       customer_support_state  = await graph.ainvoke(initial_state, config)
       return OrderInitResponse(
           thread_id=thread_id,
           target_order= customer_support_state["target_order"],
           response=customer_support_state["response"],
       )
    except Exception as exc:
        error_msg = "Error initializing customer-support order_inquery"
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=f"{error_msg}: {exc}")
    
async def invoke_order_continue_workflow(support: GenericChatInput, request: Request) -> GenericResponse:
    graph = request.app.state.support_graph
    thread_id = support.thread_id
    await check_thread_owner(graph, thread_id, request)
    config = {"configurable": {"thread_id": thread_id}}
  
    # Guard against a thread_id that was never initialized via /order/init (or whose init failed to find
    # an order): route_branch/order_continue_chat_node assume target_order is already populated, so without
    # this check a stale/uninitialized thread_id would crash the graph instead of returning a clear error.
    existing_state = await graph.aget_state(config)
    if not existing_state.values.get("target_order") or not existing_state.values.get("customer_context"):
        raise HTTPException(
            status_code=400,
            detail="Order inquiry session not found or expired. Please restart from the order selection screen.",
        )
    initial_state = {
        "messages": [HumanMessage(content= support.user_conversation)],
        # Every endpoint sets its own category (route_branch dispatches on it). Without this, a thread that last
        # visited the exchange/return or return/refund screens would route an order chat message to that flow.
        "support_category": "order_inquery",
    }

    # history is pretty steady and has been captured in initial states. We like to capture only the latest external human_reviews and human_escalates.
    memory_dict = await group_memory(store= graph.store, user_id= existing_state.values.get("customer_context").customer_id, thread_id= thread_id, include_history=False)
    if memory_dict:
        initial_state.update(memory_dict)
    try:
       customer_support_state  = await graph.ainvoke(initial_state, config)
       # escalation_reason is for the future use: communication to CSR in slack
       return GenericResponse(
           thread_id=thread_id,
           response=customer_support_state["response"],
       )
    except Exception as exc:
        error_msg = "Error continuing customer-support order_inquiry"
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=f"{error_msg}: {exc}")

async def invoke_exchange_return_recommendation_workflow(exchange_return_reason: ExchangeOrReturnInput, request: Request) -> ExchangeOrReturnOutput:
    graph = request.app.state.support_graph
    thread_id = exchange_return_reason.thread_id
    await check_thread_owner(graph, thread_id, request)
    config = {"configurable": {"thread_id": thread_id}}
    # Guard against a thread_id that was never initialized via /order/init: this node reads
    # state["order_number_provided"] without a fallback, so a missing/stale thread_id would
    # otherwise crash the graph instead of returning a clear error.
    existing_state = await graph.aget_state(config)
    if not existing_state.values.get("target_order"):
        raise HTTPException(
            status_code=400,
            detail="Order inquiry session not found or expired. Please restart from the order selection screen.",
        )
    messages = []
    messages.append(HumanMessage(content= f"The customers' exchange/ return reason: {exchange_return_reason.reason_option.value}"))
    initial_state = {
        "messages": messages,
        "support_category": "exchange_or_return",
        "exchange_return_reason": exchange_return_reason,
        "special_exchange_handling": False,
        "escalation_reason": None,   
    }     
    try:
        customer_support_state  = await graph.ainvoke(initial_state, config)
        return ExchangeOrReturnOutput(
            thread_id=thread_id,
            response=customer_support_state["response"],
            special_exchange_handling=customer_support_state["special_exchange_handling"],
        )
    except Exception as exc:
        error_msg = "Error getting exchange or return recommendation based upon the given reason"
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=f"{error_msg}: {exc}")


ONE_REFUND_REQUEST_PER_ORDER = ("This order already has a return/ refund request. For any further return of this order, "
    "please contact a customer-support representative.")


async def invoke_return_refund_init_workflow(order_to_return: OrderToReturn, request: Request) -> InitialReturnRefundResponse:
    graph = request.app.state.support_graph
    thread_id = order_to_return.thread_id
    await check_thread_owner(graph, thread_id, request)
    config = {"configurable": {"thread_id": thread_id}}
    existing_state = await graph.aget_state(config)       
    try:
        # verify if the target order and order to return are in a valid state to start a return refund.
        target_order: Order = existing_state.values.get("target_order")
        check_if_order_to_return_in_valid_state(order_to_return, target_order)
        # One CSA refund request per order: once it has left `pending` the agent creates no other. A further
        # return (e.g. the other items of the order) goes to a human CSR. A `pending` one is adopted by the init node.
        existing_requests = await request.app.state.redis_adapter.retrieve_refund_requests_by_order(target_order.order_id)
        if any(rr.status != "pending" and owns_refund_request(request, rr) for rr in existing_requests):
            raise ValueError(ONE_REFUND_REQUEST_PER_ORDER)
        initial_state = {
            "messages": [HumanMessage(content= f"Initialize return refund: {target_order.order_id}")],
            "support_category": "return_refund",
            "order_to_return": order_to_return,
            "initial_return_refund_decision": None,
            "proceed_to_process_return_refund": False, 
            "desire_to_chat_return_refund":False,
            "request_human_review_return_refund": False,
            "notes_for_human_review_override": None,
            "rr_id_in_process": 0,
            "rr_being_processed": False,
        }
        memory_dict = await group_memory(store= graph.store, user_id= existing_state.values.get("customer_context").customer_id, thread_id= thread_id, include_history=False)
        if memory_dict:
            initial_state.update(memory_dict)

        customer_support_state  = await graph.ainvoke(initial_state, config)
        rr_in_process = await request.app.state.redis_adapter.retrieve_refund_request(customer_support_state["rr_id_in_process"])
        return InitialReturnRefundResponse(
            thread_id = thread_id,
            response = customer_support_state["response"],
            initial_return_refund_decision = customer_support_state["initial_return_refund_decision"],
            rr_in_process = rr_in_process,
            rr_being_processed = customer_support_state["rr_being_processed"],
        )
    except ValueError as verr:
        error_msg = f"Error start a return refund request for thread: {order_to_return.thread_id}"
        logger.exception(error_msg)
        raise HTTPException(status_code=400, detail=f"{error_msg}: {verr}")
    except Exception as exc:
        error_msg = f"Error start a return refund request for thread: {order_to_return.thread_id}"
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=f"{error_msg}: {exc}")

async def _require_refund_request_in_redis(request: Request, rr_id_in_process: int) -> None:
    """The LangGraph checkpoint (sqlite) outlives Redis (a cache that can be flushed/restarted). If the refund
    request that the thread points to is gone, answer a clean 400 instead of letting a node crash with a 500."""
    try:
        rr = await request.app.state.redis_adapter.retrieve_refund_request(rr_id_in_process)
    except Exception as exc:
        logger.exception("Error retrieving refund request %s", rr_id_in_process)
        raise HTTPException(status_code=500, detail=f"Error retrieving refund request: {exc}")
    if rr is None:
        raise HTTPException(
            status_code=400,
            detail="Return/ refund request not found or expired. Please Exit and re-login.",
        )


async def invoke_return_refund_process_workflow(request_to_process: ReturnRefundProcessRequest, request: Request) -> ReturnRefundProcessResponse:
    graph = request.app.state.support_graph
    thread_id = request_to_process.thread_id
    await check_thread_owner(graph, thread_id, request)
    config = {"configurable": {"thread_id": thread_id}}
    existing_state = await graph.aget_state(config)
    rr_id_in_process = existing_state.values.get("rr_id_in_process")
    if not rr_id_in_process:
        raise HTTPException(
            status_code=400,
            detail="Return/ refund session not found or expired. Please Exit and re-login.",
        )
    await _require_refund_request_in_redis(request, rr_id_in_process)
    if existing_state.values.get("rr_being_processed"):
        raise HTTPException(
            status_code=400,
            detail="This return/ refund request has already been processed.",
        )
    try:
        message = HumanMessage(content= f"Please process return refund for order id: {existing_state.values.get('order_number_provided')}")
        initial_state = {
            "messages": [message],
            "proceed_to_process_return_refund": True,
            "notes_for_human_review_override": request_to_process.notes_for_human_review_override
        }
        customer_support_state  = await graph.ainvoke(initial_state, config)
        rr_in_process = await request.app.state.redis_adapter.retrieve_refund_request(customer_support_state["rr_id_in_process"])
        turn_off_slack_integration_for_test = request_to_process.turn_off_slack_integration_for_test
        if rr_in_process and rr_in_process.status == "wait_for_manual_review" and integrate_slack and not turn_off_slack_integration_for_test:
            from adapters.slack_adapter import send_interactive_blocks_payload
            await send_interactive_blocks_payload(rr_in_process)
        # rr_in_process is a snapshot: it can change after a CSR presses Approve/Reject/Flag in Slack
        # while the status is wait_for_manual_review.
        return ReturnRefundProcessResponse(
            thread_id = thread_id,
            response = customer_support_state["response"],
            rr_in_process = rr_in_process,
            rr_being_processed = customer_support_state["rr_being_processed"],
        )
    except Exception as exc:
        error_msg = f"Error process a return refund request for the order: {existing_state.values.get('order_number_provided')}"
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=f"{error_msg}: {exc}")

async def invoke_return_refund_chat_workflow(support: GenericChatInput, request: Request) -> ReturnRefundChatResponse:
    graph = request.app.state.support_graph
    thread_id = support.thread_id
    await check_thread_owner(graph, thread_id, request)
    config = {"configurable": {"thread_id": thread_id}}
    existing_state = await graph.aget_state(config)
    rr_id_in_process = existing_state.values.get("rr_id_in_process")
    if not rr_id_in_process:
        raise HTTPException(
            status_code=400,
            detail="Return/ refund session not found or expired. Please Exit and re-login.",
        )
    await _require_refund_request_in_redis(request, rr_id_in_process)
    try:
        message = HumanMessage(content= support.user_conversation)
        initial_state = {
            "messages": [message],
            "desire_to_chat_return_refund": True,
        }
        memory_dict = await group_memory(store= graph.store, user_id= existing_state.values.get("customer_context").customer_id, thread_id= thread_id, include_history=False)
        if memory_dict:
            initial_state.update(memory_dict)
        customer_support_state  = await graph.ainvoke(initial_state, config)
        # Re-read after the graph: a Slack decision may have changed the status, and the UI shows this copy.
        rr_in_process = await request.app.state.redis_adapter.retrieve_refund_request(rr_id_in_process)
        return ReturnRefundChatResponse(
            thread_id = thread_id,
            response = customer_support_state["response"],
            request_human_review_return_refund = customer_support_state["request_human_review_return_refund"],
            rr_in_process = rr_in_process,
        )
        
    except Exception as exc:
        error_msg = f"Error chat about a return refund request for thread: {thread_id}"
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=f"{error_msg}: {exc}")

async def retrieve_refund_request(refund_request_id: int, request: Request) -> RefundRequest | None:
    session_email(request)  # 401 if not signed in (before touching Redis)
    try:
        refund_request = await request.app.state.redis_adapter.retrieve_refund_request(refund_request_id, csa_only=True)
    except Exception as exc:
        error_msg = f"Error retrieving refund request by ID: {refund_request_id}"
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=f"{error_msg}: {exc}")
    # Ids are sequential and guessable: someone else's request looks exactly like a missing one (null),
    # so the endpoint cannot be used to discover which ids exist.
    if refund_request is None or not owns_refund_request(request, refund_request):
        return None
    return refund_request

async def retrieve_refund_requests_by_order(order_id: int, request: Request) -> list[RefundRequest]:
    session_email(request)
    try:
        refund_requests = await request.app.state.redis_adapter.retrieve_refund_requests_by_order(order_id, csa_only=True)
    except Exception as exc:
        error_msg = f"Error retrieving refund requests by order ID: {order_id}"
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=f"{error_msg}: {exc}")
    return [rr for rr in refund_requests if owns_refund_request(request, rr)]
       
async def invoke_summarize_on_exit(support: SummarizeOnExit, request: Request):
    graph = request.app.state.support_graph
    thread_id = support.thread_id
    await check_thread_owner(graph, thread_id, request)
    config = {"configurable": {"thread_id": thread_id}}
    try:
        await graph.ainvoke({"summarize_on_exit": True}, config)
        # escalation_reason is for the future use: communication to CSR in slack
    except Exception as exc:
        error_msg = "Error summarize on exit"
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=f"{error_msg}: {exc}")
                
    
        
# Will Reducer rules of GraphState apply to Langgraph invoke action?
# Yes, reducer rules defined in your graph state absolutely apply when calling the invoke action 
# (as well as ainvoke, stream, and update_state)
# In another word, API calls can append HumanMessage and update a few state variable at the same time.

