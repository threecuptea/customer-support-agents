"""Seeded states and the case tables for the chat nodes.

Each `build_*_state` returns the dict a node reads (a plain dict, like a LangGraph state
snapshot). Cases pair one customer message with what a good reply must/must not do.
Phrases are loose on purpose (LLM wording varies); the structured fields are exact.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from models.model import (
    Order, OrderItem, OrderRefundStatus, RefundRequest, ReturnedOrder, ReturnedOrderItem,
    ReturnRefundInitialDecision,
)
from tests.llm_harness.harness import Case

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
ORDER_ID = 12462


def make_order(status: str = "delivered", **overrides) -> Order:
    fields = dict(
        order_id=ORDER_ID, order_date=NOW - timedelta(days=50), total_amount_incl_tax=108.5,
        tax_applied_rate=0.085, status=status, tracking_number="1Z9999999999999999",
        items=[OrderItem(product_id="PRD-1", product_name="Wine Glasses", supplier_name="Heritage Brands",
                         unit_price=25.0, number_units=4)],
    )
    if status == "delivered":
        fields.update(ship_date=NOW - timedelta(days=45), estimated_delivery_date=NOW - timedelta(days=40),
                      delivery_date=NOW - timedelta(days=40))
    elif status == "transit":
        fields.update(ship_date=NOW - timedelta(days=2), estimated_delivery_date=NOW + timedelta(days=2))
    fields.update(overrides)
    return Order(**fields)


def make_refund_request(status: str, notes: str | None = None) -> RefundRequest:
    return RefundRequest(
        refund_request_id=0, request_date=NOW, status=status,
        notes_for_human_review_override=notes,
        returned_order=ReturnedOrder(
            origin_order_id=ORDER_ID, original_delivery_date=NOW - timedelta(days=40), tax_applied_rate=0.085,
            estimated_amount_refund_incl_tax=108.5,
            items=[ReturnedOrderItem(product_id="PRD-1", product_name="Wine Glasses", supplier_name="Heritage Brands",
                                     unit_price=25.0, number_units=4)],
        ),
    )


# ---------------------------------------------------------------- return_refund_chat_node
def build_return_refund_state(*, request_status: str, assigned_id: int, flag: bool, question: str,
                              initial: OrderRefundStatus = OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS,
                              history: list | None = None) -> dict:
    return {
        "messages": [*(history or []), HumanMessage(content=question)],
        "order_number_provided": ORDER_ID,
        "assigned_refund_request_id": assigned_id,
        "refund_request_to_process": make_refund_request(request_status),
        "initial_return_refund_decision": ReturnRefundInitialDecision(order_refund_status=initial),
        "request_human_review_return_refund": flag,
    }


def _rr(case_id, description, *, request_status, assigned_id, flag, question,
        initial=OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS, history=None, **case_kwargs) -> Case:
    return Case(
        id=case_id, description=description,
        build_state=lambda: build_return_refund_state(
            request_status=request_status, assigned_id=assigned_id, flag=flag, question=question,
            initial=initial, history=history),
        **case_kwargs,
    )


NO_REVIEW_OFFER = ["initiate a human review", "would you like me to"]
NO_PROCESS_PROMPT = ["press 'process the request'", "press the 'process the request'"]

RETURN_REFUND_CASES: list[Case] = [
    _rr("RR-1", "waiting for review: 'how can I get approval?' -> already with reviewer, no new offer",
        request_status="wait_for_manual_review", assigned_id=1001, flag=False,
        question="I have a good reason for a late return. How can I get approval to return?",
        must_contain=[("already", "reviewer", "under review", "being reviewed", "manual review", "human review")],
        must_not_contain=NO_REVIEW_OFFER + NO_PROCESS_PROMPT, expect={"request_human_review_return_refund": False}),
    _rr("RR-2", "waiting for review: bare 'yes, please' is not a new request",
        request_status="wait_for_manual_review", assigned_id=1001, flag=False, question="yes, please",
        must_not_contain=NO_PROCESS_PROMPT + ["notes to reviewer"], expect={"request_human_review_return_refund": False}),
    _rr("RR-3", "waiting for review: how long does it take -> 15 to 30 minutes",
        request_status="wait_for_manual_review", assigned_id=1001, flag=False,
        question="How long will a human review usually take?", must_contain=["15", "30"]),
    _rr("RR-4", "waiting for review: where to send package -> in the email, no invented address",
        request_status="wait_for_manual_review", assigned_id=1001, flag=False,
        question="Where do I send the package?", must_contain=["email"],
        must_not_contain=["street", "p.o. box", "po box", "ups store"]),
    _rr("RR-5", "auto_approve: where to send package -> in the email",
        request_status="auto_approve", assigned_id=1003, flag=False,
        initial=OrderRefundStatus.ORDER_AUTO_REFUNDABLE,
        question="Where do I send the package?", must_contain=["email"],
        must_not_contain=["street", "p.o. box", "po box", "ups store"]),
    _rr("RR-6", "auto_reject (processed): dispute -> finalized, no review offer, flag stays False",
        request_status="auto_reject", assigned_id=1002, flag=False,
        question="This is unfair, I want someone to review it",
        must_not_contain=NO_REVIEW_OFFER, expect={"request_human_review_return_refund": False}),
    _rr("RR-7", "review requested, not processed: tell to write notes and press Process",
        request_status="pending", assigned_id=0, flag=True, question="What do I do next?",
        must_contain=["notes", "process the request"], must_not_contain=["would you like me to initiate"],
        expect={"request_human_review_return_refund": True}),
    _rr("RR-8", "rejected, not processed, customer complains: offer review but do NOT set the flag yet",
        request_status="pending", assigned_id=0, flag=False,
        question="This is unfair, I only pass deadline 1 day, I should get approved",
        must_contain=["human review"], expect={"request_human_review_return_refund": False}),
    _rr("RR-9", "rejected, not processed, no complaint: answer policy question, no unprompted offer",
        request_status="pending", assigned_id=0, flag=False, question="What is the return window?",
        must_contain=["35"], must_not_contain=["would you like me to initiate"]),
    _rr("RR-10", "processed + waiting: general refund-timing question -> policy answer, not the status script",
        request_status="wait_for_manual_review", assigned_id=1001, flag=False,
        question="How long will it take to get my refund after you receive my returned item?",
        must_contain=["business days"], must_not_contain=["15 to 30", "15 minutes"]),
    _rr("RR-11", "processed + waiting: return-window question -> policy answer",
        request_status="wait_for_manual_review", assigned_id=1001, flag=False,
        question="What is the return window?", must_contain=["35"], must_not_contain=["15 to 30", "15 minutes"]),
    _rr("RR-12", "flag is sticky: a later vague turn cannot un-request the review",
        request_status="pending", assigned_id=0, flag=True, question="ok thanks",
        expect={"request_human_review_return_refund": True}),
    _rr("RR-13", "rejected, not processed, customer complain and also request a review in the conversation. It was instructed to set the flag True",
            request_status="pending", assigned_id=0, flag=False,
            question="This is unfair, I want someone to review it",
            must_contain=["human review"], must_not_contain=["would you like me to initiate"],
            expect={"request_human_review_return_refund": True}),    
]


# ---------------------------------------------------------------- order_continue_chat_node
def build_order_continue_state(*, status: str, revisit: bool, question: str, history: list | None = None,
                               memory: str | None = None, summary: str | None = None,
                               turns: int = 0, prior_topic: str | None = None) -> dict:
    messages = []
    if memory:
        messages.append(SystemMessage(content=memory))
    messages += [*(history or []), HumanMessage(content=question)]
    state = {
        "messages": messages,
        "order_number_provided": ORDER_ID,
        "target_order": make_order(status, order_date=NOW - timedelta(days=9)) if status == "pending" else make_order(status),
        "order_is_revisit": revisit,
        # Read by select_order_situation (CSA-19). Ignored by the node until step 3 wires it in.
        "order_turns": turns,
        "order_prior_topic": prior_topic,
    }
    if summary:
        state["summary"] = summary
    return state


def _oc(case_id, description, *, status, revisit, question, history=None, memory=None, summary=None,
        turns=0, prior_topic=None, **case_kwargs) -> Case:
    return Case(
        id=case_id, description=description,
        build_state=lambda: build_order_continue_state(
            status=status, revisit=revisit, question=question, history=history, memory=memory, summary=summary,
            turns=turns, prior_topic=prior_topic),
        **case_kwargs,
    )


PENDING_MEMORY = f"Customer asked about order #{ORDER_ID}, which has been pending for a long time and has not shipped."
LOST_MEMORY = f"Customer reported that order #{ORDER_ID} shows delivered but the package never arrived."
OTHER_MEMORY_ORDER = f"Customer asked a general question about order #{ORDER_ID} and its payment."

ORDER_CONTINUE_CASES: list[Case] = [
    _oc("OC-1", "pending + revisit, first turn: ask if they want to cancel, do NOT escalate yet",
        status="pending", revisit=True, question="Hi, I'm back about my order.", memory=PENDING_MEMORY,
        turns=0, prior_topic="pending_cancel",
        must_contain=["cancel"], expect={"order_issue_escalated": False}),
    _oc("OC-2", "pending + revisit, customer confirms cancel: escalate",
        status="pending", revisit=True, question="Yes, please cancel it.", memory=PENDING_MEMORY,
        turns=1, prior_topic="pending_cancel",
        history=[AIMessage(content="Your order is still pending. Would you like to cancel it and need our help?")],
        expect={"order_issue_escalated": True}),
    _oc("OC-3", "pending, not a revisit: when will it ship -> answer, no escalation",
        status="pending", revisit=False, question="When will my order ship?",
        must_not_contain=["escalate"], expect={"order_issue_escalated": False}),
    _oc("OC-4", "delivered + revisit (lost shipment), first turn: ask if found, do NOT escalate yet",
        status="delivered", revisit=True, question="Hi, I'm back about my order.", memory=LOST_MEMORY,
        turns=0, prior_topic="lost_shipment",
        must_contain=[("found", "find", "help", "assistance", "luck")], expect={"order_issue_escalated": False}),
    _oc("OC-5", "delivered + revisit, customer wants help after searching: escalate",
        status="delivered", revisit=True, question="No, I still can't find it. Please help me.", memory=LOST_MEMORY,
        turns=1, prior_topic="lost_shipment",
        history=[AIMessage(content="Have you found your package yet, or do you need our help?")],
        expect={"order_issue_escalated": True}),
    _oc("OC-6", "unrelated general question -> point to the general inquiry button",
        status="delivered", revisit=False, question="What is your policy on gift cards?",
        must_contain=[("general inquiry", "general question")]),
    _oc("OC-7", "in transit, not a revisit: where is my package -> point to tracking, no escalation",
        status="transit", revisit=False, question="Where is my package right now?",
        must_contain=[("tracking", "ups")], expect={"order_issue_escalated": False}),
    _oc("OC-8", "delivered, not a revisit: customer says it never arrived -> search steps, no escalation yet",
        status="delivered", revisit=False, question="It says delivered but I never received my package.",
        must_contain=[("tracking", "porch", "neighbor", "photo")], expect={"order_issue_escalated": False}),
    _oc("OC-9", "pending, revisit about something else: plain pending answer, no cancel escalation",
        status="pending", revisit=True, question="Any update on this order?", memory=OTHER_MEMORY_ORDER,
        turns=0, prior_topic="other",
        expect={"order_issue_escalated": False}),
    _oc("OC-10", "pending, not a revisit, customer asks to cancel now: escalate",
        status="pending", revisit=False, question="Please cancel this order now, I don't want to wait.",
        expect={"order_issue_escalated": True}),
    _oc("OC-11", "pending + cancel revisit, first turn, but the customer asks an unrelated general question -> general inquiry button",
        status="pending", revisit=True, question="Do you ship to Canada?", memory=PENDING_MEMORY,
        turns=0, prior_topic="pending_cancel",
        must_contain=[("general inquiry", "general question")], expect={"order_issue_escalated": False}),
    _oc("OC-12", "delivered, not a revisit, unrelated general question -> general inquiry button, no escalation",
        status="delivered", revisit=False, question="Do you ship to Canada?",
        must_contain=[("general inquiry", "general question")], expect={"order_issue_escalated": False}),
]


# ---------------------------------------------------------------- detect_order_revisit_node
# The revisit classifier (is_revisit + prior_topic) feeds select_order_situation, so a wrong label here
# picks the wrong situation. It runs on LLM_MODEL (the "other-node" model in the report header).
OTHER_MEMORY = f"Customer asked to return a damaged item from order #{ORDER_ID} and was told the refund decision."
DIFFERENT_ORDER_MEMORY = "Customer reported that order #99999 shows delivered but the package never arrived."


def build_revisit_state(*, status: str, memory: str | None) -> dict:
    messages = [SystemMessage(content=f"Previous conversations:\n{memory}")] if memory else []
    messages.append(HumanMessage(content=f"Order inquiry: {ORDER_ID}"))
    return {
        "messages": messages,
        "order_number_provided": ORDER_ID,
        "target_order": make_order(status, order_date=NOW - timedelta(days=9)) if status == "pending" else make_order(status),
    }


def _rev(case_id, description, *, status, memory, revisit, topic) -> Case:
    return Case(
        id=case_id, description=description,
        build_state=lambda: build_revisit_state(status=status, memory=memory),
        expect={"order_is_revisit": revisit, "order_prior_topic": topic},
    )


REVISIT_CASES: list[Case] = [
    _rev("REV-1", "memory: lost shipment on THIS order -> revisit, lost_shipment",
         status="delivered", memory=LOST_MEMORY, revisit=True, topic="lost_shipment"),
    _rev("REV-2", "memory: long pending, not shipped, on THIS order -> revisit, pending_cancel",
         status="pending", memory=PENDING_MEMORY, revisit=True, topic="pending_cancel"),
    _rev("REV-3", "memory: damaged-item return on THIS order -> revisit, other",
         status="delivered", memory=OTHER_MEMORY, revisit=True, topic="other"),
    _rev("REV-4", "no memory at all -> not a revisit, no topic",
         status="delivered", memory=None, revisit=False, topic=None),
    _rev("REV-5", "memory is about a DIFFERENT order -> not a revisit, no topic",
         status="delivered", memory=DIFFERENT_ORDER_MEMORY, revisit=False, topic=None),
]
