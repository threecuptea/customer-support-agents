from __future__ import annotations

from langchain_core.tools import tool
from rapidfuzz import process, fuzz
from models.model import CustomerContext, Order, RefundRequest, RefundProcess, FAQMatchResult
from dotenv import load_dotenv
import os

load_dotenv(override= True)

threshold_amount_auto_approve = os.getenv("AMOUNT_THRESHOLD_AUTO")
threshold_days_auto_approve = os.getenv("DAYS_THRESHOLD_AUTO=")


# Group common e-commerce FAQs into core topics:
# Shipping & Delivery
# Orders and Payment
# Return & Refunds
# Grouping these questions into clear categories helps shoppers find fast answers and reduces support requests.
# We should post them in the the login page as well as the chat page
# This should have feedback loop: we should amend those questions we miss from customers' feedback
FAQs = {
    "Shipping & Delivery": {
        "When will my order ship?": "Orders usually ship in 1 to 2 business days unless the order item is temporarily out of stock."
          "You will get a tracking number link by email when we ship",
        "How long does a delivery take?": "Standard shipping takes 3 to 5 business days. Expedited options are avilable at checkout.", 
        "How do I track my order?": "Using the tracking number included in the shipping confirmation email.",
        "Do you ship internationally?": "Yes, to select countries. Shipping costs show at checkout.",
        "What if my package is lost or late?": "Check your tracking link first. Contact us if you still have trouble to get it on time",
    },
    "Returns and Refunds": {
        "What is your return policy?": "We accept returns within 35 days of delivery for unused items",
        "Can I still get my refund if my order exceeds 35 days of return policy": "Yes, with customer support representative's approval",
        "How do I start a return?": "You can talk to me to start a return/ refund request.",
        "When will I get my refund?": "Refunds usually take 7 to 10 business days after we get the item back.",
        "Are returns free?": "Yes, we will include the return shipping label in the request confirmation email"
    },
    "Orders and Payment": {
        "What payment methods do you accept?": "We take credit/ debit cards, PayPal, Apple Pay, and Google Wallet.",
        "Can I cancel my order?": "You can cancel your order as long as the order is in pending status.  You cannot cancel an order once it has been shipped and in transit status.",
        "Is my payment secure?": "Yes. All data is encrypted via SSL.",
    }    
}

faq_dict = {}
faq_dict.update(FAQs['Shipping & Delivery'])
faq_dict.update(FAQs['Returns and Refunds'])
faq_dict.update(FAQs['Orders and Payment'])
faq_qst_lst = list(faq_dict.keys())


# Technically I don't need @tool decorator because it is not calling from LLM

@tool
def find_closest_faq(user_question: str) -> FAQMatchResult:
    """Find the closest question and answer among FAQs using fuzzy WRatio (Weighted Ratio)
    Args:
        user_question: the user's question to match against
    Returns:
       a FAQMatchResult object
    """
    match = process.extractOne(user_question, faq_qst_lst, scorer=fuzz.WRatio)
    # print(f"Best match: {match[0]} with confidence {match[1]:.2f}")
    # if match and match[1] > 70.0:  # confidence threshold
    matched_question = match[0]
    faq = next((key, val) for key, val in faq_dict.items() if key == matched_question)
    # double to escape {}
    return FAQMatchResult(question= faq[0], answer= faq[1], confidence_score=round(match[1], 2))
    

@tool
def retrieve_target_order(context: CustomerContext, order_number: int) -> Order | None:
    """ retrieve the target order from the CustomerContext
        Args:
            context: CustomerContext
            order_number: used to locate the order from the CustomerContext
        Returns:
            an target Order
    """
    if context.latest_orders:
        for order in context.latest_orders:
            if order.order_id == order_number:
                return order
    return None


@tool
def calculate_amount_refund_incl_tax(refund_request: RefundRequest) -> float:
    """Calculate total refund amount including tax base upon `ReturnedOrder` and `ReturnedOrderItem` associated 
        with the `RefundRequest` then applying `tax_applied_rate` added to total refund amount
        Args:
            refund_request: RefundRequest
        Returns:
            float: representing total amount refund including tax if there is `RefundRequest` and 
            `ReturnedOrder` and `ReturnedOrderItem` associated with it
            return float('-inf') if not
    """
    # items min_length= 1
    if refund_request is None or refund_request.returned_order is None:
        raise ValueError("The refund request does not have required information!!")

    total_before_tax = 0.0
    for item in refund_request.returned_order.items:
        total_before_tax += item.unit_price * item.number_units

    return total_before_tax * (1 + refund_request.returned_order.tax_applied_rate)

@tool
def check_if_refund_require_manual_approval(refund_request: RefundRequest) -> RefundProcess:
    """Check if this refund request requires manual approval.
    Use this right BEFORE processing a RefundRequest and AFTER set 'amount_refund_incl_tax' 
    of `ReturnedOrder` for that RefundRequest
    It compares two thresholds: 
    `threshold_amount_auto_approve` - for auto approval if the refund amount is below this threshold
    `threshold_days_auto_approve` - for auto approval if the refund request date is within this return window
    Args:
        refund_request: a valid RefundRequest
    Returns:
        A RefundProcess object.
        if the refund request requires manual approval, 'requires_manual_approval' attribute
        will return True with 'reason' expllaining why
        if the refund request does not requires manual approval, 'requires_manual_approval' attribute
        will return False with 'reason' None
    """
    refund_process = RefundProcess()
    if refund_request.returned_order and refund_request.returned_order.amount_refund_incl_tax and refund_request.returned_order.origin_delivery_date:
        # threshold_amount_auto_approve should compare product cost only 
        if refund_request.returned_order.amount_refund_incl_tax // (1 + refund_request.returned_order.tax_applied_rate) > \
        threshold_amount_auto_approve:
            refund_process = RefundProcess(requires_manual_approval= True, 
                reason=f"The refund amount excluding tax has exceeded the auto-approval threshold: {threshold_amount_auto_approve}")
        if refund_request.request_date - refund_request.returned_order.origin_delivery_date > threshold_days_auto_approve:
            refund_process = RefundProcess(requires_manual_approval= True, 
                reason=f"The refund request date has exceeded the return window: {threshold_days_auto_approve}")
        return refund_process
    
    raise ValueError("The refund request does not have required information!!")

