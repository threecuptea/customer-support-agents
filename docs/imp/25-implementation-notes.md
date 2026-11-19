- CSA-25 (backend): Integrate with LangFuse for tracing and observability
  - ConfigCoure **LANGFUSE_SECRET_KEY**, **LANGFUSE_PUBLIC_KEY**, **LANGFUSE_BASE_URL** in .env so that I can `get_client` and `auth_check` so that LangFuse start to log tracing and observability.  However, to prevent LangFuse from logging when testing, I have to add **LANGFUSE_TRACING_ENABLED** flag.  I wired LangFuse in `lifespan` of `main.py` 
  while turn off **LANGFUSE_TRACING_ENABLED** flag in the `disable_langfuse_tracinng` fixture of `conftest.py`.
  - One fundamental question is: Does LangFuse replace local logging?  Langfuse does not completely replace local application logging; instead, it complements it by specializing in **LLM-specific observability and tracing**.
    - **LLM Input/Output Tracking:** We no longer need to write custom print statements, database tables, or text files to capture prompts, model completions, raw tokens, and latencies.
    - **Cost & Usage Tracking:** It automatically calculates and aggregates token usage and financial costs per model, user, or sessio.
    - **Hierarchical Tracing & Agent Flows:** It groups multi-step agent actions, tool calls, and retrieval steps into visual trace trees rather than flat log lines.
    See LanguFuse screenshot [Tokens breakdown by type](/images/screenshot_langfuse_token_breakdown.png), [Tracing logs with chain, generation](/images/screenshot_langfuse_tracing_chain_generation_span.png) and [Hierarchical tracing](/images/screenshot_langfuse_hierarchical_tracing.png)
  - We have to capture token usage in order for LangFuse calculate the cost. In LangChain/ LangGraph world, it is called `usage_metadata`. LLM providers will not include it unless we turn on `stream_usage` flag.  For LLM with structured output, it only returns fields defined in structured output schema unless we turn on `include_raw`. For example, I made the following changes in the LLM declaration for `general_llm_for_faq_match_result` :
  ```python
  self.general_llm_for_faq_match_result = get_llm(stream_usage=True).with_structured_output(FAQMatchResult, include_raw=True)

  ```
  - For LLM with structured output, it also affects how we parse what is returned from LLM. LLM won't return a structured output object directly. The structured output object would be under `parsed` key and `usage_metadata` will be under `raw` key.
  ```python
  result = await self.order_llm_for_inquiry_chat.ainvoke([system_msg])
  order_output: OrderStructuredOutput = result["parsed"]

  ```
  We don't need to tell LangFuse where to look for `usage_metadata` returned from LLM with or w/o structured output.  LangFuse is smart enough to tell from its data structure.
  I fixed all unit tests broked by the above changes. 
  - LangFuse natively integrate with OpenTelemetry (OTel) and support 10 types of observabilty: event, span, generation, agent, tool, chain, retriever, evaluator, embedding, and guardrail. LangGraph nodes are represented with `chain` and LLM is represented with `generation`.  I added `determine_order_situation` as a customized `span` to record the input and output of the crucial logic of `determine_order_situation` and trace how we render prompt based upon the returned `OrderSituation` enums.
  ```python
  @observe(as_type="span", capture_input=True, capture_output=True)
  def determine_order_situation(*, status: str | None, is_revisit: bool, prior_topic: str | None,
                            turns: int) -> OrderSituation:
  ```
    - [ ] CSA-26 Add `determine_return_refund_situation` by applying `deterministic-prompt-text-rendered-by-situation` pattern to `return_refund_chat_node`  
  - LangFuse helps me discover the followings:
    - There is a BUG in `general_faq_llm_match_node`. I tried a simple question: `If I want a different style or color, should I return or exchange?` which is not part of keys in `FAQs`, `general_faq_fuzz_match_node` won't locate the answer and will fallback to `general_faq_llm_match_node`. The latter can easily return the correct answer based upon `RETURN_POLICY`.  However, we keep getting `ESCALATE_MESSAGE` which means we got `confidence_score` below the match threshold but LangFuse show the `confidence_score` is 0.95. It turns out the original `confidence_score` is within a  of 0-100 to accomondate the `confidence_score` that `rapidfuzz` return. It is easier/ deterministic to change the output scale of fuzz match than ensure LLM output accordingly. 0.0-1.0 is more commonly used in industries. I changed fuzz match to output `confidence_score` at 0.0-1.0 scale.
    - 
  ```python
  class FAQMatchResult(BaseModel):
    question: str
    answer: str
    confidence_score: Annotated[float, Field(ge=0.0, le=1.0)]
  ```
  and enhance the prompt for 
  ```python
  IMPORTANT: confidence_score is 0.0 - 1.0 and the passing score is 0.80.
  ```
    to fix the BUG.
    - Simplify general support workflow: **I removed general_faq_eval_node.**  It will cost us at least one-time LLM token cost of of `general_faq_eval_node` if we keep it. Go straight to `general_faq_fuzz_match_node` which is super cheap then fallback to `general_faq_llm_match_node` if the former's `confidence_score` does not the threshold. 
    - `Prompt caching` is an optimization technique that stores and reuses the computed attention states (Key-Value or KV pairs) of static prompt prefixes—such as system instructions. Providers like OpenAI handle prefix detection automatically once prompts cross minimum token thresholds (e.g., 1,024 tokens). I move the variable part: state `general_inquiry` out of STSTEM_PROMPT and put in HumanMessage. The SYSTEM_PROMPT with long `RETURN_POLICY` triggered OpenAI prompt caching minimum token thresholds (1,024 tokens).  In [Tokens breakdown by type](/images/screenshot_langfuse_token_breakdown.png), input_cache_read line came from `general_faq_fuzz_match_node`.
    - I did some research on our `order_continue_chat_node`. Here is some stats from LangFuse:
    ```python
    usage_metadata: {
      input_tokens: 1153
      output_tokens: 85
      total_tokens: 1238
      input_token_details: {
         audio: 0
         cache_read: 0
      }  
    }
    ```
    For `return_refund_chat_node`
    ```python
    usage_metadata: {
       input_tokens: 2247
       output_tokens: 64
       total_tokens: 2311
       input_token_details: {
         audio: 0
         cache_read: 0
      }  
    }
    ```
    For `general_faq_llm_match_node`
    ```python
    usage_metadata: {
      input_tokens: 1750
      output_tokens: 80
      total_tokens: 1830
      input_token_details: {
         audio: 0
         cache_read: 1664
      }   
    }
    ```
    OpenAI automatically triggers prompt caching when your API request meets these key conditions:
    Token length threshold: the prompt prefix (shared prompt) instead of the request must exceed 1,024 tokens (processed in 128-token increments). Therefore, it is futile to move ALWAYS_ON_TEXT to the top for `order_continue_chat_node`.  Token count of shared prompt is just too smalll. Please take `prompt_cahing` into consideration when re-organize and add `determine_return_refund_situation` by applying `deterministic-prompt-text-rendered-by-situation` pattern to `return_refund_chat_node`.  
    - OpenAI, Claude platform are cluster environment. Adding `prompt_cache_key` will make it go to the same host. I tried it. cache_read number disappear right away. I reverted the change. 
    - Another BUG, all structured out LLM have 2-4 seconds lag. [ChatOpenAI lag](/images/screenshot_langfuse_tracing_log.png) and also sometimes has ParsingError.  That only happens to llm.with_structured_output and does not happen to summarize_node which is straight string output.  It suggests the followings:
    - **Switch to Native JSON Schema**. Pass `method="json_schema"` explicitly when calling with_structured_output(). This uses OpenAI's native constrained decoding instead of legacy tool-calling wrappers, which is generally faster and more reliable.
    - **Trim Your Pydantic Schema**. Remove unnecessary nested objects, shorten field names, and keep Field descriptions brief.
    I applied the first. It does not help. Our structured ouput Pydantic is small and flat.
    - [] CSA-27 Fix the BUG: all structured out LLM have 2-4 seconds lag
      - Update after the CSA-25 review: it is NOT a lag between ChatOpenAI and RunnableWithFallbacks. In LangFuse's tree view
        the steps are sequential and their durations add up, e.g. `order_continue_chat_node` 2.17s = `ChatOpenAI` 2.15s +
        `RunnableWithFallbacks`/`RunnableAssign<parsed,parsing_error>` 0.01s each. The table view lists START times, so the
        parser starting ~2s after ChatOpenAI only reflects ChatOpenAI's own duration. The structured-output wrappers cost ~10ms;
        the 2-4s is OpenAI's response time (input ~1.1-2.2k tokens + generating the JSON). That is also why `method="json_schema"`
        did not help. CSA-27 should be re-scoped to reducing model latency: fewer output tokens (short replies, brief field names),
        fewer/cached input tokens (CSA-26 prompt re-org), streaming `response` to the UI, a faster model for classification nodes.
        First check: compare ChatOpenAI duration in `summarize_node` (plain string output) vs the chat nodes at similar token counts.
      - With `include_raw=True` a parse failure no longer raises: it returns `parsed: null` plus the error in `parsing_error`
        (the nodes already handle `None`). Filter LangFuse traces on a non-null `parsing_error` to measure how often ParsingErrors happen.
  - Post-review cleanup:
    - All 8 service entry points now call one helper, `_ainvoke_graph` in `services/customer_support_service.py`, which adds the LangFuse `CallbackHandler` + `propagate_attributes` when `app.state.langfuse` is set. There is no per-request `flush()` (it is a blocking network call inside an async handler); the SDK exports in the background and `lifespan` calls `shutdown()` on exit.
    - The LangFuse SDK treats an unset/empty `LANGFUSE_TRACING_ENABLED` as enabled, while `main.py` treats it as disabled. When disabled, `lifespan` now sets it to `"false"` so `@observe` spans (`determine_order_situation`) agree. `.env.example` defaults to `false`.
    - `_should_summarize` now fires at `>= SUMMARIZE_MESSAGE_THRESHOLD` messages (was `>`), i.e. one message earlier.
    - Privacy: traces carry `user_id` = the customer's session email, plus full prompts (customer names, order details, conversation). That is acceptable for the demo; in production, send a customer id or a hash and check the LangFuse data-retention/masking settings.
    - `return_refund_chat_node` now also sends the customer's latest message as its own HumanMessage after the SystemMessage (shared
      helper `split_latest_human_message`, also used by `order_continue_chat_node`). RR-13 regressed (reply no longer said "human review"),
      fixed by telling the model to confirm that a human review has been initiated. RR + OC harness cases pass 10/10 on gpt-4o-mini and gpt-4.1.
    - LLM harness bug (pre-existing since CSA-22/24): `LLM_MODEL=gpt-4.1` was silently ignored. `test_api_slack_e2e.py`/`test_slack_webhook.py`
      do `from tests.conftest import ...`, which executes conftest a second time after .env is loaded and overwrote the captured
      command-line model/temperature with .env's (gpt-4o-mini, 0.2). conftest now captures them only once. Earlier "gpt-4.1" harness
      results were really gpt-4o-mini.
