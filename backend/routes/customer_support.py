from __future__ import annotations

from fastapi import APIRouter, Request
import os
from models.model import GeneralSupportRequest, GeneralSupportResponse, OrderInitRequest, OrderInitResponse, \
    OrderContinueRequest, OrderContinueResponse, SummarizeOnExit
import logging
from services.customer_support_service import invoke_general_support_workflow, invoke_order_init_workflow, invoke_order_continue_workflow, \
    invoke_summarize_on_exit


MAX_MESSAGE_CHARS = 4_000

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/support", tags=['support'])
 

# include_in_schema=False to hide it from API docs. UI should be the only one can post the chat 
@router.post("/general")
async def general_support(support: GeneralSupportRequest, request: Request) -> GeneralSupportResponse:
    logger.info(f"Received general inquiry: {support.general_inquiry} from {support.customer_context.email}")
    return await invoke_general_support_workflow(support, request)


@router.post("/order/init")
async def order_support_init(support: OrderInitRequest, request: Request) -> OrderInitResponse:
    logger.info(f"Initialize order inquiry : {support.order_number_provided} from {support.customer_context.email}")
    return await invoke_order_init_workflow(support, request)

@router.post("/order/continue")
async def order_support_continue(support: OrderContinueRequest, request: Request) -> OrderContinueResponse:
    logger.info(f"Continue order inquiry with : {support.user_conversation}")
    return await invoke_order_continue_workflow(support, request)

@router.post("/exit")
async def exit_signal(support: SummarizeOnExit, request: Request) -> OrderContinueResponse:
    logger.info(f"Exit request by thread_id : {support.thread_id}")
    return await invoke_summarize_on_exit(support, request)




  
