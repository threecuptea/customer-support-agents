from fastapi import HTTPException, status
from models.auth_model import ALLOWED_ROLES
from fastapi import Request

class RoleChecker:
    def __init__(self, allowed_role: ALLOWED_ROLES):
        self.allowed_role = allowed_role

    def __call__(self, request: Request):
        role = request.session.get("role")
        if role is None:
            # No role in the session cookie: never signed in, or the cookie expired/was cleared.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated"
            )
        if role != self.allowed_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource"
            )
        return request