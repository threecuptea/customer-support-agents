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

from tests.llm_harness.cases import ORDER_CONTINUE_CASES, RETURN_REFUND_CASES, REVISIT_CASES, TEST_CUSTOMER, ORDER_ID, NOW
from datetime import timedelta
from tests.llm_harness import harness
from tests.llm_harness.harness import RESULTS, build_agent, run_case
from models.customer_support_model import RefundRequest, ReturnedOrder, ReturnedOrderItem

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
    def make_refund_request(status: str, notes: str | None = None) -> RefundRequest:
        return RefundRequest(
            refund_request_id=1001, request_date=NOW, status=status,
            notes_for_human_review_override=notes,
            customer=TEST_CUSTOMER,
            returned_order=ReturnedOrder(
                origin_order_id=ORDER_ID, original_delivery_date=NOW - timedelta(days=40), tax_applied_rate=0.085,
                estimated_amount_refund_incl_tax=108.5,
                items=[ReturnedOrderItem(product_id="PRD-1", product_name="Wine Glasses", supplier_name="Heritage Brands",
                                        unit_price=25.0, number_units=4)],
            ),
    )
    class _FakeRedisAdapter:
                async def retrieve_refund_request(self, refund_request_id: int) -> RefundRequest | None:
                    return make_refund_request(case.rr_status)

    agent_with_redis = build_agent(harness.REQUESTED_MODEL, harness.REQUESTED_TEMPERATURE, redis_adapter=_FakeRedisAdapter())
    _evaluate(agent_with_redis.return_refund_chat_node, case)


@pytest.mark.parametrize("case", ORDER_CONTINUE_CASES, ids=lambda c: c.id)
def test_order_continue_chat_node(agent, case):
    _evaluate(agent.order_continue_chat_node, case)


@pytest.mark.parametrize("case", REVISIT_CASES, ids=lambda c: c.id)
def test_detect_order_revisit_node(agent, case):
    _evaluate(agent.detect_order_revisit_node, case)
