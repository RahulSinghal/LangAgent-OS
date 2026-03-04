#!/usr/bin/env python3
"""
Demo: Complete workflow walkthrough with eval report checks.

Simulates a human user interacting with AgentOS from project creation through
every phase gate to completion, with eval coverage checks at key points.

Usage:
    USE_MOCK_AGENTS=true python scripts/demo_full_workflow.py

Requires Postgres running (docker compose up -d) and migrated schema
(python -m alembic upgrade head).
"""

from __future__ import annotations

import os
import sys
import textwrap

# Must be set before any app imports so mock agents activate
os.environ.setdefault("USE_MOCK_AGENTS", "true")

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.projects import create_project
from app.services.runs import resume_run, start_run
from app.services.sessions import create_session
from app.services.traceability import create_trace_link
from app.services.eval_report import build_eval_report, build_eval_report_md
from app.services.snapshots import load_latest_snapshot


# ── Pretty-print helpers ───────────────────────────────────────────────────────

WIDTH = 72

def banner(title: str) -> None:
    print()
    print("═" * WIDTH)
    print(f"  {title}")
    print("═" * WIDTH)

def section(label: str) -> None:
    print()
    print(f"  ── {label} " + "─" * max(0, WIDTH - 6 - len(label)))

def user_says(msg: str) -> None:
    print()
    print(f"  👤  USER: {msg}")

def bot_says(msg: str | None) -> None:
    if not msg:
        return
    wrapped = textwrap.fill(msg, width=WIDTH - 10, subsequent_indent=" " * 10)
    print(f"  🤖  BOT:  {wrapped}")

def info(msg: str) -> None:
    print(f"       {msg}")

def eval_snapshot(db: Session, project_id: int, label: str) -> None:
    section(f"EVAL REPORT SNAPSHOT — {label}")
    report = build_eval_report(db, project_id)
    s = report["summary"]
    print(f"       Coverage: {s['covered_features']}/{s['total_features']} features "
          f"({s['coverage_pct']}%)  |  {s['total_milestones']} milestones")

    for ms in report["milestones"]:
        cov = ms["coverage"]
        bar = "✓" if cov["pct"] >= 80 else ("~" if cov["pct"] >= 40 else "✗")
        print(f"\n       [{bar}] {ms['name']}  ({cov['covered']}/{cov['total']} covered)")
        for feat in ms["features"]:
            mark = "✓" if feat["covered"] else "✗"
            evals = ", ".join(
                f"{e['test_id']}[{e['eval_type'] or '?'}]" for e in feat["evals"]
            ) or "— no eval"
            text = feat["text"][:45] + "…" if len(feat["text"]) > 45 else feat["text"]
            print(f"           {mark}  [{feat['requirement_id'][:8]}]  {text}")
            print(f"               → {evals}")

    if report["ungrouped_features"]:
        print(f"\n       Ungrouped: {len(report['ungrouped_features'])} feature(s) "
              f"not assigned to any milestone")

    if not report["milestones"] and not report["ungrouped_features"]:
        print("       (no milestones or features in SoT yet)")


# ── Approval helpers ───────────────────────────────────────────────────────────

def get_pending_approvals(db: Session, run_id: int):
    from app.db.models import Approval
    return (
        db.query(Approval)
        .filter(Approval.run_id == run_id, Approval.status == "pending")
        .all()
    )

def approve_all(db: Session, run, label: str) -> object:
    """Approve every pending approval for this run and resume."""
    pending = get_pending_approvals(db, run.id)
    if not pending:
        info(f"No pending approvals at {label}.")
        return run

    patch = {a.type: "approved" for a in pending}
    info(f"Approving: {list(patch.keys())}")
    run = resume_run(db, run.id, approval_patch=patch)
    bot_says(run.bot_response)
    return run


# ── Main demo ─────────────────────────────────────────────────────────────────

def main() -> None:
    db: Session = SessionLocal()

    try:
        banner("AgentOS — Full Workflow Demo (mock agents)")
        info("Project: E-Commerce Platform for Independent Retailers")
        info("Agents:  Mock (deterministic, no LLM key required)")

        # ── 1. Create project + session ───────────────────────────────────────
        section("SETUP — Create project & session")
        project = create_project(db, name="E-Commerce Platform")
        session = create_session(db, project_id=project.id, channel="demo")
        info(f"Project ID : {project.id}")
        info(f"Session ID : {session.id}")

        # ── 2. DISCOVERY — first message ──────────────────────────────────────
        banner("PHASE 1 — DISCOVERY")
        user_says("I want to build an e-commerce platform with product catalog, "
                  "shopping cart, and checkout for independent retailers.")

        run = start_run(
            db,
            project_id=project.id,
            session_id=session.id,
            user_message=(
                "I want to build an e-commerce platform with product catalog, "
                "shopping cart, and checkout for independent retailers."
            ),
        )
        bot_says(run.bot_response)
        info(f"Status: {run.status}  |  Node: {run.current_node}")
        assert run.status == "waiting_user", f"Expected waiting_user, got {run.status}"

        # ── 3. DISCOVERY — user answers the question ──────────────────────────
        section("User answers discovery question")
        user_says("Primary use case is B2C: independent retailers list products, "
                  "customers browse and checkout. We need SSO, inventory management, "
                  "Stripe payments, and order tracking.")

        run = resume_run(
            db,
            run.id,
            user_message=(
                "Primary use case is B2C: independent retailers list products, "
                "customers browse and checkout. We need SSO, inventory management, "
                "Stripe payments, and order tracking."
            ),
        )
        bot_says(run.bot_response)
        info(f"Status: {run.status}  |  Node: {run.current_node}")
        assert run.status == "waiting_approval", f"Expected waiting_approval, got {run.status}"
        assert run.current_node == "prd_gate", f"Expected prd_gate, got {run.current_node}"

        # Show SoT requirements discovered
        sot = load_latest_snapshot(db, run.id)
        info(f"Requirements in SoT: {len(sot.requirements)}")
        for r in sot.requirements:
            info(f"  [{r.id[:8]}] ({r.category}) {r.text}")

        eval_snapshot(db, project.id, "After Discovery — before any milestones")

        # ── 4. PRD GATE — approve ─────────────────────────────────────────────
        banner("PHASE 2 — PRD APPROVAL")
        section("Reviewer approves PRD and server details")
        run = approve_all(db, run, "prd_gate")
        info(f"Status: {run.status}  |  Node: {run.current_node}")

        # ── 5. COMMERCIALS GATE — approve ────────────────────────────────────
        banner("PHASE 3 — COMMERCIALS APPROVAL")
        section("Reviewer approves commercial proposal")
        run = approve_all(db, run, "commercials_gate")
        info(f"Status: {run.status}  |  Node: {run.current_node}")

        # ── 6. SOW GATE — approve ─────────────────────────────────────────────
        banner("PHASE 4 — SOW APPROVAL")
        section("Reviewer approves Statement of Work")
        run = approve_all(db, run, "sow_gate")
        info(f"Status: {run.status}  |  Node: {run.current_node}")

        # ── 7. CODING PLAN GATE — approve ────────────────────────────────────
        banner("PHASE 5 — CODING PLAN APPROVAL")
        sot = load_latest_snapshot(db, run.id)
        section("Tech lead reviews milestone plan")
        info(f"Milestones proposed: {len(sot.coding_plan)}")
        for ms in sot.coding_plan:
            info(f"  [{ms.id[:8]}] {ms.name}")
            info(f"           Stories: {ms.stories}")
            info(f"           {ms.description}")

        run = approve_all(db, run, "coding_plan_gate")
        info(f"Status: {run.status}  |  Node: {run.current_node}")

        eval_snapshot(db, project.id, "After Coding Plan approved — milestones now visible")

        # ── 8. MILESTONE 1 ────────────────────────────────────────────────────
        banner("PHASE 6 — MILESTONE 1: Foundation & Auth")
        sot = load_latest_snapshot(db, run.id)
        ms1 = sot.coding_plan[0]
        info(f"Milestone: {ms1.name}  [{ms1.id[:8]}]")
        info(f"Status   : {ms1.status}")

        # Simulate engineer linking evals BEFORE approval (code review happens here)
        section("Engineer links evals for Milestone 1 features")
        req_id = sot.requirements[0].id if sot.requirements else "r-stub"

        # Link the actual SoT requirement to a test
        create_trace_link(
            db, project_id=project.id,
            requirement_id=req_id,
            test_id="test_sso_login",
            eval_type="unit",
            milestone_id=ms1.id,
            source="manual",
            notes="pytest tests/unit/test_sso_login.py",
        )
        create_trace_link(
            db, project_id=project.id,
            requirement_id=req_id,
            test_id="test_sso_e2e",
            eval_type="e2e",
            milestone_id=ms1.id,
            source="manual",
            notes="cypress tests/e2e/sso.cy.ts",
        )
        # Link milestone 1 stories as features too
        create_trace_link(
            db, project_id=project.id,
            requirement_id="story-001",
            test_id="test_db_models",
            eval_type="unit",
            milestone_id=ms1.id,
            source="manual",
        )
        info("Added: test_sso_login[unit], test_sso_e2e[e2e] → SSO requirement")
        info("Added: test_db_models[unit] → story-001 (DB models)")

        eval_snapshot(db, project.id, "Mid Milestone 1 — some evals linked")

        # Tech lead approves milestone 1
        section("Tech lead approves Milestone 1")
        run = approve_all(db, run, "milestone_gate (MS1)")
        info(f"Status: {run.status}  |  Node: {run.current_node}")

        # ── 9. MILESTONE 2 (the loop!) ────────────────────────────────────────
        banner("PHASE 7 — MILESTONE 2: Feature Implementation  [THE LOOP]")
        sot = load_latest_snapshot(db, run.id)
        ms2 = sot.coding_plan[1]
        info(f"Milestone: {ms2.name}  [{ms2.id[:8]}]")
        info(f"Status   : {ms2.status}")
        info(f"Loop: current_milestone_index = {sot.current_milestone_index}")

        # Engineer links evals for milestone 2
        section("Engineer links evals for Milestone 2 features")
        create_trace_link(
            db, project_id=project.id,
            requirement_id="story-003",
            test_id="test_product_catalog",
            eval_type="integration",
            milestone_id=ms2.id,
            source="manual",
        )
        create_trace_link(
            db, project_id=project.id,
            requirement_id="story-004",
            test_id="test_checkout_stripe",
            eval_type="e2e",
            milestone_id=ms2.id,
            source="manual",
        )
        create_trace_link(
            db, project_id=project.id,
            requirement_id="story-004",
            test_id="test_payment_unit",
            eval_type="unit",
            milestone_id=ms2.id,
            source="manual",
        )
        info("Added: test_product_catalog[integration] → story-003")
        info("Added: test_checkout_stripe[e2e], test_payment_unit[unit] → story-004")

        eval_snapshot(db, project.id, "Mid Milestone 2 — near full coverage")

        # Tech lead approves milestone 2 → workflow completes
        section("Tech lead approves Milestone 2 — workflow completes")
        run = approve_all(db, run, "milestone_gate (MS2)")
        info(f"Status: {run.status}  |  Node: {run.current_node}")

        # ── 10. FINAL STATE ───────────────────────────────────────────────────
        banner("WORKFLOW COMPLETE")
        sot = load_latest_snapshot(db, run.id)
        info(f"Final phase : {sot.current_phase}")
        info(f"Run status  : {run.status}")
        info(f"Milestones  : {[ms.name + ' (' + ms.status + ')' for ms in sot.coding_plan]}")

        eval_snapshot(db, project.id, "FINAL — complete eval coverage")

        # ── 11. Full markdown report preview ──────────────────────────────────
        section("Markdown report (as exported in ZIP)")
        report = build_eval_report(db, project.id)
        md = build_eval_report_md(report)
        # Print first 50 lines only for readability
        lines = md.splitlines()
        for line in lines[:50]:
            print(f"  {line}")
        if len(lines) > 50:
            print(f"  … ({len(lines) - 50} more lines)")

        banner("Demo complete. Run `GET /api/v1/projects/{project.id}/eval-report` for full JSON.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
