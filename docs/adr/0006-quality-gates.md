# 0006 — Lint, types, unit, integration and browser tests as merge gates

- **Status:** accepted
- **Date:** 2026-10-31

## Context

The repository is a portfolio artefact: the claims in the README must be reproducible by a
reviewer in a few minutes, on a machine with no paid services, and CI must fail for real
regressions rather than for flaky infrastructure.

## Decision

| Gate | Tool | Scope |
| --- | --- | --- |
| Style/imports/security-ish lint | `ruff check .` | all Python |
| Static types | `mypy` (strict-ish) | API app, forecasting, worker |
| Types/lint | `tsc --noEmit`, `next lint` | `apps/web` |
| Unit | `pytest packages/forecasting/tests` | library, no DB |
| Contract drift | `pytest packages/contracts/tests` | constants vs. the code that enforces them |
| Integration | `pytest tests` | API against isolated SQLite |
| Unit | `vitest run` | formatting/helpers |
| Browser | `playwright test` | login → upload → job → run → planning |
| Accessibility | `@axe-core/playwright` (same job) | login, every page, and the data-dense screens once real data exists |

Rules:

- Tests must not depend on paid services, live networks or large downloads; fixtures are
  small and deterministic (seeded generator, tiny CSV strings).
- A gate is fixed by fixing the code. `# type: ignore` and lint suppressions are only
  acceptable with a comment explaining the runtime reason (there are none in the forecasting
  library and one documented `noqa` for the fictional demo password default).
- Integration tests create and destroy their own database; no test writes to `data/local`.

## Consequences

- Mypy flagged 33 real issues when first introduced (Optional arithmetic, `Sequence` vs
  `list`, variable reuse between frames and lists, `.rowcount` on the wrong result type).
  All were fixed in code, not suppressed.
- The accessibility gate earned its place immediately: its first run reported a
  `scrollable-region-focusable` failure on a table wrapper, and the token audit behind it found
  a "large text only" ink used at 11-13px. Both were fixed in code.
- Playwright needs a Chromium download, which is impossible in the restricted sandbox used
  for development; the suite therefore runs in CI and locally, and the README says plainly
  that it has not executed in that sandbox.
- Docker Compose cannot be validated without a Docker daemon; it is reviewed by inspection
  and marked unbuilt rather than claimed as working.

## Rejected

- **Snapshot-only UI tests.** They would not prove the upload → job → run flow works.
- **A shared "dev" database for tests.** Non-deterministic and slow; isolation tests need
  clean tenants.
- **Mocking the forecasting library in API tests.** The contract between API and library is
  exactly where bugs live; integration tests run the real one.
