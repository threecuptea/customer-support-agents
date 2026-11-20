"""Offline guards for OpenAI prompt caching of the two chat nodes (CSA-26).

OpenAI caches the longest previously-seen prompt PREFIX, from 1,024 tokens on. So each chat node sends a static
SystemMessage first (cacheable) and everything per call after it. These tests fail if a per-call value leaks into the
static part (the prefix would differ per call and the cache would be lost) or if the return/ refund static part
shrinks below the minimum. order_continue_chat_node's static prompt (~330 tokens) is below it ON PURPOSE: padding it was
measured and did not pay off (see ORDER_STATIC_PROMPT in workflow/order_situation.py); it keeps the same layout.
The real cache hit is checked against the API by
tests/test_llm_chat_nodes.py::test_return_refund_chat_node_hits_the_prompt_cache.
"""
import asyncio

import pytest

from langchain_core.messages import HumanMessage, SystemMessage
from models.customer_support_model import OrderRefundStatus, OrderStructuredOutput, ReturnRefundStructuredOutput
from tests.llm_harness.cases import FakeRedisAdapter, FakeStructuredLLM, build_order_continue_state, build_return_refund_state
from workflow.customer_support import CustomerSupportAgent
from workflow.order_situation import ORDER_STATIC_PROMPT, PRIOR_LOST_SHIPMENT
from workflow.return_refund_situation import RETURN_REFUND_STATIC_PROMPT

OPENAI_CACHE_MIN_TOKENS = 1024


def _return_refund_messages(status, **state_kwargs):
    agent = CustomerSupportAgent(checkpointer=None, store=None, redis_adapter=FakeRedisAdapter(status))
    agent.return_refund_llm = llm = FakeStructuredLLM(ReturnRefundStructuredOutput(response="ok", request_human_review_return_refund=False))
    asyncio.run(agent.return_refund_chat_node(build_return_refund_state(**state_kwargs)))
    return llm.calls[0]


def _order_messages(rr_status, **state_kwargs):
    agent = CustomerSupportAgent(checkpointer=None, store=None, redis_adapter=FakeRedisAdapter(rr_status))
    agent.order_llm_for_inquiry_chat = llm = FakeStructuredLLM(OrderStructuredOutput(
        response="ok", escalate=False, escalation_reason=None, order_issue_resolved=False))
    asyncio.run(agent.order_continue_chat_node(build_order_continue_state(**state_kwargs)))
    return llm.calls[0]


def _assert_layout(messages, static):
    assert [type(m) for m in messages] == [SystemMessage, SystemMessage, HumanMessage]
    assert messages[0].content == static


def test_return_refund_static_prefix_is_identical_across_situations_and_customers():
    a = _return_refund_messages("auto_reject", rr_being_processed=True, flag=False, question="Why was it rejected?")
    b = _return_refund_messages("pending", rr_being_processed=False, flag=True, question="What now?",
                                initial=OrderRefundStatus.ORDER_AUTO_REFUNDABLE, human_reviews="note")
    _assert_layout(a, RETURN_REFUND_STATIC_PROMPT)
    _assert_layout(b, RETURN_REFUND_STATIC_PROMPT)
    assert a[1].content != b[1].content            # the per-call part does differ
    assert "Why was it rejected?" == a[2].content   # the question is not in any system message


def test_order_static_prefix_is_identical_across_situations_and_orders():
    a = _order_messages(None, status="delivered", revisit=True, question="Still missing", prior_topic=PRIOR_LOST_SHIPMENT, turns=1)
    b = _order_messages("pending", status="pending", revisit=False, question="Where is it?", summary="s", memory="m")
    _assert_layout(a, ORDER_STATIC_PROMPT)
    _assert_layout(b, ORDER_STATIC_PROMPT)
    assert a[1].content != b[1].content


def test_static_prompts_carry_no_per_call_placeholders():
    for static in (ORDER_STATIC_PROMPT, RETURN_REFUND_STATIC_PROMPT):
        assert not any(f"{{{field}}}" in static for field in ("deadline", "tracking", "delivered_on", "status"))
        assert "HELP_" not in static                 # escalation reasons are rendered as their values


def _token_count(text: str) -> int:
    tiktoken = pytest.importorskip("tiktoken")
    try:
        encoding = tiktoken.get_encoding("o200k_base")  # gpt-4o / gpt-4.1 family
    except Exception as exc:  # the encoding file is downloaded once; offline runs without it skip
        pytest.skip(f"tiktoken encoding unavailable: {exc}")
    return len(encoding.encode(text))


def test_return_refund_static_prompt_reaches_openai_cache_minimum():
    count = _token_count(RETURN_REFUND_STATIC_PROMPT)
    assert count >= OPENAI_CACHE_MIN_TOKENS, f"return/ refund static prompt is {count} tokens, below {OPENAI_CACHE_MIN_TOKENS}"


def test_order_refund_facts_name_escalation_reasons_by_value():
    messages = _order_messages("pending", status="delivered", revisit=False, question="Can I return the rest?")
    assert "HELP_NEW_RETURN_REFUND_REQUEST" not in messages[1].content
