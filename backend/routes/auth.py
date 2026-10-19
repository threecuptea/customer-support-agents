from __future__ import annotations

from fastapi import APIRouter, Request
from dotenv import load_dotenv
from contextlib import asynccontextmanager
import logging
import os
from models.auth_model import AuthRequest, AuthResponse
from models.customer_support_model import CustomerContext
from collections.abc import AsyncGenerator
from services.auth_service import validate_populate_context
from services.demo_data import adjust_days_demo_data_testable


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

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


@router.post("")
async def auth(auth_request: AuthRequest, request: Request) -> tuple[AuthResponse, CustomerContext | None]:
    auth_request.email_addr = auth_request.email_addr.strip()
    logger.info(f"Authenticate/ authorize {auth_request.email_addr}")
    response, customer_context = await validate_populate_context(auth_request.email_addr)
    if response.is_auth:
        request.session["role"] = response.role
    else:
        # A failed login must never leave (or keep) a role: AuthResponse.role defaults to
        # "customer" even when is_auth is False, which would otherwise pass RoleChecker.
        request.session.clear()
    return response, customer_context


@router.post("/logout")
async def logout(request: Request) -> dict[str, bool]:
    """Drop the server-side session (the UI's Exit button), so the cookie no longer carries a role."""
    request.session.clear()
    return {"logged_out": True}