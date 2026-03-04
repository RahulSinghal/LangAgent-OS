"""Unit tests for the cross-project memory / context retrieval service."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.db.models import ComponentStore, Project  # noqa: F401
from app.services.context_retrieval import (
    _extract_tags,
    auto_extract_and_store,
    build_context_summary,
    bulk_store_components,
    delete_component,
    get_component,
    list_components,
    purge_auto_components,
    retrieve_relevant,
    store_component,
)


# ── In-memory SQLite DB fixture ───────────────────────────────────────────────

@pytest.fixture()
def db() -> Session:
    """Provide a fresh in-memory SQLite session for each test.

    Only creates the tables needed by context_retrieval — avoids JSONB
    columns used by other models (PostgreSQL-only type).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    # Create only the tables we need (no JSONB columns in these two)
    Project.__table__.create(engine, checkfirst=True)
    ComponentStore.__table__.create(engine, checkfirst=True)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()
    yield session
    session.close()
    ComponentStore.__table__.drop(engine, checkfirst=True)
    Project.__table__.drop(engine, checkfirst=True)
    engine.dispose()


# ── _extract_tags ─────────────────────────────────────────────────────────────

def test_extract_tags_basic():
    tags = _extract_tags("authentication payments notifications")
    assert "authentication" in tags
    assert "payments" in tags
    assert "notifications" in tags


def test_extract_tags_deduplicates():
    tags = _extract_tags("auth auth auth payments")
    assert tags.count("auth") == 1


def test_extract_tags_strips_stop_words():
    tags = _extract_tags("the user should be able to login")
    assert "the" not in tags
    assert "should" not in tags
    assert "login" in tags


def test_extract_tags_respects_max():
    text = " ".join(f"word{i}" for i in range(30))
    tags = _extract_tags(text, max_tags=5)
    assert len(tags) <= 5


def test_extract_tags_empty_string():
    assert _extract_tags("") == []


# ── store_component ───────────────────────────────────────────────────────────

def test_store_component_persists(db):
    c = store_component(
        db,
        source_project_id=1,
        component_type="requirement_pattern",
        category="auth",
        name="User login",
        content="Users must be able to log in with email and password.",
        tags=["auth", "login", "email"],
    )
    assert c.id is not None
    assert c.component_type == "requirement_pattern"
    assert c.category == "auth"
    assert c.usage_count == 0
    assert c.source == "auto"


def test_store_component_auto_tags_when_none(db):
    c = store_component(
        db,
        source_project_id=None,
        component_type="risk_pattern",
        category="security",
        name="SQL injection risk",
        content="Database queries constructed with user input risk SQL injection.",
    )
    assert len(c.tags_json) > 0


def test_store_component_manual_source(db):
    c = store_component(
        db,
        source_project_id=None,
        component_type="assumption",
        category="general",
        name="Cloud hosting assumed",
        content="The system will be hosted on cloud infrastructure.",
        source="manual",
    )
    assert c.source == "manual"


# ── bulk_store_components ─────────────────────────────────────────────────────

def test_bulk_store_persists_all(db):
    items = [
        {
            "source_project_id": 1,
            "component_type": "requirement_pattern",
            "category": "payments",
            "name": "Stripe integration",
            "content": "System integrates with Stripe for payment processing.",
            "tags": ["payments", "stripe", "integration"],
        },
        {
            "source_project_id": 1,
            "component_type": "risk_pattern",
            "category": "payments",
            "name": "Payment failure risk",
            "content": "Payment provider outages may affect checkout.",
            "tags": ["payments", "risk", "availability"],
        },
    ]
    stored = bulk_store_components(db, items)
    assert len(stored) == 2
    assert all(c.id is not None for c in stored)


# ── retrieve_relevant ─────────────────────────────────────────────────────────

def test_retrieve_relevant_returns_matches(db):
    store_component(
        db,
        source_project_id=1,
        component_type="requirement_pattern",
        category="auth",
        name="OAuth login",
        content="Login with Google OAuth.",
        tags=["auth", "oauth", "login", "google"],
    )
    store_component(
        db,
        source_project_id=2,
        component_type="requirement_pattern",
        category="payments",
        name="Stripe checkout",
        content="Stripe payment integration.",
        tags=["payments", "stripe"],
    )

    results = retrieve_relevant(db, query_tags=["auth", "login"])
    names = [r["name"] for r in results]
    assert "OAuth login" in names
    assert "Stripe checkout" not in names


def test_retrieve_relevant_empty_tags_returns_empty(db):
    store_component(
        db,
        source_project_id=1,
        component_type="requirement_pattern",
        category="auth",
        name="Login req",
        content="Login flow.",
        tags=["auth"],
    )
    results = retrieve_relevant(db, query_tags=[])
    assert results == []


def test_retrieve_relevant_respects_limit(db):
    for i in range(10):
        store_component(
            db,
            source_project_id=1,
            component_type="requirement_pattern",
            category="auth",
            name=f"Auth req {i}",
            content=f"Auth requirement {i} for login.",
            tags=["auth", "login"],
        )
    results = retrieve_relevant(db, query_tags=["auth", "login"], limit=3)
    assert len(results) <= 3


def test_retrieve_relevant_increments_usage_count(db):
    c = store_component(
        db,
        source_project_id=1,
        component_type="requirement_pattern",
        category="auth",
        name="Login req",
        content="Users can log in.",
        tags=["auth", "login"],
    )
    assert c.usage_count == 0
    retrieve_relevant(db, query_tags=["auth"])
    db.refresh(c)
    assert c.usage_count == 1


def test_retrieve_relevant_min_overlap_filters(db):
    store_component(
        db,
        source_project_id=1,
        component_type="requirement_pattern",
        category="auth",
        name="Auth req",
        content="Login system.",
        tags=["auth"],
    )
    # min_overlap=2 but component only shares 1 tag
    results = retrieve_relevant(db, query_tags=["auth", "payments"], min_overlap=2)
    assert results == []


def test_retrieve_relevant_filters_by_component_type(db):
    store_component(
        db,
        source_project_id=1,
        component_type="requirement_pattern",
        category="auth",
        name="Login req",
        content="Login flow.",
        tags=["auth"],
    )
    store_component(
        db,
        source_project_id=1,
        component_type="risk_pattern",
        category="auth",
        name="Auth risk",
        content="Auth failure risk.",
        tags=["auth"],
    )
    results = retrieve_relevant(
        db,
        query_tags=["auth"],
        component_types=["risk_pattern"],
    )
    assert all(r["component_type"] == "risk_pattern" for r in results)


def test_retrieve_relevant_ranked_by_overlap(db):
    store_component(
        db,
        source_project_id=1,
        component_type="requirement_pattern",
        category="auth",
        name="High overlap",
        content="auth login oauth sso.",
        tags=["auth", "login", "oauth"],
    )
    store_component(
        db,
        source_project_id=1,
        component_type="requirement_pattern",
        category="auth",
        name="Low overlap",
        content="auth only.",
        tags=["auth"],
    )
    results = retrieve_relevant(db, query_tags=["auth", "login", "oauth"])
    assert results[0]["name"] == "High overlap"


# ── get / list / delete ───────────────────────────────────────────────────────

def test_get_component_found(db):
    c = store_component(
        db,
        source_project_id=1,
        component_type="assumption",
        category="general",
        name="Cloud infra",
        content="Cloud-hosted.",
    )
    fetched = get_component(db, c.id)
    assert fetched is not None
    assert fetched.id == c.id


def test_get_component_not_found(db):
    assert get_component(db, 99999) is None


def test_list_components_all(db):
    bulk_store_components(db, [
        {"source_project_id": 1, "component_type": "requirement_pattern",
         "category": "auth", "name": "R1", "content": "Login"},
        {"source_project_id": 1, "component_type": "risk_pattern",
         "category": "auth", "name": "Ri1", "content": "Auth risk"},
    ])
    rows = list_components(db)
    assert len(rows) >= 2


def test_list_components_filter_by_type(db):
    bulk_store_components(db, [
        {"source_project_id": 1, "component_type": "requirement_pattern",
         "category": "auth", "name": "Req", "content": "Login"},
        {"source_project_id": 1, "component_type": "risk_pattern",
         "category": "auth", "name": "Risk", "content": "Fail"},
    ])
    rows = list_components(db, component_type="requirement_pattern")
    assert all(r.component_type == "requirement_pattern" for r in rows)


def test_delete_component(db):
    c = store_component(
        db,
        source_project_id=1,
        component_type="assumption",
        category="general",
        name="Cloud infra",
        content="Cloud-hosted.",
    )
    assert delete_component(db, c.id) is True
    assert get_component(db, c.id) is None


def test_delete_component_not_found(db):
    assert delete_component(db, 99999) is False


# ── auto_extract_and_store ────────────────────────────────────────────────────

def _make_sot(domain="saas"):
    return {
        "domain": domain,
        "requirements": [
            {"id": "r1", "category": "functional", "text": "Users can log in with email and password.", "priority": "high"},
            {"id": "r2", "category": "non_functional", "text": "System must handle 10000 concurrent users.", "priority": "medium"},
        ],
        "decisions": [
            {"id": "d1", "decision": "Use PostgreSQL as the primary database.", "rationale": "Strong ACID compliance and ecosystem."},
        ],
        "risks": [
            {"id": "ri1", "description": "Vendor lock-in with cloud provider.", "mitigation": "Use Terraform for IaC.", "likelihood": "medium"},
        ],
        "assumptions": [
            {"id": "a1", "text": "Client will provide SSO credentials before development starts."},
        ],
    }


def test_auto_extract_requirements(db):
    stored = auto_extract_and_store(db, project_id=1, sot=_make_sot())
    types = [c.component_type for c in stored]
    assert "requirement_pattern" in types


def test_auto_extract_decisions(db):
    stored = auto_extract_and_store(db, project_id=1, sot=_make_sot())
    types = [c.component_type for c in stored]
    assert "architecture_decision" in types


def test_auto_extract_risks(db):
    stored = auto_extract_and_store(db, project_id=1, sot=_make_sot())
    types = [c.component_type for c in stored]
    assert "risk_pattern" in types


def test_auto_extract_assumptions(db):
    stored = auto_extract_and_store(db, project_id=1, sot=_make_sot())
    types = [c.component_type for c in stored]
    assert "assumption" in types


def test_auto_extract_count(db):
    stored = auto_extract_and_store(db, project_id=1, sot=_make_sot())
    # 2 requirements + 1 decision + 1 risk + 1 assumption = 5
    assert len(stored) == 5


def test_auto_extract_tags_include_domain(db):
    stored = auto_extract_and_store(db, project_id=1, sot=_make_sot(domain="fintech"))
    for c in stored:
        assert "fintech" in c.tags_json


def test_auto_extract_source_is_auto(db):
    stored = auto_extract_and_store(db, project_id=1, sot=_make_sot())
    assert all(c.source == "auto" for c in stored)


def test_auto_extract_empty_sot(db):
    stored = auto_extract_and_store(db, project_id=1, sot={"domain": "generic"})
    assert stored == []


def test_auto_extract_skips_empty_text(db):
    sot = {
        "domain": "saas",
        "requirements": [{"id": "r1", "category": "functional", "text": ""}],
    }
    stored = auto_extract_and_store(db, project_id=1, sot=sot)
    assert not any(c.component_type == "requirement_pattern" for c in stored)


def test_auto_extract_then_retrieve(db):
    """Full round-trip: extract from completed project, retrieve for new one."""
    auto_extract_and_store(db, project_id=1, sot=_make_sot(domain="saas"))

    # New project about SaaS login — should retrieve the login requirement
    results = retrieve_relevant(db, query_tags=["saas", "login", "email"])
    assert len(results) > 0
    contents = [r["content"] for r in results]
    assert any("log in" in c.lower() or "login" in c.lower() for c in contents)


# ── build_context_summary ─────────────────────────────────────────────────────

def test_build_context_summary_empty():
    assert build_context_summary([]) == ""


def test_build_context_summary_contains_names(db):
    stored = auto_extract_and_store(db, project_id=1, sot=_make_sot())
    components = retrieve_relevant(db, query_tags=["saas", "login", "auth"], limit=20)
    summary = build_context_summary(components)
    assert "## Relevant patterns" in summary
    assert len(summary) > 0


def test_build_context_summary_sections_by_type(db):
    auto_extract_and_store(db, project_id=1, sot=_make_sot())
    components = retrieve_relevant(db, query_tags=["saas", "database", "risk", "vendor"], limit=20)
    summary = build_context_summary(components)
    # Should contain section headings
    assert "###" in summary


# ── run_id tracking ───────────────────────────────────────────────────────────

def test_bulk_store_records_run_id(db):
    stored = bulk_store_components(
        db,
        [{"source_project_id": 1, "component_type": "requirement_pattern",
          "category": "auth", "name": "Login", "content": "Login flow."}],
        run_id=42,
    )
    assert stored[0].run_id == 42


def test_auto_extract_records_run_id(db):
    stored = auto_extract_and_store(db, project_id=1, sot=_make_sot(), run_id=99)
    assert all(c.run_id == 99 for c in stored)


def test_auto_extract_run_id_none_by_default(db):
    stored = auto_extract_and_store(db, project_id=1, sot=_make_sot())
    assert all(c.run_id is None for c in stored)


# ── purge_auto_components (revision handling) ─────────────────────────────────

def test_purge_auto_removes_auto_rows(db):
    auto_extract_and_store(db, project_id=1, sot=_make_sot())
    count_before = len(list_components(db, source_project_id=1))
    assert count_before > 0

    deleted = purge_auto_components(db, project_id=1)
    assert deleted == count_before
    assert list_components(db, source_project_id=1) == []


def test_purge_auto_preserves_manual_components(db):
    # Store one manual component
    store_component(
        db,
        source_project_id=1,
        component_type="assumption",
        category="general",
        name="Manual note",
        content="Approved by client.",
        source="manual",
    )
    # Store auto components
    auto_extract_and_store(db, project_id=1, sot=_make_sot())

    # Purge auto — manual must survive
    purge_auto_components(db, project_id=1)
    remaining = list_components(db, source_project_id=1)
    assert len(remaining) == 1
    assert remaining[0].source == "manual"
    assert remaining[0].name == "Manual note"


def test_purge_auto_only_affects_target_project(db):
    auto_extract_and_store(db, project_id=1, sot=_make_sot())
    auto_extract_and_store(db, project_id=2, sot=_make_sot(domain="fintech"))

    purge_auto_components(db, project_id=1)

    p1_rows = list_components(db, source_project_id=1)
    p2_rows = list_components(db, source_project_id=2)
    assert p1_rows == []
    assert len(p2_rows) > 0


def test_purge_auto_returns_zero_when_nothing_to_delete(db):
    assert purge_auto_components(db, project_id=999) == 0


# ── Revision round-trip ───────────────────────────────────────────────────────

def _make_v1_sot():
    return {
        "domain": "saas",
        "requirements": [
            {"id": "r1", "category": "functional",
             "text": "Users can log in with email and password."},
        ],
        "decisions": [],
        "risks": [],
        "assumptions": [],
    }


def _make_v2_sot():
    """Simulates PRD v2: login requirement updated + OAuth added."""
    return {
        "domain": "saas",
        "requirements": [
            {"id": "r1", "category": "functional",
             "text": "Users can log in with email, password, or Google OAuth."},
            {"id": "r2", "category": "non_functional",
             "text": "Login must complete within 2 seconds."},
        ],
        "decisions": [
            {"id": "d1", "decision": "Use Auth0 for identity management.",
             "rationale": "Reduces time-to-market and supports OAuth natively."},
        ],
        "risks": [],
        "assumptions": [],
    }


def test_revision_replaces_stale_components(db):
    """PRD v1 completes → extract. PRD v2 completes → extract again.
    Only v2 knowledge should remain for project 1.
    """
    # v1 completion
    auto_extract_and_store(db, project_id=1, sot=_make_v1_sot(), run_id=1)
    v1_rows = list_components(db, source_project_id=1)
    assert len(v1_rows) == 1  # one requirement

    # v2 completion — should replace, not append
    auto_extract_and_store(db, project_id=1, sot=_make_v2_sot(), run_id=2)
    v2_rows = list_components(db, source_project_id=1)

    # 2 requirements + 1 decision = 3 (v1 row is gone)
    assert len(v2_rows) == 3
    # All rows belong to run 2
    assert all(c.run_id == 2 for c in v2_rows)


def test_revision_stale_content_not_retrievable(db):
    """After revision, the v1 'email and password' requirement should be
    replaced by the v2 'OAuth' requirement in retrieval results.
    """
    auto_extract_and_store(db, project_id=1, sot=_make_v1_sot(), run_id=1)
    auto_extract_and_store(db, project_id=1, sot=_make_v2_sot(), run_id=2)

    results = retrieve_relevant(db, query_tags=["saas", "login", "oauth"])
    contents = " ".join(r["content"] for r in results).lower()

    # v2 OAuth content must be present
    assert "oauth" in contents
    # v1-only content (just "email and password" without OAuth) must not dominate
    # (the v1 row was deleted; only the updated v2 version exists)
    v1_only_rows = [
        r for r in results
        if r["content"] == "Users can log in with email and password."
    ]
    assert v1_only_rows == []


def test_revision_manual_components_survive_multiple_revisions(db):
    """Manual annotations created between v1 and v2 must survive both revisions."""
    auto_extract_and_store(db, project_id=1, sot=_make_v1_sot(), run_id=1)

    # PM adds a manual note mid-project
    store_component(
        db,
        source_project_id=1,
        component_type="assumption",
        category="general",
        name="SLA agreed",
        content="99.9% uptime SLA signed by client on 2026-01-15.",
        source="manual",
    )

    # v2 revision completes
    auto_extract_and_store(db, project_id=1, sot=_make_v2_sot(), run_id=2)

    manual_rows = [
        c for c in list_components(db, source_project_id=1)
        if c.source == "manual"
    ]
    assert len(manual_rows) == 1
    assert "SLA" in manual_rows[0].name
