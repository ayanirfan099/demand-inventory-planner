# 0005 — Server-side sessions, centralized authorization, 404 for cross-tenant access

- **Status:** accepted
- **Date:** 2026-10-30

## Context

The app needs authenticated users, three roles, multiple organizations per user, and a
tested guarantee that one tenant can never read another tenant's data. It also needs a
credential-free way to demo the product.

## Decision

- **Opaque session tokens** stored in an `HttpOnly`, `SameSite=Lax` cookie. The database
  stores only `sha256(token)`; a dump of `sessions` cannot be replayed.
- **Absolute expiry** (`FORECASTOPS_SESSION_TTL_HOURS`, default 12) checked on every request,
  plus `last_seen_at` for visibility. Expired sessions are deleted on use.
- **Centralized authz**: `deps.get_auth` builds `AuthContext(user, org, role)`;
  `require_role(minimum)` enforces `owner > analyst > viewer`. Routers declare the minimum
  role, never hand-roll role checks.
- **Tenant scoping in one place**: `deps.get_dataset/get_job/get_run/…` always filter by
  `auth.org_id`. Cross-tenant ids return **404 `not_found`**, so the existence of another
  tenant's rows is not disclosed. This is asserted by `tests/test_isolation.py`.
- **CSRF**: `SameSite=Lax` plus an origin check middleware rejecting unsafe methods from an
  unknown `Origin`.
- **Demo accounts are seeded data**, not a bypass: fictional users with hashed passwords
  created by `scripts/seed_demo.py`, disabled by not running the seed.

## Consequences

- No refresh-token machinery and no JWT revocation problem.
- Logout deletes the server-side session, which actually kills it.
- Sessions in one database table mean a session check is a DB read on every request; at this
  scale that is fine and simpler than a cache with invalidation.
- Role checks are greppable: every privileged endpoint shows its minimum role.

## Rejected

- **JWT in `localStorage`.** XSS-extractable and unrevocable; also forces the browser to know
  the API origin.
- **403 for cross-tenant reads.** Leaks existence; 404 does not.
- **Per-router tenant filters.** Too easy to forget one; the failure mode is a data breach.
