from __future__ import annotations

from fastapi import Request, HTTPException
import os
from langchain_core.messages import HumanMessage, SystemMessage
from models.model import GeneralSupportRequest, GeneralSupportResponse, OrderInitRequest, OrderInitResponse, \
    OrderContinueRequest, OrderContinueResponse, SummarizeOnExit
from memory import load_user_memory
import uuid
import logging

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


async def invoke_general_support_workflow(support: GeneralSupportRequest, request: Request) -> GeneralSupportResponse:
    graph = request.app.state.support_graph
    thread_id = support.thread_id if support.thread_id else str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    messages = []
    memory = await load_user_memory(request.app.state.store, support.customer_context.customer_id)
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
       return GeneralSupportResponse(
           thread_id=thread_id,
           general_inquiry=support.general_inquiry,
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
    memory = await load_user_memory(request.app.state.store, support.customer_context.customer_id)
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
            "order_issue_escalated": False,
            "order_issue_resolved": False,
            "escalation_reason": None,
            "intent_for_return_refund": False,
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
    
async def invoke_order_continue_workflow(support: OrderContinueRequest, request: Request) -> OrderContinueResponse:
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
       return OrderContinueResponse(
           thread_id=thread_id,
           response=customer_support_state["response"],
           escalation_reason= customer_support_state["escalation_reason"],
           intent_for_return_refund= customer_support_state["intent_for_return_refund"],
       )
    except Exception as exc:
        error_msg = "Error continuing customer-support order_inquery"
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

