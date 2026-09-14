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
npm test             # vitest run (single pass)
npm run test:watch   # vitest watch mode
# npm run lint         # eslint — not yet configured (next lint prompts interactively; no eslint config committed)
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

The backend is in `backend/` — a `uv` project (Python 3.12) using FastAPI.  Currently, all API endpoints are in in `backend/main.py`. I have already separated into `route` and `services` and `models`. `models/model.py` have all model schemas shared by `auth` and `customer-support` services.  

The frontend is in `frontend/` — Next.js 16, React 19, Tailwind 4. It will be statically exported (`next.config.ts` → `output: "export"`) to `frontend/out/`, which FastAPI serves at runtime. 

I decide to use DEMO_MODE for prototype because return refund involves the product return window. The data in database will be stale and not testable.  I can adjust data in memory in DEMO mode to always be testable and I have done that.

Backend is available at http://localhost:8000

## Architecture

### Request flow summary

The main workflow will create customer-support AI agents that help general FAQs, order inquiry and more importantly, automate refund request process.  However, human-in-the-loop approve/ reject/ flag workflow will get involved when requests exceeds certain thresholds: ex. refund amount > 500 (configurable) or disputable non-refundable return/ refund request (escalated to human approval). 

I plan to use Slack Bot interactivity to implement the approve/ reject/ flag workflow for return/ refund requests. I have already got n8n app (AI workflow automation) to integrate successfully with Slack Bot interactivity for the same workflow.  See [Slack Bot Interactivity Screenshot for the the approve/ reject/ flag workflow of a refund request request ](n8n-slack-interactivity/slack-screenshot-screenshot-refund-request-approval.png) and have configured `customer-support-dev` app mimicing `n8n-integration`'s and will code the main workflow soon.  

Workflows are orchestrated with LangGraph. The main workflow will be like: a customer login in with its account email address using `api/auth`. API will lookup customer orders if the customer is a valid `customer` role. Despite my best effort, I cannot prevent customers from asking question of general policy. To manage the flow easier, I add a Customer initial selections screen with 'Order inquiry & return refund' button, 'Others' button and 'Exit' button. We will display the full list of FAQs described in workflow/customer_support_tools.py of 3 sections: Shipping & Delivery, Returns and Refunds and Orders and Payment in an highlighted formal way.  Hopefully, customers will read and find their answers from FAQs and do not prceed further. Customers' general questions would be handled either by fuzzy match or LLM match if either of them would be helpful based upon LLM's reasoning and judgement. It will be escalated to human CSR (send to a Slack channel eventually) if the customer-support agent cannot find an answer with confidence. 

For 'Order inquiry & return refund' initial screen, we will display summary of customer's latest orders in descending order from `CustomerContext`, the customer can select the order he/ she is concerned about. The backend can retrieve the target order and the UI can display the order details (delivered_date, estimated_delivered_date, ship_date, tracking_number, order notes) so that LLM can strike meaningful conversation with the customer. This might be the most difficult part.  Despite throrough system prompt/ instrauctions, we cannot always predicte where the conversation will go. customer-support-agent is instructed that he/ she can always escalate to human CSR if needed. 

If the customer request return/ refund, it will hit `api/request/start` (tentatively).  UI will display itemized order with check boxes and quantity filled in and the customer can override quanties and check boxes etc. The workflow can create a return/ refund request and calculate total refund amount including tax and if human approval is required. Interal tools are helpful in 'Order inquiry & return refund' process.

Workflow Will trigger a HITL process to send customized Slack Interactivity message to Slack if human approval is required.  When customer-support team press Approve or Reject or Flag button in Slack with optional reason, slack will post the response info back to our API webhook (The webhook in local environment will be exposed as a public URL via `ngrok` reverse proxy) which will indirectly calls `api/request/decide` (tentaticely)to do: 1. clear HITL interruption (will explain it later) and 2. log status (manual_approve/ manual_reject/ manual_flag), decided_by, decision_reason and decision_date etc.  All those decisions should send the confimation.  The confirmation letter might include a return shipping barcode if the company pay for products returned from customers. The flagged request might requires follow-up.

The above screen is for customers. There should be a separate screen for customer-support team.  From visibility perspective, `customer-support-agents`  is a small `multi-tenant` app.  It's recommended to use domain names(s) to configure customer-support team in production environment. 

For `customer-support` team,  they cannot see order/ return inquiry screen.  However, they can see return/ refund requests report screen.  The initial phase will include  `Ask AI to draft customized customer-support letter` task. That will reference GET api/approval (codes are in `frontend/app/approval/page.tsx`).  Once the query/ task is filled in and submited, it will trigger POST  `api/approval/start`. Then, it will trigger `api/approval/decide` once the initiator choose approve/ edit/ request change with a reason. This means to demonstrate human approval gate.  Later, we will include return/ refund inquiry/ report by date range and status (auto-approval, manual approval, reject etc.).  


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

### Sqlite persistence paths

`CHECKPOINT_DB` and `STORE_DB` (used in demo mode for durable `AsyncSqliteSaver`/`AsyncSqliteStore`) are configured as relative filenames, but `sqlite3`/`aiosqlite` resolve relative paths against the process's **current working directory at connect time** — not against `.env`'s or `main.py`'s location. Launching `uvicorn`/`pytest` from `backend/` vs. the repo root used to produce sqlite files in different places for the exact same `.env` (and `STORE_DB` needed a `../data/` prefix hack just to land next to `CHECKPOINT_DB` at all).

Fixed by anchoring both at `DATA_DIR = BACKEND_DIR.parent / "data"` in `main.py` (`BACKEND_DIR = Path(__file__).resolve().parent`), via a `_resolve_db_path()` helper:
- A relative filename (e.g. `checkpoints.sqlite`) always resolves under `DATA_DIR` — the repo root's `data/` locally, `/app/data` in the container (Docker's `WORKDIR` puts `main.py` at `/app/backend`, so `BACKEND_DIR.parent` is `/app`), matching the `./data:/app/data` volume mount in `docker-compose.yml`.
- An absolute path is used as-is (an operator override).

`.env`/`.env.example` now just use bare filenames (`checkpoints.sqlite`, `stores.sqlite`); leaving both unset still falls back to in-memory `MemorySaver`/`InMemoryStore` as before.

## Color Scheme

- Accent Yellow: `#ecad0a`
- Blue Primary: `#209dd7`
- Purple Secondary: `#753991` (submit buttons)
- Dark Navy: `#032147` (headings)
- Gray Text: `#888888`

## Implementation Status

### Completed
- CSA-2: Moved from two Docker containers (separate frontend + backend) to one. `Dockerfile` is a multi-stage build — stage 1 (`node:20-alpine`) runs `npm run build` against `frontend/` to produce the static export at `frontend/out` (`next.config.ts` sets `output: "export"`); stage 2 (`python:3.12-slim`) installs the backend with `uv sync --no-dev` and copies `frontend/out` in alongside it. `docker-compose.yml` runs a single service on port 8000. The root cause of the original failure (`/approval` 404ing at `:8000`) was that FastAPI never mounted/served `frontend/out` even though the image already contained it — fixed via the static-file serving + catch-all described in [Routing guard](#routing-guard). Also added: a root `.dockerignore` (host `node_modules`/`.venv`/`backend/checkpoints.sqlite` were previously copyable into the build context and image), and the frontend's `API_URL` now defaults to the relative `/api` instead of an absolute `http://localhost:8000/api`, so the same build works regardless of the host/domain the single container is served from.

- CSA-3: [API] Re-organize, build the infrastrure: cross-cutting long-term memory and clean-up
  - Move approval API calls out of main.py. Re-organize to have separate route/service and shared models. The approval API functions are in `routes/approval.py` now.  Two new routes/ services: auth and customer-support would follow the new structures.  `models/model.py` , having core schemas: CustomerSupportState, CustomerContext, Order, OrderItem, RefundRequest, ReturnedOrder, ReturnedOrderItem etc., are shared by auth and customer-support routes/ services
  - I make use of LangGraph cross-cutting long-term memory.  Add long-term memory (so called store) wiring in the `lifespan` function of main.py. `customer-support` workflow is using long-term memory.
  - Update `save_user_memory` in memory.py to use thread_id as the key.  There will be one summary for a conversation thread. 
  - `load_user_memory` will look up by user_id (customer_id).  It will be called before LLM start conversations with the user in `customer-support` screens so that LLM have the context of previous conversations
  - Add `summarize_node` to customer-support workflow to summarize if the conversation exceeds 6 messages or we just cut-off a series of conversations of one topic
  - I retire `agent` set. I use plain `interrupt` and `Commmand(resume)` instead of HumanInTheLoopMiddlewar. 
  
- CSA-4: Add `auth` route/service
    - Use `DEMO_MODE` only in prototype (demo_data is in memory).  I states the reason in `Request flow summary`
    - I apply `adjust_days_demo_data_testable` logic to `demo_data` in memory by test customer's assigned `OrderRefundStatus` so that they are always testable.
    - `customer-support-agents` is a multi-tenant application.  `auth` service returns `AuthResponse` with a role of (`csr` or `customer`) by the login user email. `csr` is regulated by `CSR_WHITELIST` and `CSR_DOMAINS` defined.  The former has higher priority. Then fall back to search customer order system for `customer` role. It will return is_auth = False if it cannot find the customer. `AuthResponse` is prefilled with `CustomerContext` of recent orders for users of `customer` role. 

- Post CSA-3/CSA-4 bug-fix pass (PR #4): general_inquiry flow was left half-done after CSA-3/CSA-4, so `order_inquiry_node`/order-return flow is still a stub (CSA-8 will build it out) — these are the bugs fixed on the general_inquiry side plus a couple that predate it:
  - `services/auth_service.py`: fixed `elif`/`else` short-circuiting the CSR whitelist + domain checks (the domain check was skipped whenever a whitelist was configured, even if the email didn't match it); return `is_auth = False` instead of raising 401/404 when a customer can't be found or fails `CustomerContext` validation, so `/api/auth` always returns a consistent `AuthResponse` shape
  - `routes/customer_support.py`: fixed a `str.join()` crash on every `/api/support/start` call (was passing two positional args instead of a list)
  - `workflow/customer_support.py`: fixed `general_issue_resolved` never being set on the non-escalate branches of `general_faq_eval_node`/`general_faq_fuzz_match_node`, which raised `KeyError` in the routers on the normal/resolved path — declaring a field in the `ChatState` TypedDict does **not** give it a runtime default; LangGraph only exposes a channel once something actually writes it. Also reworked `summarize_node` routing: it's now reachable from every terminal branch of the general_inquiry flow (not just the LLM-match path) via a shared, flow-agnostic `_should_summarize(state, topic_concluded)` helper — each flow passes its own "topic concluded" signal (`general_issue_resolved` for general_inquiry), and the message-count threshold (`SUMMARIZE_MESSAGE_THRESHOLD = 6`) is the only generic part, kept out of `summarize_node` itself so future flows (order/return, CSA-8) can reuse it without depending on a field that's specific to general_inquiry
  - `memory.py`: `_namespace()` passed `customer_id` (an `int`) straight into the store namespace tuple; LangGraph stores require string namespace segments, so `save_user_memory`/`load_user_memory` were silently failing (swallowed by their own `try/except`, logged only as a `WARNING`) on every single call — cross-session memory never actually persisted until this was fixed
  - See [Sqlite persistence paths](#sqlite-persistence-paths) for the `CHECKPOINT_DB`/`STORE_DB` path-resolution fix

- CSA-5/CSA-6/CSA-7: [UI] Login screen, CSR draft-approval screen, customer initial-selections screen (built together on one branch/PR since CSA-5's redirects land directly on CSA-6/CSA-7)
  - CSA-5: new `frontend/app/page.tsx` (root route) — single email-address input, calls `POST /api/auth`, shows the required "unable to find any customer" message when `is_auth` is false (keying off `is_auth`, not `role`, since the backend defaults `role` to `"customer"` even on failure), and redirects to `/customer` or `/csr` by `role` on success. No logo exists, so the login card shows a handful of FAQ questions (first two per section from `lib/faq.ts`) as decorative, non-interactive tags.
  - CSA-6: `frontend/app/approval/page.tsx` (the only page that existed before this work) was `git mv`'d to `frontend/app/csr/page.tsx` and wrapped with a `useRequireRole("csr")` guard; its draft/approve/edit/reject state machine against `/api/approval/start`/`/api/approval/decide` is otherwise unchanged. The "return/refund report screen" mentioned in the ticket is not part of this work — only the already-built draft-letter approve/edit/reject gate was ported, per the ticket's own "the latter part is ready" framing.
  - CSA-7: new `frontend/app/customer/page.tsx` — greets the customer from `session.customer_context`, displays the full 3-section FAQ list from `lib/faq.ts` as a collapsible accordion, and offers three actions: "Order inquiry & return refund" and "Others" navigate to placeholder pages (`frontend/app/customer/order-inquiry/`, `frontend/app/customer/others/`) since their real destinations belong to un-started tickets (no order-inquiry UI ticket yet; "Others" is CSA-9, backed by CSA-8); "Exit" clears the session and returns to `/`.
  - New `frontend/lib/auth-context.tsx`: a React Context (`AuthProvider`, `useAuth`, `useRequireRole`) persisting `{email_addr, role, customer_context}` to `localStorage`, hydrating on mount so a page refresh doesn't lose the session. `useRequireRole(role)` redirects unauthenticated or wrong-role visitors to `/` and returns `session: null` whenever unauthorized (including on a role mismatch) so guarded pages only need `if (isLoading || !session) return null;` — no per-page re-check of `session.role`.
  - New `frontend/lib/faq.ts`: a **generated** file (do not hand-edit) produced by `backend/scripts/export_faq.py` from `workflow/customer_support_tools.py`'s `FAQs` dict, keeping the frontend's FAQ content and the backend's single source of truth from drifting apart. `backend/tests/test_faq_export_freshness.py` fails the backend test suite if the committed file is stale — regenerate with `uv run python -m scripts.export_faq` (from `backend/`) after editing `FAQs`.
  - Brand colors (Accent Yellow/Blue Primary/Purple Secondary/Dark Navy/Gray Text, see [Color Scheme](#color-scheme)) are now wired into `frontend/tailwind.config.js` as `brand.*` tokens and used across the login, CSR, and customer screens — this is the first UI work to actually apply the documented palette.
  - Bootstrapped frontend testing (previously nonexistent): `vitest` + `@testing-library/react` + `jsdom`, with `frontend/vitest.config.ts`/`vitest.setup.ts` and a shared `frontend/lib/test-utils.tsx` (`renderWithAuth`, `jsonResponse`). Coverage: `frontend/app/page.test.tsx`, `frontend/app/csr/page.test.tsx`, `frontend/app/customer/page.test.tsx`.
  - Root `.gitignore` had a blanket `lib/`/`lib64/` Python-venv rule that was unintentionally shadowing the new `frontend/lib/` directory — removed, since `.venv/`/`venv/`/`env/` already cover virtualenv `lib/` dirs.

- CSA-8: [API & workflow] customer-support generic API and general/ other workflow — scoped to the `general/ others` FAQ path only; `order_inquiry_node`/return-refund flow stays a stub for a later ticket.
  - `routes/customer_support.py` collapsed down to a single `POST /api/support/general` endpoint (dropping the earlier `/api/support/start` + `/api/support/continue` pair), delegating to a new `services/customer_support_service.py::invoke_general_support_workflow`. Users are allowed to switch support category, so there's no need to special-case the first turn from the rest — one endpoint handles both.
  - Implemented the `general_faq_eval_node` → `general_faq_fuzz_match_node` → `general_faq_llm_match_node` chain per the ticket's design: `general_faq_eval_node` asks the LLM (`FAQMatchEvals` structured output) whether a rapidfuzz match, an LLM semantic match, neither, or both would help; the fuzz node runs `find_closest_faq` (rapidfuzz `partial_ratio`, not `WRatio` — the scorer was switched mid-ticket and the field/docs/system-prompt renamed to match: `rapid_fuzz_partial_ratio_match_helpful`) and answers directly above `FAQ_MATCH_THRESHOLD` (75), otherwise falls through to the LLM match node (`FAQMatchResult` structured output) using the same threshold; anything below threshold, or both flags False upfront, returns `ESCALATE_MESSAGE`.
  - Fixed the crash blocking the whole flow: `general_faq_fuzz_match_node` instantiated `BaseMessage` directly, which pydantic rejects (`type` field required — only concrete subclasses like `AIMessage`/`SystemMessage` supply it, and setting `type=` manually doesn't help since downstream LangChain code dispatches on the actual Python class, not that string). Switched to `AIMessage(content=response)`, matching `general_faq_llm_match_node`'s existing pattern for the same "surface the matched answer to the customer" case. Both matched-answer `AIMessage`s now also carry a `name=` source tag (`FAQ_FUZZY_MATCH_SOURCE` / `FAQ_LLM_MATCH_SOURCE`) so it's later inspectable which path answered.
  - Added multi-round support: `GeneralSupportRequest`/`GeneralSupportResponse` now carry an optional `thread_id` (defaulting to `None` so a first-ever call can omit it — Pydantic v2 requires an explicit `= None` for a field to be omittable, not just `| None` typing) that the service reuses as the LangGraph `configurable.thread_id` instead of minting a fresh UUID every call, so a second question from the same customer resumes the same checkpointed thread. Verified end-to-end (real two-round run against the compiled graph, inspecting checkpointed state) that `add_messages` correctly accumulates/prunes history and that `general_inquiry`/`faq_match_evals`/`general_issue_resolved` correctly reset each call so a new question gets a fresh evaluation. `general_faq_eval_node`'s prompt references `state["summary"]` (the running digest `summarize_node` already maintains) for prior-turn context, rather than a fixed message-list index (`messages[-2]`), which would `IndexError` on a brand-new thread's very first message.
  - `general_faq_eval_node`/`general_faq_llm_match_node` still only ever see the *current* question plus that rolling summary — not the full raw message history — when asking the LLM to judge a match; genuinely open-ended multi-turn reasoning (e.g. "no, I meant the other order") is a known gap left for a future pass.
  - `backend/tests/test_customer_support.py` added: direct node-level tests for `general_faq_fuzz_match_node` (fake `FAQMatchEvals` state, bypassing the LLM eval call entirely) plus one end-to-end `/api/support/general` test. Note: the built-in `MockChatModel` can't fake `with_structured_output` (it only knows how to fake `bind_tools`-style tool calls keyed by a `.name` attribute, which plain Pydantic schema classes don't have), so `general_faq_eval_node`/`general_faq_llm_match_node` always get `None` back under mock and always escalate — genuine "confident LLM match" scenarios for those two nodes can only be tested by faking the node's input state directly, never by driving them through `.ainvoke()` under mock.

### Current API Endpoints
- `GET /api/health` — liveness check
- `POST /api/approval/start` — draft content for a task, pauses for human review (HITL interrupt)
- `POST /api/approval/decide` — resume the approval workflow with `approve` / `edit` / `reject`
- `POST/api/auth` - authorize role: `csr` (customer-support representative) or `customer`.  Users of different role access different screen
- `POST /api/support/general` — general/others FAQ inquiry (fuzzy/LLM match, escalate on low confidence); optional `thread_id` in the request/response resumes the same LangGraph thread across rounds
- `GET /{full_path:path}` — catch-all serving the Next.js static export (`frontend/out`); see [Routing guard](#routing-guard)
