"""Seed users and demo cases (Phase 1 test data).

Usage: python -m scripts.seed
Creates one user per role (password: Password123!) and two empty cases.
"""
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.db import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models.case import Case, CaseMember
from app.models.user import User
from app.services import audit

USERS = [
    ("investigator@example.gov", "Alex Rivera", "investigator"),
    ("supervisor@example.gov", "Sam Chen", "supervisor"),
    ("admin@example.gov", "Jordan Blake", "admin"),
]


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        users = {}
        for email, name, role in USERS:
            existing = db.query(User).filter(User.email == email).first()
            if existing:
                users[role] = existing
                continue
            u = User(email=email, full_name=name, role=role,
                     password_hash=hash_password("Password123!"))
            db.add(u)
            db.flush()
            users[role] = u
            audit.log(db, action="user.create", actor_type="system", entity_type="user",
                      entity_id=u.id, detail={"email": email, "role": role, "seed": True})
        for i, (number, title) in enumerate(
            [("CASE-2026-001", "Storefront incident — demo"), ("CASE-2026-002", "Parking lot CCTV — demo")]
        ):
            if db.query(Case).filter(Case.case_number == number).first():
                continue
            c = Case(
                case_number=number, title=title,
                context_description="Demo case seeded for development.",
                owner_id=users["investigator"].id, status="created",
                retention_expires_at=datetime.now(timezone.utc) + timedelta(days=settings.retention_days),
            )
            db.add(c)
            db.flush()
            db.add(CaseMember(case_id=c.id, user_id=users["investigator"].id, role_in_case="owner"))
            audit.log(db, action="case.create", actor_type="system", case_id=c.id,
                      entity_type="case", entity_id=c.id, detail={"seed": True})
        db.commit()
    print("Seeded users:", ", ".join(e for e, _, _ in USERS), "(password: Password123!)")


if __name__ == "__main__":
    main()
