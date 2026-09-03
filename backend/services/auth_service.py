
from __future__ import annotations

from models.model import AuthResponse
from dotenv import load_dotenv
import logging
import os
import re
from fastapi import HTTPException
from services.demo_data import demo_customers
from models.model import CustomerContext
from pydantic import ValidationError

load_dotenv(override=True)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

__csr_whitelist = os.getenv("CSR_WHITELIST")
__csr_domains = os.getenv("CSR_DOMAINS")
# os.makedirs("path/to/my_folder", exist_ok=True)

async def validate_populate_context(email_addr: str) -> AuthResponse:
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true" # we are using demo mode in dev environment
    # if CSR_WHITELIST exists, use its content because they are more restricted; otherwise use domain
    # In the production, we should use domain
    if __csr_whitelist:
        csr_members = re.split(r',\s*', __csr_whitelist)
        if email_addr in csr_members:
            return AuthResponse(email_addr = email_addr, is_auth = True, role = "csr")
    elif __csr_domains:
        csr_member_domains = re.split(r',\s*', __csr_domains)
        if any(email_addr.endswith(f'@{domain}') for domain in csr_member_domains):
            return AuthResponse(email_addr = email_addr, is_auth = True, role = "csr")
    else:
        raise HTTPException(status_code=500, detail="Missing CSR (Customer Support Representatives) configuration")
    if demo_mode:
        # TODO: Add a set up function to dynamically adjust date fields od demo_data so that it fit well with the order status: delivered but not
        # refundable without human approval (exceeding the return window),  delivered and auto-refundable; transit and pending statuses.
        # so that demo_data are always testable.
        return load_from_demo_data(email_addr)
    else:
        raise HTTPException(status_code=500, detail="Non-demo mode is not yet implemented.  Please use demo mode for now.")
    
def load_from_demo_data(email_addr: str) -> AuthResponse:
    d = demo_customers.get(email_addr)
    if d:
        try: 
            customer_context = CustomerContext.model_validate(d) # CustomerContext(**d), which go straight to init 
            
            # or model_validate or model_validate_json. The model_validate method takes a dictionary as input, 
            # while model_validate_json takes a JSON string as input. Need to retrieve conversation, do some research on summarize messages
            return AuthResponse(email_addr = email_addr, is_auth = True, role = "customer", 
                customer_context = customer_context)
        except ValidationError as ve:
            logger.error(ve) # Human-readable error 
            logger.error(ve.errors) # The debugging details 
            raise HTTPException(status_code=401, detail=f"Unable to retrieve a valid CustomerContext: {ve}")

    else:
        raise HTTPException(status_code=404, detail="Unable to locate the customer by the email address")



        




    

    

    

    
        

        


    
    

    