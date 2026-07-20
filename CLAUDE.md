# [](https://)[](https://)CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`customer-support-agents` project aims to demonstrate how human-in-the-loop can be combined with AI workflow automation to improve business efficiency and efficacy.  

## Development process

When instructed to build a feature:

1. Use your Atlassian tools to read the feature instructions from Jira
2. Develop the feature - do not skip any step from the feature-dev 7 step process
3. Always use `uv sync` with `pyproject.toml` instead of `pip install` with `requirements.txt` for backend build
4. Thoroughly test the feature with unit tests and integration tests and fix any issues
5. Submit a PR using your github tools

## Commands

### Backend (run from `backend/`)

```bash
USE_MOCK_LLM=true uv run pytest -v   # run all backend tests
uv run uvicorn main:app --reload     # dev server on :8000
```

### Frontend (run from `frontend/`)

```bash
npm run dev          # dev server on :3000 (hot reload, proxies /api to :8000)
npm run build        # static export to frontend/out/
# npm test             # vitest run (single pass)
# npm run test:watch   # vitest watch mode
# npm run lint         # eslint
```

### Docker (run from repo root)

```bash
scripts/start-mac.sh   # docker compose up --build -d
scripts/stop-mac.sh    # docker compose down
```

## AI design

Part of codes are originated from [langgraph-interrupt-workflow-template](https://github.com/KirtiJha/langgraph-interrupt-workflow-template) which is designed calling AI models agostically (tag along with LangChain's `init_chat_model`) and also pluged in with mocked LLM implementation in case LLM calling failed. 
There is an OPENAI_API_KEY in the .env file in the project root.

## Technical design

The entire project should be packaged into a Docker container.

The backend is in `backend/` — a `uv` project (Python 3.12) using FastAPI.  Currently, all API endpoints are in in `backend/main.py`. We might separate into at least `route` and `services` once the app become bigger and I have a better idea. 

The frontend is in `frontend/` — Next.js 16, React 19, Tailwind 4. It will be statically exported (`next.config.ts` → `output: "export"`) to `frontend/out/`, which FastAPI serves at runtime. 

As for database, I will have a flag DEMO_MODE. It will be DEMO_MODE = true for local environment and DEMO_MODE = false for prod environment. For DEMO_MODE = true, all business objects, LangGraph short-term checkpointer saver and additional interrupt_mgmt objects should be in memroy too. LangGraph long-term cross-thread store should persist (Possibly SQLLite).  Everything should persist in POSTGRES for DEMO_MODE = false in production.  

Backend is available at http://localhost:8000

## Architecture

### Request flow

The main workflow will create customer-support AI agents that help automate refund request process.  However, human-in-the-loop approve/ reject/ flag workflow will get involved when requests exceeds certain thresholds: ex. refund amount >= 100 (configurable) or return/ refund request date exceeds 30 (configurable) days from the order delivery date. 

I plan to use Slack Bot interactivity to implement the approve/ reject/ flag workflow for return/ refund requests. I have already got n8n app (AI workflow automation) to integrate successfully with Slack Bot interactivity for the same workflow.  See [Slack Bot Interactivity Screenshot for the the approve/ reject/ flag workflow of a refund request request ](n8n-slack-interactivity/slack-screenshot-screenshot-refund-request-approval.png) and have configured `customer-support-dev` app mimicing `n8n-integration`'s and will code the main workflow soon.  

Workflows would be orchestrated with LangGraph. The main workflow will be like: a user login in with its account email address using `api/start`. API will retrieve LangGraph's long-terms memory store for the previous summarized conversation with the customer and also lookup his/ her latest order. AI initialize the conversation with the above context and answer questions accordingly. If the customer request return/ refund, it will hit `api/request/start` and create a return/ refund request and auto approve the requests that are below the escalation threshold.  Will trigger a HITL process to send customized Slack Interactivity message to Slack if otherwise.  When customer-support team press Approve or Reject or Flag button in Slack with optional reason, slack will post the response info back to our API webhook (The webhook in local environment will be exposed as a public URL via `ngrok` reverse proxy) which will indirectly calls `api/request/decide` to do: 1. clear HITL interruption (will explain it later) and 2. log status (manual_approve/ manual_reject/ manual_flag), decided_by, decision_reason and decision_date etc.  All those decisions should send the confimation.  The confirmation letter might include a return shipping barcode if the company pay for products returned from customers. The flagged request might requires follow-up.

The above screen is for customers. There should be a separate screen for customer-support team.  From visibility perspective, `customer-support-agents`  is small `multi-tenant` app.  It's recommended to use domain names(s) to configure customer-support team in production environment. 

For `customer-support` team,  they cannot see order/ return inquiry screen.  However, they can see return/ refund requests report screen. The screen should have 2 drop downs.  One for date range and the other for status.  I might also include order report in this screen too.  There should be a button labeled `Ask AI to draft customized customer-support letter`.  That will reference GET `api/approval` (codes are in frontend/app/approval/page.tsx).  Once the query/ task is filled in and submited, it will trigger POST  `api/approval/start`. It will trigger `api/approval/decide` once the initiator choose approve/ edit/ request change with a reason.   

`api/agent/start` and `api/agent/start` and `workflow/agent.py` are for referencing streaming and HumanInTheLoopMiddleware implementation only and will most likly are needed and clean up soon.

### How human-in-the-loop work in LangGraph's interrupt - Command resume framework
When human-in-the-loop step is needed, issue `interrupt` with key-value dictionary of info to convey to the frontend like actions (action buttons), and message. LangGraph captures state in StateSnapshot including all accumulated messages (HumanMessage, AIMessage and ToolMessage).  Each message comes with argument details and checkpoint_id. In LangGraph, you can invoke a config with thread_id and checkpoint_id, it will execute/ resume the worklfow of that thread at that checkpoint_id. That's how you can test partial workflow in LangGraph. `interrupt` will release the thread.  When a human press a button, API will issue a Command(resume=...). Langugraph will resume the workflow at the point following `interrupt`.  It's important that `interrupt` need to be at the very beginning of that node.  Any preparation should be in a separate node.

Why do we need interrupt - Command resume mechanism for HITL? 
- It's a dynamic workflow: `interrupt` can be triggered or not depending upon thresholds or circumstance.  We might escalate due to customers' frustration oe edge case.
- The normal flow is UI -> API -> LangGraphWorkflow.  Need a way to signal HITL is required.
  
Why if a customer-support member has never pressed a button? What would be the impact on UI?
- LanGrgaph does not hold on that thread.  However, the thread is in interrupted/ paused state. UI screen will be frozen (not responsive) until the Command(resume=...) is issued.  A config with thread_id in upted/ paused state cannot be re-invoke.
- When we insert a return/ refund request business object/ entry, we will also insert a interrupt management object/ entry.  There will be an interruption TTL. When a customer-support member press a button before the TTL expire, it will update both request business object as well as interrupt state mgmt object, and issue Command(resume...).  If TTL expire prior to any human inteervention, it will update interrupt state mgmt object, and issue Command(resume...). From user perspective, the request was timeout (customer-support member might be late to repond). It won't touch the business object.   When a customer-support member finally respond, it will check the state of interrupt state mgmt object and not to re-issue Command(resume...).  However, it will still update the request business object and send the confirmation email ex.  The interrupt management entries are temporary records and will be cleaned up by DB TTL.


### Key files

### Routing guard

The single-container image serves both the API and the Next.js static export (`frontend/out`) from one FastAPI app (`backend/main.py`):

- All API routes are registered under `/api/*` and are added to the router before the catch-all, so they always match first.
- `/_next` is mounted via `StaticFiles` (guarded by an `is_dir()` check, since `frontend/out` won't exist when running the backend standalone in dev).
- A catch-all `GET /{full_path:path}`, registered last, serves the rest of `frontend/out`: it 404s immediately if `full_path` starts with `api/` (explicit guard, on top of registration order already protecting this), then tries the exact file, `{full_path}.html`, `{full_path}/index.html`, and — only for the empty path (`/`) — `index.html`. Any other unmatched path falls through to the export's own `404.html` (status 404), so typos/dead links don't silently render the homepage with a 200.
- Path traversal is blocked by resolving each candidate and checking `candidate.is_relative_to(FRONTEND_DIR)` before serving it.

## Color Scheme

- Accent Yellow: `#ecad0a`
- Blue Primary: `#209dd7`
- Purple Secondary: `#753991` (submit buttons)
- Dark Navy: `#032147` (headings)
- Gray Text: `#888888`

## Implementation Status

### Completed
- CSA-2: Moved from two Docker containers (separate frontend + backend) to one. `Dockerfile` is a multi-stage build — stage 1 (`node:20-alpine`) runs `npm run build` against `frontend/` to produce the static export at `frontend/out` (`next.config.ts` sets `output: "export"`); stage 2 (`python:3.12-slim`) installs the backend with `uv sync --no-dev` and copies `frontend/out` in alongside it. `docker-compose.yml` runs a single service on port 8000. The root cause of the original failure (`/approval` 404ing at `:8000`) was that FastAPI never mounted/served `frontend/out` even though the image already contained it — fixed via the static-file serving + catch-all described in [Routing guard](#routing-guard). Also added: a root `.dockerignore` (host `node_modules`/`.venv`/`backend/checkpoints.sqlite` were previously copyable into the build context and image), and the frontend's `API_URL` now defaults to the relative `/api` instead of an absolute `http://localhost:8000/api`, so the same build works regardless of the host/domain the single container is served from.

### Current API Endpoints
- `GET /api/health` — liveness check
- `POST /api/approval/start` — draft content for a task, pauses for human review (HITL interrupt)
- `POST /api/approval/decide` — resume the approval workflow with `approve` / `edit` / `reject`
- `POST /api/agent/start` — start/continue an agentic run (reference implementation for streaming + `HumanInTheLoopMiddleware`; see note in `main.py`, likely to be cleaned up)
- `POST /api/agent/decide` — resume the agent with `approve` / `edit` / `reject` / `respond` decisions
- `GET /{full_path:path}` — catch-all serving the Next.js static export (`frontend/out`); see [Routing guard](#routing-guard)
