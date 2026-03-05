"""Source of Truth (SoT) — ProjectState Pydantic model.

Design principles:
- Every agent reads from this model.
- Agents never write directly; they return patches validated by apply_patch().
- A JSONB snapshot is saved to the DB after every node execution.
- Fields marked (Phase 2) or (Phase 3) are stubbed now, filled in later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class Phase(str, Enum):
    INIT = "init"
    DISCOVERY = "discovery"
    MARKET_EVAL = "market_eval"   # Phase 2: buy/build/hybrid analysis
    PRD = "prd"
    COMMERCIALS = "commercials"
    SOW = "sow"
    NEGOTIATION = "negotiation"
    USER_GUIDE = "user_guide"     # Optional: user guide generation gate (after SOW)
    CODING = "coding"             # Step 4: milestone plan awaiting tech lead approval
    MILESTONE = "milestone"       # Step 4: per-milestone code generation + review loop
    READINESS = "readiness"
    COMPLETED = "completed"


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# ── Sub-models ────────────────────────────────────────────────────────────────

class RequirementItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    category: str  # "functional" | "non_functional" | "integration"
    text: str
    priority: Priority = Priority.MEDIUM
    source: str = "discovery"  # "discovery" | "brd_upload" | "user"
    accepted: bool = True


class AssumptionItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    text: str
    confirmed: bool = False


class DecisionItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    decision: str
    rationale: str = ""
    made_by: str = ""  # agent name or "user"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RiskItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    description: str
    likelihood: str = "medium"  # "low" | "medium" | "high"
    impact: str = "medium"      # "low" | "medium" | "high"
    mitigation: str = ""


class QuestionItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    question: str
    category: str = "general"
    answered: bool = False
    answer: str | None = None


class ArtifactRef(BaseModel):
    """Pointer from state into the artifacts table."""
    version: int
    artifact_id: int  # FK → artifacts.id


# ── Phase 2 models ────────────────────────────────────────────────────────────

class MarketOption(BaseModel):
    """Scored option in a buy/build/hybrid analysis."""
    name: str  # "build" | "buy" | "hybrid"
    scores: dict[str, float] = Field(default_factory=dict)
    # e.g. {"ip_ownership": 8.5, "time_to_market": 3.0, ...}
    total_score: float = 0.0
    vendors: list[str] = Field(default_factory=list)
    rationale: str = ""


class MarketEval(BaseModel):
    """Phase 2: Buy/build/hybrid analysis results from MarketScanAgent."""
    options: list[MarketOption] = Field(default_factory=list)
    recommendation: str | None = None  # "buy" | "build" | "hybrid"
    decision: str | None = None        # confirmed after gate
    confidence: float | None = None    # 0.0 – 1.0
    vendors_evaluated: list[str] = Field(default_factory=list)
    deep_mode: str = "suggest"         # "off" | "suggest" | "auto"


# ── Phase 2: DeepWork output models ───────────────────────────────────────────

class DeepWorkFinding(BaseModel):
    """A single research finding produced by DeepWorkAgent."""
    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    category: str  # "market" | "technical" | "commercial" | "general"
    finding: str
    source: str = "analysis"
    confidence: float = 0.8  # 0.0 – 1.0


class DeepWorkDecision(BaseModel):
    """A recommended decision from DeepWorkAgent."""
    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    recommendation: str
    rationale: str
    confidence: float = 0.8  # 0.0 – 1.0


class DeepWorkOutput(BaseModel):
    """Structured output from DeepWorkAgent — every run must produce this.

    The sot_patch field contains the validated dict to be applied via apply_patch().
    """
    findings: list[DeepWorkFinding] = Field(default_factory=list)
    decisions_recommended: list[DeepWorkDecision] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    sot_patch: dict[str, Any] = Field(default_factory=dict)
    references: list[str] = Field(default_factory=list)


# ── Project-type and tech-stack models ────────────────────────────────────────

class TechStackSpec(BaseModel):
    """Typed tech-stack selections — populated by discovery or TechStackAgent."""
    language: str | None = None               # "python" | "typescript" | "go" | ...
    backend_framework: str | None = None      # "fastapi" | "django" | "express" | ...
    frontend_framework: str | None = None     # "react" | "vue" | "next" | None
    database: str | None = None               # "postgresql" | "mysql" | "mongodb" | ...
    vector_store: str | None = None           # RAG: "pgvector" | "pinecone" | "chroma"
    llm_provider: str | None = None           # RAG/voice: "openai" | "anthropic" | "azure"
    embedding_model: str | None = None        # RAG: "text-embedding-3-small" | ...
    auth_method: str | None = None            # "jwt" | "oauth2" | "session" | "api_key"
    telephony: str | None = None              # voice: "twilio" | "vonage" | None
    tts_provider: str | None = None           # voice: "elevenlabs" | "azure" | "google"
    nlu_provider: str | None = None           # voice: "dialogflow" | "rasa" | "custom"
    test_framework: str | None = None         # "pytest" | "jest" | "vitest" | ...
    package_manager: str | None = None        # "pip" | "poetry" | "npm" | "pnpm"


class CodeFile(BaseModel):
    """A single generated source file within a milestone."""
    path: str           # relative path: "src/rag/retriever.py"
    language: str       # "python" | "typescript" | "yaml" | ...
    content: str        # full file content
    description: str = ""


class ArchitectureSpec(BaseModel):
    """Architecture blueprint generated before code — file tree + contracts."""
    style: str = "layered"                             # "layered" | "microservices" | "monorepo" | ...
    file_tree: list[str] = Field(default_factory=list) # relative paths of ALL project files
    api_contracts: list[dict] = Field(default_factory=list)    # OpenAPI-style endpoint defs
    database_schema: list[dict] = Field(default_factory=list)  # table/collection defs
    milestone_file_map: dict[str, list[str]] = Field(default_factory=dict)
    # Maps milestone_id → list[relative_file_path] for targeted code gen


# ── Step 4: Milestone-based code generation models ────────────────────────────

# Default eval sets per project type
_DEFAULT_EVALS: dict[str, list[str]] = {
    "rag_pipeline": [
        "unit: retrieval accuracy",
        "unit: embedding pipeline",
        "integration: vector store",
        "e2e: query → answer",
    ],
    "web_app": [
        "unit: component rendering",
        "integration: API endpoints",
        "e2e: user flows",
        "security: auth headers",
    ],
    "crm": [
        "unit: business logic",
        "integration: org hierarchy",
        "e2e: CRUD workflows",
        "security: role permissions",
    ],
    "voice_chatbot": [
        "unit: NLU intent detection",
        "integration: telephony webhook",
        "e2e: dialogue flow",
        "unit: TTS output quality",
    ],
    "generic": [
        "unit: core logic",
        "integration: API",
        "e2e: main flow",
    ],
}


class MilestoneItem(BaseModel):
    """A single coding milestone within the tech-lead-approved plan."""
    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    name: str                                             # e.g. "Auth & User Management"
    description: str                                      # what this milestone covers
    stories: list[str] = Field(default_factory=list)      # backlog story refs in scope
    status: str = "pending"                               # pending|in_progress|approved|rejected
    code_artifact_path: str | None = None                 # base path written by MilestoneCodeAgent
    code_files: list[CodeFile] = Field(default_factory=list)  # structured file manifest
    expected_evals: list[str] = Field(default_factory=list)
    review_feedback: str | None = None                    # CodeReviewAgent findings
    # e.g. ["unit: auth service", "e2e: login flow", "integration: DB session"]


# ── Phase 3 models ────────────────────────────────────────────────────────────

class DeploymentPrefs(BaseModel):
    """Phase 3: Cloud/infra preferences collected during readiness."""
    cloud_provider: str | None = None  # "aws" | "azure" | "gcp" | "on_prem"
    region: str | None = None
    compliance_requirements: list[str] = Field(default_factory=list)
    # Deployment topology
    container_platform: str | None = None  # "docker" | "kubernetes" | "ecs" | None
    cicd_tool: str | None = None           # "github_actions" | "gitlab_ci" | "jenkins" | None
    monitoring_tool: str | None = None     # "datadog" | "cloudwatch" | "grafana" | None


class ReadinessCheckItem(BaseModel):
    """A single item in the deployment readiness checklist."""
    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    category: str   # "infrastructure" | "security" | "cicd" | "compliance" | "handover"
    item: str       # what needs to be confirmed / set up
    owner: str = "client"  # who is responsible: "client" | "vendor"
    status: str = "pending"  # "pending" | "done" | "n/a"


# ── ProjectState (the SoT) ────────────────────────────────────────────────────

class ProjectState(BaseModel):
    """Central Source of Truth threaded through every LangGraph node.

    Agents NEVER mutate this directly — they return a patch dict that is
    validated and applied by apply_patch().  A JSONB snapshot is written
    to the DB after every node execution so runs can pause and resume.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    project_id: int
    run_id: int | None = None
    session_id: int | None = None

    # ── Workflow control ──────────────────────────────────────────────────────
    current_phase: Phase = Phase.INIT
    last_user_message: str | None = None

    # ── Content ───────────────────────────────────────────────────────────────
    requirements: list[RequirementItem] = Field(default_factory=list)
    assumptions: list[AssumptionItem] = Field(default_factory=list)
    decisions: list[DecisionItem] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)
    open_questions: list[QuestionItem] = Field(default_factory=list)

    # ── Artifact tracking: {"prd": ArtifactRef, "sow": ArtifactRef, ...} ─────
    artifacts_index: dict[str, ArtifactRef] = Field(default_factory=dict)

    # ── Approval gates: {"prd": ApprovalStatus, ...} ─────────────────────────
    approvals_status: dict[str, ApprovalStatus] = Field(default_factory=dict)

    # ── Phase 2: Market evaluation ────────────────────────────────────────────
    market_eval: MarketEval = Field(default_factory=MarketEval)

    # ── Phase 3: Deployment / Readiness ──────────────────────────────────────
    deployment_prefs: DeploymentPrefs = Field(default_factory=DeploymentPrefs)
    # Hosting preference — drives server-details approval routing.
    # "client" = client hosts on their own server/infrastructure
    # "vendor" = deploy on our (delivery) infrastructure
    hosting_preference: str = "client"
    # Generated by ReadinessAgent; approved at readiness_gate before end.
    readiness_checklist: list[ReadinessCheckItem] = Field(default_factory=list)

    # ── Phase 4: Document upload metadata ─────────────────────────────────────
    document_type: str | None = None        # "brd" | "prd" | "sow" | "unknown"
    domain: str = "generic"                 # domain for LLM prompt specialisation

    # ── Project type and architecture ─────────────────────────────────────────
    # project_type drives agent routing, milestone ordering, and eval defaults.
    # Values: "generic" | "rag_pipeline" | "web_app" | "crm" | "voice_chatbot"
    project_type: str = "generic"
    tech_stack: TechStackSpec | None = None
    architecture_spec: ArchitectureSpec | None = None

    # ── User guide ────────────────────────────────────────────────────────────
    # Set to True/False after the user guide gate asks the user (after SOW approval).
    # None = not yet asked.
    user_guide_requested: bool | None = None
    # LLM-generated markdown content for the project user guide (if requested).
    user_guide_content: str | None = None

    # ── Phase 4: Coverage-score driven discovery ───────────────────────────────
    coverage_scores: dict[str, float] = Field(default_factory=lambda: {
        "business_context": 0.0,
        "users_and_scale": 0.0,
        "functional_requirements": 0.0,
        "non_functional_requirements": 0.0,
        "technical_architecture": 0.0,
        "technology_stack": 0.0,
        "cloud_infrastructure": 0.0,
        "security_architecture": 0.0,
        "data_architecture": 0.0,
        "integrations": 0.0,
        "timeline_and_budget": 0.0,
    })
    gathered_requirements: dict[str, Any] = Field(default_factory=dict)
    followup_questions: list[str] = Field(default_factory=list)  # BRD gap Qs
    discovery_complete: bool = False

    # ── Phase 4: Artifact content ──────────────────────────────────────────────
    scope: dict[str, Any] | None = None             # generated project scope
    commercial_model: str | None = None              # commercials narrative
    milestones: list[dict[str, Any]] = Field(default_factory=list)
    sow_sections: list[dict[str, Any]] = Field(default_factory=list)

    # ── Phase 4: Rejection feedback for re-generation cycles ──────────────────
    # e.g. {"artifact_type": "prd", "comment": "Missing non-functional reqs"}
    rejection_feedback: dict[str, Any] | None = None

    # ── Step 4: Milestone-based code generation ────────────────────────────────
    coding_plan: list[MilestoneItem] = Field(default_factory=list)
    current_milestone_index: int = 0

    # ── Cross-project memory (read-only for agents) ────────────────────────────
    # Populated by intake_normalize from ComponentStore; agents may reference
    # this in their prompts to leverage institutional knowledge from past projects.
    past_context: list[dict[str, Any]] = Field(default_factory=list)

    def model_dump_jsonb(self) -> dict[str, Any]:
        """Serialize to a JSONB-safe dict (all values JSON-serialisable)."""
        return self.model_dump(mode="json")


def detect_project_type(text: str) -> str:
    """Heuristic: infer project_type from the user's initial message.

    Returns one of: "rag_pipeline" | "web_app" | "crm" | "voice_chatbot" | "generic".
    """
    t = text.lower()
    if any(k in t for k in ("rag", "retrieval", "vector", "embedding", "knowledge base", "semantic search")):
        return "rag_pipeline"
    if any(k in t for k in ("voice", "chatbot", "ivr", "telephony", "twilio", "call centre", "call center", "speech")):
        return "voice_chatbot"
    if any(k in t for k in ("crm", "customer relationship", "lead management", "sales pipeline", "org hierarchy")):
        return "crm"
    if any(k in t for k in ("website", "web app", "web application", "landing page", "frontend", "react", "next.js", "nuxt")):
        return "web_app"
    return "generic"


def create_initial_state(
    project_id: int,
    run_id: int | None = None,
    session_id: int | None = None,
    user_message: str | None = None,
    initial_patch: dict | None = None,
) -> ProjectState:
    """Factory: create a fresh ProjectState at the start of a run.

    Args:
        project_id:    Project this state belongs to.
        run_id:        Run that owns this state (set after run row creation).
        session_id:    Optional session for message threading.
        user_message:  Initial user prompt or document summary.
        initial_patch: Optional dict to overlay on the fresh state (e.g.,
                       requirements/assumptions extracted from an uploaded
                       document).  Applied via apply_patch — unknown keys raise
                       ValueError.  List fields are REPLACED, not appended.

    Returns:
        A fully initialised ProjectState, optionally pre-populated.
    """
    state = ProjectState(
        project_id=project_id,
        run_id=run_id,
        session_id=session_id,
        last_user_message=user_message,
    )
    if initial_patch:
        from app.sot.patch import apply_patch  # lazy — patch.py imports state.py
        state = apply_patch(state, initial_patch)
    return state
