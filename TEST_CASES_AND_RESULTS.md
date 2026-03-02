### Test Cases and Results (Verification Artifact)

This document lists the test cases for the recent changes (UI layer, document uploads, multi-approval flow, server-details routing) and records what was executed in this environment.

Date: 2026-03-01

---

### Automated tests added

- `tests/integration/test_ui_smoke.py`
  - UI root served
  - UI static asset served
  - Plain-text document extraction works
  - (Indirectly) UI history button relies on existing sessions/messages endpoint

- `tests/integration/test_prd_server_details_approvals.py`
  - PRD gate requires `server_details_client` when hosting is client-hosted (mock mode)
  - PRD gate requires `server_details_infra` when hosting is vendor-hosted (mock mode)

- `tests/unit/test_persistence_features.py`
  - `/documents/extract_and_save` returns artifact metadata when persistence succeeds (mocked)
  - `runs.start_run` persists user messages and assistant `bot_response` into session messages (mocked)
  - `approvals.resolve_approval` persists a system message into session messages (mocked)

---

### Manual test checklists

- `UI_TEST_CASES.md`

---

### Results in this environment

#### UI smoke tests

- **Executed**: `python -m pytest -q tests/integration/test_ui_smoke.py`
- **Result**: PASS

#### Unit tests

- **Executed**: `python -m pytest -q tests/unit`
- **Result**: PASS

#### PRD server-details approval tests

- **Executed**: `python -m pytest -q tests/integration/test_prd_server_details_approvals.py`
- **Result**: NOT EXECUTABLE HERE (DB unavailable)

Reason:
- These tests call DB-backed endpoints (`/projects`, `/sessions`, `/runs/start`) which require PostgreSQL.
- Docker was not available in this runtime environment (cannot start the Postgres container).

What to do to execute locally:
- Ensure Docker Desktop is running
- Run:

```bash
docker compose up -d
python -m alembic upgrade head
python -m pytest -q tests/integration/test_prd_server_details_approvals.py
```

---

### Notes on deterministic test mode

To run deterministic tests without external LLM keys:
- Set `USE_MOCK_AGENTS=true`

This switches the workflow nodes to use mock agents for discovery/PRD/commercials/SOW.

