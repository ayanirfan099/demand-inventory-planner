"""Authentication, session lifecycle and organization membership."""

from __future__ import annotations

import logging
from datetime import UTC, timedelta

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import AuthContext, get_auth, get_session_token, require_role
from ..errors import ForbiddenError, NotFoundError, UnauthorizedError
from ..models import Membership, Organization, SessionToken, User, utcnow
from ..schemas import LoginRequest, MembershipRoleRequest, SwitchOrgRequest
from ..security import generate_session_token, hash_password, hash_token, verify_password
from ..serializers import iso, organization
from ..services.ratelimit import enforce

router = APIRouter(tags=["auth"])
logger = logging.getLogger("forecastops.auth")

# A fixed dummy hash keeps failed logins on the same code path as successful ones for
# unknown emails, so response timing does not reveal whether an account exists.
_DUMMY_HASH = hash_password("not-a-real-password-placeholder")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


def _memberships(db: Session, user_id: int) -> list[Membership]:
    return list(
        db.scalars(select(Membership).where(Membership.user_id == user_id).order_by(Membership.id))
    )


def _session_payload(db: Session, user: User, active_org_id: int | None) -> dict:
    memberships = _memberships(db, user.id)
    orgs = []
    for membership in memberships:
        org = db.get(Organization, membership.org_id)
        if org is None:
            continue
        orgs.append({**organization(org), "role": membership.role, "membership_id": membership.id})
    active = next((item for item in orgs if item["id"] == active_org_id), orgs[0] if orgs else None)
    return {
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name, "is_demo": user.is_demo},
        "organizations": orgs,
        "active_org": None if active is None else {"id": active["id"], "name": active["name"], "slug": active["slug"]},
        "role": None if active is None else active["role"],
    }


@router.post("/auth/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    ip = _client_ip(request)
    enforce(f"login-ip:{ip}", settings.login_rate_limit, window_seconds=900)
    email = payload.email.strip().lower()
    enforce(f"login-email:{email}", settings.login_rate_limit, window_seconds=900)

    user = db.scalar(select(User).where(User.email == email))
    stored_hash = user.password_hash if user else _DUMMY_HASH
    valid = verify_password(payload.password, stored_hash)
    if user is None or not valid or not user.is_active:
        logger.warning("failed login attempt", extra={"context": {"ip": ip}})
        raise UnauthorizedError("Email or password is incorrect.")

    # Housekeeping: drop this user's expired sessions.
    now = utcnow()
    for stale in db.scalars(select(SessionToken).where(SessionToken.user_id == user.id)).all():
        expires = stale.expires_at if stale.expires_at.tzinfo else stale.expires_at.replace(tzinfo=UTC)
        if expires <= now:
            db.delete(stale)

    memberships = _memberships(db, user.id)
    if not memberships:
        raise ForbiddenError("This account has no organization access.")

    token = generate_session_token()
    session = SessionToken(
        token_hash=hash_token(token),
        user_id=user.id,
        active_org_id=memberships[0].org_id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
    )
    db.add(session)
    db.flush()

    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    payload_data = _session_payload(db, user, session.active_org_id)
    payload_data["session"] = {"expires_at": iso(session.expires_at)}
    return payload_data


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session: SessionToken = Depends(get_session_token),
    db: Session = Depends(get_db),
) -> Response:
    db.delete(session)
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/auth/me")
def me(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)) -> dict:
    data = _session_payload(db, auth.user, auth.org_id)
    data["session"] = {"expires_at": iso(auth.session.expires_at)}
    return data


@router.post("/auth/switch-org")
def switch_org(
    payload: SwitchOrgRequest,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    membership = db.scalar(
        select(Membership).where(Membership.user_id == auth.user.id, Membership.org_id == payload.org_id)
    )
    if membership is None:
        # Same generic error whether the org exists or not.
        raise NotFoundError("Organization not found.")
    auth.session.active_org_id = membership.org_id
    db.add(auth.session)
    return _session_payload(db, auth.user, membership.org_id)


@router.get("/organizations")
def list_organizations(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)) -> dict:
    data = _session_payload(db, auth.user, auth.org_id)
    return {"organizations": data["organizations"], "active_org": data["active_org"], "role": data["role"]}


@router.get("/organizations/members")
def list_members(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)) -> dict:
    memberships = list(
        db.scalars(select(Membership).where(Membership.org_id == auth.org_id).order_by(Membership.id))
    )
    members = []
    for membership in memberships:
        user = db.get(User, membership.user_id)
        if user is None:
            continue
        members.append(
            {
                "membership_id": membership.id,
                "user_id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "role": membership.role,
                "created_at": iso(membership.created_at),
            }
        )
    return {"members": members, "role": auth.role}


@router.patch("/organizations/members/{membership_id}")
def update_member_role(
    membership_id: int,
    payload: MembershipRoleRequest,
    auth: AuthContext = Depends(require_role("owner")),
    db: Session = Depends(get_db),
) -> dict:
    membership = db.scalar(
        select(Membership).where(Membership.id == membership_id, Membership.org_id == auth.org_id)
    )
    if membership is None:
        raise NotFoundError("Member not found.")
    if membership.user_id == auth.user.id and payload.role != "owner":
        owners = db.scalars(
            select(Membership).where(Membership.org_id == auth.org_id, Membership.role == "owner")
        ).all()
        if len(owners) <= 1:
            raise ForbiddenError("An organization must keep at least one owner.")
    membership.role = payload.role
    db.add(membership)
    return {"membership_id": membership.id, "role": membership.role}
