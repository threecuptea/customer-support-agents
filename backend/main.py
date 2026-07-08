"""FastAPI server exposing the LangGraph human-in-the-loop research workflow.

The graph is compiled at startup with a checkpointer chosen from the
environment:

- ``CHECKPOINT_DB=checkpoints.sqlite`` → durable, resumable state via
  ``AsyncSqliteSaver`` (survives server restarts — LangGraph's durable
  execution feature).
- unset → in-memory state via ``MemorySaver`` (great for local dev).

No secrets are hardcoded here; configure everything through environment
variables (see ``.env.example``).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from workflow.agent import build_agent, stream_agent_response
from workflow.approval import build_approval_graph
from memory import load_user_memory, save_user_memory

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Compile the graphs with a checkpointer (+ store for long-term memory)."""
    # Cross-thread long-term memory. Swap for a Postgres-backed store in prod.
    store = InMemoryStore()
    app.state.store = store

    checkpoint_db = os.getenv("CHECKPOINT_DB")
    if checkpoint_db:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        logger.info("Using durable AsyncSqliteSaver at %s", checkpoint_db)
        async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as saver:
            app.state.approval_graph = build_approval_graph(checkpointer=saver)
            app.state.agent_graph = build_agent(checkpointer=saver, store=store)
            yield
    else:
        logger.info("Using in-memory MemorySaver (set CHECKPOINT_DB for durability)")
        saver = MemorySaver()
        app.state.approval_graph = build_approval_graph(checkpointer=saver)
        app.state.agent_graph = build_agent(checkpointer=saver, store=store)
        yield


app = FastAPI(title="Custom Support Agent", lifespan=lifespan)

_allowed_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request models ---------------------------------------------------------
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


class ApprovalStart(BaseModel):
    task: str


class ApprovalDecision(BaseModel):
    thread_id: str
    action: str  # "approve" | "edit" | "reject"
    content: str | None = None  # edited draft, when action == "edit"
    feedback: str | None = None  # change request, when action == "reject"


# --- Helpers ----------------------------------------------------------------
def _interrupt_info(result) -> tuple[bool, str | None]:
    """Extract interrupt status and message from an ainvoke result."""
    if isinstance(result, dict) and result.get("__interrupt__"):
        return True, result.get("__interrupt__")[0].value
    return False, None
    

@app.get("/health")
async def health():
    return {"status": "ok"}


# --- Approval workflow (draft → approve / edit / reject → send) -------------
def _approval_payload(state, result) -> dict:
    """Build a response describing the current approval state."""
    is_interrupted, interrupt_message = _interrupt_info(result)
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


@app.post("/approval/start")
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


@app.post("/approval/decide")
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


# --- Agent engine (create_agent + HITL middleware) --------------------------
def _sse(generator) -> StreamingResponse:
    async def body():
        async for chunk in generator:
            yield f"data: {json.dumps(chunk)}\n\n"

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/agent/start")
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

    return _sse(gen())


@app.post("/agent/decide")
async def agent_decide(data: AgentDecision, request: Request):
    """Resume the agent with approve / edit / reject / respond decisions."""
    graph = request.app.state.agent_graph
    config = {"configurable": {"thread_id": data.thread_id}}
    command = Command(resume={"decisions": data.decisions})
    return _sse(stream_agent_response(graph, data.thread_id, command, config))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
