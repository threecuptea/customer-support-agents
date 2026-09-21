from __future__ import annotations

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal, Annotated
from langgraph.graph import MessagesState
from zoneinfo import ZoneInfo
from enum import StrEnum, auto

MAX_MESSAGE_CHARS = 4_000
MAX_MESSAGES = 100

MAX_REASON_CHARS = 50

# "Help handle a lost shipment", "Help cancel an order", "Help answer an order inquiry that an AI Agent cannot handle"

class ESCALATE_REASON(StrEnum):
    HELP_LOST_SHIPMENT = "Help handle a lost shipment"
    HELP_CANCEL_ORDER = "Help cancel an order"
    HELP_ANSWER_ORDER_INQUIRY = "Help answer an order inquiry that an AI Agent cannot handle"


# ORDER_NON_REFUNDABLE_DAYS means an order is non-refundable because the refund request has exceeded the return window.
# ORDER_HUMAN_REFUNDABLE_ITEMS means an order is non-refundable because the return item(s) are intimate items that CSR need to 
# make sure that it is unworn, unwashed, tag is on
# ORDER_DELIVERED_BORDERLINE are order supposed to be delivered according to the carrier but the customer does not see
# the delivered items.  That's what a lot of order inquiry dispute come from and cases will be escalated. 
class OrderRefundStatus(StrEnum):
    ORDER_AUTO_REFUNDABLE = auto()
    ORDER_NON_REFUNDABLE_DAYS = auto()
    ORDER_HUMAN_REFUNDABLE_ITEMS = auto()
    ORDER_HUMAN_REFUNDABLE_AMOUNT = auto()
    # The above are related to return_refund_eligible
    ORDER_IN_TRANSIT = auto()
    ORDER_IN_PENDING = auto()
    ORDER_DATA_INVALID = auto() # for test reason
    ORDER_DELIVERED_BORDERLINE = auto()


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
    intimate_item: bool = False

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
    refurbishable: bool = False

class ReturnedOrder(BaseModel):
    origin_order_id: Annotated[int, Field(gt=0)]
    origin_delivery_date: datetime
    returned_date: datetime | None = None
    status: Literal["returned", "partial_returned", "pending"] = 'pending'
    tax_applied_rate: Annotated[float, Field(ge=0)]
    amount_refund_incl_tax: Annotated[float, Field(ge=0)] 
    items: Annotated[list[ReturnedOrderItem], Field(min_length=1)]
    processed: bool = False

class RefundRequest(BaseModel):
    refund_request_id: Annotated[int, Field(gt=0)]
    request_date: datetime
    status: Literal["pending", "auto_approve", "auto_reject", "manaul_approve", "manaul_reject", "manual_flag"] = 'pending'
    expected_amount_refund_incl_tax: Annotated[float, Field(gt=0)] # copied from the ReturnedOrder initially
    requires_manual_approval: bool = False
    manual_approval_reason: str | None = None 
    decided_by: Annotated[str, Field(min_length=1)] | None = None
    decision_reason: Annotated[str, Field(min_length=1, max_length=MAX_REASON_CHARS)] | None = None
    decided_date: datetime | None = None
    returned_order: ReturnedOrder | None = None

class FAQMatchEvals(BaseModel):
    rapid_fuzz_partial_ratio_match_helpful: bool = False
    llm_semantic_match_helpful: bool = False

class FAQMatchResult(BaseModel):
    question: str
    answer: str
    confidence_score: Annotated[float, Field(ge=0.0, le=100.0)]


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
    support_category: Literal["order_inquery", "return_refund", "general/ others"] = 'general/ others'
    general_inquiry: str
    faq_match_evals: FAQMatchEvals | None
    escalation_reason: str = None # This is for the future use: escalating and summarizing the reason to slack's CSR channel
    general_issue_resolved: bool = False
    order_number_provided:  int
    target_order: Order = None
    order_issue_escalated: bool = False
    order_issue_resolved: bool = False
    intent_for_return_refund: bool
    order_refund_eligible: OrderRefundStatus
    refund_request: RefundRequest
    summarize_on_exit: bool = False

# Unfortunately we have to know what items to be return to devide
class RefundProcess(BaseModel):

    requires_manual_approval: bool = False
    reason: str | None = None

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
# The followings are used in authentication/ authorization
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
# The followings are used in authentication/ authorization
#########################################

class GeneralSupportRequest(BaseModel):
    thread_id: str | None = None
    customer_context: CustomerContext
    general_inquiry: str

class GeneralSupportResponse(BaseModel):
    thread_id: Annotated[str, Field(min_length=1)]
    general_inquiry: str
    response: str

class OrderInitRequest(BaseModel):
    thread_id: str | None = None
    customer_context: CustomerContext
    order_number_provided: int

class OrderStructuredOutput(BaseModel):
    response: str | None = None
    escalate: bool = False
    escalation_reason: Literal[ESCALATE_REASON.HELP_LOST_SHIPMENT, ESCALATE_REASON.HELP_CANCEL_ORDER, ESCALATE_REASON.HELP_ANSWER_ORDER_INQUIRY] | None = None
    intent_for_return_refund: bool = False
    order_issue_resolved: bool = False

class OrderInitResponse(BaseModel):
    thread_id: str
    target_order: Order
    response: str

class OrderContinueRequest(BaseModel):
    thread_id: Annotated[str, Field(min_length=1)]
    user_conversation: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_CHARS)]

class OrderContinueResponse(BaseModel):
    thread_id: str
    response: str
    escalation_reason: str | None = None
    intent_for_return_refund: bool = False

class SummarizeOnExit(BaseModel):
    thread_id: str    


   
        

    

