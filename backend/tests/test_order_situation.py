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


# ---- step 2: the revisit node also classifies the prior topic -----------------------------------
from typing import get_args

from models.model import OrderPriorTopic, OrderRevisitEval


def test_prior_topic_literal_matches_the_situation_module():
    assert set(get_args(OrderPriorTopic)) == set(PRIOR_TOPICS)


def _revisit_node_result(eval_result):
    agent = CustomerSupportAgent(checkpointer=None, store=None)

    class FakeLLM:
        async def ainvoke(self, *_a, **_k):
            return eval_result

    agent.order_llm_for_revisit_eval = FakeLLM()
    state = build_order_continue_state(status="delivered", revisit=False, question="Order inquiry: 12462")
    return asyncio.run(agent.detect_order_revisit_node(state))


def test_revisit_node_returns_the_prior_topic_for_a_revisit():
    result = _revisit_node_result(OrderRevisitEval(is_revisit=True, prior_topic=PRIOR_LOST_SHIPMENT))
    assert result == {"order_is_revisit": True, "order_prior_topic": PRIOR_LOST_SHIPMENT}


def test_revisit_node_drops_a_prior_topic_given_without_a_revisit():
    result = _revisit_node_result(OrderRevisitEval(is_revisit=False, prior_topic=PRIOR_PENDING_CANCEL))
    assert result == {"order_is_revisit": False, "order_prior_topic": None}


def test_revisit_node_defaults_when_the_llm_returns_nothing():
    # the mock LLM returns None for structured output
    assert _revisit_node_result(None) == {"order_is_revisit": False, "order_prior_topic": None}


def test_revisit_with_no_topic_stays_a_revisit_with_none():
    result = _revisit_node_result(OrderRevisitEval(is_revisit=True))
    assert result == {"order_is_revisit": True, "order_prior_topic": None}


# ---- step 3 (texts only; not wired into the node yet) ------------------------------------------
from workflow.order_situation import ALWAYS_ON_TEXT, SITUATION_TEXT, render_situation_text


def test_every_situation_has_a_text():
    assert set(SITUATION_TEXT) == set(OrderSituation)
    assert all(text.strip() for text in SITUATION_TEXT.values())


def test_texts_render_without_leftover_placeholders():
    for situation in OrderSituation:
        text = render_situation_text(situation, deadline="2026-10-16", tracking="1Z999", delivered_on="2026-10-01")
        assert "{" not in text and "}" not in text


def test_texts_only_name_escalation_reasons_that_fit_their_situation():
    # The escalation reasons a situation may ask for; a text must not drag in an unrelated one.
    allowed = {
        OrderSituation.LOST_SHIPMENT_FIRST_REVISIT: set(),
        OrderSituation.LOST_SHIPMENT_FOLLOWUP: {"HELP_LOST_SHIPMENT"},
        OrderSituation.PENDING_CANCEL_FIRST_REVISIT: set(),
        OrderSituation.PENDING_CANCEL_FOLLOWUP: {"HELP_CANCEL_ORDER"},
        OrderSituation.PENDING: {"HELP_CANCEL_ORDER"},
        OrderSituation.IN_TRANSIT: set(),
        OrderSituation.DELIVERED: set(),
        OrderSituation.DEFAULT: {"HELP_ANSWER_ORDER_INQUIRY"},
    }
    reasons = {"HELP_LOST_SHIPMENT", "HELP_CANCEL_ORDER", "HELP_ANSWER_ORDER_INQUIRY", "HELP_CHECK_RETURN_REFUND_STATUS"}
    for situation, text in SITUATION_TEXT.items():
        assert {r for r in reasons if r in text} == allowed[situation], situation


def test_first_revisit_situations_forbid_escalating():
    for situation in (OrderSituation.LOST_SHIPMENT_FIRST_REVISIT, OrderSituation.PENDING_CANCEL_FIRST_REVISIT):
        assert "Do NOT escalate" in SITUATION_TEXT[situation]


def test_always_on_text_has_no_situation_specific_rules():
    for word in ("pending", "in transit", "tracking number", "porch", "deadline"):
        assert word not in ALWAYS_ON_TEXT.lower()


# ---- code veto of impossible escalations (CSA-19 step 3)
from models.model import ESCALATE_REASON
from workflow.order_situation import escalation_allowed


def test_escalation_vetoed_on_first_revisit_situations():
    for situation in (OrderSituation.LOST_SHIPMENT_FIRST_REVISIT, OrderSituation.PENDING_CANCEL_FIRST_REVISIT):
        assert not escalation_allowed(ESCALATE_REASON.HELP_ANSWER_ORDER_INQUIRY, situation, "delivered")


def test_cancel_only_for_pending_and_lost_only_for_delivered():
    assert escalation_allowed(ESCALATE_REASON.HELP_CANCEL_ORDER, OrderSituation.PENDING, "pending")
    assert not escalation_allowed(ESCALATE_REASON.HELP_CANCEL_ORDER, OrderSituation.DELIVERED, "delivered")
    assert escalation_allowed(ESCALATE_REASON.HELP_LOST_SHIPMENT, OrderSituation.LOST_SHIPMENT_FOLLOWUP, "delivered")
    assert not escalation_allowed(ESCALATE_REASON.HELP_LOST_SHIPMENT, OrderSituation.PENDING, "pending")


def test_other_escalations_allowed_outside_first_revisit():
    assert escalation_allowed(ESCALATE_REASON.HELP_CHECK_RETURN_REFUND_STATUS, OrderSituation.DELIVERED, "delivered")
