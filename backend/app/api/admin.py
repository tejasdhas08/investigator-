"""Admin: user management + audit chain verification + MFA enrollment."""
import uuid

import pyotp
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_role
from app.core.security import encrypt_secret, hash_password
from app.models.user import ROLES, User
from app.schemas.api import UserOut
from app.services import audit

router = APIRouter(prefix="/admin", tags=["admin"])


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: str = "investigator"
    badge_number: str | None = None
    department: str | None = None


class UserPatch(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None


@router.post("/users", response_model=UserOut, dependencies=[Depends(require_role("admin"))])
def create_user(body: UserCreate, db: Session = Depends(get_db),
                actor: User = Depends(get_current_user)):
    if body.role not in ROLES:
        raise HTTPException(422, detail={"error": "bad_role", "message": f"Role must be one of {ROLES}"})
    if db.execute(select(User).where(User.email == body.email)).scalar_one_or_none():
        raise HTTPException(409, detail={"error": "duplicate_email", "message": "Email already registered"})
    user = User(email=body.email, full_name=body.full_name, password_hash=hash_password(body.password),
                role=body.role, badge_number=body.badge_number, department=body.department)
    db.add(user)
    db.flush()
    audit.log(db, action="user.create", actor_user_id=actor.id, entity_type="user", entity_id=user.id,
              detail={"email": body.email, "role": body.role})
    db.commit()
    db.refresh(user)
    return user


@router.get("/users", response_model=list[UserOut], dependencies=[Depends(require_role("admin"))])
def list_users(db: Session = Depends(get_db)):
    return db.execute(select(User).order_by(User.created_at)).scalars().all()


@router.patch("/users/{user_id}", response_model=UserOut, dependencies=[Depends(require_role("admin"))])
def patch_user(user_id: uuid.UUID, body: UserPatch, db: Session = Depends(get_db),
               actor: User = Depends(get_current_user)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, detail={"error": "not_found", "message": "User not found"})
    detail = {}
    if body.full_name is not None:
        detail["full_name"] = {"from": user.full_name, "to": body.full_name}
        user.full_name = body.full_name
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(422, detail={"error": "bad_role", "message": f"Role must be one of {ROLES}"})
        detail["role"] = {"from": user.role, "to": body.role}
        user.role = body.role
    if body.is_active is not None:
        detail["is_active"] = {"from": user.is_active, "to": body.is_active}
        user.is_active = body.is_active
    if detail:
        audit.log(db, action="user.update", actor_user_id=actor.id, entity_type="user",
                  entity_id=user.id, detail=detail)
    db.commit()
    db.refresh(user)
    return user


@router.post("/mfa/enroll")
def enroll_mfa(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    secret = pyotp.random_base32()
    user.mfa_totp_secret = encrypt_secret(secret)
    audit.log(db, action="user.update", actor_user_id=user.id, entity_type="user",
              entity_id=user.id, detail={"mfa": "enrolled"})
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="CrimeScene AI")
    return {"otpauth_uri": uri, "secret": secret}


@router.get("/audit/verify", dependencies=[Depends(require_role("admin"))])
def verify_audit_chain(db: Session = Depends(get_db)):
    ok, broken_id = audit.verify_chain(db)
    return {"ok": ok, "first_broken_row_id": broken_id}
