from __future__ import annotations

from fastapi import APIRouter
import logging
import os
from models.model import ChatConversation

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=['chat'])

@router.post("", response_model=ChatConversation)
async def chat(request: ChatConversation) -> ChatConversation:
    return request # placeholder for now.

