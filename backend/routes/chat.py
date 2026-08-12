from __future__ import annotations

from fastapi import APIRouter
import logging
import os
from models.model import ChatConversation

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=['chat'])

# include_in_schema=False to hide it from API docs. UI should bbe the only one can post the chat 
@router.post("", response_model=ChatConversation, include_in_schema=False)
async def chat(request: ChatConversation) -> ChatConversation:
    return request # placeholder for now.

