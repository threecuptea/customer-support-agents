from __future__ import annotations

from pydantic import BaseModel
from typing import Literal, TypedDict, Annotated, List, Any
from langgraph.graph import MessagesState

class ApprovalStart(BaseModel):
    task: str


class ApprovalDecision(BaseModel):
    thread_id: str
    action: str = Literal["approve", "edit", "reject"]
    content: str | None = None  # edited draft, when action == "edit"
    feedback: str | None = None  # change request, when action == "reject"

class ApprovalState(MessagesState):
    task: str
    draft: str
    feedback: str
    revision_count: int
    decision: str
    status: str
    final_output: str
