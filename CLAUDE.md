# [](https://)[](https://)CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`customer-support-agents` project aims to demonstrate how human-in-the-loop can be combined with AI workflow automation to improve business efficiency and efficacy.  We are using LangGraph `interrupt-Command(resume=resume_value)` human-in-the-loop pattern for CSR's(Customer Support Representative) email draft `approval` workflow.  We integrate with Slack Interactivity for async human review of refund requests that can not be automatically authorized.  `customer-support-agents` covers general/ FAQ inquiries, order inquiries, and more importantly, automate refund request process.

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
RUN_LLM_TESTS=1 uv run pytest -m llm -s # for LLM harness tests
# Variants, (default temperature 0; LLM_TRIALS=20 for fewer flukes, and default model is gpt-4o-mini ),    
LLM_MODEL=gpt-4.1 [LLM_TEMPERATURE=0.7] [LLM_TRIALS=5] RUN_LLM_TESTS=1 uv run pytest -m llm -s  
# Token usage/ cost of the chat nodes (see "LLM cost harness and prompt caching" below): write a per-node summary,
# then diff two summaries (e.g. before vs. after a prompt change, or model A vs. model B)
LLM_MODEL=gpt-4.1-mini LLM_TRIALS=10 LLM_COST_OUT=../data/llm_cost/after_gpt-4.1-mini.json RUN_LLM_TESTS=1 uv run pytest -m llm -s
uv run python scripts/compare_llm_cost.py ../data/llm_cost/before_gpt-4.1-mini.json ../data/llm_cost/after_gpt-4.1-mini.json
RUN_LLM_TESTS=1 uv run pytest -m llm -s -k prompt_cache   # real-API prompt-cache hit test only

uv run uvicorn main:app --reload     # dev server on :8000
uv run uvicorn --port 8080 slack_webhook:app --reload # slack_webhook on :8080
```

### Frontend (run from `frontend/`)

```bash
npm run dev          # dev server on :3000 (hot reload, proxies /api to :8000)
npm run build        # static export to frontend/out/
npm test             # vitest run (single pass)
npm run test:watch   # vitest watch mode
# npm run lint         # eslint — not yet configured (next lint prompts interactively; no eslint config committed)
```

### Start customer-support-agents integrated with Slack in dev

```bash
uv run uvicorn --timeout-keep-alive 75 main:app --reload
npm run dev
uv run uvicorn --port 8080 slack_webhook:app --reload
ngrok http 8080 --url https://uncloak-aviator-cradling.ngrok-free.dev # ngrok requires setting up secret key, adjust with your URL.
```

### Docker (run from repo root)

```bash
scripts/start-mac.sh   # docker compose up --build -d
scripts/stop-mac.sh    # docker compose down
```

### START redis server via docker if it is not running or in dev environment 
```bash
docker compose up redis -d
```

### START redis-cli to verify refund_request data and purge data for testing

```bash
redis-cli --askpass -n 0   # redis-cli will prompt you to key in your redis password, DB=0 is for dev, DB=15 is for unit test
127.0.0.1:6379> GET "rr:1" # to retrieve refund request ID=1
127.0.0.1:6379> DEL "rr:1" # to delete refund request ID=1
127.0.0.1:6379> FLUSHDB.   # to clean up the database
```

## AI design

Part of codes are originated from [langgraph-interrupt-workflow-template](https://github.com/KirtiJha/langgraph-interrupt-workflow-template) which is designed calling AI models agostically (tag along with LangChain's `init_chat_model`) and also pluged in with mocked LLM implementation in case LLM calling failed. 
There is an OPENAI_API_KEY in the .env file in the project root.

## Technical design

The entire project is packaged into a Docker container.

The backend is in `backend/` — a `uv` project (Python 3.12) using FastAPI.  I follow a consistent architect design across all my projects.  All sub-domains: `auth`, `approval` and `customer_support` are organized into `routes` and `services` and `models` folders. I also added a `workflow` folder that all LangGraph workflows: `approval.py` and `customer_support.py` reside in. 

There are two FastAPI apps: `main.py` and `slack_webhook.py`. The former is the major APIs supports all customers' support functions and   CSR's draft `approval` function. `slack_webhook.py` is for Slack to postback interactive payload then update the refund request status accordingly. To support apps, I added `adapters` folder that contains `slack_adapter.py` and `redis_adapter.py` 

The frontend is in `frontend/` — Next.js 16, React 19, Tailwind 4. It will be statically exported (`next.config.ts` → `output: "export"`) to `frontend/out/`.

Officially, we are using one Docker container deployment with one entry point. In Dockerfile,  API build will copy static output `frontend/out/` from `frontend-build` to its build and mount it so that FastAPI can serve them at runtime at port `:8000`. A docker container can be started with `scripts/start-xxxx.sh` (`xxxx` is a placehold).  In dev, it's easier to deploy `backend` and `frontend` separately. Start backend `uv run uvicorn --timeout-keep-alive 75 main:app --reload` at the backend folder and start `npm run dev` at the frontend folder. Use `localhost:3000` Next.js port to proxy to`localhost:8000` FastAPI port.  

I decide to build `customer-support-agents` in DEMO_MODE because return refund involves the product return window. The data in database will be stale and not testable.  I dynamically adjust data in memory in DEMO mode so that they always be testable.  In a real-world, customer, order, inventory, return, and refund should be in the company's persistent stores. 

## Architecture summary & general data flow

[API Route] -> [Service] -> [Worflow Entry] -> [Execution Node]
In general, a customer-support request flows through the system following above paths.
- API Route: expose API endpoints and enforce RBAC (role-based access control)
- Service: validate workflow in a valid `state` if needed, equipped with domain knowledge, then invoke the workflow
- Worflow Entry: routes to the desinated node based upon the workflow `state`
- Execution Node: retrieve and update data, execute function, and call LLM and update `state`

`customer-support-agents` workflows are built upon LangGraph framework. Short-term `state` management and long-term memory are cross-cutting fundamentals to a LangGraph workflow. A session is called `thread` in LangGraph.  When the customer start a customer-support session, we new a `thread_id` for the first request and a workflow(graph) `state` will be associated with that `thread_id`.  Whatever graph nodes that the request traverse, `state` variable updated, messages created would be stored in `state` management.  

A following request invokes the workflow using the same `thread_id` can retrieve the existing `state` and know where to pick up - `Worflow Entry `know what node to route etc.  That's how multi-round workflow work in LangGraph. We will periodically summarize recent conversations/ messages and store in the long-term memory.  When the customer exit/ logout, re-login, we will know what the previous conversation is about so that LLM won't repeat the same script and can strike an intelligent conversation with the customer.  Short-term `state` management and long-term memory help us fill the context for LLM. 

The main workflow will be like: a customer login in with his/ her account email address. We will lookup the customer and pre-retrieve recent orders if he/ she is a valid customer.  I call it `CustomerContext`.  `customer-support-agents` is an intelligent and friendly application and we do not require the customer to provide the order number to proceed.

 `CustomerContext` help `customer-support-agents` in the following aspects:
 - enlist recent orders and their summaries so that the customer can choose the target order that the customer is concerned about.
 - retrieve the details of the target order so that LLM have the full context: order context plus recent conversations and the previous conversations for an intelligent chat
 - prefill items and quantities for the target order so that the customer can select and adjust if the customer like to return
  
 Automate return for refund request process amended with human reviews of requests that can not be automatically authorized are important features of `CustomerContext`

`customer-support-agents` automate refund request pre-process:
- create a return/ refund request, return order and return order item(s) based upon the customer's itemized input
- calculate total refund amount plus tax
- pre-determine the eligibility/ status of the return for refund request: `auto_approve`, `auto_reject` and `wait_for_manual_review` if the customer decide to process.
  
In `customer-support-agents`, a pre-determine the eligibility/ status is decided by the following rules (can be customized):   
- `auto_approve`: the AI agent can authorize and approve if the refund amount does not exceed the predefined AMOUNT_THRESHOLD_AUTO and the request does not pass predefined DAYS_THRESHOLD_AUTO (so called return window).
-  `wait_for_manual_review`: Requests exceeding the predefined AMOUNT_THRESHOLD_AUTO require human review and approve.
-  `auto_reject`: the request passes predefined DAYS_THRESHOLD_AUTO or the request contains a non-refundable item.  However, the customer can request one-time human review of the request via a chat with the AI agent. The request will be changed to `wait_for_manual_review` if the customer decide to do that and process with the reason/ note to reviewers.   

`customer-support-agents` will automatically send the details of `wait_for_manual_review` requests to Slack.  The Slack interactive request will be equipped with `Approve`, `Reject`, and `Flag` buttons and optional `reason` input box [Slack Interactive request](/images/screenshot_slack_interactive_payload.png).  Once a CSR press a button with or w/o `reason`, a Slack interactive payload will post back to `slack_webhook` that will update the refund request with the new status `manual_approve`, `manual_reject` or `manual_flag` and optional reason and the CSR who made the decision etc.

`customer-support-agents` will also make the effort to prevent `double click` and `double update` for concurrency reasons.
- to prevent `double update`, we will only update the request if its status is at `wait_for_manual_review`
- to prevent `double click`, we will send Slack interactivity replacement w/o any button and `reason` input box plus acknowledge text. [Slack interactive replacement plus acknowledge](/images/screenshot_post_interactive_text.png) so that a CSR can tell a refund request being reviewed by his/ her colleague from the one not yet reviewed.

I mentioned why I design `customer-support-agents` in DEMO_MODE and all demo customer and order objects are in memory for easy adjustment.  Natually, all refund requests should be in memory too.  However, `main.py` and `slack_webhook.py` are separate apps. They live in separate memory spaces. `slack_webhook.py` won't be able to see any refund request that `main.py` store in memory.  `customer-support-agents` use Redis to store refund requests in DEMO_MODE (dev) for cross-app communication.

Other than integrations with **Slack**, **Redis**, `customer-support-agents` also integrate with **LangFuse** for workflow tracing and LLM-specific tracing and observability. LangFuse help us keep track of LLM token usages & breakdowns, cost and latency. Help us answer the question if we make use of **prompt caching** on LLM callings.   

See @docs/architecture.md for detailed architecture design on human-in-the-loop or other topics

### Routing guard

The single-container image serves both the API and the Next.js static export (`frontend/out`) from one FastAPI app (`backend/main.py`):

- All API routes are registered under `/api/*` and are added to the router before the catch-all, so they always match first.
- `/_next` is mounted via `StaticFiles` (guarded by an `is_dir()` check, since `frontend/out` won't exist when running the backend standalone in dev).
- A catch-all `GET /{full_path:path}`, registered last, serves the rest of `frontend/out`: it 404s immediately if `full_path` starts with `api/` (explicit guard, on top of registration order already protecting this), then tries the exact file, `{full_path}.html`, `{full_path}/index.html`, and — only for the empty path (`/`) — `index.html`. Any other unmatched path falls through to the export's own `404.html` (status 404), so typos/dead links don't silently render the homepage with a 200.
- Path traversal is blocked by resolving each candidate and checking `candidate.is_relative_to(FRONTEND_DIR)` before serving it.

### Sqlite persistence paths

`CHECKPOINT_DB` and `STORE_DB` (used in demo mode for durable `AsyncSqliteSaver`/`AsyncSqliteStore`) are configured as relative filenames, but `sqlite3`/`aiosqlite` resolve relative paths against the process's **current working directory at connect time** — not against `.env`'s or `main.py`'s location. Launching `uvicorn`/`pytest` from `backend/` vs. the repo root used to produce sqlite files in different places for the exact same `.env` (and `STORE_DB` needed a `../data/` prefix hack just to land next to `CHECKPOINT_DB` at all).

Fixed by anchoring both at `DATA_DIR = BACKEND_DIR.parent / "data"` in `main.py` (`BACKEND_DIR = Path(__file__).resolve().parent`), via a `_resolve_db_path()` helper:
- A relative filename (e.g. `checkpoints.sqlite`) always resolves under `DATA_DIR` — the repo root's `data/` locally, `/app/data` in the container (Docker's `WORKDIR` puts `main.py` at `/app/backend`, so `BACKEND_DIR.parent` is `/app`), matching the `./data:/app/data` volume mount in `docker-compose.yml`.
- An absolute path is used as-is (an operator override).

`.env`/`.env.example` now just use bare filenames (`checkpoints.sqlite`, `stores.sqlite`); leaving both unset still falls back to in-memory `MemorySaver`/`InMemoryStore` as before.

### LLM Test Harness
We implement LLM test harness: `test/llm_haness` and `tests/test_chat_nodes.py`.  We add a lot of test cases for both `order_llm_for_inquiry_chat` and `return_refund_llm`. We now have a tool to automate evaluating LLM output quality and ensuring its stability.  Please run LLM test harness whenever we add new test cases against `gpt-4o-mini` as well as `gpt-4.1` with at least 10 trials to make sure all test cases pass 80% passing threshold. I also gear toward making use of prompt caching as possible. 

### LLM cost harness and prompt caching (CSA-26)
- **Prompt layout of the chat nodes**: `[SystemMessage(static), SystemMessage(per-call), HumanMessage(latest customer message)]`. The static part never changes, so OpenAI can serve it from its prompt cache: `RETURN_REFUND_STATIC_PROMPT` (`workflow/return_refund_situation.py`, ~1,220 tokens, cached) and `ORDER_STATIC_PROMPT` (`workflow/order_situation.py`, ~330 tokens, below OpenAI's 1,024-token minimum, so not cached). Everything per call (CURRENT SITUATION, order/ refund request JSON, conversation) goes in the second message. **Never put a per-call value into a static prompt**: one changed character loses the cache.
- **Situations**: both chat nodes pick ONE situation in code, `determine_order_situation` and `determine_return_refund_situation`, each a Langfuse span (input + output), so a bad reply can be traced to either a wrong situation or a wrong LLM answer.
- **Cost recorder**: `tests/llm_harness/usage.py` wraps the two chat nodes' LLMs during a harness run and records `input_tokens`, `cache_read` and `output_tokens` from `usage_metadata`. The terminal summary prints a per-node table; `LLM_COST_OUT=path.json` also writes it to a file. `scripts/compare_llm_cost.py before.json after.json` diffs two such files. Keep the files in `data/llm_cost/` (git-ignored).
- **Prices are hard-coded** in `PRICES` (`tests/llm_harness/usage.py`, USD per 1M tokens: input, cached input, output). Update them when OpenAI changes prices or a new model is used (an unknown model shows `n/a`). A before/after comparison of the same model is still valid when prices change, if both files are compared with the same prices.
- **Per-call data is unique in the harness** (`tests/llm_harness/cases.py` `_UNIQUE`): without it every trial of a case sends a byte-identical prompt and the WHOLE prompt is cached, overstating cache hits (80-95% in the harness vs. 0 in production before CSA-26).
- **Cache tests**: `tests/test_prompt_caching.py` (offline) checks the layout, that the static prompt is identical across states, and that `RETURN_REFUND_STATIC_PROMPT` is >= 1,024 tokens (tiktoken). `tests/test_llm_chat_nodes.py::test_return_refund_chat_node_hits_the_prompt_cache` (real API, `-m llm`) checks `cache_read >= 1,024` after a warm-up. Caching is best-effort, so an occasional miss under load is possible.
- **CSA-26 measurement** (10 trials, cost per call): return_refund_chat_node -38% (gpt-4o-mini), -40% (gpt-4.1-mini), -38% (gpt-4.1) with 70-100% cache hits. Padding `ORDER_STATIC_PROMPT` with background text to pass 1,024 tokens was measured and rejected (+5% gpt-4o-mini, -4% gpt-4.1-mini, +27% gpt-4.1).
- **Do not use OpenAI's `prompt_cache_key`**: tried in CSA-25 and CSA-26, and cache hits dropped with it. (Also, `.bind(...)` before `.with_structured_output(...)` silently drops bound kwargs.)
- **Model choice**: if the harness ever shows that `gpt-4.1-mini` is the best balance of quality and cost, switch `DEFAULT_CHAT_NODE_MODEL` in `workflow/customer_support.py` to `gpt-4.1-mini` and run the harness against `gpt-4.1-mini` and `gpt-4o-mini` instead of `gpt-4.1`.

## Color Scheme

- Accent Yellow: `#ecad0a`
- Blue Primary: `#209dd7`
- Purple Secondary: `#753991` (submit buttons)
- Dark Navy: `#032147` (headings)
- Gray Text: `#888888`

      
### Current API Endpoints
- `GET /api/health` — liveness check
- `POST /api/approval/start` — draft content for a task, pauses for human review (HITL interrupt)
- `POST /api/approval/decide` — resume the approval workflow with `approve` / `edit` / `reject`
- `POST/api/auth` - authorize role: `csr` (customer-support representative) or `customer`.  Users of different role access different screen
- `POST /api/support/general` — general/others FAQ inquiry (fuzzy/LLM match, escalate on low confidence); optional `thread_id` in the request/response resumes the same LangGraph thread across rounds
- `POST /api/support/order/init` - initialize order inquiry by passing in `order_number_provided` from UI and the backend retrieve the `target_order` and start the `order_inquery` conversation
- `POST /api/support/order/continue` - UI calls this endpoint after the customer starts his/ her `order_inquery` and the endpoint can be called multiple time for each new input from the customer
- `POST /api/support/exchange_return/recommend` - take the survey of the customer's choice why he/ she want to exchange/ return and give recommendation and the instruction what's the next step; the response includes `special_exchange_handling` (True for damaged/defective/wrong item, which the UI must not route into the normal return/refund flow)
- `POST /api/support/return_refund/init` - take item(s) to return to put together a RefundRequest and generate ReturnRefundInitialDecision with OrderRefundStatus enum that can be mapped to status of RefundRequest when processing 
- `POST /api/support/return_refund/process` - take ReturnRefundInitialDecision plus `request_human_review_return_refund` into consideration when processing the RefundRequest
- `POST /api/support/return_refund/chat` - engage conversation with the customer for his/ her RefundRequest and set `request_human_review_return_refund` flag upon his/ her request; the response also carries the latest `rr_in_process` from Redis
- `GET /api/support/return_refund/{refund_request_id}` - retrieve a refund request by refund request id (customer role; `null` unless it belongs to the signed-in customer)
- `GET /api/support/return_refund/by_order/{order_id}` - retrieve refund requests by order id (customer role; only the signed-in customer's own)
- `POST /api/support/exit` - UI calls this end when the customer press `Exit` button 
- `GET /{full_path:path}` — catch-all serving the Next.js static export (`frontend/out`); see [Routing guard](#routing-guard)

- `POST /webhook/slack/interactive` - Slack post interactive payload to the endpoint after CSR review the refund request and press `Approve/ Reject/ Flag` buttons.  The full path is configured as `Request URL` in `Interactivity & Shortcuts` window of SlackAPI. Signature-verified (`X-Slack-Signature`); there is no test-only variant of this route.
 