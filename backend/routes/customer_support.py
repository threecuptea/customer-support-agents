from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Request, HTTPException
import os
from langchain_core.messages import HumanMessage, SystemMessage
from typing import Literal, Annotated
from models.model import CustomerContext, ChatState
from memory import load_user_memory
from helper import parse_interrupt_info
import uuid
import logging


MAX_MESSAGE_CHARS = 4_000

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/support", tags=['support'])


class GeneralChatStart(BaseModel):
    customer_context: CustomerContext
    general_inquiry: str

class OrderChatStart(BaseModel):
    customer_context: CustomerContext
    order_number_provided: int   

class SupportChatContinue(BaseModel):
    thread_id: Annotated[str, Field(min_length=1)]
    user_conversation: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_CHARS)]
    

def _support_payload(state, result) -> dict:
    """Build a response describing the current approval state."""
    is_interrupted, interrupt_message = parse_interrupt_info(result)
    # I copied it from 'approval' and will revise it later
    return {
        "state": state.values,
        "next": state.next,
        "requires_input": is_interrupted,
        "interrupt": interrupt_message,
        "draft": state.values.get("draft", ""),
        "status": state.values.get("status", "unknown"),
        "final_output": state.values.get("final_output", ""),
        "revision_count": state.values.get("revision_count", 0),
    }

# include_in_schema=False to hide it from API docs. UI should bbe the only one can post the chat 
@router.post("")
async def customer_support_start(support: GeneralChatStart | OrderChatStart, request: Request):
    # await
    graph = request.app.state.support_graph
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    messages = []
    memory = await load_user_memory(request.appe.state.store, support.customer_context.customer_id)
    if memory:
        messages.append(SystemMessage(content=f"Previous conversations:\n{memory}"))
    initial_state = {}     
    if isinstance(support, GeneralChatStart):
        messages.append(HumanMessage(content= support.general_inquiry))
        initial_state = {
            "messages": messages,
            "customer_name": " ".join(support.customer_context.title, support.customer_context.last_name),
            "customer_context": support.customer_context,
            "support_category": "general/ others",
            "general_inquiry": support.general_inquiry,
        }
    else:
        messages.append(HumanMessage(content= f"The order: {support.order_number_provided} is what I am concerned about"))
        initial_state = {
            "messages": messages,
            "customer_name": " ".join(support.customer_context.title, support.customer_context.last_name),
            "customer_context": support.customer_context,
            "support_category": "order_inquery/ return_refund",
            "order_number_provided": support.order_number_provided,
        }         
    try:
        result = await graph.ainvoke(initial_state, config)
        state = await graph.aget_state(config)
        return {"thread_id": thread_id, **_support_payload(state, result)}
    except Exception as exc:
        logger.exception("Error starting customer-support workflow")
        raise HTTPException(status_code=500, detail=f"Error starting customer-support: {exc}")

@router.post("", include_in_schema=False)
async def customer_support_continue(chat: SupportChatContinue, request: Request):
    graph = request.app.state.support_graph
    thread_id = chat.thread_id
    config = {"configurable": {"thread_id": thread_id}}
    try:
        result = await graph.ainvoke({"messages": [HumanMessage(content=chat.user_conversation)]}, config)
        state = await graph.aget_state(config)
        return {"thread_id": thread_id, **_support_payload(state, result)}
    except Exception as exc:
        logger.exception("Error continuing customer-support workflow")
        raise HTTPException(status_code=500, detail=f"Error starting customer-support: {exc}")

# Will Reducer rules of GraphState apply to Langgraph invoke action?
# Yes, reducer rules defined in your graph state absolutely apply when calling the invoke action 
# (as well as ainvoke, stream, and update_state)
# In another word, API calls can append HumanMessage and update a few state variable at the same time.

