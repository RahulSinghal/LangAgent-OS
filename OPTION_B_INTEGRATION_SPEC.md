### Option B Integration Spec (SOP as first-class workflow)

This document is a **step-by-step implementation plan** to integrate the SOP from `Standard_Project_Workflow.pdf` as a **first-class, enforced workflow** in this AgentOS codebase.

It is written so you can later paste it into ChatGPT and ask: “Verify my repo matches this spec.”

Date: 2026-03-01

---

### Goals

- Encode the SOP lifecycle (BRD → SOW → Discovery → PRD → Tech Prep → Approvals → Dev → User Guide → Evaluation) into:
  - **SoT state** (`ProjectState`)
  - **LangGraph workflow graph** (nodes + gates)
  - **Artifacts** (Jinja templates + stored versions)
  - **Approvals** (DB-backed, pause/resume)
  - **UI timeline** (optional but recommended)

---

### Current state (baseline)

Current graph (already implemented in `app/workflow/graph.py`):

- `init → intake → discovery → market_eval → market_eval_gate → prd → prd_gate → commercials → commercials_gate → sow → sow_gate → end`

Artifacts currently rendered only for:
- `prd`, `sow` (see `app/services/runs.py:_process_result`)

Approvals currently exist as:
- DB table: `approvals` (`app/db/models.py`)
- Endpoints: `GET /runs/{run_id}/approval`, `POST /approvals/{id}/resolve`
- Gate nodes: `app/workflow/nodes/approval_gate.py` (prd/commercials/sow)

---

### Target SOP workflow (Option B)

#### Target phases (high-level)

1. **Client Communication** (captured as intake context)
2. **BRD** (high-level alignment) + iterative approval loop
3. **SOW** (based on BRD) + approval gate
4. **Discovery** (deep technical questions) until complete
5. **Design + PRD** + approval gate
6. **Tech Prep** (DB schema + API spec + detailed test cases + 3rd-party planning) + multi-approval gate(s)
7. **Development** (starts only after approvals)
8. **User Guide** artifact
9. **Evaluation Report** artifact
10. **Completed**

#### Target graph structure (recommended)

Use the same pattern you already use: generation node → approval gate → next phase.

Proposed nodes:

- `intake`
- `brd`
- `brd_gate`
- `sow`
- `sow_gate`
- `discovery`
- `prd`
- `prd_gate`
- `tech_prep`
- `tech_prep_gate`
- `development`
- `user_guide`
- `evaluation`
- `end`

Proposed edges (simplified):

- `intake → brd → brd_gate → sow → sow_gate → discovery → prd → prd_gate → tech_prep → tech_prep_gate → development → user_guide → evaluation → end`

Rejection loops:
- If `brd` rejected: gate routes back to `brd`
- If `sow` rejected: back to `sow`
- If `prd` rejected: back to `prd`
- If `tech_prep` rejected: back to `tech_prep`

Resume behavior:
- On resume, conditional entry should jump to the **appropriate gate** node for the current phase (same pattern as PRD/SOW now).

---

### SoT changes (app/sot/state.py)

#### 1) Extend Phase enum

Add phases (names are suggestions; use whatever naming you prefer, but keep consistent everywhere):

- `BRD = "brd"`
- `TECH_PREP = "tech_prep"`
- `DEVELOPMENT = "development"`
- `USER_GUIDE = "user_guide"`
- `EVALUATION = "evaluation"`

You can keep existing phases (discovery/prd/commercials/sow/etc.) or retire `commercials` if it doesn’t fit your SOP.

#### 2) Add new SoT fields (structured artifact inputs)

Add fields to `ProjectState` that store content the new artifacts need:

- **BRD**
  - `brd_sections: list[dict]` or `brd: dict` (structured)
  - `business_objectives: list[str]` (optional convenience)
  - `scope_boundaries: dict` (in_scope/out_of_scope)

- **Tech Prep**
  - `db_schema_notes: dict | None`
  - `api_spec: dict | None`
  - `test_plan: dict | None` (detailed cases)
  - `third_party_plan: dict | None`

- **Development (optional tracking)**
  - `development_plan: dict | None` (milestones, team, etc.)

- **User Guide**
  - `user_guide_sections: list[dict]`

- **Evaluation**
  - `evaluation_report: dict | None`
  - `product_type: str` ("ai" | "non_ai") to determine report sections

#### 3) Approval model usage in SoT

Continue using:

- `approvals_status: dict[str, ApprovalStatus]`

New approval keys to add:

- `brd`
- `api_spec`
- `db_schema`
- `test_plan`
- `third_party_plan`
- `tech_prep` (optional umbrella) — recommended to avoid; prefer per-artifact approvals
- `user_guide` (optional)
- `evaluation` (optional)

---

### Workflow implementation tasks

#### 1) Update entry routing (app/workflow/graph.py)

Update `_route_entry()` mapping to include the new phases.

Recommended pattern:
- Enter the **gate node** for phases that are “waiting approval” so resume does not re-generate unnecessarily.

Example mapping:
- `"brd" → "brd_gate"`
- `"sow" → "sow_gate"`
- `"prd" → "prd_gate"`
- `"tech_prep" → "tech_prep_gate"`
- `"development" → "development"`
- `"user_guide" → "user_guide"`
- `"evaluation" → "evaluation"`

#### 2) Add nodes (new files under app/workflow/nodes/)

Create:
- `app/workflow/nodes/brd.py`
- `app/workflow/nodes/tech_prep.py`
- `app/workflow/nodes/development.py`
- `app/workflow/nodes/user_guide.py`
- `app/workflow/nodes/evaluation.py`

Each node should:
- Deserialize SoT (`ProjectState(**state["sot"])`)
- Run an agent (preferred) OR deterministic logic
- Return updated SoT + no pause signal (gates handle pausing)

#### 3) Add gates

You can implement gates either:
- by extending `app/workflow/nodes/approval_gate.py` (generic `_gate()` already exists)
- or by creating `tech_prep_gate.py` if it needs multi-approval logic

Tech prep gate logic (recommended):
- Pause until ALL required approvals are `approved`:
  - `db_schema`, `api_spec`, `test_plan`, `third_party_plan`
- If any are `rejected`, patch `rejection_feedback` with the specific artifact and route back

---

### Agents to implement (app/agents/)

Add agents mirroring existing patterns (`BaseAgent` → `run()` returns patch dict):

- `BRDAgent`
  - Produces high-level objectives/workflows/scope boundaries
  - Sets `approvals_status["brd"]="pending"`
  - Supports rejection feedback loop (like PRDAgent)

- `TechPrepAgent`
  - Produces structured `api_spec`, `db_schema_notes`, `test_plan`, `third_party_plan`
  - Sets each required approval key to `pending`

- `DevelopmentAgent` (optional)
  - Often this phase may not generate an artifact; it may just set `current_phase`

- `UserGuideAgent`
  - Generates `user_guide_sections` and sets optional approval status

- `EvaluationAgent`
  - Generates `evaluation_report` and sets optional approval status

Registry updates:
- Add these to `app/registry/agents.yaml`
- Ensure `registry/loader.py` picks them up (already does)

---

### Artifact system changes (app/artifacts/)

#### 1) Add templates

Add Jinja templates:
- `app/artifacts/templates/brd.md.j2`
- `app/artifacts/templates/api_spec.md.j2`
- `app/artifacts/templates/db_schema.md.j2`
- `app/artifacts/templates/test_plan.md.j2`
- `app/artifacts/templates/third_party_plan.md.j2`
- `app/artifacts/templates/user_guide.md.j2`
- `app/artifacts/templates/evaluation_report.md.j2`

#### 2) Extend generator

Update `app/artifacts/generator.py`:
- Add `_CONTEXT_BUILDERS` and `_TEMPLATE_FILES` entries for the new types
- Context builder inputs should come from SoT fields added above

#### 3) Generalize rendering trigger

Update `app/services/runs.py:_process_result()`:
- Replace `_ARTIFACT_PHASES={"prd","sow"}` with “render if template exists”
- For phases with multiple artifacts (tech prep), you can:
  - Render multiple artifacts on pause, or
  - Render one bundle artifact, or
  - Render as each sub-artifact becomes pending

Recommended: render **one artifact per approval type** so reviewers see exactly what they approve.

---

### Approval service and API (existing, mostly reusable)

Existing endpoints should remain valid:
- `POST /approvals/{id}/resolve` resumes runs with `{approval.type: decision}`

What changes:
- approval “types” will expand beyond `prd` and `sow`
- `tech_prep_gate` must check multiple approval keys

Optional enhancement:
- Add `GET /runs/{run_id}/approvals` to list all approvals for a run (UI checklist)

---

### UI upgrades (optional but recommended)

Your current UI (already added) is minimal and supports:
- file upload → extracted text
- start/resume runs
- approve/reject a single pending approval

For Option B, recommended UI enhancements:
- Show a **phase timeline** with current phase highlighted
- Show a **checklist** of pending approvals (tech prep will have multiple)
- Add a “Review artifact” panel that loads content for each artifact type before approval

---

### Implementation order (incremental milestones)

This order reduces risk and keeps the system always runnable:

#### Milestone 1 — BRD phase (end-to-end)
- Add `Phase.BRD`
- Add BRD node + BRD gate
- Add `BRDAgent`
- Add `brd.md.j2` template + generator support
- Ensure approval resolve resumes the run

#### Milestone 2 — Tech Prep phase (multi-approval)
- Add `Phase.TECH_PREP`
- Add `TechPrepAgent` + `tech_prep` node
- Add templates for API/DB/Test/3rd parties
- Add `tech_prep_gate` that requires multiple approvals
- Add UI checklist (optional but useful)

#### Milestone 3 — User Guide + Evaluation
- Add `Phase.USER_GUIDE`, `Phase.EVALUATION`
- Add agents + templates + gates (if required)

#### Milestone 4 — Cleanup & deprecations
- Decide whether to keep/remove `commercials` and `market_eval` paths
- Align README/architecture docs with actual graph

---

### Verification checklist (for ChatGPT later)

Ask ChatGPT to verify the repo contains:

- **SoT**
  - New `Phase` values exist in `app/sot/state.py`
  - New SoT fields exist for BRD/TechPrep/UserGuide/Evaluation

- **Workflow**
  - `app/workflow/graph.py` includes new nodes and routing for new phases
  - New node files exist under `app/workflow/nodes/`
  - Gates pause and resume as specified

- **Agents**
  - New agent files exist under `app/agents/`
  - Agents follow BaseAgent patch pattern (return dict of top-level SoT fields)
  - `app/registry/agents.yaml` includes new agents

- **Artifacts**
  - Templates exist under `app/artifacts/templates/`
  - `app/artifacts/generator.py` supports new artifact types
  - `runs._process_result()` renders the right artifacts at pause points

- **Approvals**
  - Approval types include `brd`, `api_spec`, `db_schema`, `test_plan`, `third_party_plan`
  - `tech_prep_gate` blocks until all required approvals are approved

- **UI**
  - UI still loads at `/` and `/ui/`
  - UI can list multiple approvals (if implemented) and approve them

---

### Related docs

- `CHANGES_UI_LAYER_AND_UPLOADS.md` documents the already-added UI + upload endpoints and how to manually test them.

