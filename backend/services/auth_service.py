
from __future__ import annotations

from models.model import AuthRequest, AuthResponse
from dotenv import load_dotenv
import logging
import os
import re
from fastapi import HTTPException
from demo_data import demo_customers
from models.model import CustomerContext

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


async def validate_populate_context(request: AuthRequest) -> AuthResponse:
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true" # we are using demo mode in dev environment
    csr_whitelist = os.getenv("CSR_WHITELIST")
    csr_domains = os.getenv("CSR_DOMAINS")
    # if CSR_WHITELIST exists, use its content because they are more restricted; otherwise use domain
    # In the production, we should use domain
    if csr_whitelist:
        csr_members = re.split(r',\s*', csr_whitelist)
        if request.email_addr in csr_members:
            return AuthResponse(email_addr = request.email_addr, is_auth = True, role = "csr")
    elif csr_domains:
        csr_member_domains = re.split(r',\s*', csr_domains)
        if any(request.email_addr.endswith(f'@{domain}') for domain in csr_member_domains):
            return AuthResponse(email_addr = request.email_addr, is_auth = True, role = "csr")
    else:
        raise HTTPException(status_code=500, detail="Missing CSR (Customer Support Representatives) configuration")
    if demo_mode:
        return load_from_demo_data(request.email_addr)
    else:
        raise HTTPException(status_code=500, detail="Non-demo mode is not yet implemented.  Please use demo mode for now.")
    
def load_from_demo_data(email_addr: str) -> AuthResponse:
    d = demo_customers.get(email_addr)
    if d:
        customer_context = CustomerContext.model_validate(d) # CustomerContext(**d) or model_validate or model_validate_json
        # The model_validate method takes a dictionary as input, while model_validate_json takes a JSON string as input.
        # need to retrieve conversation, do some research on summarize messages
        return AuthResponse(email_addr = email_addr, is_auth = True, role = "customer", 
                            customer_context = customer_context)
    else:
        raise HTTPException(status_code=404, detail="Unable to locate the customer by the email address")



        




    

    

    

    
        

        


    
    

    