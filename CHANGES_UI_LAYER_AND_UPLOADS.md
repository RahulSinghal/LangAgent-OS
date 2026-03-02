### Purpose

This document records the **UI + document upload** changes added to this repository so you (or ChatGPT later) can verify:

- **What changed** (files + code areas)
- **What new capabilities exist**
- **How to run and manually test** the full flow
- **Known limitations**

Date: 2026-03-01

---

### Summary of changes (high level)

- **Added a minimal web UI** (no build step) served directly by FastAPI:
  - Chat input
  - A **“+” attachment button** for uploading documents/images
  - Approval actions (approve/reject) with optional comments
  - Artifact viewing (click to fetch Markdown content)
- **Added API endpoints** to support the UI:
  - Upload a file and extract text
  - Fetch latest SoT snapshot for a run (UI can show “next question”)
- **Extended approvals to support multiple pending approvals** per run (UI shows a list).
- **Added server-details approval routing** tied to the PRD gate (client vs infra).
- **Added dependencies** for parsing PDFs and DOCX files.

---

### Files added

- **UI**
  - `app/ui/index.html`
  - `app/ui/styles.css`
  - `app/ui/app.js`

- **New API routes**
  - `app/api/routes_documents.py`
  - `app/api/routes_sot.py`

- **New artifact template**
  - `app/artifacts/templates/server_details.md.j2`

- **Testing support**
  - `tests/integration/test_ui_smoke.py`
  - `tests/integration/test_prd_server_details_approvals.py`
  - `app/agents/mock_commercial.py`

---

### Files modified

- `app/main.py`
  - Mounts the UI at `/ui`
  - Serves the UI index at `/`
  - Registers the new routers:
    - `documents_router` under `/api/v1`
    - `sot_router` under `/api/v1`

- `pyproject.toml`
  - Added dependencies:
    - `pypdf>=4.0.0`
    - `python-docx>=1.1.0`

- `app/services/runs.py`
  - Creates/ensures **multiple** pending approvals and renders artifacts for pending types.

- `app/services/approvals.py`, `app/api/routes_approvals.py`
  - Added: `GET /runs/{run_id}/approvals` (list pending approvals)

- `app/workflow/nodes/approval_gate.py`
  - PRD gate now requires PRD + server-details (client or infra) approval.

- `app/workflow/nodes/intake.py`
  - Sets `hosting_preference` via heuristics from the initial message.

- `app/sot/state.py`
  - Added `hosting_preference` field.

- `app/ui/app.js`, `app/ui/index.html`
  - UI shows multiple pending approvals as a list and lets you resolve the selected one.

---

### New/updated runtime behavior

#### UI serving

- `GET /` serves `app/ui/index.html`
- `GET /ui/*` serves static UI assets (HTML/CSS/JS)

#### Dashboard + project spend/time metrics (new)

The UI now has a **project dashboard** that lists all projects and their key progress fields, and it adds per-project tracking of:

- **tokens spent** (summed across runs)
- **estimated cost in USD** (as reported by `litellm` when available)
- **system hours spent** (wall-clock runtime of workflow invocation; aggregated across runs)

##### New API endpoint

- `GET /api/v1/projects/dashboard`
  - **Purpose**: Returns a dashboard-friendly list of projects including current state, latest artifacts, pending approvals, and spend/time metrics.
  - **Output**: JSON `{ projects: [...], total: N }` where each row includes:
    - `name`
    - `current_state` (derived from the latest `runs.current_node` or run status)
    - `pending_approvals` (count of `approvals` rows in status `pending`)
    - `artifacts` (latest artifact IDs for common types like `prd`, `sow`, `input_document`, etc.)
    - `tokens_spent`, `cost_usd`
    - `system_hours` (derived from aggregated `run_metrics.total_latency_ms`)

##### How tokens/cost/time are collected and stored

- **Collection scope**: per run invocation (start or resume).
- **Mechanism**:
  - `app/core/metrics.py` provides a run-scoped in-memory collector (via `contextvars`).
  - `app/services/llm_service.py` records token usage, latency, and best-effort cost from each `litellm.completion()` call into the collector.
  - `app/services/runs.py` wraps `get_workflow().invoke(...)` and persists the collected totals into the DB.
- **Storage**: `run_metrics` table (SQLAlchemy model `RunMetrics`) is used as the persistent source of truth for spend/time aggregation.

##### UI behavior change

- `GET /` still serves the UI, but the UI now **starts on the dashboard**.
- The chat view opens after you click **Load** for a project from the dashboard.

#### New API endpoints

- `POST /api/v1/documents/extract`
  - **Input**: multipart form upload with field name `file`
  - **Output**: JSON `{ filename, content_type, text, warnings }`
  - **Supported extraction**:
    - `text/*` and common text extensions (`.txt`, `.md`, `.json`, `.csv`, `.yaml`, `.yml`)
    - PDFs (`.pdf` / `application/pdf`) via `pypdf`
    - DOCX (`.docx`) via `python-docx`
  - **Images**: accepted, but returns empty `text` and a warning (OCR is not enabled yet)

- `POST /api/v1/documents/extract_and_save`
  - **Input**: multipart form upload with:
    - `file` (required)
    - `project_id` (required)
    - `run_id` (optional)
  - **Output**: JSON `{ filename, content_type, text, warnings, artifact_id?, artifact_version? }`
  - **Behavior**:
    - Extracts text (same rules as `/extract`)
    - Persists extracted text as an `Artifact` of type `input_document`
    - Returns artifact metadata when successfully saved

- `GET /api/v1/runs/{run_id}/sot`
  - **Purpose**: Return latest SoT snapshot and unanswered questions
  - **Output**: JSON `{ run_id, sot, unanswered_questions }`

---

### How the UI uses the backend

The UI calls existing endpoints plus the new ones:

- **Create project**: `POST /api/v1/projects`
- **Create session**: `POST /api/v1/projects/{project_id}/sessions`
- **Dashboard list**: `GET /api/v1/projects/dashboard` (new)
- **Start run**: `POST /api/v1/runs/start`
  - UI can include `document_content` + `document_filename` (extracted from upload)
- **Resume run**: `POST /api/v1/runs/{run_id}/resume`
- **Get run status**: `GET /api/v1/runs/{run_id}`
- **Get pending approval**: `GET /api/v1/runs/{run_id}/approval`
- **Resolve approval**: `POST /api/v1/approvals/{approval_id}/resolve`
- **List artifacts**: `GET /api/v1/projects/{project_id}/artifacts`
- **Fetch artifact content**: `GET /api/v1/artifacts/{artifact_id}/content`
- **Fetch latest SoT**: `GET /api/v1/runs/{run_id}/sot` (new)
- **Extract document text**: `POST /api/v1/documents/extract` (new)
- **Extract + persist upload**: `POST /api/v1/documents/extract_and_save` (new)

---

### Manual verification checklist (end-to-end)

#### Prerequisites

- Docker is running
- DB container is healthy:

```bash
docker compose up -d
docker compose ps
```

#### Install dependencies

```bash
python -m pip install -e ".[dev]"
```

#### Run migrations

```bash
python -m alembic upgrade head
```

#### Start the API

Important (Windows): use python module form if `uvicorn` is not on PATH.

```bash
python -m uvicorn app.main:app --reload --port 8001
```

#### Verify API and UI load

- Open `http://localhost:8001/` (UI should render)
- Open `http://localhost:8001/docs` (FastAPI docs)
- Open `http://localhost:8001/health` (should return status + DB ok)

#### Verify dashboard + metrics

- Open the UI and confirm you see the **Projects dashboard**.
- Create a project and click **Load**.
- Send at least one message (start a run).
- Return to **Dashboard** and click **Refresh**.
- Confirm the project row shows:
  - Updated **State**
  - **Tokens** and **Cost** increasing after real LLM calls
  - **System hours** increasing after each run invocation

#### Verify document upload extraction

In the UI:
- Click **“+”**
- Upload a PDF or DOCX
- Confirm you see:
  - “Extracted N chars …”
  - Extracted text populated in the “Document text” box

#### Verify run start + discovery pause

In the UI:
- Enter a Project name, click Create (or just send and it will auto-create)
- Type a message and click Send
- Click Refresh
- You should see:
  - `run: <id>`
  - Status changes to `waiting_user` (if discovery asks a question)
  - “Next question” populated (pulled from `/runs/{id}/sot`)

#### Verify resume

In the UI:
- Type an answer to the question and click Send
- Click Refresh and see the next question or next phase

#### Verify approvals (PRD/SOW)

When the run reaches an approval gate:
- UI should show pending approvals (Refresh pulls `/runs/{id}/approvals`)
- Click Approve or Reject (optionally add comments)
- Confirm:
  - Approval resolves successfully
  - Run resumes and progresses to next phase (Refresh)

---

### Known limitations / intentional scope

- **Image uploads**: accepted, but there is no OCR/vision extraction yet.
- **UI is minimal**:
  - No authentication
  - No streaming responses
  - No chat history persistence view (though sessions/messages exist in the API)
- **SoT “next question”**:
  - The UI derives next question from `open_questions` in the latest SoT snapshot.
  - Update: `runs.start_run` / `runs.resume_run` now write user messages to `sessions/messages` (when a session exists).
  - Update: run engine now persists `bot_response` to `sessions/messages` as an assistant message (when a session exists).

---

### Quick “what to check in code”

- UI mount + routers: `app/main.py`
- Document extraction logic: `app/api/routes_documents.py`
- Latest SoT endpoint: `app/api/routes_sot.py`
- UI behavior and API calls: `app/ui/app.js`

