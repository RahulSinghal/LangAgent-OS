# LangGraph AgentOS

A consulting delivery operating system built on LangGraph.
A Supervisor agent dynamically assembles teams from a registry, executes task DAGs with dependencies, enforces approval gates, and generates versioned PRD + SOW artifacts.

---

## Architecture Overview

```
User Input
    │
    ▼
intake_normalize          ← normalise message + extract initial requirements
    │
    ▼
discovery_loop            ← DiscoveryAgent fills open_questions (loops until answered)
    │
    ▼
supervisor_plan_team      ← Supervisor reads SoT + registry, builds TaskDAG
    │
    ▼
task_runner               ← executes DAG tasks in topological order
    │
    ▼
prd_phase                 ← PRDAgent generates PRD → Jinja2 artifact
    │
    ▼
prd_approval_gate ─── PAUSE (waiting_approval) ──► POST /approvals/{id}/resolve
    │ (approved)
    ▼
sow_phase                 ← SOWAgent generates SOW → Jinja2 artifact
    │
    ▼
sow_approval_gate ─── PAUSE (waiting_approval) ──► POST /approvals/{id}/resolve
    │ (approved)
    ▼
end                       ← mark run completed
```

**Key design decisions:**
- Every agent reads only from the Source of Truth (SoT) and writes only validated patches.
- All tool calls go through the Tool Gateway — enforces allowlists, logs every call.
- Runs pause at approval gates; resume via API (not by restarting the process).
- JSONB snapshots saved after every node — full replay history available.

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.115+ |
| Orchestration | LangGraph 0.2+ |
| LLM | litellm (OpenAI / Anthropic) |
| Database | PostgreSQL 16 + SQLAlchemy 2.x |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Templating | Jinja2 |
| Logging | structlog |
| Testing | pytest + httpx |

---

## Quickstart

### Prerequisites
- Python 3.11+
- Docker + Docker Compose
- `pip` (or `uv`)

### 1. Clone and install

```bash
cd "LangGraph_AgentOS"
pip install -e ".[dev]"
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set OPENAI_API_KEY (or ANTHROPIC_API_KEY), keep DB defaults for local dev
```

### 3. Start PostgreSQL

```bash
docker compose up -d
# Wait for healthy: docker compose ps
```

### 4. Run migrations (Phase 1B — skip in 1A)

```bash
python -m alembic upgrade head
```

### 5. Start the API

```bash
uvicorn app.main:app --reload --port 8001
```

### 6. Verify

```
GET http://localhost:8001/health
GET http://localhost:8001/docs
```

---

## Running Tests

```bash
# All unit tests (no DB required)
pytest tests/unit -v

# Integration tests (requires Docker DB)
pytest tests/integration -v

# Full suite
pytest -v
```

---

## Project Structure

```
LangGraph_AgentOS/
├── app/
│   ├── main.py                  # FastAPI app factory
│   ├── api/                     # Route handlers (one file per resource)
│   ├── core/                    # Config, logging, security
│   ├── db/                      # SQLAlchemy models, session, Alembic
│   ├── sot/                     # Source of Truth: state schema + patch engine
│   ├── registry/                # agents.yaml + loader
│   ├── agents/                  # BaseAgent, mock agents, Supervisor, Deep
│   ├── tools/                   # Tool Gateway + local tools + MCP adapter
│   ├── workflow/                # LangGraph graph + nodes
│   ├── artifacts/               # Generator + Jinja2 templates
│   └── services/                # Business logic (projects, runs, approvals…)
├── tests/
│   ├── unit/                    # Fast, no DB
│   ├── contract/                # OpenAPI + Pydantic schema validation
│   ├── integration/             # Full DB lifecycle
│   └── e2e/                     # API-level end-to-end with httpx
├── docker-compose.yml
├── pyproject.toml
├── alembic.ini
└── .env.example
```

---

## Implementation Phases

### ✅ Phase 1A — Scaffold (current)
- Full folder structure scaffolded
- FastAPI app runs with health endpoint
- PostgreSQL in Docker
- Pydantic settings, structlog, CORS

### 🔲 Phase 1B — Data Model
- SQLAlchemy models: projects, sessions, messages, runs, run_steps, snapshots, artifacts, approvals, tool_calls
- Alembic migrations
- Project CRUD endpoint + DB test

### 🔲 Phase 1C — Source of Truth
- `ProjectState` Pydantic model (all fields)
- `apply_patch()` with schema validation
- Snapshot save/load to/from DB

### 🔲 Phase 1D — Agent Registry + Mock Agents
- `agents.yaml` + `loader.py` validation
- `BaseAgent` ABC
- Deterministic mock agents (no API keys needed)
- `SupervisorAgent` + `TaskDAG` schema

### 🔲 Phase 1E — LangGraph Workflow + Run Engine
- All Phase 1 nodes implemented
- Pause/resume mechanics
- Run service: start, pause at gate, resume after approval/user input
- Integration test: run pauses at PRD gate

### 🔲 Phase 1F — Artifacts + Approvals
- Jinja2 artifact rendering (PRD.md, SOW.md)
- Approval resolution endpoint
- Full flow integration test: PRD approve → SOW → approve → end

### 🔲 Phase 2 — Deep Agent + Market Eval + Testing Suite
- DeepWorkAgent (bounded plan-act-observe loop)
- MarketScanAgent + BuyBuildDecisionNode
- Test pyramid: unit / contract / integration / e2e
- Traceability matrix

### 🔲 Phase 3 — Governance + Reliability
- Multi-tenant RBAC (organizations, users, JWT)
- Full policy engine
- Baselines + change control
- Async workers (Celery/RQ)
- Observability + cost tracking
- Artifact linting + export pack

---

## API Reference (Phase 1)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check + DB status |
| POST | `/api/v1/projects` | Create project |
| GET | `/api/v1/projects` | List projects |
| GET | `/api/v1/projects/{id}` | Get project |
| POST | `/api/v1/projects/{id}/sessions` | Create session |
| POST | `/api/v1/sessions/{id}/messages` | Add message |
| POST | `/api/v1/runs/start` | Start a run |
| GET | `/api/v1/runs/{id}` | Get run status |
| POST | `/api/v1/runs/{id}/resume` | Resume paused run |
| POST | `/api/v1/approvals/{id}/resolve` | Approve or reject |
| GET | `/api/v1/projects/{id}/artifacts` | List artifacts |
| GET | `/api/v1/artifacts/{id}/download` | Download artifact file |

Full interactive docs: `http://localhost:8001/docs`
