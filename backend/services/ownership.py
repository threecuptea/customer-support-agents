"""Bind a signed-in customer's identity to what they may touch (CSA-21 review).

RoleChecker only proves the caller *is a customer*. These helpers prove they are *the* customer in
the request: the session carries the authenticated email (set by /api/auth), and
  - a `customer_context` sent in a request body must have that email, and
  - an existing LangGraph thread (checkpoint) must belong to a customer_context with that email.
Without them a customer could post another customer's `customer_context` or reuse their `thread_id`.
"""
from __future__ import annotations

from fastapi import HTTPException, Request, status


def _norm(email: str | None) -> str:
    return (email or "").strip().lower()


def session_email(request: Request) -> str:
    email = _norm(request.session.get("email"))
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return email


def _forbidden() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to access this resource")


def check_context_owner(request: Request, customer_context) -> None:
    if _norm(customer_context.email) != session_email(request):
        raise _forbidden()


async def check_thread_owner(graph, thread_id: str, request: Request) -> None:
    """403 if the thread already exists and belongs to someone else. A thread with no state yet is not owned."""
    email = session_email(request)
    state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    ctx = state.values.get("customer_context") if state and state.values else None
    if ctx is None:
        return
    owner = ctx.get("email") if isinstance(ctx, dict) else getattr(ctx, "email", None)
    if _norm(owner) != email:
        raise _forbidden()
