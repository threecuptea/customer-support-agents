"""Real-LLM evaluation of the chat nodes. Opt-in: `RUN_LLM_TESTS=1 uv run pytest -m llm -s`
(do NOT set USE_MOCK_LLM). Default `USE_MOCK_LLM=true uv run pytest` skips these.

Each case calls the node directly with a seeded state N times (LLM_TRIALS, default 5) at
temperature 0 and requires a pass rate. Choose the model on the command line, no .env edit needed:
`LLM_MODEL=gpt-4.1 RUN_LLM_TESTS=1 uv run pytest -m llm` (optionally LLM_TEMPERATURE=0.7). The
model and temperature actually used are verified and printed in the report header. See tests/llm_harness/ for the runner and cases.
"""
import asyncio
import os

import pytest

from tests.llm_harness.cases import ORDER_CONTINUE_CASES, RETURN_REFUND_CASES, REVISIT_CASES, FakeRedisAdapter, per_customer, \
    build_return_refund_state
from tests.llm_harness import harness
from tests.llm_harness.harness import RESULTS, build_agent, run_case
from models.customer_support_model import OrderRefundStatus
from tests.llm_harness.usage import UsageLog, UsageRecorder

TRIALS = int(os.getenv("LLM_TRIALS", "5"))

pytestmark = pytest.mark.llm


@pytest.fixture()
def agent():
    # A fresh agent (so a fresh HTTP client/connection pool) per case. Each case runs in its own asyncio.run()
    # event loop; a shared client would reuse pooled connections that belong to the previous, closed loop and
    # fail with APIConnectionError right after a large burst of trials.
    # LLM_MODEL / LLM_TEMPERATURE from the command line win over .env; default temperature is 0.
    return build_agent(harness.REQUESTED_MODEL, harness.REQUESTED_TEMPERATURE)


def _evaluate(node, case):
    result = asyncio.run(run_case(node, case, TRIALS))
    RESULTS.append(result)
    if result.inconclusive:
        # Infrastructure problem, not a verdict on the prompt: fail loudly (even for known issues) but say why.
        errs = "\n".join(f"  - {r}" for r in sorted(set(result.error_messages)))
        pytest.fail(f"{case.id} ERROR: {result.errors}/{result.trials} trials hit API errors, too many to judge:\n{errs}")
    if not result.ok:
        reasons = "\n".join(f"  - {r}" for r in sorted(set(result.failures)))
        sample_text = "\n".join(f"  > {s}" for s in result.samples)
        message = f"{case.id} passed {result.passes}/{result.trials} (need {case.threshold:.0%}):\n{reasons}\n  sample replies:\n{sample_text}"
        if case.known_issue:
            pytest.xfail(f"{message}\n  known issue: {case.known_issue}")
        pytest.fail(message)


@pytest.mark.parametrize("case", RETURN_REFUND_CASES, ids=lambda c: c.id)
def test_return_refund_chat_node(case):
    agent_with_redis = build_agent(harness.REQUESTED_MODEL, harness.REQUESTED_TEMPERATURE, redis_adapter=FakeRedisAdapter(case.rr_status))
    _evaluate(agent_with_redis.return_refund_chat_node, case)


@pytest.mark.parametrize("case", ORDER_CONTINUE_CASES, ids=lambda c: c.id)
def test_order_continue_chat_node(case):
    # The order node reads the order's refund request from Redis too; cases without rr_status see none.
    agent_with_redis = build_agent(harness.REQUESTED_MODEL, harness.REQUESTED_TEMPERATURE, redis_adapter=FakeRedisAdapter(case.rr_status))
    _evaluate(per_customer(agent_with_redis.order_continue_chat_node), case)


@pytest.mark.parametrize("case", REVISIT_CASES, ids=lambda c: c.id)
def test_detect_order_revisit_node(agent, case):
    _evaluate(agent.detect_order_revisit_node, case)


# --- prompt caching against the real API (CSA-26) ------------------------------------------------------------

def test_return_refund_chat_node_hits_the_prompt_cache():
    """Different customers/ situations share only the static SystemMessage (RETURN_REFUND_STATIC_PROMPT), which must
    be served from OpenAI's cache. (order_continue_chat_node's static prompt is below the 1,024-token minimum on purpose.)

    Caching is best-effort (a request may land on a machine without the prefix), so after one warm-up call at least
    one of the next calls must read >= 1,024 cached tokens. Uses its own UsageLog (not the cost report).
    """
    log = UsageLog()
    agent = build_agent(harness.REQUESTED_MODEL, harness.REQUESTED_TEMPERATURE, redis_adapter=FakeRedisAdapter("pending"))
    agent.return_refund_llm = UsageRecorder(agent.return_refund_llm.inner, "return_refund_chat_node", None, log)
    states = [build_return_refund_state(rr_being_processed=False, flag=False, question=q, initial=initial)
              for q, initial in (("hi", OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS),
                                 ("Why was it rejected?", OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS),
                                 ("When do I get my money?", OrderRefundStatus.ORDER_AUTO_REFUNDABLE),
                                 ("Can someone review it?", OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS),
                                 ("How long is the return window?", OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_DUE_TO_AMOUNT))]

    async def run_sequentially():
        for state in states:  # sequential on purpose: the warm-up must finish before the next call
            for attempt in range(4):  # same transient-error policy as harness.run_case
                try:
                    await agent.return_refund_chat_node(state)
                    break
                except Exception as exc:  # noqa: BLE001
                    if not harness.is_transient(exc) or attempt == 3:
                        raise
                    await asyncio.sleep(2 ** attempt)
    asyncio.run(run_sequentially())

    cached = [call.cache_read for call in log.calls]
    assert len(cached) == len(states)
    assert max(cached[1:]) >= 1024, f"no prompt-cache hit after warm-up, cache_read per call = {cached}"
