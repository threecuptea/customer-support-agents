"""FastAPI server exposing the LangGraph human-in-the-loop research workflow.

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
from workflow.customer_support import CustomerSupportAgent
from routes.approval import router as approval_router  # noqa: E402
from routes.agent import router as agent_router  # noqa: E402
from routes.customer_support import router as chat_router # noqa: E402
from routes.auth import router as auth_router # noqa: E402


load_dotenv(override=True)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Compile the graphs with a checkpointer (+ store for long-term memory)."""
    # Cross-thread long-term memory. Swap for a Postgres-backed store in prod.
    store = InMemoryStore()
    app.state.store = store

    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true" # we are using demo mode in dev environment.
    checkpoint_db = os.getenv("CHECKPOINT_DB")
    store_db = os.getenv("STORE_DB")
    connection_url = os.getenv("CONNECTION_URL")
    if demo_mode and checkpoint_db and store_db:
        # We are not persistinh any business entities in demo_mode (local)
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from langgraph.store.sqlite.aio import AsyncSqliteStore
        # root data dir is the default folder for the sqlite db files.
        async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as saver:
            # I have to use ../data/stores.sqlite to point to the correct path. 
            async with AsyncSqliteStore.from_conn_string(store_db) as store:
                logger.info("In demo mode, initializing durable AsyncSqliteSaver at %s", checkpoint_db)
                logger.info("In demo mode, initializing durable AsyncSqliteStore at %s", store_db)
                app.state.approval_graph = build_approval_graph(checkpointer=saver)
                app.state.agent_graph = build_agent(checkpointer=saver, store=store)
                app.state.support_graph = CustomerSupportAgent(checkpointer=saver, store=store).build_support_graph()
                yield

    elif not demo_mode and connection_url:
        from langgraph.checkpoint.postgres import AsyncPostgresSaver
        from langgraph.store.postgres import AsyncPostgresStore
        # not testing the connection here in production
        async with AsyncPostgresSaver.from_conn_string(f'{connection_url}/checkpointer') as saver:
            async with AsyncPostgresStore.from_conn_string(f'{connection_url}/store') as store:
                app.state.approval_graph = build_approval_graph(checkpointer=saver)
                app.state.agent_graph = build_agent(checkpointer=saver, store=store)
                app.state.support_graph = CustomerSupportAgent(checkpointer=saver, store=store).build_support_graph()
                yield

    else:
        logger.info("Using in-memory MemorySaver and InMemoryStore")
        saver = MemorySaver()
        app.state.approval_graph = build_approval_graph(checkpointer=saver)
        app.state.agent_graph = build_agent(checkpointer=saver, store=store)
        app.state.support_graph = CustomerSupportAgent(checkpointer=saver, store=store).build_support_graph()
        yield

# FastAPI lifespan manages application startup (before taking the first request)and shutdown logic (after taking the final request). 
# It requires an asynchronouscontextmanager where code before yield statement runs when the app starts, 
# and code after the yield runs when the app stops. . Under the hood, FastAPI relies on Starlettet which expects this object to 
# implement the standard Python async context manager protocol (having __aenter__ and __aexit__ methods)
# FastAPI depends upon lifespan. lifespan depends upon FastAPI parameter app. 
# Without from __future__ import annotations, the app parameter would be evaluated at runtime, which would cause a circular import error.
app = FastAPI(title="Custom Support Agent", lifespan=lifespan)  # noqa: E402
# not app.add_route(...)
app.include_router(approval_router)
app.include_router(agent_router)
app.include_router(chat_router)
app.include_router(auth_router)


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
@app.get("/{full_path:path}", include_in_schema=False)
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
