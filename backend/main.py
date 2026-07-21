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

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from workflow.agent import build_agent
from workflow.approval import build_approval_graph
from routes.approval import router as approval_router  # noqa: E402
from routes.agent import router as agent_router  # noqa: E402


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
# not app.add_route(...)
app.include_router(approval_router)
app.include_router(agent_router)


_allowed_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static frontend (Next.js `output: "export"` build) ---------------------
# In the single-container image, `frontend/out` is copied next to this file
# (see Dockerfile). It won't exist when running the backend standalone in dev
# (`npm run dev` serves the frontend separately in that case).
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "out"

if (FRONTEND_DIR / "_next").is_dir():
    app.mount("/_next", StaticFiles(directory=FRONTEND_DIR / "_next"), name="next-static")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# --- Static frontend catch-all ----------------------------------------------
# Registered last so every /api/* route above always wins the match first.
# Guards against shadowing /api/* explicitly too, in case that ordering ever
# changes.
@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")

    root = FRONTEND_DIR.resolve()

    def _resolve(*parts: str) -> Path | None:
        candidate = (root.joinpath(*parts)).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return candidate
        return None

    for candidate in (
        _resolve(full_path) if full_path else None,
        _resolve(f"{full_path}.html") if full_path else None,
        _resolve(full_path, "index.html") if full_path else None,
        _resolve("index.html") if not full_path else None,
    ):
        if candidate is not None:
            return FileResponse(candidate)

    not_found = _resolve("404.html")
    if not_found is not None:
        return FileResponse(not_found, status_code=404)
    raise HTTPException(status_code=404, detail="Not Found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
