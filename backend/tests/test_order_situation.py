"""Offline tests: the order situation is chosen by code, exactly one, strictest first (no LLM involved)."""
import asyncio
import itertools

import pytest

from models.model import OrderStructuredOutput
from tests.llm_harness.cases import build_order_continue_state
from workflow.customer_support import CustomerSupportAgent
from workflow.order_situation import (
    PRIOR_LOST_SHIPMENT, PRIOR_OTHER, PRIOR_PENDING_CANCEL, PRIOR_TOPICS, OrderSituation, select_order_situation,
)

STATUSES = ["pending", "transit", "delivered", None, "weird"]
PRIORS = [None, *PRIOR_TOPICS]


def pick(status, revisit, prior, turns):
    return select_order_situation(status=status, is_revisit=revisit, prior_topic=prior, turns=turns)


def test_every_combination_yields_exactly_one_situation():
    for status, revisit, prior, turns in itertools.product(STATUSES, [True, False], PRIORS, [0, 1, 5]):
        assert isinstance(pick(status, revisit, prior, turns), OrderSituation)


@pytest.mark.parametrize("status, revisit, prior, turns, expected", [
    ("delivered", True, PRIOR_LOST_SHIPMENT, 0, OrderSituation.LOST_SHIPMENT_FIRST_REVISIT),
    ("delivered", True, PRIOR_LOST_SHIPMENT, 1, OrderSituation.LOST_SHIPMENT_FOLLOWUP),
    ("pending", True, PRIOR_PENDING_CANCEL, 0, OrderSituation.PENDING_CANCEL_FIRST_REVISIT),
    ("pending", True, PRIOR_PENDING_CANCEL, 3, OrderSituation.PENDING_CANCEL_FOLLOWUP),
])
def test_strictest_situations(status, revisit, prior, turns, expected):
    assert pick(status, revisit, prior, turns) == expected


@pytest.mark.parametrize("status, expected", [
    ("pending", OrderSituation.PENDING), ("transit", OrderSituation.IN_TRANSIT),
    ("delivered", OrderSituation.DELIVERED), ("weird", OrderSituation.DEFAULT), (None, OrderSituation.DEFAULT),
])
def test_plain_status_situations(status, expected):
    assert pick(status, False, None, 0) == expected


def test_a_revisit_that_is_not_special_behaves_as_its_status():
    # unknown / other prior topic, or a topic that no longer matches the order's status
    for prior in (None, PRIOR_OTHER):
        assert pick("pending", True, prior, 0) == OrderSituation.PENDING
        assert pick("delivered", True, prior, 2) == OrderSituation.DELIVERED
    assert pick("pending", True, PRIOR_LOST_SHIPMENT, 0) == OrderSituation.PENDING       # topic/status mismatch
    assert pick("delivered", True, PRIOR_PENDING_CANCEL, 0) == OrderSituation.DELIVERED
    assert pick("transit", True, PRIOR_LOST_SHIPMENT, 1) == OrderSituation.IN_TRANSIT


def test_special_situations_need_a_revisit():
    # The same prior topic on a non-revisit never selects a revisit situation.
    assert pick("delivered", False, PRIOR_LOST_SHIPMENT, 0) == OrderSituation.DELIVERED
    assert pick("pending", False, PRIOR_PENDING_CANCEL, 4) == OrderSituation.PENDING


def test_started_conversation_only_changes_the_special_situations():
    for status in ("pending", "transit", "delivered"):
        assert pick(status, False, None, 0) == pick(status, False, None, 9)


# ---- the turn counter on order_continue_chat_node ------------------------------------------
def test_counter_increments_on_a_normal_reply():
    agent = CustomerSupportAgent(checkpointer=None, store=None)

    class FakeLLM:
        async def ainvoke(self, *_a, **_k):
            return OrderStructuredOutput(response="hi")

    agent.order_llm_for_inquiry_chat = FakeLLM()
    state = build_order_continue_state(status="delivered", revisit=False, question="hello")
    assert asyncio.run(agent.order_continue_chat_node(state))["order_turns"] == 1
    state["order_turns"] = 4
    assert asyncio.run(agent.order_continue_chat_node(state))["order_turns"] == 5


def test_counter_increments_on_the_escalate_path_too():
    agent = CustomerSupportAgent(checkpointer=None, store=None)

    class FakeLLM:
        async def ainvoke(self, *_a, **_k):
            return OrderStructuredOutput(response="x", escalate=True)

    agent.order_llm_for_inquiry_chat = FakeLLM()
    state = build_order_continue_state(status="pending", revisit=True, question="cancel it")
    assert asyncio.run(agent.order_continue_chat_node(state))["order_turns"] == 1
