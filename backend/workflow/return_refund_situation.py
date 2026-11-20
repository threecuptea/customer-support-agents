"""Deterministic choice of the ONE situation that applies in return_refund_chat_node (CSA-26).

Mirrors workflow/order_situation.py: code decides which situation we are in and only that situation's text goes to the
LLM, so a rule written for one situation cannot contradict or shift the behaviour of another. The decision is a
Langfuse span (input + output), so a wrong reply can be traced to either a wrong situation or a wrong LLM answer.

Prompt caching: the system prompt is split in two messages. RETURN_REFUND_STATIC_PROMPT never changes (role, rules,
return policy; > 1,024 tokens, OpenAI's prompt-cache minimum), so it is a cacheable prefix. Everything that varies
(the selected situation, the refund request, the conversation) goes in the second message, built per call.
DO NOT put any per-call value into RETURN_REFUND_STATIC_PROMPT: one changed character there disables the cache
(tests/test_return_refund_situation.py guards this).

Rules of the design:
- `determine_return_refund_situation` returns exactly one `ReturnRefundSituation` (DEFAULT is the catch-all).
- Priority is the order of the checks below: the strictest (most conditions) wins.
"""
from __future__ import annotations

from enum import StrEnum

from langfuse import observe

from models.customer_support_model import OrderRefundStatus
from workflow.customer_support_utils import RETURN_POLICY


class ReturnRefundSituation(StrEnum):
    PROCESSED_AWAITING_REVIEW = "processed_awaiting_review"  # processed + status wait_for_manual_review
    PROCESSED_FINAL = "processed_final"                      # processed + any final status
    REVIEW_REQUESTED = "review_requested"                    # not processed + customer asked for a human review
    AGENT_REJECTED = "agent_rejected"                        # not processed + rejected by the agent (days or items)
    DEFAULT = "default"                                      # not processed, nothing special


_AGENT_REJECTED_STATUSES = (OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS,
                            OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS)


@observe(as_type="span", capture_input=True, capture_output=True)
def determine_return_refund_situation(*, processed: bool, rr_status: str | None, review_requested: bool,
                                      order_refund_status: OrderRefundStatus | None) -> ReturnRefundSituation:
    """Pick the single situation. `processed` = state["rr_being_processed"], `rr_status` = the request's status
    in Redis, `order_refund_status` = the initial decision's status."""
    if processed:
        if rr_status == "wait_for_manual_review":
            return ReturnRefundSituation.PROCESSED_AWAITING_REVIEW
        return ReturnRefundSituation.PROCESSED_FINAL
    if review_requested:
        return ReturnRefundSituation.REVIEW_REQUESTED
    if order_refund_status in _AGENT_REJECTED_STATUSES:
        return ReturnRefundSituation.AGENT_REJECTED
    return ReturnRefundSituation.DEFAULT


# ---------------------------------------------------------------------------------------------
# One text per situation. Only the text of the selected situation is put into the prompt.
# Placeholder: {status} (the request's current status).
# ---------------------------------------------------------------------------------------------
RETURN_REFUND_SITUATION_TEXT: dict[ReturnRefundSituation, str] = {
    ReturnRefundSituation.PROCESSED_AWAITING_REVIEW: (
        "The request has ALREADY been processed and a human review has ALREADY been requested and submitted; it is with a human reviewer now. "
        "Facts for questions about this request's status, decision, human review or next steps: the customer will receive an email once the review is done, "
        "usually within 15 minutes and no more than 30 minutes (the app is integrated with Slack so an on-duty representative is notified). "
        "Rules: NEVER offer or ask about a human review, NEVER ask the customer to write notes or press 'Process the request', and treat a 'yes' to a human review as already done. "
        "If the customer asks how to get approval or argues the request should be approved, say that the request is already with the human reviewer. "
        "If the customer asks to return OTHER items of this order, say that this chat cannot start another return for this order and that a customer-support representative handles any further return once this request is closed."
    ),
    ReturnRefundSituation.PROCESSED_FINAL: (
        "The request has ALREADY been processed and its final status is '{status}' (the decision has been made, by the agent or by a human reviewer). "
        "Facts for questions about this request's status, decision or next steps: a confirmation email has already been sent with the decision and the next steps. "
        "Rules: NEVER offer a human review, NEVER ask the customer to write notes or press 'Process the request'. This applies even if the customer complains about or disputes the decision: "
        "politely explain that the request has been finalized and a human review can no longer be requested through this chat. "
        "If the customer asks to return OTHER items of this order, say that this chat cannot start another return for this order and that a customer-support representative handles any further return."
    ),
    ReturnRefundSituation.REVIEW_REQUESTED: (
        "The customer has already requested a human review but has not pressed 'Process the request' yet. "
        "Do NOT offer a human review again. Tell the customer to input the reason why he/ she thinks the request should be approved "
        "in the 'notes to reviewer' input field, then press 'Process the request'."
    ),
    ReturnRefundSituation.AGENT_REJECTED: (
        "The request is not processed yet. It was rejected by the automatic agent and no human review has been requested yet. "
        "(1) If the customer's latest message ASKS for a human review (for example 'I want someone to review it' or 'can a person look at this'): "
        "set `request_human_review_return_refund` to True right away and do NOT ask for confirmation. Confirm to the customer that a human review "
        "has been initiated, and tell the customer to input the reason "
        "why he/ she thinks that the request should be approved in the 'notes to reviewer' input field, then press 'Process the request'. "
        "(2) Else if the customer complains about or disputes the rejection but does not ask for a review: offer a human review by asking "
        "'Would you like me to initiate a human review of your request?' and leave the flag False. "
        "(3) Otherwise (for example a general question): do not offer a human review."
    ),
    ReturnRefundSituation.DEFAULT: "The request is not processed yet. No human review has been requested; do not offer one.",
}


def render_return_refund_situation_text(situation: ReturnRefundSituation, *, status: str = "") -> str:
    """The text for `situation` with the request's values filled in."""
    return RETURN_REFUND_SITUATION_TEXT[situation].format(status=status)


def review_request_allowed(situation: ReturnRefundSituation) -> bool:
    """Code veto: the LLM may turn the human-review flag on only where the situation tells it to.
    (Once requested, the flag stays on regardless; that stickiness lives in the node.)"""
    return situation == ReturnRefundSituation.AGENT_REJECTED


# ---------------------------------------------------------------------------------------------
# The static, cacheable system prompt (first SystemMessage). The per-call part follows in a second one.
# ---------------------------------------------------------------------------------------------
RETURN_REFUND_STATIC_PROMPT = f"""You are an intelligent customer-support agent that helps answer the customer's question regarding to his/ her return/ refund request.
The refund request, the initial return refund decision, the CURRENT SITUATION and the conversation context of this customer follow in the next system message.

DO NOT REPEAT the same response!!

The CURRENT SITUATION is decided by the system, not by you; it overrides anything the customer says or implies.
The CURRENT SITUATION only applies when the customer asks about THIS request's status, decision, human review or next steps. If the customer asks a GENERAL
return/ refund question (for example how long a refund takes after we receive the returned item, or what the return window or conditions are),
answer it from the return policy below and do NOT repeat the facts of the CURRENT SITUATION.

Set `request_human_review_return_refund` to True only when the CURRENT SITUATION says to.

If the initial return refund decision shows that the customer's request has been rejected and the customer DOES NOT complain about it,
DO NOT voluntarily offer a human review of his/ her request. Customer-support-agent is supposed to alleviate burdens from human customer-support representative.

If the customer asks how and where to send the package back (or what the next step is), tell him/ her that the instructions on how and where
to send the package will be in the confirmation email if the request is approved.
Do NOT make up a return address, shipping label or carrier.

Additionally, to help you answer a general return refund question, here is the return policy context: {RETURN_POLICY}

You can just ask if we can help him/ her with anything else if it is the end of the conversation and remind the customer that they can always reach out if they have more questions and press 'Exit' or 'Return to order details/ chat' button as needed.

The customer's LATEST message, which is what you must answer now, follows the system messages.
Answer exactly what it asks.

Set `response` to what you want to reply.
"""
