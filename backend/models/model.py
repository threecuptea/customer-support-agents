from __future__ import annotations

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal, Annotated

MAX_MESSAGE_CHARS = 4_000
MAX_MESSAGES = 100


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

class Order(BaseModel):
    order_id: Annotated[int, Field(gt=0)]
    order_date: datetime
    total_amount_incl_tax: Annotated[float, Field(gt=0)]
    tax_applied_rate: Annotated[float, Field(gt=0)]
    status: Literal["delivered", "transit", "pending"] = "pending"
    notes: str | None = None
    ship_date: datetime | None = None
    estimated_delivery_date: datetime | None = None
    tracking_number: str | None = None
    items: list[OrderItem]

class ReturnedOrderItem(OrderItem):
    refurbishable: bool = False

class ReturnedOrder(BaseModel):
    origin_order_id: Annotated[int, Field(gt=0)]
    returned_date: datetime | None = None
    status: Literal["returned", "partial_returned", "pending"]
    actual_amount_refund_incl_tax: Annotated[float, Field(gt=0)]
    items: list[ReturnedOrderItem]
    processed: bool = False

class RefundRequest(BaseModel):
    refund_request_id: Annotated[int, Field(gt=0)]
    request_date: datetime
    status: Literal["pending", "auto_approve", "auto_reject", "manaul_approve", "manaul_reject", "manual_flag"] = 'pending'
    expected_amount_refund_incl_tax: Annotated[float, Field(gt=0)]
    reference: ReturnedOrder
    

# This comes from long-term memory value dictionary     
class Conversation(BaseModel):
    thread_id: Annotated[str, Field(min_length=1)]
    chat_date: datetime
    summary: Annotated[str, Field(min_length=1)]

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_CHARS)]

class CustomerContext(BaseModel):
    customer_id: Annotated[int, Field(gt=0)]
    first_name: Annotated[str, Field(min_length=1)]
    last_name: Annotated[str, Field(min_length=1)]
    email: Annotated[str, Field(min_length=1)]
    # How many orders: 3 do I need and how many conversation: 5, hard code for now, configurable later 
    latest_orders: list[Order] | None = None
    latest_conversations: list[Conversation] | None = None
    

class ChatConversation(BaseModel):
    messages: Annotated[list[ChatMessage], Field(max_length=MAX_MESSAGES, min_length=0)] 
    context: CustomerContext
    intent_for_return_refund: bool = False


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
    


        

    

