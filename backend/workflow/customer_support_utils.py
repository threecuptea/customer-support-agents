from __future__ import annotations

from langchain_core.tools import tool
from rapidfuzz import process, fuzz
from models.model import CustomerContext, Order, RefundRequest, ReturnRefundInitialDecision, FAQMatchResult, OrderToReturn, \
    ReturnedOrderItem, ReturnedOrder, OrderRefundStatus
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta

load_dotenv(override= True)

threshold_amount_auto_approve = float(os.getenv("AMOUNT_THRESHOLD_AUTO", "500"))
threshold_days_auto_approve = int(os.getenv("DAYS_THRESHOLD_AUTO", "35"))

NO_RETURN_ORDER = "No return order"
NO_ORIGINAL_ORDER_FOR_RETURN = "No original order for the return" 
ORIGINAL_ORDER_FOR_RETURN_IS_NOT_DELIVERED = "the original order for the return is not in 'delivered' status"
NOT_A_VALID_PRODUCT_ID = "not a valid product_id of its original order" 
NOT_A_VALID_RETURN_QUANTITY = "not a valid return quantity of its original order"


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
    "Exchange, Return and Refund": {
        "How do I choose between exchange and return?": "Exchange when your item has wrong size or fit or you want a different color or style or the product arrived broken "
        "or doesn't work and you want a fresh replacement. Return when the product didn't meet expectations or you change your mind entirely "
        "or the product you like to exchange with is out of stock", 
        "How do I start an exchange? ": "Go to e-shopping.com, look for Support -> Echange on the top of the screen then follow the instruction to initiate an exchange. "
        "We'll include the return shipping label in the confirmation email and ship the exchange once the original item is scanned by the carrier.",

        "What items cannot be returned?": "We cannot accept returns on final sale items, customized items, perishable items, gift cards, or items that have been altered or damaged by the customer. "
        "Certain high-risk items, such as luxury goods and intimate items, are marked as non-returnable unless they are defective or damaged upon receipt.",

        "What is your return policy in summary?": "We accept returns within 35 days of delivery for unused items.  The return item must have its tags attached "
        "and be returned in its original packaging with your receipt or proof of purchase",

        "Can I still get my refund if my order exceeds the return window of the policy": "No, we have already extended 5 more days.",
        "How do I start a return?": "You can talk to me to start a return/ refund request.",
        "When will I get my refund?": "Refunds usually take 3 to 5 business days after we get the item back.",

        "Are returns free?": "We are not charging any re-stocking fees. However, you will return at your own expense unless for defective, damaged or wrong items. "
        "We do cover the return shipping label if you exchange instead."
    },
    "Orders and Payment": {
        "What payment methods do you accept?": "We take credit/ debit cards, PayPal, Apple Pay, and Google Wallet.",
        "Would you price match if your competitor offer a better price?": "We will price match on selective items.", 
        "Can I cancel my order?": "You can cancel your order as long as the order is in pending status.  You cannot cancel an order once it has been shipped and in transit status.",
        "Is my payment secure?": "Yes. All data is encrypted via SSL.",
    }    
}

faq_dict = {}
faq_dict.update(FAQs['Shipping & Delivery'])
faq_dict.update(FAQs['Exchange, Return and Refund'])
faq_dict.update(FAQs['Orders and Payment'])
faq_qst_lst = list(faq_dict.keys())


RETURN_POLICY = f"""
Overview
At 'e-shopping.com, we want you to love what you ordered. If something's not quite right, we're here to help.

We have a 35 days return policy, starting from the day you receive your item, to request a return.  We extends 5 more days than most other vendors for the courtesy.

2. What can I return?
To be eligible for a return, you must provide your receipt or proof of purchase, and:

The item must be in the same condition in which you received it
The item must be unworn or unused
The item must still have its tags attached
The item must be in its original packaging
We reserve the right to decline return requests if patterns of abuse, such as frequent returns or use of items before returning, are detected.

3. What cannot be returned?
We cannot accept returns on final sale items, customized items, perishable items, gift cards, or items that have been altered or damaged by the customer.

Certain high-risk items, such as luxury goods and intimate items, are marked non-returnable unless they are defective or damaged upon receipt.

4. Are there any fees for returns?
We are not charging any re-stocking fees. However, you will return at your own expense unless an exchange is involved in that case we will cover return shipping labels. Damaged items will be covered in item 6.     

5. How do I start a return?
To initiate a return, you can contact our customer support web site. You'll need your the email address to login and start the process.

If your return is accepted, We will email you instructions on how and where to send your package.

6. Damages and issues
Please inspect your order upon receipt and contact us within five days if the item is defective, damaged or if you receive the wrong item, so we can evaluate and address the issue promptly.
A photo of proof might be required for such a request and the request could be denied if it comes too late.   
We will email you a return shipping label along with instructions on how and where to send your package once your request has been approved.

7. Exchanges
Need a different size, color or style? We offer free exchanges on eligible items within 35 days of delivery.

To request an exchange:

Go to e-shopping.com, look for Support -> Echange on the top of the screen and follow the instruction to initiate the exchange.

We'll ship the exchange once the original item is scanned by the carrier.

Please note:

Exchanges are subject to inventory availability
Certain items (i.e. final sale or custom products) may not be eligible for an exchange
If your requested item is out of stock, you can still return your ite for the refund.

8. Refunds
We will notify you once we've received and inspected your return to let you know if the refund was approved or not. If approved, you'll be automatically refunded on your original payment method within 3-5 business days. Refunds will only be issued to the original payment method used during the purchase. Please remember it can take some time for your bank or credit card company to process and post the refund too.

If more than 5 business days have passed since we've approved your return, please visit our customer-support site.

9. What will take to get the approval for a return refund request?
An AI agent will automatically approve such a request if the return amount before tax is within ${threshold_amount_auto_approve} and is requested within the return window of {threshold_days_auto_approve} days.
A customer-support representative is required to approve if the amount is more than ${threshold_amount_auto_approve}.
An AI agent will automatically reject a return order if the request pass the return window deadline or the returned item is nonrefundable.
However, the customer has one chance to request for approval from a customer-support representative.  The decision is subject to his/ her discretion.
"""




# Technically I don't need @tool decorator because it is not calling from LLM
# It treat it as StructuredTool

def find_closest_faq(user_question: str) -> FAQMatchResult:
    """Find the closest question and answer among FAQs using fuzzy partial_ratio
    Args:
        user_question: the user's question to match against
    Returns:
       a FAQMatchResult object
    """
    match = process.extractOne(user_question, faq_qst_lst, scorer=fuzz.partial_ratio)
    # print(f"Best match: {match[0]} with confidence {match[1]:.2f}")
    # if match and match[1] > 70.0:  # confidence threshold
    matched_question = match[0]
    faq = next((key, val) for key, val in faq_dict.items() if key == matched_question)
    # double to escape {}
    return FAQMatchResult(question= faq[0], answer= faq[1], confidence_score=round(match[1], 2))
    

def retrieve_target_order(context: CustomerContext, order_number: int) -> Order | None:
    """ retrieve the target order from the CustomerContext
        Args:
            context: CustomerContext
            order_number: used to locate the order from the CustomerContext
        Returns:
            an target Order
    """
    if context.latest_orders and order_number:
        for order in context.latest_orders:
            if order.order_id == order_number:
                return order
    return None


def _populateRefundRequest(order_to_return: OrderToReturn, original_order: Order) -> RefundRequest:
    """
    Populate a RefundRequest object from an OrderToReturn object based upon the original Order and OrderItem
    Args:
        order_to_return: a simplified order of returned item with product_id and qty
        original_order: the original Order and OrderItem as references
    Returns:
        a RefundRequest referencing a ReturnedOrder and list of ReturnedOrderItem
    Please notice that _check_if_order_to_return_in_valid_state in the customer_support_service.py 
    has already flagged/ excluded any abnormal cases.
    """
    # _check_if_order_to_return_in_valid_state has already excluded those abnormal cases:
    # target_order exists, product_id in returned_item exists in order item and quantity  
    product_id_dict = {item.product_id: item for item in original_order.items}
    items = []
    
    for r_item in order_to_return.items:
        item = product_id_dict[r_item.product_id]
        items.append(ReturnedOrderItem(
            product_id= item.product_id, 
            product_name= item.product_name, 
            supplier_name= item.supplier_name, 
            unit_price= item.unit_price, 
            number_units= r_item.qty, 
            nonrefundable_item= item.nonrefundable_item, 
            nonrefundable_reason = item.nonrefundable_reason
            ))
    returned_order = ReturnedOrder(
        origin_order_id= original_order.order_id, 
        original_delivery_date= original_order.delivery_date, 
        tax_applied_rate= original_order.tax_applied_rate, 
        items = items)
    return RefundRequest(
        request_date= datetime.now(tz= original_order.order_date.tzinfo), 
        returned_order= returned_order)
               
def _calculate_amount_refund_incl_tax(refund_request: RefundRequest) -> float:
    """Calculate total refund amount including tax base upon `ReturnedOrder` and `ReturnedOrderItem` associated 
        with the `RefundRequest` then applying `tax_applied_rate` added to total refund amount
        Args:
            refund_request: RefundRequest
        Returns:
            float: representing total amount refund including tax if there is `RefundRequest` and 
            `ReturnedOrder` and `ReturnedOrderItem` associated with it
    """
    total_before_tax = 0.0
    for item in refund_request.returned_order.items:
        total_before_tax += item.unit_price * item.number_units

    return round(total_before_tax * (1 + refund_request.returned_order.tax_applied_rate), 2)


def _get_initial_return_refund_decision(refund_request: RefundRequest) -> ReturnRefundInitialDecision:
    """ Return initial return refund decision
    It compares two thresholds: 
    `threshold_amount_auto_approve`, and `threshold_days_auto_approve`
    - OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_DUE_TO_AMOUNT: if purchase amount (w/o tax) > `threshold_amount_auto_approve`
    - OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS: if the refund request date >`threshold_days_auto_approve`
    - OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS: if the return items are non_refunable item
    - OrderRefundStatus.ORDER_AUTO_REFUNDABLE: for everything else

    Args:
        refund_request: a valid RefundRequest
    Returns:
        A ReturnRefundDecision object with order_refund_status: OrderRefundStatus 
        if the refund request requires manual approval, 'requires_manual_approval' attribute
        will return True with 'reason' expllaining why
        Specify the reason for `auto_reject`
        No need to specify the reason for `auto_approve`
    """
    returned_order = refund_request.returned_order 
    if returned_order.estimated_amount_refund_incl_tax / (1 + returned_order.tax_applied_rate) > \
        threshold_amount_auto_approve:
        return ReturnRefundInitialDecision(order_refund_status= OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_DUE_TO_AMOUNT) 
            # reason=f"The refund amount excluding tax has exceeded the auto-approval amount threshold: {threshold_amount_auto_approve}")
    if refund_request.request_date - returned_order.original_delivery_date > timedelta(days=threshold_days_auto_approve):
        return ReturnRefundInitialDecision(order_refund_status= OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS)
            # reason=f"The refund request date has exceeded the return window: {threshold_days_auto_approve} days")
    # Do a simple handling for now. Not to take multiple order item into consideration
    if any([item.nonrefundable_item for item in returned_order.items]):
        return ReturnRefundInitialDecision(order_refund_status= OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS)

    return ReturnRefundInitialDecision(order_refund_status= OrderRefundStatus.ORDER_AUTO_REFUNDABLE)
            
def check_if_order_to_return_in_valid_state(return_order: OrderToReturn, original_order: Order) -> bool:
    """ Check if we can put together a valid `RefundRequest` to process 
        Check if there is a valid `original_order` of `delivered` status
        Check if there is a valid `return_order` with items of valid product_id and quanity   
    Args:
        return_order: OrderToReturn with items of product_id and quantity to return
        original_order: the referenced original Order
    Returns:
        True if pass all validation else a ValueError w/ a reason will be raised
    """
    if not return_order:
        raise ValueError(NO_RETURN_ORDER)
    if not original_order:
        raise ValueError(NO_ORIGINAL_ORDER_FOR_RETURN)
    if not original_order.delivery_date:
        raise ValueError(ORIGINAL_ORDER_FOR_RETURN_IS_NOT_DELIVERED)
        
    product_dict = {item.product_id: item.number_units for item in original_order.items}
    for item_return in return_order.items:
        if item_return.product_id not in product_dict:
            raise ValueError(f"{item_return.product_id} is {NOT_A_VALID_PRODUCT_ID}: {original_order.order_id}")
        if item_return.qty > product_dict[item_return.product_id]:
            raise ValueError(f"The return {item_return.qty} units of {item_return.product_id} is {NOT_A_VALID_RETURN_QUANTITY}: {original_order.order_id}.")
    return True    

def get_initial_return_refund_decision(return_order: OrderToReturn, original_order: Order) -> tuple[RefundRequest, ReturnRefundInitialDecision]:
    """ Get ReturnRefundDecision with OrderRefundStatus signals how we should handle return refund
        It goes through the following steps:
            check_if_order_to_return_in_valid_state:  to pre-check and flag/ exclude all abnormal cases
            _populateRefundRequest: put together a RefundRequest object from a return_order and original_order
            _calculate_amount_refund_incl_tax: calculate amount to refund, including tax
            _get_initial_return_refund_decision: get initial return refund decision based upon all factors
    Args:
        return_order: OrderToReturn with items of product_id and quantity to return
        original_order: the referenced original Order
    Returns:
        RefundRequest so that the customer will know total amount will be refunded.
        ReturnRefundDecision with OrderRefundStatus
    """
    try:
        check_if_order_to_return_in_valid_state(return_order, original_order)
    except ValueError as verr:
        # It should not come here. The service layer has validate before invoke the graph
        return (None, ReturnRefundInitialDecision(order_refund_status= OrderRefundStatus.ORDER_INVALID_REFUNDABLE_STATE))
    refund_request: RefundRequest = _populateRefundRequest(return_order, original_order)
    refund_request.returned_order.estimated_amount_refund_incl_tax = _calculate_amount_refund_incl_tax(refund_request)
    
    initial_decision: ReturnRefundInitialDecision = _get_initial_return_refund_decision(refund_request)
    return (refund_request, initial_decision)