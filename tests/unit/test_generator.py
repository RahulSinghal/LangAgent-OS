"""Unit tests for Phase 1F — artifact generator (no DB required)."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.artifacts.generator import (
    _build_prd_context,
    _build_sow_context,
    _jinja_env,
    render_artifact,
)
from app.sot.patch import apply_patch
from app.sot.state import RequirementItem, RiskItem, AssumptionItem, create_initial_state


# ── Context builders ──────────────────────────────────────────────────────────

def test_prd_context_has_required_keys():
    sot = create_initial_state(project_id=1)
    ctx = _build_prd_context(sot, "Test Project", version=1)
    for key in ("project_name", "version", "generated_at", "scope",
                "objectives", "requirements", "assumptions", "risks", "open_questions"):
        assert key in ctx, f"Missing key: {key}"


def test_sow_context_has_required_keys():
    sot = create_initial_state(project_id=1)
    ctx = _build_sow_context(sot, "Test Project", version=1)
    for key in ("project_name", "version", "generated_at", "scope",
                "milestones", "commercial_model", "payment_terms"):
        assert key in ctx, f"Missing key: {key}"


def test_prd_context_maps_requirements():
    sot = apply_patch(
        create_initial_state(project_id=1),
        {"requirements": [{"category": "functional", "text": "User login", "id": "r1"}]},
    )
    ctx = _build_prd_context(sot, "Project", 1)
    assert len(ctx["requirements"]) == 1
    assert ctx["requirements"][0]["text"] == "User login"
    assert "requirement_id" in ctx["requirements"][0]


def test_sow_context_in_scope_from_requirements():
    sot = apply_patch(
        create_initial_state(project_id=1),
        {"requirements": [{"category": "functional", "text": "CRM module", "id": "r1", "accepted": True}]},
    )
    ctx = _build_sow_context(sot, "Project", 1)
    assert "CRM module" in ctx["scope"]["in_scope"]


def test_prd_context_version_set_correctly():
    sot = create_initial_state(project_id=1)
    ctx = _build_prd_context(sot, "My Project", version=3)
    assert ctx["version"] == 3
    assert ctx["project_name"] == "My Project"


# ── Template rendering ────────────────────────────────────────────────────────

def test_prd_template_renders_without_error():
    sot = create_initial_state(project_id=1)
    ctx = _build_prd_context(sot, "Template Test", 1)
    template = _jinja_env.get_template("prd.md.j2")
    rendered = template.render(**ctx)
    assert "Template Test" in rendered
    assert "Product Requirements Document" in rendered


def test_sow_template_renders_without_error():
    sot = create_initial_state(project_id=1)
    ctx = _build_sow_context(sot, "SOW Test Project", 1)
    template = _jinja_env.get_template("sow.md.j2")
    rendered = template.render(**ctx)
    assert "SOW Test Project" in rendered
    assert "Statement of Work" in rendered


def test_prd_template_renders_requirements():
    sot = apply_patch(
        create_initial_state(project_id=1),
        {"requirements": [{"category": "functional", "text": "Audit logging required", "id": "r1"}]},
    )
    ctx = _build_prd_context(sot, "Project", 1)
    template = _jinja_env.get_template("prd.md.j2")
    rendered = template.render(**ctx)
    assert "Audit logging required" in rendered


def test_sow_template_includes_milestones():
    sot = create_initial_state(project_id=1)
    ctx = _build_sow_context(sot, "Project", 1)
    template = _jinja_env.get_template("sow.md.j2")
    rendered = template.render(**ctx)
    assert "Discovery" in rendered
    assert "UAT" in rendered


# ── render_artifact (mocked DB + filesystem) ──────────────────────────────────

def _make_mock_db(project_name: str = "Mock Project", existing_artifacts: int = 0):
    """Build a minimal SQLAlchemy Session mock."""
    mock_db = MagicMock()
    mock_project = MagicMock()
    mock_project.name = project_name

    mock_db.get.side_effect = lambda model, pk: mock_project  # any .get() returns project
    mock_db.query.return_value.filter.return_value.count.return_value = existing_artifacts

    mock_artifact = MagicMock()
    mock_artifact.id = 42
    mock_artifact.version = existing_artifacts + 1
    mock_artifact.type = "prd"
    mock_artifact.project_id = 1
    mock_artifact.file_path = None
    mock_artifact.created_at = None
    mock_artifact.derived_from_snapshot_id = None

    def _refresh(obj):
        if hasattr(obj, 'id'):
            obj.id = 42

    mock_db.refresh = _refresh
    mock_db.add = MagicMock()
    mock_db.commit = MagicMock()
    return mock_db


def test_render_artifact_writes_file(tmp_path):
    sot = create_initial_state(project_id=1)
    mock_db = _make_mock_db("Test Project")

    with patch("app.artifacts.generator.settings") as mock_settings:
        mock_settings.ARTIFACTS_DIR = str(tmp_path)
        artifact, updated_sot = render_artifact("prd", sot, mock_db)

    # File should be written
    expected = tmp_path / "1" / "prd" / "v1.md"
    assert expected.exists()
    content = expected.read_text()
    assert "Test Project" in content


def test_render_artifact_updates_sot_index(tmp_path):
    sot = create_initial_state(project_id=1)
    mock_db = _make_mock_db("Project X")

    with patch("app.artifacts.generator.settings") as mock_settings:
        mock_settings.ARTIFACTS_DIR = str(tmp_path)
        _, updated_sot = render_artifact("prd", sot, mock_db)

    assert "prd" in updated_sot.artifacts_index
    assert updated_sot.artifacts_index["prd"].version == 1


def test_render_artifact_unknown_type_raises():
    sot = create_initial_state(project_id=1)
    mock_db = MagicMock()
    with pytest.raises(ValueError, match="Unknown artifact_type"):
        render_artifact("unknown_type", sot, mock_db)


def test_render_artifact_sow(tmp_path):
    sot = apply_patch(
        create_initial_state(project_id=2),
        {"requirements": [{"category": "functional", "text": "Order management", "id": "r1"}]},
    )
    mock_db = _make_mock_db("SOW Project")

    with patch("app.artifacts.generator.settings") as mock_settings:
        mock_settings.ARTIFACTS_DIR = str(tmp_path)
        artifact, updated_sot = render_artifact("sow", sot, mock_db)

    expected = tmp_path / "2" / "sow" / "v1.md"
    assert expected.exists()
    content = expected.read_text()
    assert "SOW Project" in content
    assert "Order management" in content
    assert "sow" in updated_sot.artifacts_index


def test_render_artifact_version_increments(tmp_path):
    """When 2 artifacts already exist, version should be 3."""
    sot = create_initial_state(project_id=1)
    mock_db = _make_mock_db("Versioned Project", existing_artifacts=2)

    with patch("app.artifacts.generator.settings") as mock_settings:
        mock_settings.ARTIFACTS_DIR = str(tmp_path)
        _, updated_sot = render_artifact("prd", sot, mock_db)

    assert updated_sot.artifacts_index["prd"].version == 3
    expected = tmp_path / "1" / "prd" / "v3.md"
    assert expected.exists()
