"""Authentication, session and role tests."""

from __future__ import annotations

from datetime import timedelta

from app.config import settings
from app.db import SessionLocal
from app.models import SessionToken, utcnow
from app.security import hash_token

from tests.helpers import PASSWORDS, login


def test_login_sets_httponly_session_cookie(api, seeded_org):
    response = api.post(
        "/api/v1/auth/login",
        json={"email": "owner@test.example", "password": PASSWORDS["owner@test.example"]},
    )
    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie.lower() or "samesite=lax" in set_cookie.lower()
    body = response.json()
    assert body["role"] == "owner"
    assert body["active_org"]["id"] == seeded_org["org_id"]
    assert "password" not in response.text.lower()


def test_session_token_is_not_stored_in_plaintext(api, seeded_org):
    login(api, "owner@test.example")
    token = api.cookies.get(settings.session_cookie_name)
    assert token
    with SessionLocal() as session:
        stored = session.query(SessionToken).all()
        assert stored
        assert all(row.token_hash != token for row in stored)
        assert session.query(SessionToken).filter_by(token_hash=hash_token(token)).one()


def test_wrong_password_and_unknown_email_are_indistinguishable(api, seeded_org):
    wrong = api.post(
        "/api/v1/auth/login",
        json={"email": "owner@test.example", "password": "definitely-not-it"},
    )
    unknown = api.post(
        "/api/v1/auth/login",
        json={"email": "nobody@test.example", "password": "definitely-not-it"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"]


def test_protected_routes_require_a_session(api, seeded_org):
    for path in ("/api/v1/datasets", "/api/v1/forecast-jobs", "/api/v1/me", "/api/v1/forecast-runs"):
        route = path.replace("/api/v1/me", "/api/v1/auth/me")
        assert api.get(route).status_code == 401


def test_logout_invalidates_the_session(owner_client):
    assert owner_client.post("/api/v1/auth/logout").status_code == 204
    assert owner_client.get("/api/v1/auth/me").status_code == 401


def test_expired_session_is_rejected(owner_client):
    with SessionLocal() as session:
        row = session.query(SessionToken).order_by(SessionToken.id.desc()).first()
        row.expires_at = utcnow() - timedelta(minutes=1)
        session.commit()
    assert owner_client.get("/api/v1/auth/me").status_code == 401


def test_role_permissions_are_enforced(viewer_client, analyst_client, seeded_org):
    assert viewer_client.get("/api/v1/datasets").status_code == 200
    blocked = viewer_client.post("/api/v1/forecast-jobs", json={"dataset_id": seeded_org["dataset_id"]})
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "forbidden"

    allowed = analyst_client.post(
        "/api/v1/forecast-jobs",
        json={"dataset_id": seeded_org["dataset_id"], "idempotency_key": "analyst-job-0001"},
    )
    assert allowed.status_code == 201

    # Audit visibility is owner-only, even for a read.
    assert analyst_client.get("/api/v1/audit-events").status_code == 403


def test_organization_switch_is_membership_scoped(owner_client, seeded_org):
    forbidden = owner_client.post("/api/v1/auth/switch-org", json={"org_id": seeded_org["other_org_id"]})
    assert forbidden.status_code == 404

    allowed = owner_client.post("/api/v1/auth/switch-org", json={"org_id": seeded_org["org_id"]})
    assert allowed.status_code == 200
    assert allowed.json()["active_org"]["id"] == seeded_org["org_id"]


def test_login_is_rate_limited(api, seeded_org):
    for _ in range(settings.login_rate_limit):
        api.post("/api/v1/auth/login", json={"email": "owner@test.example", "password": "wrong"})
    response = api.post(
        "/api/v1/auth/login",
        json={"email": "owner@test.example", "password": PASSWORDS["owner@test.example"]},
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"


def test_owner_cannot_remove_the_last_owner(owner_client, seeded_org):
    members = owner_client.get("/api/v1/organizations/members").json()["members"]
    owner = next(member for member in members if member["email"] == "owner@test.example")
    response = owner_client.patch(
        f"/api/v1/organizations/members/{owner['membership_id']}", json={"role": "viewer"}
    )
    assert response.status_code == 403
