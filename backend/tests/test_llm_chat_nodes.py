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

from tests.llm_harness.cases import ORDER_CONTINUE_CASES, RETURN_REFUND_CASES
from tests.llm_harness import harness
from tests.llm_harness.harness import RESULTS, build_agent, run_case

TRIALS = int(os.getenv("LLM_TRIALS", "5"))

pytestmark = pytest.mark.llm


@pytest.fixture(scope="module")
def agent():
    # LLM_MODEL / LLM_TEMPERATURE from the command line win over .env; default temperature is 0.
    return build_agent(harness.REQUESTED_MODEL, harness.REQUESTED_TEMPERATURE)


def _evaluate(node, case):
    result = asyncio.run(run_case(node, case, TRIALS))
    RESULTS.append(result)
    if not result.ok:
        reasons = "\n".join(f"  - {r}" for r in sorted(set(result.failures)))
        message = f"{case.id} passed {result.passes}/{result.trials} (need {case.threshold:.0%}):\n{reasons}"
        if case.known_issue:
            pytest.xfail(f"{message}\n  known issue: {case.known_issue}")
        pytest.fail(message)


@pytest.mark.parametrize("case", RETURN_REFUND_CASES, ids=lambda c: c.id)
def test_return_refund_chat_node(agent, case):
    _evaluate(agent.return_refund_chat_node, case)


@pytest.mark.parametrize("case", ORDER_CONTINUE_CASES, ids=lambda c: c.id)
def test_order_continue_chat_node(agent, case):
    _evaluate(agent.order_continue_chat_node, case)
