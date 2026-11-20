"""Offline tests: the return/ refund situation is chosen by code, exactly one, strictest first (no LLM involved)."""
import asyncio
import itertools

import pytest

from models.customer_support_model import OrderRefundStatus, ReturnRefundStructuredOutput
from tests.llm_harness.cases import FakeRedisAdapter, FakeStructuredLLM, build_return_refund_state
from workflow.customer_support import CustomerSupportAgent
from workflow.return_refund_situation import (
    RETURN_REFUND_SITUATION_TEXT, ReturnRefundSituation as S, determine_return_refund_situation, render_return_refund_situation_text,
    review_request_allowed,
)

RR_STATUSES = ["pending", "wait_for_manual_review", "auto_approve", "auto_reject", "manual_approve", "manual_reject",
               "manual_flag", None]
DECISIONS = [*OrderRefundStatus, None]


def pick(processed, rr_status, review_requested, decision):
    return determine_return_refund_situation(processed=processed, rr_status=rr_status,
                                             review_requested=review_requested, order_refund_status=decision)


def test_every_combination_yields_exactly_one_situation():
    for combo in itertools.product([True, False], RR_STATUSES, [True, False], DECISIONS):
        assert isinstance(pick(*combo), S)


@pytest.mark.parametrize("processed, rr_status, review_requested, decision, expected", [
    (True, "wait_for_manual_review", True, OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS, S.PROCESSED_AWAITING_REVIEW),
    (True, "wait_for_manual_review", False, OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_DUE_TO_AMOUNT, S.PROCESSED_AWAITING_REVIEW),
    (True, "auto_reject", False, OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS, S.PROCESSED_FINAL),
    (True, "manual_approve", True, OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS, S.PROCESSED_FINAL),
    (False, "pending", True, OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS, S.REVIEW_REQUESTED),
    (False, "pending", False, OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS, S.AGENT_REJECTED),
    (False, "pending", False, OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS, S.AGENT_REJECTED),
    (False, "pending", False, OrderRefundStatus.ORDER_AUTO_REFUNDABLE, S.DEFAULT),
    (False, "pending", False, OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_DUE_TO_AMOUNT, S.DEFAULT),
])
def test_situation_priority(processed, rr_status, review_requested, decision, expected):
    assert pick(processed, rr_status, review_requested, decision) == expected


def test_every_situation_has_a_text_and_final_status_is_filled_in():
    assert set(RETURN_REFUND_SITUATION_TEXT) == set(S)
    assert all(text.strip() for text in RETURN_REFUND_SITUATION_TEXT.values())
    assert "'manual_reject'" in render_return_refund_situation_text(S.PROCESSED_FINAL, status="manual_reject")
    assert all("{" not in render_return_refund_situation_text(s, status="x") for s in S)


def test_only_agent_rejected_lets_the_llm_request_a_human_review():
    assert [s for s in S if review_request_allowed(s)] == [S.AGENT_REJECTED]


# --- the node applies the veto and keeps the flag sticky ---------------------------------------------------
def _run(*, status, processed, flag_in_state, llm_flag, initial):
    agent = CustomerSupportAgent(checkpointer=None, store=None, redis_adapter=FakeRedisAdapter(status))
    agent.return_refund_llm = FakeStructuredLLM(
        ReturnRefundStructuredOutput(response="ok", request_human_review_return_refund=llm_flag))
    state = build_return_refund_state(rr_being_processed=processed, flag=flag_in_state, question="hi", initial=initial)
    return asyncio.run(agent.return_refund_chat_node(state))["request_human_review_return_refund"]


@pytest.mark.parametrize("status, processed, flag_in_state, llm_flag, initial, expected", [
    # AGENT_REJECTED: the LLM may turn it on.
    ("pending", False, False, True, OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS, True),
    # DEFAULT (auto-approvable / amount review): vetoed.
    ("pending", False, False, True, OrderRefundStatus.ORDER_AUTO_REFUNDABLE, False),
    ("pending", False, False, True, OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_DUE_TO_AMOUNT, False),
    # Processed: frozen, the LLM cannot turn it on ...
    ("auto_reject", True, False, True, OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS, False),
    # ... nor off.
    ("wait_for_manual_review", True, True, False, OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS, True),
    # Sticky before processing as well.
    ("pending", False, True, False, OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS, True),
])
def test_node_veto_and_stickiness(status, processed, flag_in_state, llm_flag, initial, expected):
    assert _run(status=status, processed=processed, flag_in_state=flag_in_state, llm_flag=llm_flag, initial=initial) is expected
