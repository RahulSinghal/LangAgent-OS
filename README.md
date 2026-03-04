# LangGraph AgentOS

A consulting delivery operating system built on LangGraph. Starting from a client brief, it autonomously drives the full engagement lifecycle — discovery, market evaluation, PRD, commercials, SOW, and milestone-by-milestone code generation — with human approval gates at every major decision point.

---

## How It Works

A **Supervisor agent** dynamically assembles specialist teams from a registry, executes task DAGs with dependencies, enforces approval gates, and generates versioned artifacts (PRD, SOW, code). Every agent reads from and writes only validated patches to a central **Source of Truth (ProjectState)**. Runs pause at gates; humans approve or reject via the REST API; the workflow resumes from exactly where it stopped.

---

## Workflow

```
User message / BRD upload
        │
        ▼
intake_normalize            normalise message, extract initial requirements
        │
        ▼
discovery_loop              DiscoveryAgent asks questions until 70% coverage
        │  ↑ (loops until discovery_complete)
        ▼
market_eval                 buy / build / hybrid analysis
        │
        ▼
market_eval_gate ────── PAUSE ──► POST /approvals/{id}/resolve
        │ approved
        ▼
prd_phase                   PRDAgent generates PRD + server details → Jinja2 artifact
        │
        ▼
prd_approval_gate ─────PAUSE ──► POST /approvals/{id}/resolve
        │ approved          ↑ rejected: loops back to prd_phase with feedback
        ▼
commercials_phase           CommercialAgent generates pricing, milestones
        │
        ▼
commercials_gate ───────PAUSE ──► POST /approvals/{id}/resolve
        │ approved          ↑ rejected: loops back to commercials_phase
        ▼
sow_phase                   SOWAgent generates SOW with legal guard check → artifact
        │
        ▼
sow_approval_gate ──────PAUSE ──► POST /approvals/{id}/resolve
        │ approved          ↑ rejected: loops back to sow_phase with feedback
        ▼
coding_plan                 CodingPlanAgent divides backlog into 3–6 milestones
        │
        ▼
coding_plan_gate ───────PAUSE ──► POST /approvals/{id}/resolve  (tech lead)
        │ approved          ↑ rejected: loops back to coding_plan with feedback
        ▼
coding_milestone            MilestoneCodeAgent implements milestone[i], writes files
        │
        ▼
milestone_gate ─────────PAUSE ──► POST /approvals/{id}/resolve  (tech lead)
        │ approved          ↑ rejected: loops back to coding_milestone with feedback
        │ more milestones → coding_milestone (index + 1)
        │ all done
        ▼
end                         mark run completed
```

### Key design principles

- **Source of Truth (SoT):** Every agent returns a patch dict; `apply_patch()` validates it against the Pydantic schema before merging. No agent mutates state directly.
- **Tool Gateway:** All tool calls are routed through a gateway that enforces per-agent allowlists and logs every invocation.
- **Pause / Resume:** Runs pause by setting `pause_reason` in WorkflowState. Resuming re-enters the graph at the correct gate via `current_phase` routing — no need to restart.
- **Snapshots:** Full JSONB snapshots of ProjectState are saved after every node, giving a complete audit trail and enabling replay.
- **Rejection loops:** Every approval gate supports rejection with reviewer comments. Comments are patched into `rejection_feedback` so the agent incorporates them on the next attempt.

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.115+ |
| Orchestration | LangGraph 0.2+ |
| LLM | litellm (OpenAI / Anthropic / Gemini) |
| Database | PostgreSQL 16 + SQLAlchemy 2.x |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Templating | Jinja2 (PRD, SOW, server details artifacts) |
| Logging | structlog (structured JSON) |
| Testing | pytest + httpx |
| Code quality | ruff |

---

## Quickstart

### Prerequisites

- Python 3.11+
- Docker + Docker Compose (for PostgreSQL)
- An LLM API key — OpenAI, Anthropic, or Gemini *(optional: runs in mock mode without one)*

### 1. Clone and install

```bash
git clone <repo-url>
cd LangGraph_AgentOS
pip install -e ".[dev]"
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` — minimum required changes:

```env
# Choose one LLM provider
LLM_PROVIDER=openai          # or "anthropic" / "gemini"
LLM_MODEL=gpt-4o
OPENAI_API_KEY=sk-...        # or ANTHROPIC_API_KEY / GEMINI_API_KEY

# Leave DB defaults for local Docker dev
POSTGRES_HOST=localhost
POSTGRES_PORT=5434
```

> **No API key?** Set `USE_MOCK_AGENTS=true` to run fully offline with deterministic mock agents. All workflow phases and approval loops work; no LLM calls are made.

### 3. Start PostgreSQL

```bash
docker compose up -d
docker compose ps        # wait until Status = healthy
```

### 4. Run database migrations

```bash
python -m alembic upgrade head
```

### 5. Start the server

```bash
uvicorn app.main:app --reload --port 8001
```

### 6. Verify

```
GET  http://localhost:8001/health       → { "status": "ok", "db": "ok" }
GET  http://localhost:8001/docs         → interactive Swagger UI
GET  http://localhost:8001/ui           → built-in web UI
```

---

## Using the UI

Open `http://localhost:8001/ui` in a browser.

| Action | How |
|---|---|
| Create a project | Click **Create project** in the top bar |
| Start a run | Type a brief in the chat and press Enter |
| Attach a BRD | Click **+** to upload a PDF or DOCX — text is extracted and sent with your message |
| Approve / reject | Use the **Approval** panel on the right; add optional reviewer comments before clicking |
| View artifacts | Click any artifact button in the side panel to read the rendered Markdown |
| Track progress | The **workflow stepper** in the chat header shows which phase is active |

---

## Running Tests

```bash
# Fast unit tests — no database required
pytest tests/unit -v

# Integration tests — requires running PostgreSQL (docker compose up -d)
pytest tests/integration -v

# End-to-end API tests
pytest tests/e2e -v

# Full suite
pytest -v

# Run without LLM keys (mock mode)
USE_MOCK_AGENTS=true pytest tests/unit -v
```

> **Note:** `test_health.py` and `test_security.py` require a working `python-jose` / `cryptography` native install. They may fail in environments where the C extension is unavailable; all other tests are unaffected.

---

## Project Structure

```
LangGraph_AgentOS/
├── app/
│   ├── main.py                    FastAPI app factory + router registration
│   ├── api/                       Route handlers (one file per resource)
│   │   ├── routes_projects.py
│   │   ├── routes_runs.py
│   │   ├── routes_approvals.py
│   │   ├── routes_artifacts.py
│   │   ├── routes_documents.py
│   │   ├── routes_sot.py
│   │   ├── routes_system.py
│   │   └── ...
│   ├── core/                      Config, logging, runtime mode, security
│   ├── db/                        SQLAlchemy ORM models, session, Alembic migrations
│   ├── sot/                       Source of Truth: ProjectState schema + patch engine
│   ├── registry/                  agents.yaml + loader (AgentSpec validation)
│   ├── agents/                    BaseAgent ABC, all agent implementations, mock agents
│   │   ├── base.py
│   │   ├── supervisor.py
│   │   ├── discovery_agent.py
│   │   ├── prd_agent.py
│   │   ├── sow_agent.py
│   │   ├── coding_plan_agent.py   Step 4: milestone plan generation
│   │   ├── milestone_code_agent.py Step 4: per-milestone code generation
│   │   └── mock_agents.py
│   ├── tools/                     Tool Gateway + local tools + MCP adapter
│   ├── workflow/                  LangGraph graph builder + all phase nodes
│   │   ├── graph.py
│   │   └── nodes/
│   │       ├── intake.py
│   │       ├── discovery.py
│   │       ├── market_eval.py
│   │       ├── prd.py
│   │       ├── commercials.py
│   │       ├── sow.py
│   │       ├── coding_plan.py
│   │       ├── coding_milestone.py
│   │       ├── approval_gate.py
│   │       └── end.py
│   ├── artifacts/                 Jinja2 renderer + templates (PRD, SOW, server details)
│   ├── services/                  Business logic (runs, approvals, snapshots, dashboard…)
│   └── ui/                        Single-file browser UI (no build step)
│       ├── index.html
│       ├── app.js
│       └── styles.css
├── tests/
│   ├── unit/                      Fast, no DB — agents, SoT, workflow nodes, graph routing
│   ├── contract/                  OpenAPI + Pydantic schema validation
│   ├── integration/               Full DB lifecycle tests
│   └── e2e/                       API-level end-to-end with httpx
├── docker-compose.yml
├── pyproject.toml
├── alembic.ini
└── .env.example
```

---

## API Reference

### System

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check + DB connectivity |
| `GET` | `/api/v1/system/status` | Agent mode (real/mock), LLM provider, key validity |

### Projects

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/projects` | Create project |
| `GET` | `/api/v1/projects` | List all projects |
| `GET` | `/api/v1/projects/dashboard` | Dashboard summary (state, artifacts, spend) |
| `GET` | `/api/v1/projects/{id}` | Get project |
| `GET` | `/api/v1/projects/{id}/messages` | All messages across sessions |
| `GET` | `/api/v1/projects/{id}/state_graph` | Workflow phase graph + substates |
| `DELETE` | `/api/v1/projects/{id}` | Delete project (cascades all data) |

### Sessions & Messages

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/projects/{id}/sessions` | Create session |
| `GET` | `/api/v1/sessions/{id}/messages` | Get session messages |

### Runs

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/runs/start` | Start a new run |
| `GET` | `/api/v1/runs/{id}` | Get run status + current node |
| `POST` | `/api/v1/runs/{id}/resume` | Resume a paused run |
| `GET` | `/api/v1/runs/{id}/sot` | Get latest ProjectState snapshot |
| `GET` | `/api/v1/runs/{id}/approvals` | List approvals for a run |

### Approvals

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/approvals/{id}` | Get approval details |
| `POST` | `/api/v1/approvals/{id}/resolve` | Approve or reject (`decision`, `comments`) |

### Artifacts

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/projects/{id}/artifacts` | List artifacts |
| `GET` | `/api/v1/artifacts/{id}/content` | Read rendered Markdown content |

### Documents

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/documents/extract` | Extract text from PDF/DOCX (no save) |
| `POST` | `/api/v1/documents/extract_and_save` | Extract + save as artifact |

Full interactive docs: `http://localhost:8001/docs`

---

## Agents

| Agent | Role | Phase |
|---|---|---|
| `SupervisorAgent` | Plans TaskDAGs from registry based on current phase | All |
| `DiscoveryAgent` | LLM-driven requirements discovery with coverage scoring | Discovery |
| `DeepWorkAgent` | Bounded plan-act-observe research loop (market intelligence) | Market eval |
| `MarketScanAgent` | Buy / build / hybrid vendor scoring | Market eval |
| `PRDAgent` | Generates PRD sections + server details; supports rejection loop | PRD |
| `CommercialAgent` | Pricing models, milestones, team estimates | Commercials |
| `SOWAgent` | Generates SOW sections with legal guard check; supports rejection loop | SOW |
| `CodingPlanAgent` | Divides backlog into 3–6 sequential milestones for tech lead sign-off | Coding |
| `MilestoneCodeAgent` | Generates code for one milestone at a time; writes files via tool gateway | Milestone |

Each agent has a per-agent **tool allowlist**, **step budget**, and **cost ceiling** defined in `app/registry/agents.yaml`. All tool calls are enforced through the Tool Gateway.

---

## Approval Types

Each approval type maps to a specific gate in the workflow:

| Approval type | Gate | Who reviews |
|---|---|---|
| `prd` | `prd_approval_gate` | Product owner |
| `server_details_client` / `server_details_infra` | `prd_approval_gate` | Infrastructure team |
| `commercials` | `commercials_gate` | Client / finance |
| `sow` | `sow_approval_gate` | Client / legal |
| `coding_plan` | `coding_plan_gate` | Tech lead |
| `milestone_{id}` | `milestone_gate` | Tech lead |

Resolve any approval via:

```bash
curl -X POST http://localhost:8001/api/v1/approvals/{id}/resolve \
  -H "Content-Type: application/json" \
  -d '{"decision": "approved", "comments": "Looks good."}'
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` \| `anthropic` \| `gemini` |
| `LLM_MODEL` | `gpt-4o` | Model name passed to litellm |
| `OPENAI_API_KEY` | — | Required if `LLM_PROVIDER=openai` |
| `ANTHROPIC_API_KEY` | — | Required if `LLM_PROVIDER=anthropic` |
| `GEMINI_API_KEY` | — | Required if `LLM_PROVIDER=gemini` |
| `USE_MOCK_AGENTS` | `false` | `true` = fully offline, no LLM calls |
| `DEEP_MODE` | `suggest` | `off` \| `suggest` \| `auto` |
| `POSTGRES_HOST` | `localhost` | DB host |
| `POSTGRES_PORT` | `5434` | DB port |
| `POSTGRES_DB` | `agentosdb` | Database name |
| `POSTGRES_USER` | `agentosuser` | DB user |
| `POSTGRES_PASSWORD` | `agentospassword` | DB password |
| `ARTIFACTS_DIR` | `./storage/artifacts` | Where rendered artifacts are saved |
| `JWT_SECRET_KEY` | `change-me-in-production` | JWT signing secret (Phase 3) |
| `API_PREFIX` | `/api/v1` | API route prefix |

---

## Implementation Status

| Phase | Description | Status |
|---|---|---|
| 1A | Scaffold — FastAPI, PostgreSQL, config, logging | ✅ Done |
| 1B | Data models — SQLAlchemy ORM, Alembic migrations, project/session CRUD | ✅ Done |
| 1C | Source of Truth — `ProjectState`, `apply_patch()`, JSONB snapshots | ✅ Done |
| 1D | Agent registry — `agents.yaml`, `BaseAgent`, mock agents, Supervisor + TaskDAG | ✅ Done |
| 1E | LangGraph workflow — all nodes, pause/resume, run engine | ✅ Done |
| 1F | Artifacts + approvals — Jinja2 rendering, approval resolution, rejection loops | ✅ Done |
| 2 | Deep agent + market eval + traceability matrix | ✅ Done |
| 3 | Governance — RBAC, policy engine, multi-tenancy, change control, audit logs | ✅ Done |
| Step 4 | Milestone-based code generation with tech lead approval loop | ✅ Done |
| Next | QA / test generation (QAAuditorAgent) | 🔲 Planned |
| Next | Deployment readiness — DevOpsAgent, IaC generation | 🔲 Planned |
