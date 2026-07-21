
from __future__ import annotations

from pydantic import BaseModel
from fastapi import Request, APIRouter
import uuid
from helper import sse_wrapper
from langgraph.types import Command
from workflow.agent import stream_agent_response
from memory import load_user_memory, save_user_memory


router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentStart(BaseModel):
    message: str
    user_id: str | None = None
    thread_id: str | None = None  # provide to continue an existing agent thread


class AgentDecision(BaseModel):
    thread_id: str
    # One decision per pending tool call, e.g.
    #   {"type": "approve"}
    #   {"type": "edit", "edited_action": {"name": "web_search", "args": {...}}}
    #   {"type": "reject", "message": "..."}  /  {"type": "respond", "message": "..."}
    decisions: list[dict]

@router.post("/start")
async def agent_start(data: AgentStart, request: Request):
    """Start (or continue) an agentic run; streams progress, tokens, approvals."""
    graph = request.app.state.agent_graph
    store = request.app.state.store
    is_new = not data.thread_id
    thread_id = data.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    from langchain_core.messages import HumanMessage, SystemMessage

    messages = []
    if is_new:
        # Inject cross-session memory as a leading system message (first turn only).
        memory = await load_user_memory(store, data.user_id)
        if memory:
            messages.append(SystemMessage(content=f"Remembered context:\n{memory}"))
    messages.append(HumanMessage(content=data.message))

    async def gen():
        # IMPORTANT: yield the thread ID first so the client can store it for future requests.
        yield {"type": "thread", "thread_id": thread_id}
        final_seen = ""
        """``command_input parameter is the initial ``{"messages": [...]}`` (to start) or a
        Command(resume=...)`` (to resume after an approval decision)."""
        async for ev in stream_agent_response(graph, thread_id, {"messages": messages}, config):
            if ev.get("type") == "state" and not ev.get("requires_input"):
                final_seen = ev.get("final_response", "")
            yield ev
        if final_seen:
            await save_user_memory(store, data.user_id, f"Asked the agent about: {data.message[:120]}")

    return sse_wrapper(gen())


@router.post("/decide")
async def agent_decide(data: AgentDecision, request: Request):
    """Resume the agent with approve / edit / reject / respond decisions."""
    graph = request.app.state.agent_graph
    config = {"configurable": {"thread_id": data.thread_id}}
    command = Command(resume={"decisions": data.decisions})
    return sse_wrapper(stream_agent_response(graph, data.thread_id, command, config))
