from __future__ import annotations

from fastapi import APIRouter, Request
import os
from models.model import GeneralSupportRequest, GeneralSupportResponse
import logging
from services.customer_support_service import invoke_general_support_workflow


MAX_MESSAGE_CHARS = 4_000

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/support", tags=['support'])
 

# include_in_schema=False to hide it from API docs. UI should be the only one can post the chat 
@router.post("/general")
async def general_support(support: GeneralSupportRequest, request: Request) -> GeneralSupportResponse:
    logger.info(f"Received general inquiry: {support.general_inquiry} from {support.customer_context.email}")
    return await invoke_general_support_workflow(support, request)
  
