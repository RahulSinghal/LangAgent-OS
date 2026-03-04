"""Run service — Phase 1C / 1E / Phase 2.

Manages run lifecycle: create, status updates, start, pause, resume.

Phase 1C: create_run, get_run, update_run_status, list_runs (basic CRUD).
Phase 1E: start_run, resume_run (full run engine with LangGraph invocation).
Phase 2:  market_eval gate support (approval without artifact rendering).
"""

from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.db.models import Run


# ── Basic CRUD ────────────────────────────────────────────────────────────────

def create_run(
    db: Session,
    project_id: int,
    session_id: int | None = None,
    status: str = "pending",
) -> Run:
    """Create a new Run row and return it."""
    run = Run(project_id=project_id, session_id=session_id, status=status)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, run_id: int) -> Run | None:
    return db.get(Run, run_id)


def update_run_status(
    db: Session,
    run_id: int,
    status: str,
    current_node: str | None = None,
) -> Run | None:
    run = db.get(Run, run_id)
    if run is None:
        return None
    run.status = status
    if current_node is not None:
        run.current_node = current_node
    db.commit()
    db.refresh(run)
    return run


def list_runs(db: Session, project_id: int) -> list[Run]:
    return (
        db.query(Run)
        .filter(Run.project_id == project_id)
        .order_by(Run.created_at.desc())
        .all()
    )


# ── Run engine helpers ────────────────────────────────────────────────────────

def _process_result(db: Session, run_id: int, result: dict) -> Run:
    """Save final snapshot, render artifacts, create approval records, update run status."""
    from app.services.snapshots import save_snapshot
    from app.sot.state import ProjectState

    pause_reason = result.get("pause_reason")
    final_sot = ProjectState(**result["sot"])
    phase = final_sot.current_phase.value
    bot_response = result.get("bot_response")

    if pause_reason == "waiting_approval":
        # Render artifacts (for approval types that have templates) and ensure Approval records.
        run = db.get(Run, run_id)
        if run is not None:
            from app.services.approvals import ensure_pending_approval

            pending_types = [
                k for k, v in final_sot.approvals_status.items()
                if v.value == "pending"
            ]

            # Ensure a DB approval exists for every pending approval type
            for t in pending_types:
                ensure_pending_approval(
                    db,
                    project_id=run.project_id,
                    run_id=run_id,
                    approval_type=t,
                )

            # Render any missing artifacts that have templates.
            from app.artifacts.generator import render_artifact
            for t in pending_types:
                if t not in final_sot.artifacts_index:
                    try:
                        _, final_sot = render_artifact(
                            artifact_type=t,
                            state=final_sot,
                            db=db,
                            run_id=run_id,
                        )
                    except ValueError:
                        # No template/context builder for this approval type (e.g., market_eval)
                        continue

    # ── Persist final SoT snapshot ────────────────────────────────────────────
    save_snapshot(db, run_id=run_id, state=final_sot)

    # ── Update run status ─────────────────────────────────────────────────────
    if pause_reason == "waiting_user":
        status, node = "waiting_user", "discovery"
    elif pause_reason == "waiting_approval":
        status, node = "waiting_approval", f"{phase}_gate"
    elif phase == "completed":
        status, node = "completed", "end"
    else:
        status, node = "running", phase

    updated = update_run_status(db, run_id, status=status, current_node=node)

    # Persist assistant/system response into session history for later replay
    if bot_response:
        try:
            run = db.get(Run, run_id)
            if run and run.session_id:
                from app.services.sessions import add_message
                add_message(db, session_id=run.session_id, role="assistant", content=str(bot_response))
        except Exception:
            pass

    return updated


# ── Run engine ────────────────────────────────────────────────────────────────

def start_run(
    db: Session,
    project_id: int,
    session_id: int | None = None,
    user_message: str | None = None,
    document_content: str | None = None,
    document_filename: str | None = None,
) -> Run:
    """Create a run, build the initial SoT, and invoke the LangGraph workflow.

    The graph runs synchronously until it pauses (waiting_user /
    waiting_approval) or completes.  The final SoT snapshot is persisted and
    the run status is updated before returning.

    Args:
        db:                Active DB session.
        project_id:        Project this run belongs to.
        session_id:        Optional session for message context.
        user_message:      Initial user prompt (e.g. "Build me a CRM").
        document_content:  Optional raw text of a document shared by the client.
                           When provided, structured data (requirements, assumptions,
                           open questions, risks) is extracted and used to pre-populate
                           the initial ProjectState, shortening the discovery phase.
        document_filename: Original filename of the uploaded document (used in the
                           auto-generated summary message).

    Returns:
        The updated Run ORM object.
    """
    from app.sot.state import create_initial_state
    from app.workflow.graph import WorkflowState, get_workflow
    from app.core.metrics import RunMetricCollector, reset_run_collector, set_run_collector

    # Create the run record
    run = create_run(db, project_id=project_id, session_id=session_id, status="running")

    # ── Document ingestion (optional) ─────────────────────────────────────────
    initial_patch: dict = {}
    combined_message: str | None = user_message

    if document_content:
        from app.services.document_ingestion import ingest_document  # lazy import
        ingestion = ingest_document(document_content, filename=document_filename or "")
        initial_patch = ingestion.get("sot_patch", {})
        doc_type = ingestion.get("document_type", "unknown")
        doc_summary = ingestion.get("summary_message", "")

        # document_type is set in initial_patch (from sot_patch) so discovery
        # knows which phase to fast-track to after gap Q&A completes.
        # No manual current_phase override — the graph handles routing generically.

        if doc_summary:
            # User note (if any) is appended so it takes semantic precedence.
            combined_message = (
                f"{doc_summary}\n\nUser note: {user_message}" if user_message else doc_summary
            )

    # Persist incoming message to session history (if a session is present)
    if session_id and combined_message:
        try:
            from app.services.sessions import add_message
            add_message(db, session_id=session_id, role="user", content=combined_message)
        except Exception:
            pass

    # Build initial SoT, applying document patch when present
    initial_sot = create_initial_state(
        project_id=project_id,
        run_id=run.id,
        session_id=session_id,
        user_message=combined_message,
        initial_patch=initial_patch if initial_patch else None,
    )

    wf_state: WorkflowState = {
        "sot": initial_sot.model_dump_jsonb(),
        "run_id": run.id,
        "pause_reason": None,
        "bot_response": None,
        "approval_id": None,
    }

    collector = RunMetricCollector()
    token = set_run_collector(collector)
    started = time.perf_counter()
    try:
        result = get_workflow().invoke(wf_state)
    finally:
        runtime_ms = int((time.perf_counter() - started) * 1000)
        reset_run_collector(token)

    _process_result(db, run.id, result)
    try:
        from app.services.provenance import record_run_metrics

        totals = collector.totals()
        node_metrics = {
            "runtime_ms": runtime_ms,
            "llm": totals,
        }
        record_run_metrics(
            db,
            run_id=run.id,
            project_id=project_id,
            total_tokens=int(totals.get("total_tokens") or 0),
            total_cost_usd=float(totals.get("total_cost_usd") or 0.0),
            total_latency_ms=int(runtime_ms),
            node_metrics=node_metrics,
        )
    except Exception:
        pass
    db.refresh(run)
    return run


def resume_run(
    db: Session,
    run_id: int,
    user_message: str | None = None,
    approval_patch: dict | None = None,
    document_content: str | None = None,
    document_filename: str | None = None,
) -> Run:
    """Resume a paused run.

    Loads the latest SoT snapshot, patches it with the user's message or
    approval decision, then re-invokes the graph.  The conditional entry
    point routes the graph to the correct node based on current_phase.

    When a document is shared mid-conversation (document_content provided),
    it is ingested, extracted content is added to the SoT, and document_type
    is recorded.  The discovery node then runs gap Q&A as needed; on
    completion it advances current_phase and the graph fast-tracks:
      - prd              → prd_gate  (uploaded doc IS the PRD)
      - sow              → sow_gate  (uploaded doc IS the SOW)
      - market_eval      → market_eval_gate
      - commercials      → commercials_gate
      - technical_design → coding_plan (generates milestone plan from the design)
      - brd / unknown    → normal market_eval flow

    Args:
        db:                Active DB session.
        run_id:            Run to resume.
        user_message:      User's answer to the last discovery question.
        approval_patch:    e.g. {"prd": "approved"} — injected by approval service.
        document_content:  Raw text of a document shared mid-conversation.
        document_filename: Original filename of the uploaded document.

    Returns:
        The updated Run ORM object.

    Raises:
        ValueError: Run not found or no snapshot exists.
    """
    from app.sot.patch import apply_patch
    from app.sot.state import ProjectState
    from app.services.snapshots import load_latest_snapshot
    from app.workflow.graph import WorkflowState, get_workflow
    from app.core.metrics import RunMetricCollector, reset_run_collector, set_run_collector

    run = get_run(db, run_id)
    if run is None:
        raise ValueError(f"Run {run_id} not found")

    sot = load_latest_snapshot(db, run_id)
    if sot is None:
        raise ValueError(f"No snapshot found for run {run_id}")

    # ── Mid-conversation document ingestion (optional) ────────────────────────
    combined_message: str | None = user_message
    if document_content:
        from app.services.document_ingestion import ingest_document
        ingestion = ingest_document(document_content, filename=document_filename or "")
        doc_sot_patch = ingestion.get("sot_patch", {})
        doc_type = ingestion.get("document_type", "unknown")
        doc_summary = ingestion.get("summary_message", "")

        # Merge extracted data into SoT immediately
        if doc_sot_patch:
            sot = apply_patch(sot, doc_sot_patch)

        # Build combined message so the user note + doc summary are both captured
        if doc_summary:
            combined_message = (
                f"{doc_summary}\n\nUser note: {user_message}" if user_message else doc_summary
            )

        # document_type is already set in sot via sot_patch.
        # Phase routing is handled generically by the discovery node and
        # _route_after_discovery: after gap Q&A completes, the graph fast-tracks
        # to whichever gate/node corresponds to the detected document type.

    # Apply incoming context
    patch: dict = {}
    if combined_message is not None:
        patch["last_user_message"] = combined_message
        # Save to conversation history when resuming from waiting_user
        if run.session_id and combined_message:
            try:
                from app.services.sessions import add_message
                add_message(db, session_id=run.session_id, role="user", content=combined_message)
            except Exception:
                pass
    if approval_patch:
        current = {k: v.value for k, v in sot.approvals_status.items()}
        current.update(approval_patch)
        patch["approvals_status"] = current
    if patch:
        sot = apply_patch(sot, patch)

    update_run_status(db, run_id, status="running")

    wf_state: WorkflowState = {
        "sot": sot.model_dump_jsonb(),
        "run_id": run_id,
        "pause_reason": None,
        "bot_response": None,
        "approval_id": None,
    }

    collector = RunMetricCollector()
    token = set_run_collector(collector)
    started = time.perf_counter()
    try:
        result = get_workflow().invoke(wf_state)
    finally:
        runtime_ms = int((time.perf_counter() - started) * 1000)
        reset_run_collector(token)

    _process_result(db, run_id, result)
    try:
        from app.services.provenance import record_run_metrics

        totals = collector.totals()
        node_metrics = {
            "runtime_ms": runtime_ms,
            "llm": totals,
        }
        record_run_metrics(
            db,
            run_id=run_id,
            project_id=run.project_id,
            total_tokens=int(totals.get("total_tokens") or 0),
            total_cost_usd=float(totals.get("total_cost_usd") or 0.0),
            total_latency_ms=int(runtime_ms),
            node_metrics=node_metrics,
        )
    except Exception:
        pass
    db.refresh(run)
    return run
