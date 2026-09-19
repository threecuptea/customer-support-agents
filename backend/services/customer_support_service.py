from __future__ import annotations

from fastapi import Request, HTTPException
import os
from langchain_core.messages import HumanMessage, SystemMessage
from models.model import GeneralSupportRequest, GeneralSupportResponse, OrderInitRequest, OrderInitResponse, ORDER_INQUIRY
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
    }    
    try:
       customer_support_state  = await graph.ainvoke(initial_state, config)
       return GeneralSupportResponse(
           thread_id=thread_id,
           general_inquiry=support.general_inquiry,
           response=customer_support_state["response"],
       )

    except Exception as exc:
        logger.exception("Error starting customer-support workflow")
        raise HTTPException(status_code=500, detail=f"Error starting customer-support: {exc}")


async def invoke_order_init_workflow(support: OrderInitRequest, request: Request) -> OrderInitResponse:
    graph = request.app.state.support_graph
    thread_id = support.thread_id if support.thread_id else str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    messages = [] 
    messages.append(HumanMessage(content= f"{ORDER_INQUIRY}: {support.order_number_provided}"))
    initial_state = {
            "messages": messages,
            "customer_name": " ".join([support.customer_context.title, support.customer_context.last_name]),
            "customer_context": support.customer_context,
            "support_category": "order_inquery/ return_refund",
            "order_number_provided": support.order_number_provided,
            "target_order": None,
    }    
    try:
       customer_support_state  = await graph.ainvoke(initial_state, config)
       return OrderInitResponse(
           thread_id=thread_id,
           target_order= customer_support_state["target_order"],
           response=customer_support_state["response"],
       )
    except Exception as exc:
        logger.exception("Error starting customer-support workflow")
        raise HTTPException(status_code=500, detail=f"Error starting customer-support: {exc}")
    




# Will Reducer rules of GraphState apply to Langgraph invoke action?
# Yes, reducer rules defined in your graph state absolutely apply when calling the invoke action 
# (as well as ainvoke, stream, and update_state)
# In another word, API calls can append HumanMessage and update a few state variable at the same time.

