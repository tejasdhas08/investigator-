from datetime import datetime, timezone

import jwt as pyjwt
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.limiter import limiter
from app.core.deps import get_current_user
from app.core.security import (
    create_access_token, create_refresh_token, decode_token, decrypt_secret, verify_password,
)
from app.models.user import User
from app.schemas.api import LoginRequest, LoginResponse, UserOut
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "csai_refresh"


def _login_response(user: User, response: Response) -> LoginResponse:
    access = create_access_token(str(user.id), user.role)
    refresh = create_refresh_token(str(user.id), user.role)
    response.set_cookie(
        REFRESH_COOKIE, refresh,
        httponly=True, secure=True, samesite="strict",
        max_age=settings.refresh_token_hours * 3600, path="/api/v1/auth",
    )
    return LoginResponse(
        access_token=access,
        expires_in=settings.access_token_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    ip = request.client.host if request.client else None
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        audit.log(db, action="auth.login_failed", actor_type="system",
                  detail={"email": body.email}, ip_address=ip)
        db.commit()
        raise HTTPException(401, detail={"error": "bad_credentials", "message": "Invalid email or password"})
    if user.mfa_totp_secret:
        if not body.totp_code or not pyotp.TOTP(decrypt_secret(user.mfa_totp_secret)).verify(
            body.totp_code, valid_window=1
        ):
            audit.log(db, action="auth.login_failed", actor_user_id=user.id,
                      detail={"reason": "totp"}, ip_address=ip)
            db.commit()
            raise HTTPException(401, detail={"error": "totp_required", "message": "Valid TOTP code required"})
    user.last_login_at = datetime.now(timezone.utc)
    audit.log(db, action="auth.login", actor_user_id=user.id, ip_address=ip)
    db.commit()
    return _login_response(user, response)


@router.post("/refresh", response_model=LoginResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(401, detail={"error": "unauthenticated", "message": "Missing refresh cookie"})
    try:
        payload = decode_token(token, "refresh")
    except pyjwt.PyJWTError:
        raise HTTPException(401, detail={"error": "invalid_token", "message": "Invalid refresh token"})
    import uuid as _uuid

    user = db.get(User, _uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(401, detail={"error": "invalid_token", "message": "Unknown or disabled user"})
    return _login_response(user, response)


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
