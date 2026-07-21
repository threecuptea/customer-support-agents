from __future__ import annotations

from pydantic import BaseModel
from fastapi import HTTPException, Request, APIRouter
import logging
import os
import uuid
from helper import parse_interrupt_info
from langgraph.types import Command


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approval", tags=["approval"])


class ApprovalStart(BaseModel):
    task: str


class ApprovalDecision(BaseModel):
    thread_id: str
    action: str  # "approve" | "edit" | "reject"
    content: str | None = None  # edited draft, when action == "edit"
    feedback: str | None = None  # change request, when action == "reject"


# --- Approval workflow (draft → approve / edit / reject → send) -------------
def _approval_payload(state, result) -> dict:
    """Build a response describing the current approval state."""
    is_interrupted, interrupt_message = parse_interrupt_info(result)
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


@router.post("/start")
async def approval_start(data: ApprovalStart, request: Request):
    """Draft content for a task and pause for human review."""
    graph = request.app.state.approval_graph
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "messages": [],
        "task": data.task,
        "draft": "",
        "feedback": "",
        "revision_count": 0,
        "decision": "",
        "status": "drafting",
        "final_output": "",
    }
    try:
        result = await graph.ainvoke(initial_state, config)
        state = await graph.aget_state(config)
        return {"thread_id": thread_id, **_approval_payload(state, result)}
    except Exception as exc:
        logger.exception("Error starting approval workflow")
        raise HTTPException(status_code=500, detail=f"Error starting approval: {exc}")


@router.post("/decide")
async def approval_decide(data: ApprovalDecision, request: Request):
    """Resume the approval workflow with approve / edit / reject."""
    graph = request.app.state.approval_graph
    config = {"configurable": {"thread_id": data.thread_id}}

    action = data.action.lower()
    resume_value: dict = {"action": action}
    if action == "edit":
        resume_value["content"] = data.content or ""
    elif action == "reject":
        resume_value["feedback"] = data.feedback or ""  

    try:
        result = await graph.ainvoke(Command(resume=resume_value), config)
        state = await graph.aget_state(config)
        return _approval_payload(state, result)
    except Exception as exc:
        logger.exception("Error deciding approval workflow")
        raise HTTPException(status_code=500, detail=f"Error in approval decision: {exc}")
