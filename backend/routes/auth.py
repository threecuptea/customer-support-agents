from __future__ import annotations

from fastapi import APIRouter
from dotenv import load_dotenv
from contextlib import asynccontextmanager
import logging
import os
from models.model import AuthRequest, AuthResponse
from collections.abc import AsyncGenerator
from services.auth_service import validate_populate_context
from services.demo_data import adjust_days_demo_data_testable


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=['auth'])
load_dotenv(override= True)

@asynccontextmanager
async def auth_lifespan(router: APIRouter) -> AsyncGenerator[None, None]:
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    if demo_mode:
        adjust_days_demo_data_testable()
        yield
    else:
        yield    

router = APIRouter(prefix="/api/auth", tags=['auth'], lifespan= auth_lifespan)

@router.post("", response_model=AuthResponse)
async def auth(request: AuthRequest) -> AuthResponse:
    logger.info(f"Authenticate/ authorize {request.email_addr.strip()}")
    return await validate_populate_context(request.email_addr.strip())