"""GitHub webhook receiver.

Receives inbound GitHub webhook events, verifies the HMAC-SHA256 signature,
and processes relevant event types to provide CI feedback back into the system.

Supported events:
  - check_run   (completed) — updates the deployment readiness checklist in
                              the latest project snapshot when a CI job finishes.
  - push        (any)       — logged to audit_logs for traceability.

Configuration:
  GITHUB_WEBHOOK_SECRET — set this to the same secret configured in the GitHub
                          repository webhook settings (under Settings → Webhooks).
                          Leave empty to disable signature verification (dev only).

Endpoint:
  POST /github/webhook
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core.config import settings

router = APIRouter(tags=["github"])
_log = logging.getLogger(__name__)


# ── HMAC verification ─────────────────────────────────────────────────────────

def _verify_signature(payload: bytes, signature_header: str | None) -> None:
    """Verify the GitHub webhook HMAC-SHA256 signature.

    Raises HTTPException 401 when verification fails.  Skipped when
    GITHUB_WEBHOOK_SECRET is empty (useful for local development only).
    """
    secret = settings.GITHUB_WEBHOOK_SECRET
    if not secret:
        _log.warning("GitHub webhook signature verification is DISABLED (no secret configured)")
        return

    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed X-Hub-Signature-256 header.",
        )

    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="GitHub webhook signature verification failed.",
        )


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post(
    "/github/webhook",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Receive GitHub webhook events",
    include_in_schema=False,  # Internal endpoint; hide from Swagger
)
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> None:
    """Process an inbound GitHub webhook event.

    Verifies the HMAC-SHA256 signature and dispatches to the appropriate
    handler based on the event type.  Always returns 204 to GitHub regardless
    of processing outcome so GitHub does not retry unnecessarily.
    """
    payload_bytes = await request.body()
    _verify_signature(payload_bytes, x_hub_signature_256)

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        _log.warning("GitHub webhook received non-JSON payload; ignoring.")
        return

    event = (x_github_event or "").lower()
    _log.info("github.webhook.received", extra={"event": event})

    if event == "check_run":
        _handle_check_run(payload)
    elif event == "push":
        _handle_push(payload)
    else:
        _log.debug("github.webhook.ignored", extra={"event": event})


# ── Event handlers ────────────────────────────────────────────────────────────

def _handle_check_run(payload: dict) -> None:
    """Process a check_run event.

    When a CI check completes, find the project whose GitHub repo URL matches
    the repository in the payload, then update the deployment readiness
    checklist to reflect the CI outcome.
    """
    action = payload.get("action", "")
    if action != "completed":
        return  # Only care about completed checks

    check_run = payload.get("check_run", {})
    conclusion = check_run.get("conclusion", "")  # "success" | "failure" | "neutral" | ...
    check_name = check_run.get("name", "CI")
    repo_data = payload.get("repository", {})
    repo_html_url = repo_data.get("html_url", "")

    _log.info(
        "github.check_run.completed",
        extra={"repo": repo_html_url, "check": check_name, "conclusion": conclusion},
    )

    if not repo_html_url:
        return

    # Find projects that published to this repo URL and update their
    # readiness checklist.
    try:
        _update_ci_readiness(repo_html_url, check_name, conclusion)
    except Exception:
        _log.exception("github.check_run.update_failed", extra={"repo": repo_html_url})


def _handle_push(payload: dict) -> None:
    """Log a push event to the audit trail."""
    repo_data = payload.get("repository", {})
    repo_name = repo_data.get("full_name", "unknown")
    pusher = payload.get("pusher", {}).get("name", "unknown")
    ref = payload.get("ref", "")

    _log.info(
        "github.push",
        extra={"repo": repo_name, "ref": ref, "pusher": pusher},
    )

    try:
        _write_audit_log(
            event_type="github.push",
            detail={"repo": repo_name, "ref": ref, "pusher": pusher},
        )
    except Exception:
        _log.exception("github.push.audit_failed")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _update_ci_readiness(repo_url: str, check_name: str, conclusion: str) -> None:
    """Find project(s) by GitHub repo URL and update their CI readiness item.

    Looks up the most recent `github_repo` artifact with a matching file_path
    (which stores the repo URL), loads the corresponding run's latest snapshot,
    and updates the readiness_checklist item for CI/CD.
    """
    from app.db.session import SessionLocal
    from app.db.models import Artifact, Snapshot

    ci_status = "done" if conclusion == "success" else "pending"
    ci_item_key = "cicd"

    with SessionLocal() as db:
        # Find artifact rows that store this repo URL
        matching = (
            db.query(Artifact)
            .filter(
                Artifact.type == "github_repo",
                Artifact.file_path == repo_url,
            )
            .all()
        )

        if not matching:
            _log.debug("github.check_run.no_matching_project", extra={"repo": repo_url})
            return

        for artifact in matching:
            project_id = artifact.project_id
            _write_audit_log(
                event_type="github.ci.feedback",
                project_id=project_id,
                detail={
                    "repo": repo_url,
                    "check": check_name,
                    "conclusion": conclusion,
                    "ci_status": ci_status,
                },
                db=db,
            )

            # Load latest snapshot for this project and update readiness checklist
            snapshot = (
                db.query(Snapshot)
                .filter(Snapshot.project_id == project_id)
                .order_by(Snapshot.id.desc())
                .first()
            )
            if snapshot is None or not snapshot.state_jsonb:
                continue

            try:
                from app.sot.state import ProjectState
                from app.sot.patch import apply_patch
                from app.services.snapshots import save_snapshot

                sot_data = snapshot.state_jsonb
                if isinstance(sot_data, str):
                    import json as _json
                    sot_data = _json.loads(sot_data)

                sot = ProjectState(**sot_data)

                # Find or create a CI readiness checklist item
                checklist = [item.model_dump() for item in sot.readiness_checklist]
                ci_items = [i for i in checklist if i.get("category") == ci_item_key]

                if ci_items:
                    for item in ci_items:
                        item["status"] = ci_status
                        item["item"] = (
                            f"CI: {check_name} — {conclusion}"
                        )
                else:
                    checklist.append({
                        "id": f"gh_ci_{project_id}",
                        "category": ci_item_key,
                        "item": f"CI: {check_name} — {conclusion}",
                        "owner": "vendor",
                        "status": ci_status,
                    })

                # Save an updated snapshot with the new checklist
                # We use the latest run_id from the snapshot
                run_id = sot.run_id
                if run_id is not None:
                    new_sot = apply_patch(sot, {"readiness_checklist": checklist})
                    save_snapshot(db, run_id=run_id, state=new_sot)
                    _log.info(
                        "github.ci.readiness_updated",
                        extra={
                            "project_id": project_id,
                            "ci_status": ci_status,
                        },
                    )
            except Exception:
                _log.exception("github.ci.snapshot_update_failed", extra={"project_id": project_id})


def _write_audit_log(
    event_type: str,
    detail: dict,
    project_id: int | None = None,
    db=None,
) -> None:
    """Write an event to audit_logs.  Creates its own DB session when db=None."""
    from app.db.models import AuditLog

    def _write(session) -> None:
        log = AuditLog(
            actor="github_webhook",
            event_type=event_type,
            project_id=project_id,
            detail_jsonb=detail,
        )
        session.add(log)
        session.commit()

    if db is not None:
        _write(db)
    else:
        from app.db.session import SessionLocal
        with SessionLocal() as session:
            _write(session)
