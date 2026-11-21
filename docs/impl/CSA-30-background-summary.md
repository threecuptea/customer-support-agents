# CSA-30: Run summarize_node in the background, after the response is returned

- **Status**: current
- **PR**: #28 (Nov 2026)
- **Jira**: CSA-30. The agreed design is in the comment "Agreed design (Nov 20)".

## Why
CSA-27 measured `summarize_node` (its LLM call; the memory save is ~5 ms) as 51-52% of order-inquiry and general turns that summarize, and ~99% of return_refund init/process and exchange_or_return requests (p50 1.9-2.7 s). The owner wants to keep summarizing often, because a customer may close the browser at any moment, so only WHEN the summary runs changes, not WHETHER.

## Design
- **Graph** (`workflow/customer_support.py`): every edge that led to `summarize_node` from a request flow now leads to `mark_summarize_due_node`, which sets `summarize_due=True`, has no side effects, and goes to END. `route_branch` sends `summarize_on_exit` (Exit) or `summarize_due` (the background run) to `summarize_node`, which is reachable only from START.
- **Summarize triggers**:
  - **Unconditional** after `general_faq_llm_match_node`, `order_init_static_response_node` and `return_refund_process_node`.
  - **`_should_summarize`** (topic concluded or message count) after `general_faq_fuzz_match_node` and `order_continue_chat_node`.
  - **Message count only** (`route_by_message_threshold`) after `exchange_return_reason_recommendation_node`, `initial_return_refund_decision_node`, `return_refund_chat_node` and the order-not-found path of `retrieve_target_order_node`. The owner chose to drop the unconditional summary after exchange/return and the initial decision: a customer who stops there is acceptable to lose.
- **Background run** (`services/customer_support_service.py`):
  - After the graph returns, `_ainvoke_graph` schedules `_background_summarize` with `asyncio.create_task`.
  - The task invokes the graph on the same thread with `{"summarize_due": True}`: run_name `summarize`, `invoke_from="summarize_due"`, tags `["summarize", "background"]`, in its own Langfuse trace. Exit's input is `{"summarize_on_exit": True}`, so the two are distinguishable in Langfuse.
  - The task gets `app` and `user_id`, not `request`, because it outlives the request.
  - Errors are logged (`Background summary failed for thread ...`) and never returned to the customer.
- **Stuck flags**: `_ainvoke_graph` adds `summarize_due: False, summarize_on_exit: False` to the input of every request flow (not to Exit's or the background run's), and `summarize_node` clears both. A flag left in the checkpoint (e.g. after a failed background summary) therefore never routes a customer's request into `summarize_node`. This also fixed `summarize_on_exit`, which used to be reset only by the general and order-init services.
- **Nothing new, no LLM call**: `summarize_node` records `last_summarized_message_id` (the newest message it covered). When the newest message is still that one, e.g. on Exit right after a background summary, it skips the LLM call and the memory save.
- **Per-thread lock**: `BackgroundSummaries` (`services/background_summaries.py`, `app.state.summaries`, created in the lifespan) holds:
  - an `asyncio.Lock` per `thread_id`, ref-counted and removed when unused;
  - strong references to the background tasks.

  `_locked_ainvoke` is the only place the support graph is invoked, and it always holds the thread's lock. The next request or Exit on a thread therefore waits for an unfinished summary instead of writing the checkpoint concurrently; LangGraph does not lock threads. The lock is in-process only, which is fine for the single uvicorn process; revisit (e.g. a Redis lock) if `--workers` is ever added. It must not be a `threading.Lock`, which would block the event loop.
- **Shutdown**: the lifespan awaits `app.state.summaries.drain(SUMMARY_DRAIN_TIMEOUT)` (default 30 s) after each `yield`, before the sqlite/postgres saver and store close and before `langfuse.shutdown()`.

## Rejected
- **Starting the task inside `mark_summarize_due_node`** (`asyncio.create_task(summarize_node)` or `BackgroundTasks`):
  - A task that calls the node function directly discards the node's return value, so the summary and the `RemoveMessage`s never reach the checkpoint.
  - A task that invokes the graph would race the parent run's own checkpoint write.
  - `BackgroundTasks` belongs to the FastAPI layer and is not reachable from a node.
  - Nothing could wait for the task at shutdown, its errors would be lost, and it could be garbage-collected.
- **FastAPI `BackgroundTasks` in the routes**: it would need a new parameter on 8 routes, and `TestClient` runs background tasks before returning, so "the response returns before the summary" could not be tested.
- **Reusing `invoke_summarize_on_exit` for the background run**: rejected so that Exit and background summaries are clearly separate in Langfuse.
- **Removing the unconditional edges** and summarizing only at the message-count threshold: it would capture less activity when the customer closes the browser.

## Known, accepted
- **A request already waiting on the lock can run before the just-scheduled summary.** The task is created after the request releases the lock, and `asyncio.Lock` serves waiters in arrival order. Nothing is skipped: the summary just runs later and includes that request's messages. It happens only on a double submit or two tabs, and it was seen once in a back-to-back scripted run.
- **A new thread started within ~2 s of the previous thread's last summary** may not see that summary in `history` (`group_memory` reads long-term memory).
- **A hard kill during a summary loses it** until the next trigger or Exit. Messages are only deleted when a summary succeeds.

## Tests
- API tests use `tests/background.py`'s `SummaryDrainingTestClient`, which waits for pending summaries after every request. Without it, a test that reads the checkpoint from its own `asyncio.run` loop while a summary runs fails with "bound to a different event loop", from AsyncSqliteSaver's lock.
- `tests/test_background_summary.py` uses a plain `TestClient`, with the checkpoint read on the app's loop via `client.portal.call`. It covers:
  - the response returning before the summary;
  - the next request waiting while other threads don't;
  - a failing summary, then the next turn answered normally;
  - Exit right after a summary skipping the LLM;
  - Exit during a summary waiting for it;
  - shutdown waiting for pending summaries;
  - unit tests for the lock, drain and routing.

## Measured (live, real LLM, sqlite, Langfuse, 4 s between steps, Nov 20 2026)
| Endpoint | Time |
| --- | --- |
| `exchange_return/recommend` | 0.04 s |
| `return_refund/init` | 0.05 s |
| `return_refund/process` | 0.06 s (was ~2.7 s p50) |
| `exit` | 0.03 s (nothing new, skipped) |
| `order/init` | 2.3 s (revisit-detection LLM, no summary) |

Langfuse showed a separate `summarize` trace after each request trace (1.4-2.2 s), and a 0.0 s one for the skipped Exit.
