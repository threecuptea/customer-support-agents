from __future__ import annotations

from fastapi import APIRouter, Request
import os
from models.model import ExchangeOrReturnOutput, GeneralSupportRequest, OrderInitRequest, OrderInitResponse, \
    GenericChatInput, SummarizeOnExit, OrderToReturn, ExchangeOrReturnInput, GenericResponse, InitialReturnRefundResponse, \
    ReturnRefundProcessRequest, ReturnRefundProcessResponse, ReturnRefundChatResponse
import logging
from services.customer_support_service import invoke_general_support_workflow, invoke_order_init_workflow, invoke_order_continue_workflow, \
    invoke_exchange_return_recommendation_workflow, invoke_return_refund_init_workflow,  invoke_return_refund_process_workflow, \
    invoke_return_refund_chat_workflow, invoke_summarize_on_exit 


MAX_MESSAGE_CHARS = 4_000

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/support", tags=['support'])
 

# include_in_schema=False to hide it from API docs. UI should be the only one can post the chat 
@router.post("/general")
async def general_support(support: GeneralSupportRequest, request: Request) -> GenericResponse:
    logger.info(f"Received general inquiry: {support.general_inquiry} from {support.customer_context.email}")
    return await invoke_general_support_workflow(support, request)


@router.post("/order/init")
async def order_support_init(support: OrderInitRequest, request: Request) -> OrderInitResponse:
    logger.info(f"Initialize order inquiry : {support.order_number_provided} from {support.customer_context.email}")
    return await invoke_order_init_workflow(support, request)

@router.post("/order/continue")
async def order_support_continue(support: GenericChatInput, request: Request) -> GenericResponse:
    logger.info(f"Continue order inquiry with : {support.user_conversation}")
    return await invoke_order_continue_workflow(support, request)

@router.post("/exchange_return/recommend")
async def exchange_return_recommend(exchange_return_reason: ExchangeOrReturnInput, request: Request) -> ExchangeOrReturnOutput :
    logger.info(f"Get exchange or return recommendation based upon the given reason for thread: {exchange_return_reason.thread_id}")
    return await invoke_exchange_return_recommendation_workflow(exchange_return_reason, request)

@router.post("/return_refund/init")
async def return_refund_init(order_to_return: OrderToReturn, request: Request) -> InitialReturnRefundResponse:
    logger.info(f"Initialize a return refund request for thread: {order_to_return.thread_id}")
    return await invoke_return_refund_init_workflow(order_to_return, request)

@router.post("/return_refund/process")
async def return_refund_process(request_to_process: ReturnRefundProcessRequest, request: Request) -> ReturnRefundProcessResponse:
    logger.info(f"Process a return refund request for thread: {request_to_process.thread_id}")
    return await invoke_return_refund_process_workflow(request_to_process, request)

@router.post("/return_refund/chat")
async def return_refund_chat(support: GenericChatInput, request: Request) -> ReturnRefundChatResponse:
    logger.info(f"Chat about a return refund request for thread: {support.thread_id}")
    return await invoke_return_refund_chat_workflow(support, request)

@router.post("/exit")
async def exit_signal(support: SummarizeOnExit, request: Request):
    logger.info(f"Exit request by thread_id : {support.thread_id}")
    await invoke_summarize_on_exit(support, request)
