from __future__ import annotations

from fastapi import APIRouter
import logging
import os
from models.model import AuthRequest, AuthResponse

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=['auth'])


@router.post("", response_model=AuthResponse)
async def auth(request: AuthRequest) -> AuthResponse:
    return request # placeholder for now.