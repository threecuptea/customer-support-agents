from __future__ import annotations

from fastapi import Request, APIRouter, Depends
import logging
import os

from models.approval_model import ApprovalStart, ApprovalDecision
from services.approval_service import invoke_approval_workflow, resume_approval_workflow
from routes.role_checker import RoleChecker


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approval", tags=["approval"])


restrict_to_csr = RoleChecker("csr")


@router.post("/start")
async def approval_start(data: ApprovalStart, request: Request = Depends(restrict_to_csr)):
    """Draft content for a task and pause for human review."""
    logger.info(f"Received a letter draft request for task: {data.task}")
    return await invoke_approval_workflow(data, request)
    

@router.post("/decide")
async def approval_decide(data: ApprovalDecision, request: Request = Depends(restrict_to_csr)):
    """Resume the approval workflow with approve / edit / reject."""
    logger.info(f"Received a review decision: {data.action} for thread: {data.thread_id}")
    return await resume_approval_workflow(data, request)
    