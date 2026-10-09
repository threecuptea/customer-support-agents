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
