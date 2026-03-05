"""Run service — Phase 1C / 1E / Phase 2.

Manages run lifecycle: create, status updates, start, pause, resume.

Phase 1C: create_run, get_run, update_run_status, list_runs (basic CRUD).
Phase 1E: start_run, resume_run (full run engine with LangGraph invocation).
Phase 2:  market_eval gate support (approval without artifact rendering).
"""

from __future__ import annotations

import logging
import re
import time

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Run

_log = logging.getLogger(__name__)

# Control characters to strip from user input (keeps \t \n \r).
_CTRL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_user_input(text: str | None) -> str | None:
    """Strip control characters and enforce a maximum length.

    Protects against prompt injection via malicious user messages fed into
    LLM system prompts.  Legitimate punctuation and Unicode are preserved.
    """
    if text is None:
        return None
    # Remove ASCII control characters (non-printable, non-whitespace)
    text = _CTRL_CHAR_RE.sub("", text)
    # Hard cap to prevent runaway context window bloat
    max_len = settings.MAX_USER_MESSAGE_LENGTH
    if len(text) > max_len:
        _log.warning("User message truncated from %d to %d chars", len(text), max_len)
        text = text[:max_len]
    return text


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
    """Save final snapshot, render artifacts, create approval records, update run status.

    All DB writes are performed inside a single nested transaction (savepoint)
    so that a partial failure rolls back all writes for this result, leaving
    the run in the last-good-snapshot state rather than a partial one.
    """
    from app.services.snapshots import save_snapshot
    from app.sot.state import ProjectState

    pause_reason = result.get("pause_reason")
    final_sot = ProjectState(**result["sot"])
    phase = final_sot.current_phase.value
    bot_response = result.get("bot_response")

    try:
        with db.begin_nested():  # savepoint — all writes here are atomic
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
                                # No template/context builder for this approval type
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

    except Exception as exc:
        _log.error("_process_result failed for run %d: %s", run_id, exc, exc_info=True)
        raise

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

    # Sanitize user input before it touches the SoT or LLM prompts.
    user_message = _sanitize_user_input(user_message)

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

        if doc_summary:
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
    except Exception as exc:
        runtime_ms = int((time.perf_counter() - started) * 1000)
        reset_run_collector(token)
        _log.error("Workflow invocation failed for run %d: %s", run.id, exc, exc_info=True)
        update_run_status(db, run.id, status="error")
        raise
    finally:
        runtime_ms = int((time.perf_counter() - started) * 1000)
        reset_run_collector(token)

    try:
        _process_result(db, run.id, result)
    except Exception as exc:
        _log.error("_process_result failed for run %d: %s", run.id, exc, exc_info=True)
        update_run_status(db, run.id, status="error")
        raise

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

    A database row-level lock (SELECT FOR UPDATE) is acquired on the run row
    before checking its status, preventing two concurrent callers from both
    invoking the workflow for the same run simultaneously.

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
        ValueError: Run not found, already running, or no snapshot exists.
    """
    from app.sot.patch import apply_patch
    from app.sot.state import ProjectState
    from app.services.snapshots import load_latest_snapshot
    from app.workflow.graph import WorkflowState, get_workflow
    from app.core.metrics import RunMetricCollector, reset_run_collector, set_run_collector

    # Sanitize user input before it touches the SoT or LLM prompts.
    user_message = _sanitize_user_input(user_message)

    # ── Concurrent-access lock ────────────────────────────────────────────────
    # Acquire a row-level lock on the Run row so that only one caller can
    # transition it from a paused state to "running" at a time.  The lock is
    # released when we commit the status update below, which is atomic with
    # the status write, so a competing caller will see status="running" when
    # it acquires the lock and raise immediately.
    run = db.query(Run).with_for_update().filter(Run.id == run_id).first()
    if run is None:
        raise ValueError(f"Run {run_id} not found")
    if run.status == "running":
        raise ValueError(
            f"Run {run_id} is already being processed. "
            "Wait for the current invocation to complete before resuming."
        )

    sot = load_latest_snapshot(db, run_id)
    if sot is None:
        raise ValueError(f"No snapshot found for run {run_id}")

    # ── Mid-conversation document ingestion (optional) ────────────────────────
    combined_message: str | None = user_message
    if document_content:
        from app.services.document_ingestion import ingest_document
        ingestion = ingest_document(document_content, filename=document_filename or "")
        doc_sot_patch = ingestion.get("sot_patch", {})
        doc_summary = ingestion.get("summary_message", "")

        # Merge extracted data into SoT immediately
        if doc_sot_patch:
            sot = apply_patch(sot, doc_sot_patch)

        if doc_summary:
            combined_message = (
                f"{doc_summary}\n\nUser note: {user_message}" if user_message else doc_summary
            )

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

    # Commit "running" status now — this also releases the row-level lock so
    # other requests can see the updated status without blocking.
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
    except Exception as exc:
        runtime_ms = int((time.perf_counter() - started) * 1000)
        reset_run_collector(token)
        _log.error("Workflow invocation failed for run %d: %s", run_id, exc, exc_info=True)
        update_run_status(db, run_id, status="error")
        raise
    finally:
        runtime_ms = int((time.perf_counter() - started) * 1000)
        reset_run_collector(token)

    try:
        _process_result(db, run_id, result)
    except Exception as exc:
        _log.error("_process_result failed for run %d: %s", run_id, exc, exc_info=True)
        update_run_status(db, run_id, status="error")
        raise

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
