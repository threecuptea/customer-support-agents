from __future__ import annotations

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal, Optional

MAX_MESSAGE_CHARS = 4_000
MAX_MESSAGES = 100


#############################################
#
# The followings are database schema FYI. They can be enhanced as thing go
#
#############################################

class CustomerNF(BaseModel):
    customer_id: int
    first_name: str
    last_name: str
    email: str # There should be a secondary key
    state_abbrv: str

class ProductNF(BaseModel):
    product_id: str
    product_name: str
    supplier_name: str
    unit_price: float

class OrderItemNF(BaseModel):
    order_id: int
    product_id: int
    number_units: int

class OrderNF(BaseModel):
    order_id: int
    customer_id: int
    order_date: datetime
    total_amount_incl_tax: float
    tax_applied_rate: float
    status: Literal["delivered", "transit", "pending", "returned"]
    ship_date: datetime | None
    tracking_number: str | None


#############################################
#
# The followings are business objects or DAO
#
#############################################

class OrderItem(BaseModel):
    product_id: str
    product_name: str
    supplier_name: str
    unit_price: float
    number_units: int

class Order(BaseModel):
    order_id: int
    order_date: datetime
    total_amount_incl_tax: float
    tax_applied_rate: float
    status: Literal["delivered", "transit", "pending", "returned", "partial_returned"]
    notes: str | None
    ship_date: datetime | None
    estimated_delivery_date: datetime | None
    tracking_number: str | None
    items: list[OrderItem]

class ReturnedOrderItem(BaseModel):
    product_id: int
    product_name: str
    supplier_name: str
    unit_price: float
    number_units: int

class ReturnedOrder(BaseModel):
    order_id: int
    order_date: datetime
    status: Literal["returned", "partial_returned"]
    total_amount_refund_incl_tax: float
    items: list[ReturnedOrderItem]

class RefundRequest(BaseModel):
    refund_request_id: int | None
    request_date: datetime
    status: Literal["pending", "auto_approve", "auto_reject", "manaul_approve", "manaul_reject", "manual_flag"] | None
    total_amount_refund_incl_tax: float
    returned: ReturnedOrder
    

# This comes from long-term memory value dictionary     
class Conversation(BaseModel):
    thread_id: str
    chat_date: datetime
    summary: str

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=MAX_MESSAGE_CHARS)

class CustomerContext(BaseModel):
    customer_id: int
    first_name: str
    last_name: str
    email: str
    # How many orders: 3 do I need and how many conversation: 5, hard code for now, configurable later 
    latest_orders: list[Order] | None
    latest_conversations: list[Conversation] | None
    

class ChatConversation(BaseModel):
    messages: list[ChatMessage] = Field(..., max_length=MAX_MESSAGES, min_length=0)
    context: CustomerContext
    intent_for_return_refund: bool = False
    refund_request: Optional[RefundRequest] = None
    ready_to_process_refund_request: bool = False

#########################################
# The followings are used in authentication/ authorization
#########################################
class AuthRequest(BaseModel):
    email_addr: str

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
    customer_context: Optional[CustomerContext] = None # CustomerContext exists if the role is customer
    


        

    

