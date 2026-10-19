from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Annotated, Literal


ALLOWED_ROLES = Literal["csr", "customer"]

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
    role: ALLOWED_ROLES