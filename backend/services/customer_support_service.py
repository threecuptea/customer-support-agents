from __future__ import annotations

from fastapi import Request, HTTPException
import os
from langchain_core.messages import HumanMessage, SystemMessage
from models.model import ExchangeOrReturnOutput, GeneralSupportRequest, OrderInitRequest, OrderInitResponse, \
    GenericChatInput, SummarizeOnExit, OrderToReturn, Order, ExchangeOrReturnInput, GenericResponse, InitialReturnRefundResponse, RefundRequest, \
    ReturnRefundProcessRequest, ReturnRefundProcessResponse, ReturnRefundChatResponse
from memory import load_user_memory
import uuid
import logging
from workflow.customer_support_utils import check_if_order_to_return_in_valid_state

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


async def invoke_general_support_workflow(support: GeneralSupportRequest, request: Request) -> GenericResponse:
    graph = request.app.state.support_graph
    thread_id = support.thread_id if support.thread_id else str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    messages = []
    memory = await load_user_memory(graph.store, support.customer_context.customer_id)
    if memory:
        messages.append(SystemMessage(content=f"Previous conversations:\n{memory}"))
    messages.append(HumanMessage(content= support.general_inquiry))
    initial_state = {
            "messages": messages,
            "customer_name": " ".join([support.customer_context.title, support.customer_context.last_name]),
            "customer_context": support.customer_context,
            "support_category": "general/ others",
            "general_inquiry": support.general_inquiry,
            "escalation_reason": None,
            "faq_match_evals": None,
            "general_issue_resolved": False,
            "summarize_on_exit": False,
    }    
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
    thread_id = support.thread_id if support.thread_id else str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    messages = []
    memory = await load_user_memory(graph.store, support.customer_context.customer_id)
    if memory:
        messages.append(SystemMessage(content=f"Previous conversations:\n{memory}"))         
    messages.append(HumanMessage(content= f"Order inquiry: {support.order_number_provided}"))
    initial_state = {
            "messages": messages,
            "customer_name": " ".join([support.customer_context.title, support.customer_context.last_name]),
            "customer_context": support.customer_context,
            "support_category": "order_inquery",
            "order_number_provided": support.order_number_provided,
            "target_order": None,
            "order_is_revisit": False,
            "order_issue_escalated": False,
            "order_issue_resolved": False,
            "escalation_reason": None,
            "summarize_on_exit": False,
    }    
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
    config = {"configurable": {"thread_id": thread_id}}
    # We cannot inject long-terms memory for each invoke. That should come from `invoke_order_init_workflow``
    # Guard against a thread_id that was never initialized via /order/init (or whose init failed to find
    # an order): route_branch/order_continue_chat_node assume target_order is already populated, so without
    # this check a stale/uninitialized thread_id would crash the graph instead of returning a clear error.
    existing_state = await graph.aget_state(config)
    if not existing_state.values.get("target_order"):
        raise HTTPException(
            status_code=400,
            detail="Order inquiry session not found or expired. Please restart from the order selection screen.",
        )
    try:
       customer_support_state  = await graph.ainvoke({"messages": [HumanMessage(content= support.user_conversation)]}, config)
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


async def invoke_return_refund_init_workflow(order_to_return: OrderToReturn, request: Request) -> InitialReturnRefundResponse:
    graph = request.app.state.support_graph
    thread_id = order_to_return.thread_id
    config = {"configurable": {"thread_id": thread_id}}
    existing_state = await graph.aget_state(config)       
    try:
        # verify if the target order and order to return are in a valid state to start a return refund.
        target_order: Order = existing_state.values.get("target_order")
        check_if_order_to_return_in_valid_state(order_to_return, target_order)
        messages = []
        memory = await load_user_memory(graph.store, existing_state.values.get("customer_context").customer_id)
        if memory:
            messages.append(SystemMessage(content=f"Previous conversations:\n{memory}"))  
        messages.append(HumanMessage(content= f"Initialize return refund: {target_order.order_id}"))
        initial_state = {
            "messages": messages,
            "support_category": "return_refund",
            "order_to_return": order_to_return,
            "initial_return_refund_decision": None,
            "refund_request_to_process": None,
            "proceed_to_process_return_refund": False, 
            "assigned_refund_request_id":0,
            "desire_to_chat_return_refund":False,
            "request_human_review_return_refund": False,
            "notes_for_human_review_override": None,
        }
        customer_support_state  = await graph.ainvoke(initial_state, config)
        return InitialReturnRefundResponse(
            thread_id = thread_id,
            response = customer_support_state["response"],
            initial_return_refund_decision = customer_support_state["initial_return_refund_decision"],
            refund_request_to_process = customer_support_state["refund_request_to_process"],
        )
    except ValueError as verr:
        error_msg = f"Error start a return refund request for thread: {order_to_return.thread_id}"
        logger.exception(error_msg)
        raise HTTPException(status_code=400, detail=f"{error_msg}: {verr}")
    except Exception as exc:
        error_msg = f"Error start a return refund request for thread: {order_to_return.thread_id}"
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=f"{error_msg}: {exc}")

async def invoke_return_refund_process_workflow(request_to_process: ReturnRefundProcessRequest, request: Request) -> ReturnRefundProcessResponse:
    graph = request.app.state.support_graph
    thread_id = request_to_process.thread_id
    config = {"configurable": {"thread_id": thread_id}}
    existing_state = await graph.aget_state(config)
    refund_request: RefundRequest = existing_state.values.get("refund_request_to_process")
    if not refund_request:
        raise HTTPException(
            status_code=400,
            detail="Return/ refund session not found or expired. Please Exit and re-login.",
        )
    if existing_state.values.get("assigned_refund_request_id"):
        raise HTTPException(
            status_code=400,
            detail="This return/ refund request has already been processed.",
        )
    try:
        message = HumanMessage(content= f"Please process return refund for order id: {refund_request.returned_order.origin_order_id}")
        initial_state = {
            "messages": [message],
            "proceed_to_process_return_refund": True,
            "notes_for_human_review_override": request_to_process.notes_for_human_review_override
        }
        customer_support_state  = await graph.ainvoke(initial_state, config)
        return ReturnRefundProcessResponse(
            thread_id = thread_id,
            response = customer_support_state["response"],
            assigned_refund_request_id = customer_support_state["assigned_refund_request_id"],
            refund_request_to_process = customer_support_state["refund_request_to_process"],
        )
    except Exception as exc:
        error_msg = f"Error process a return refund request for the order: {refund_request.returned_order.origin_order_id}"
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=f"{error_msg}: {exc}")

async def invoke_return_refund_chat_workflow(support: GenericChatInput, request: Request) -> ReturnRefundChatResponse:
    graph = request.app.state.support_graph
    thread_id = support.thread_id
    config = {"configurable": {"thread_id": thread_id}}
    existing_state = await graph.aget_state(config)
    refund_request: RefundRequest = existing_state.values.get("refund_request_to_process")
    if not refund_request:
        raise HTTPException(
            status_code=400,
            detail="Return/ refund session not found or expired. Please Exit and re-login.",
        )
    try:
        message = HumanMessage(content= support.user_conversation)
        initial_state = {
            "messages": [message],
            "desire_to_chat_return_refund": True,
        }
        customer_support_state  = await graph.ainvoke(initial_state, config)
        return ReturnRefundChatResponse(
            thread_id = thread_id,
            response = customer_support_state["response"],
            request_human_review_return_refund = customer_support_state["request_human_review_return_refund"],
        )
        
    except Exception as exc:
        error_msg = f"Error chat about a return refund request for thread: {refund_request.returned_order.origin_order_id}"
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=f"{error_msg}: {exc}")

                
async def invoke_summarize_on_exit(support: SummarizeOnExit, request: Request):
    graph = request.app.state.support_graph
    thread_id = support.thread_id
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

