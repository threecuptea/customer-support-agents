from __future__ import annotations

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal, Annotated
from langgraph.graph import MessagesState
from enum import StrEnum, auto

MAX_MESSAGE_CHARS = 4_000
MAX_MESSAGES = 100

MAX_REASON_CHARS = 500


# Eventually, we should have an escalation slack chanel. This message is for CSR (human customer-support representative) to 
# inform why we escalate this ticket.  However, escalation reason alone is not good enough, need customer, order, return refund
# all the information
class ESCALATE_REASON(StrEnum):
    HELP_LOST_SHIPMENT = "Help handle a lost shipment"
    HELP_CANCEL_ORDER = "Help cancel an order"
    HELP_ANSWER_ORDER_INQUIRY = "Help answer an order inquiry that an AI Agent cannot handle"
    HELP_EXPEDITE_EXCHANGE_FOR_DEFECTIVE_WRONG_ITEM = "Help expedite the exchange of defective, broken or wrong item(s)"
    HELP_CHECK_RETURN_REFUND_STATUS = "Help check the return refund status of an order"
    HELP_DECIDE_IF_PRICE_MATCH_WITH_COMPETITOR = "Decide if we should offer a refund so we can price match to beat our competitor(s)"
    

# ORDER_NON_REFUNDABLE_DAYS means an order is non-refundable because the refund request has exceeded the return window.
# ORDER_HUMAN_REFUNDABLE_ITEMS means an order is non-refundable because the return item(s) are intimate items that CSR need to 
# make sure that it is unworn, unwashed, tag is on
# ORDER_DELIVERED_BORDERLINE are order supposed to be delivered according to the carrier but the customer does not see
# the delivered items.  That's what a lot of order inquiry dispute come from and cases will be escalated. 
class OrderRefundStatus(StrEnum):
    ORDER_AUTO_REFUNDABLE = "The return/ refund request has been approved by an automatic agent."
    ORDER_NON_REFUNDABLE_DUE_TO_DAYS = "The return/ refund request has been rejected by an automatic agent because it has passed the return window deadline"
    ORDER_NON_REFUNDABLE_DUE_TO_ITEMS = "The return/ refund request has been rejected by an automatic agent because it includes a non-refundable item"
    ORDER_HUMAN_REFUNDABLE_DUE_TO_AMOUNT = "The return/ refund request requires a customer-support representative's manual approval because it exceeds the automatic authorized refund amount"
    ORDER_INVALID_REFUNDABLE_STATE = "The return/ refund request is in a invalid state to proceed."

    # The above are related to return_refund_eligible
    ORDER_IN_TRANSIT = auto()
    ORDER_IN_PENDING = auto()
    ORDER_DATA_INVALID = auto() # for test reason
    ORDER_DELIVERED_BORDERLINE = auto()



class ExchangeReturnReason(StrEnum):
    WRONG_SIZE_OR_FIT = "Size is too small or too large, different from size chart or just does not fit well"
    NOT_MATCH_DESCRIPTION_OR_PHOTO = "Discrepancies in color, material quality, or features create a gap between customer expectations and reality"
    DAMAGED_DEFECTIVE_OR_MISSING_PARTS = "Items arriving broken, defective or missing parts and make it non-funcional and a return or replacement mandatory"
    CHANGED_MIND_OR_IMPULSE_BUY = "Buyer's remorse to buy it or just don't want it any more"
    LATE_DELIVERY_NO_LONGER_NEEDED = "Products arriving past the needed date of a holiday/ event/ project or the event got canceled and no longer needed any more"
    WRONG_ITEM_SHIPPED = "Possibly pick-and-pack or labeling mistakes in the warehouse"
    BETTER_PRICE_FOUND = "Find a better price in a competitor's site" # possibly price matching
    DIFFICULT_TO_ASSEMBLY = "The item is overly complex or the instructions are incomprehensive"
    DIFFERENT_COLOR_OR_STYLE = "Want a different color or style"
    OTHERS = "None of the above"

    # Other reasons like duplicate gift, gift not liked, accidental dulicate ordeer, incompatible hardware software, difficult assembly to use

class ExchangeReturnRefundAction(StrEnum):
    EXCHANGE = "exchange"
    RETURN = "return"
    PARTIAL_REFUND = "partial_refund"
    EXPEDITE_EXCHANGE = "expedite_exchange"

       
#############################################
#
# The followings are business objects or DAO
#
#############################################

# A common trap in Pydantic V2 is assuming Optional[str] or str | None makes a field omittable by itself. 
# Type hinting alone does not change a field's requirement status and a default value is still required.
# name: str | None = None: Input Value Can Be None? Yes, Field Can Be Omitted entirely? Yes
# name: str | None:        Input Value Can Be None? Yes, Field Can Be Omitted entirely? No
# name: str = None:        Input Value Can Be None? Yes (Coerced), Field Can Be Omitted entirely? Yes (Triggers static typing warnings)

class OrderItem(BaseModel):
    product_id: Annotated[str, Field(min_length=1)]
    product_name: Annotated[str, Field(min_length=1)]
    supplier_name: Annotated[str, Field(min_length=1)]
    unit_price: Annotated[float, Field(gt=0)]
    number_units: Annotated[int, Field(gt=0)]
    nonrefundable_item: bool = False
    nonrefundable_reason:  Literal["intimate item", "luxury goods"] | None = None

# All date fields be TZ-aware 
class Order(BaseModel):
    order_id: Annotated[int, Field(gt=0)]
    order_date: datetime
    total_amount_incl_tax: Annotated[float, Field(gt=0)]
    tax_applied_rate: Annotated[float, Field(ge=0)]
    status: Literal["delivered", "transit", "pending"] = "pending"
    notes: str | None = None
    ship_date: datetime | None = None
    estimated_delivery_date: datetime | None = None
    tracking_number: str | None = None
    delivery_date: datetime | None = None
    items: Annotated[list[OrderItem], Field(min_length=1)]

class ReturnedOrderItem(OrderItem):
    refurbished_amount: float = 0.0

class ReturnedOrder(BaseModel):
    origin_order_id: Annotated[int, Field(gt=0)]
    original_delivery_date: datetime
    returned_date: datetime | None = None
    status: Literal["returned", "pending"] = 'pending'
    tax_applied_rate: Annotated[float, Field(ge=0)]
    estimated_amount_refund_incl_tax: float = 0
    refurbished_amount_incl_tax: float = 0
    items: Annotated[list[ReturnedOrderItem], Field(min_length=1)]
    processed_date: datetime | None = None

class RefundRequest(BaseModel):
    refund_request_id: Annotated[int, Field(ge=0)] = 0
    request_date: datetime
    status: Literal["pending", "auto_approve", "auto_reject", "wait_for_manual_review", "manual_approve", "manual_reject", "manual_flag"] = 'pending'
    requires_manual_approval: bool = False
    requires_manual_approval_reason: str | None = None
    notes_for_human_review_override: str | None = None 
    decided_by: Annotated[str, Field(min_length=1)] | None = None
    decision_reason: Annotated[str, Field(min_length=1, max_length=MAX_REASON_CHARS)] | None = None
    decided_date: datetime | None = None
    returned_order: ReturnedOrder

class FAQMatchEvals(BaseModel):
    rapid_fuzz_partial_ratio_match_helpful: bool = False
    llm_semantic_match_helpful: bool = False

class FAQMatchResult(BaseModel):
    question: str
    answer: str
    confidence_score: Annotated[float, Field(ge=0.0, le=100.0)]

class OrderRevisitEval(BaseModel):
    is_revisit: bool = False


# It's TypedDict not BaseModel.  Which is correct decision for accumulated state. I don't need to guard
# # the value.  However, it's TypedDict.  However, I cannot use attribute and have to use key to get the value. 
class CustomerSupportState(MessagesState):
    """
    CustomerSupportState stores the customer-support conversation and state.
    `messages` are collections of LangGraph's BaseMessage like HumanMessage, AIMessage and ToolMessage
    `response` is used to store LLM's reply text to communicate with UI.
    We will summarize `messages` so to prevent its size from growing. 
    """
    response: str = ""
    summary: str
    customer_name: str
    customer_context: CustomerContext
    support_category: Literal["order_inquery", "exchange_or_return", "return_refund", "general/ others"] = 'general/ others'
    general_inquiry: str
    faq_match_evals: FAQMatchEvals | None
    escalation_reason: str = None # This is for the future use: escalating and summarizing the reason to slack's CSR channel
    general_issue_resolved: bool = False
    order_number_provided:  int
    target_order: Order = None
    order_is_revisit: bool = False # set by detect_order_revisit_node; routes order_init straight into order_continue_chat_node
    order_issue_escalated: bool = False
    order_issue_resolved: bool = False
    exchange_return_reason: ExchangeOrReturnInput
    special_exchange_handling: bool = False
    order_to_return: OrderToReturn
    initial_return_refund_decision: ReturnRefundInitialDecision
    refund_request_to_process: RefundRequest = None
    proceed_to_process_return_refund: bool = False
    assigned_refund_request_id: int = 0
    desire_to_chat_return_refund: bool = False
    request_human_review_return_refund: bool = False
    notes_for_human_review_override: str = None
    summarize_on_exit: bool = False

# Unfortunately we have to know what items to be return to devide
class ReturnRefundInitialDecision(BaseModel):
    order_refund_status: Literal[OrderRefundStatus.ORDER_AUTO_REFUNDABLE, 
                                 OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS,
                                 OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS,
                                 OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_DUE_TO_AMOUNT,
                                 OrderRefundStatus.ORDER_INVALID_REFUNDABLE_STATE]
    
 # latest_orders should be by date instead of by count. For example, order_date within the last 45 days.
 # UI should be able to display the summary of recent orders in descending order so that the customer can choose
 # which order is what he/ she is concerned about.   
class CustomerContext(BaseModel):
    customer_id: Annotated[int, Field(gt=0)]
    title: Literal["Mr.", "Ms.", "Mrs.", "Dr.", "Mx."] = "Mx."
    first_name: Annotated[str, Field(min_length=1)]
    last_name: Annotated[str, Field(min_length=1)]
    email: Annotated[str, Field(min_length=1)]
    latest_orders: list[Order] = []
    

#########################################
# The followings are used in auth API
#########################################
class AuthRequest(BaseModel):
    email_addr: Annotated[str, Field(min_length=1)]

# User login using his/ her account email addresss, For non demo-mode, we retrieved the customer info using email address.
# We retrieve customer orders using customer_id and retrieve order items by order_id, then
# retrieve product info using product_id.  However, in demo-mode, we can short-cut to use business objects themselves
# The `role` is used for multi-tenant management.  Customers (role: 'customer) will go to customer-support AI Agent chat screen
# We will provide CustomerContext so that AI will know what are previous conversation between the customer and AI assistant and 
# and what are customer latest orders
class AuthResponse(BaseModel):
    email_addr: str
    is_auth: bool = False
    role: Literal["csr", "customer"] # customer-support-representative, or customer
    customer_context: CustomerContext | None = None # CustomerContext exists if the role is customer

    
#########################################
# The followings are used in customer_support API
#########################################

class GenericResponse(BaseModel):
    thread_id: str
    response: str

class GeneralSupportRequest(BaseModel):
    thread_id: str | None = None
    customer_context: CustomerContext
    general_inquiry: str

class OrderInitRequest(BaseModel):
    thread_id: str | None = None
    customer_context: CustomerContext
    order_number_provided: int

class OrderStructuredOutput(BaseModel):
    response: str
    escalate: bool = False
    escalation_reason: ESCALATE_REASON | None = None
    order_issue_resolved: bool = False

class OrderInitResponse(GenericResponse):
    target_order: Order | None = None

class GenericChatInput(BaseModel):
    thread_id: Annotated[str, Field(min_length=1)]
    user_conversation: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_CHARS)]

class SummarizeOnExit(BaseModel):
    thread_id: str 

class ItemToReturn(BaseModel):
    product_id: Annotated[str, Field(min_length=1)]
    qty: Annotated[int, Field(gt=0)]

class OrderToReturn(BaseModel):
    thread_id: Annotated[str, Field(min_length=1)]
    items: Annotated[list[ItemToReturn], Field(min_length=1)]

class ExchangeOrReturnInput(BaseModel):
    thread_id: Annotated[str, Field(min_length=1)]
    reason_option: ExchangeReturnReason
    reason_input: str | None = None

class ExchangeOrReturnOutput(GenericResponse):
    special_exchange_handling: bool = False


class InitialReturnRefundResponse(GenericResponse):
    initial_return_refund_decision: ReturnRefundInitialDecision
    refund_request_to_process: RefundRequest | None = None

class ReturnRefundStructuredOutput(BaseModel):
    response: str
    request_human_review_return_refund: bool = False
    
class ReturnRefundProcessRequest(BaseModel):
    thread_id: Annotated[str, Field(min_length=1)]
    notes_for_human_review_override: str | None = None

class ReturnRefundProcessResponse(GenericResponse):
    refund_request_to_process: RefundRequest
    assigned_refund_request_id: Annotated[int, Field(gt=0)]

class ReturnRefundChatResponse(GenericResponse):
    request_human_review_return_refund: bool = False
    