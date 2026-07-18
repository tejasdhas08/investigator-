import uuid

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_token
from app.models.case import Case, CaseMember
from app.models.user import User

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(401, detail={"error": "unauthenticated", "message": "Missing bearer token"})
    try:
        payload = decode_token(creds.credentials, "access")
    except pyjwt.PyJWTError:
        raise HTTPException(401, detail={"error": "invalid_token", "message": "Invalid or expired token"})
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(401, detail={"error": "invalid_token", "message": "Unknown or disabled user"})
    request.state.user = user
    return user


def require_role(*roles: str):
    def guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, detail={"error": "forbidden", "message": "Insufficient role"})
        return user

    return guard


def get_case_for_user(
    case_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, detail={"error": "not_found", "message": "Case not found"})
    if user.role in ("supervisor", "admin") or case.owner_id == user.id:
        return case
    member = db.execute(
        select(CaseMember).where(CaseMember.case_id == case_id, CaseMember.user_id == user.id)
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(403, detail={"error": "forbidden", "message": "Not a member of this case"})
    return case
