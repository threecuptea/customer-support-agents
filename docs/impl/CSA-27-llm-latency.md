# CSA-27: LLM latency, timeout and retries

- **Status**: current
- **PR**: #27
- Moved from CLAUDE.md as written (Nov 20 2026).

- **There is no lag between `ChatOpenAI` and `RunnableWithFallbacks`.** In Langfuse, `RunnableWithFallbacks` (the `include_raw=True` parser) starts 1-4 ms after `ChatOpenAI` ends and takes ~10 ms; the seconds before it are the `ChatOpenAI` call itself, i.e. OpenAI's response time (queue + prefill + decode). Structured (`json_schema`, strict) calls are not slower than plain ones: gpt-4o-mini p50 2.0 s structured vs. 2.5 s plain (`summarize_node`), max ~4-4.7 s for both (Langfuse, Nov 2026). A cold connection after an idle pause adds only ~60-150 ms.
- **Timeout and retries are always set** in `get_llm()` (`workflow/llm.py`): `LLM_TIMEOUT` (default 30 s per attempt) and `LLM_MAX_RETRIES` (default 2). Without them the OpenAI SDK default is a 600 s read timeout x 3 attempts. The SDK retries 408/409/429/5xx and connection errors with backoff and logs each retry at INFO: `Retrying request to /chat/completions in ... seconds` (grep the uvicorn log). A retry shows up as a longer `ChatOpenAI` span in Langfuse, never as a gap after it.
- **Latency per model**: the harness cost recorder also records each chat-node call's wall-clock latency (p50/ p90/ max columns, and in the `LLM_COST_OUT` file). Compare models by running the harness once per model and diffing the files; rows are matched by node, so two different models line up:
  ```bash
  LLM_MODEL=gpt-4o-mini  LLM_TRIALS=10 LLM_COST_OUT=../data/llm_cost/gpt-4o-mini.json  RUN_LLM_TESTS=1 uv run pytest -m llm -s
  LLM_MODEL=gpt-4.1-mini LLM_TRIALS=10 LLM_COST_OUT=../data/llm_cost/gpt-4.1-mini.json RUN_LLM_TESTS=1 uv run pytest -m llm -s
  uv run python scripts/compare_llm_cost.py ../data/llm_cost/gpt-4o-mini.json ../data/llm_cost/gpt-4.1-mini.json
  ```
  Latency is client-side with `LLM_CONCURRENCY` (default 4) calls in flight and varies with OpenAI's load, so compare runs made with the same concurrency and close in time.
- **Reducing latency, what was measured** (Nov 2026, off-peak): every model answers the return/refund prompt in ~1 s p50; the 3-4 s calls are busy-hour tails. Decode speed is ~60 output tokens/s on all of them, so **output length is the lever we control**. `ORDER_STATIC_PROMPT` asks for short replies (2-3 sentences, no greeting/ restating; full steps only when the situation gives steps): order-chat output -19%/-16%, p90 -15%/-4%, max -16%/-35% (gpt-4o-mini/ gpt-4.1-mini, 10 trials, all cases pass), cost +1-2%. **OpenAI priority tier was rejected**: it reported 0 cached tokens (loses the CSA-26 savings), -0.17 s p50 on gpt-4o-mini and no gain on gpt-4.1-mini. `gpt-4.1-nano` is retired (404). Streaming the reply to the UI (first text ~0.5 s) is scoped in CSA-28.
- **Reading trace data back from Langfuse**: use the SDK, `get_client().api.observations.get_many(...)` or the paginated `get_client().iter_observation_pages(from_start_time=..., to_start_time=..., type="GENERATION", fields="core,basic,usage,model")` (`GET /api/public/v2/observations`; the v1 `/api/public/traces` endpoint was removed on 2026-11-16). The public API is rate-limited (30 requests/ window), so page with `limit=1000`.
