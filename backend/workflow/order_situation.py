"""Deterministic choice of the ONE situation that applies in order_continue_chat_node.

The prompt used to carry every rule at once, so a wording change near one rule moved cases that looked
unrelated (CSA-18 A/B). Instead, code decides which situation we are in and only that situation's text goes to the
LLM (the pattern CSA-17 introduced for return_refund_chat_node). This module is pure (no LLM, no I/O), so the
"exactly one situation, strictest first" property is tested offline.

Rules of the design:
- `select_order_situation` returns exactly one `OrderSituation`; there is always a result (DEFAULT is the catch-all).
- Priority is the order of the checks below: the strictest (most conditions) wins.
- A revisit whose prior topic does not match the order's status (or is "other"/unknown) is not special: it behaves
  as its plain status situation.
"""
from __future__ import annotations

from enum import StrEnum

from models.model import ESCALATE_REASON

# Prior-visit topics that have their own situations. Anything else (including None) is not special.
PRIOR_LOST_SHIPMENT = "lost_shipment"
PRIOR_PENDING_CANCEL = "pending_cancel"
PRIOR_OTHER = "other"
PRIOR_TOPICS = (PRIOR_LOST_SHIPMENT, PRIOR_PENDING_CANCEL, PRIOR_OTHER)


class OrderSituation(StrEnum):
    LOST_SHIPMENT_FOLLOWUP = "lost_shipment_followup"            # revisit + lost shipment + conversation started
    PENDING_CANCEL_FOLLOWUP = "pending_cancel_followup"          # revisit + pending cancel + conversation started
    LOST_SHIPMENT_FIRST_REVISIT = "lost_shipment_first_revisit"  # revisit + lost shipment + no conversation yet
    PENDING_CANCEL_FIRST_REVISIT = "pending_cancel_first_revisit"
    PENDING = "pending"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    DEFAULT = "default"                                          # unknown status: no special handling


def select_order_situation(*, status: str | None, is_revisit: bool, prior_topic: str | None,
                           turns: int) -> OrderSituation:
    """Pick the single situation. `turns` = replies already given in this thread (state["order_turns"])."""
    started = turns > 0
    if is_revisit:
        # Strictest first: a revisit about a topic that still matches the order's status.
        if prior_topic == PRIOR_LOST_SHIPMENT and status == "delivered":
            return OrderSituation.LOST_SHIPMENT_FOLLOWUP if started else OrderSituation.LOST_SHIPMENT_FIRST_REVISIT
        if prior_topic == PRIOR_PENDING_CANCEL and status == "pending":
            return OrderSituation.PENDING_CANCEL_FOLLOWUP if started else OrderSituation.PENDING_CANCEL_FIRST_REVISIT
    if status == "pending":
        return OrderSituation.PENDING
    if status == "transit":
        return OrderSituation.IN_TRANSIT
    if status == "delivered":
        return OrderSituation.DELIVERED
    return OrderSituation.DEFAULT


# ---------------------------------------------------------------------------------------------
# One text per situation. Only the text of the selected situation is put into the prompt (step 3),
# so a rule written here cannot contradict a rule that belongs to another situation.
# Placeholders: {deadline} (order date + 7 days), {tracking} (tracking number), {delivered_on}.
# Escalation reasons are named by their ESCALATE_REASON member (resolved by the node), e.g. HELP_LOST_SHIPMENT.
# ---------------------------------------------------------------------------------------------
SITUATION_TEXT: dict[OrderSituation, str] = {
    OrderSituation.LOST_SHIPMENT_FIRST_REVISIT: (
        "The customer is revisiting this order. On the previous visit they reported that the shipment shows as delivered but never arrived. "
        "We have not discussed it yet in this visit. First check the customer's latest message: if it is a general question unrelated to this order, "
        "ONLY ask him/ her to click the 'general inquiry' button and do not ask the question below. Otherwise ask, in one short message, whether he/ she has "
        "found the package and whether he/ she needs our help. Do NOT escalate yet: leave `escalate` False."
    ),
    OrderSituation.LOST_SHIPMENT_FOLLOWUP: (
        "The customer is revisiting this order about a lost shipment (it shows as delivered but never arrived) and we have already asked whether "
        "he/ she found it and needs our help. Unless the customer's latest message is about something else: if the customer says the package is still missing and wants our help, set `escalate` to True and "
        "`escalate_reason` to HELP_LOST_SHIPMENT. If the customer found the package, say so warmly and ask whether we can help with anything else. "
        "Otherwise keep helping with the search steps (tracking-photo, porch, neighbours). Never repeat the same question."
    ),
    OrderSituation.PENDING_CANCEL_FIRST_REVISIT: (
        "The customer is revisiting this order. On the previous visit they asked about it being pending for a long time and not shipped. "
        "We have not discussed it yet in this visit. First check the customer's latest message: if it is a general question unrelated to this order, "
        "ONLY ask him/ her to click the 'general inquiry' button and do not ask the question below. Otherwise ask, in one short message, whether he/ she would "
        "like to cancel the order and needs our help. Do NOT escalate yet: leave `escalate` False."
    ),
    OrderSituation.PENDING_CANCEL_FOLLOWUP: (
        "The customer is revisiting this pending order and we have already asked whether he/ she wants to cancel it. Unless the customer's latest message is about "
        "something else: if the customer says he/ she wants to cancel, set `escalate` to True and `escalate_reason` to HELP_CANCEL_ORDER. If not, tell him/ her the order should be fulfilled "
        "no later than {deadline} and ask whether we can help with anything else."
    ),
    OrderSituation.PENDING: (
        "The order is 'pending'. Tell the customer it should be fulfilled no later than {deadline} (within 7 days) and that he/ she can always call "
        "back by then to cancel. Do NOT offer to cancel and do NOT escalate unless the customer asks to cancel the order now; in that case set "
        "`escalate` to True and `escalate_reason` to HELP_CANCEL_ORDER."
    ),
    OrderSituation.IN_TRANSIT: (
        "The order is in 'transit'. Ask the customer to track its whereabouts with the UPS tracking number {tracking}. Do not escalate."
    ),
    OrderSituation.DELIVERED: (
        "The order is 'delivered' (on {delivered_on}). Answer the customer's question from the order details. Only if the customer says the shipment "
        "did not arrive: ask him/ her to click the tracking number link to see whether a delivery photo was taken; if yes, ask whether it was taken on "
        "his/ her porch and, if so, to check any Ring or SimpliSafe footage or ask family members before concluding it was stolen (UPS is not "
        "responsible for a stolen shipment); if there is no photo or it is not his/ her porch, ask him/ her to look around the house and check with "
        "neighbours. Let him/ her know to revisit us after exhausting those searches. Do not escalate at this point."
    ),
    OrderSituation.DEFAULT: (
        "No special situation applies. Answer from the order details. If you cannot answer, set `escalate` to True and `escalate_reason` to "
        "HELP_ANSWER_ORDER_INQUIRY."
    ),
}

# Rules that hold in every situation (kept short on purpose; nothing situation-specific belongs here).
ALWAYS_ON_TEXT = (
    "If the customer's latest message is a general question not related to this order (shipping policy, gift cards, other countries, etc.), "
    "ignore the situation instructions above: ask him/ her to click the 'general inquiry' button, where the agent will be happy to help, and do NOT escalate. "
    "If the customer wants to exchange or return an item for a refund, or is complaining about item(s) delivered for any of these reasons: "
    "wrong size or fit, doesn't match description or photos, damaged or defective, changed mind or impulse buy, late delivery, wrong item, "
    "tell him/ her to press the 'Like to Exchange or Return for Refund' button and we will help with the process. "
    "This app cannot check the status of a return or refund for a specific order: set `escalate` to True and `escalate_reason` to "
    "HELP_CHECK_RETURN_REFUND_STATUS. If the conversation reaches a scenario you do not cover or you do not know the answer, set `escalate` to True "
    "and `escalate_reason` to HELP_ANSWER_ORDER_INQUIRY. You can wrap up by saying 'Can I help you with anything else?' when the conversation seems to be at its end. "
    "When the customer replies with an ending signal, set `order_issue_resolved` to True. "
    "DO NOT REPEAT the same response."
)


def render_situation_text(situation: OrderSituation, *, deadline: str = "", tracking: str = "",
                          delivered_on: str = "") -> str:
    """The text for `situation` with the order's values filled in."""
    return SITUATION_TEXT[situation].format(deadline=deadline, tracking=tracking, delivered_on=delivered_on)


_NO_ESCALATION = (OrderSituation.LOST_SHIPMENT_FIRST_REVISIT, OrderSituation.PENDING_CANCEL_FIRST_REVISIT)


def escalation_allowed(reason: ESCALATE_REASON | None, situation: OrderSituation, status: str | None) -> bool:
    """Code veto for escalations that cannot apply (a model slip, not a customer need).

    - Nothing escalates on the two first-revisit situations: we have only just asked the question.
    - Cancel help only exists for a pending order; lost-shipment help only for a delivered one.
    """
    if situation in _NO_ESCALATION:
        return False
    if reason == ESCALATE_REASON.HELP_CANCEL_ORDER:
        return status == "pending"
    if reason == ESCALATE_REASON.HELP_LOST_SHIPMENT:
        return status == "delivered"
    return True
