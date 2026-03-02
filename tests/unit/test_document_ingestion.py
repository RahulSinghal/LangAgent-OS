"""Unit tests for the document ingestion service.

Tests: extract_sections, extract_requirements, extract_assumptions,
       extract_questions, extract_risks, summarize_document, ingest_document.

No DB required — all functions are pure Python with no external dependencies.
"""

from __future__ import annotations

import pytest

from app.services.document_ingestion import (
    detect_document_type,
    extract_assumptions,
    extract_questions,
    extract_requirements,
    extract_risks,
    extract_sections,
    gap_analysis,
    ingest_document,
    summarize_document,
)


# ── Test helpers ──────────────────────────────────────────────────────────────

def _brd_markdown() -> str:
    """Realistic BRD in markdown format with all four section types."""
    return """# Business Requirements Document

## Requirements
- [R-1] The system shall support SSO via OAuth2
- The platform must handle 10,000 concurrent users
- [R-2] Data shall be encrypted at rest and in transit
- API integration with Salesforce CRM is required

## Assumptions
- Assume the client has an existing Active Directory
- As a baseline, the project budget is $500,000
- Given that users are enterprise employees, SSO will be pre-configured

## Open Questions
- What authentication providers are supported?
- Has the compliance team reviewed GDPR requirements?
- TBD: payment gateway selection

## Risks
- Risk: Third-party API dependency may change without notice
- Vendor lock-in to cloud provider is a potential risk
- Risk of data breach due to insufficient access controls
"""


def _plain_text_brd() -> str:
    """BRD with ALL-CAPS section headings (no markdown)."""
    return """REQUIREMENTS
The system must process orders within 2 seconds.
The platform shall support multi-currency transactions.
Users should be able to export reports to PDF.

ASSUMPTIONS
Given that users are enterprise employees, SSO will be pre-configured.

OPEN QUESTIONS
What is the expected peak load?
TBD: payment gateway selection
"""


def _bullet_only_doc() -> str:
    """Pure bullet list, no headings."""
    return """- User registration and login
- Dashboard with analytics charts
- Export to CSV and PDF
- Email notification system
- Role-based access control
"""


def _empty_doc() -> str:
    return ""


def _whitespace_doc() -> str:
    return "   \n\n   \t\n"


# ── extract_sections ──────────────────────────────────────────────────────────

def test_extract_sections_markdown_headings_detected():
    sections = extract_sections(_brd_markdown())
    assert "requirements" in sections
    assert "assumptions" in sections
    assert "open questions" in sections
    assert "risks" in sections


def test_extract_sections_uppercase_titles_detected():
    sections = extract_sections(_plain_text_brd())
    keys = list(sections.keys())
    # ALL-CAPS headings should produce keys like "requirements", "assumptions", etc.
    assert any("requirements" in k for k in keys)


def test_extract_sections_no_headings_returns_full_document_only():
    sections = extract_sections(_bullet_only_doc())
    assert "_full_document" in sections
    # Should have only the _full_document key (no headings were detected)
    assert len(sections) == 1


def test_extract_sections_body_excludes_heading_line():
    sections = extract_sections(_brd_markdown())
    body = sections.get("requirements", "")
    # The heading line itself must not appear in the body
    assert "## Requirements" not in body
    # But the content must be present
    assert "[R-1]" in body


def test_extract_sections_full_document_always_present():
    for doc in [_brd_markdown(), _plain_text_brd(), _bullet_only_doc(), _empty_doc()]:
        sections = extract_sections(doc)
        assert "_full_document" in sections


# ── extract_requirements ──────────────────────────────────────────────────────

def test_extract_requirements_explicit_id_tags():
    text = "[R-1] The system shall support SSO\n[R-2] Encryption is required at rest"
    result = extract_requirements(text)
    assert len(result) >= 2
    assert all(r["source"] == "document_upload" for r in result)


def test_extract_requirements_bullet_items():
    text = "- User can log in\n- User can export data\n* Dashboard is required"
    result = extract_requirements(text)
    assert len(result) == 3
    assert all(r["category"] in ("functional", "non_functional", "integration") for r in result)


def test_extract_requirements_shall_must_keywords():
    text = (
        "The system shall process 1000 requests per second.\n"
        "Users must authenticate via MFA.\n"
        "This sentence has no modal verbs."
    )
    result = extract_requirements(text)
    texts = [r["text"] for r in result]
    assert any("shall" in t or "must" in t for t in texts)
    assert len(result) >= 2


def test_extract_requirements_nfr_category_inference():
    text = "- The system shall maintain 99.9% uptime and high availability."
    result = extract_requirements(text)
    assert len(result) == 1
    assert result[0]["category"] == "non_functional"


def test_extract_requirements_integration_category_inference():
    text = "- API integration with Salesforce CRM is required"
    result = extract_requirements(text)
    assert len(result) == 1
    assert result[0]["category"] == "integration"


def test_extract_requirements_functional_category_default():
    text = "- Users shall be able to reset their password"
    result = extract_requirements(text)
    assert result[0]["category"] == "functional"


def test_extract_requirements_empty_input():
    assert extract_requirements("") == []


def test_extract_requirements_whitespace_only():
    assert extract_requirements("   \n\n\t") == []


def test_extract_requirements_no_matches():
    # No bullets, no modal verbs, no IDs — narrative paragraph
    text = "This document describes the overall vision for the enterprise platform."
    result = extract_requirements(text)
    assert result == []


def test_extract_requirements_deduplication():
    text = "[R-1] The system shall support SSO\n[R-1] The system shall support SSO"
    result = extract_requirements(text)
    assert len(result) == 1


def test_extract_requirements_priority_always_medium():
    text = "- [R-1] Critical authentication feature must be implemented"
    result = extract_requirements(text)
    assert result[0]["priority"] == "medium"


def test_extract_requirements_accepted_always_true():
    text = "- The system must handle concurrent users"
    result = extract_requirements(text)
    assert result[0]["accepted"] is True


# ── extract_assumptions ───────────────────────────────────────────────────────

def test_extract_assumptions_assume_prefix():
    text = "Assume the client uses AWS\nAssumed budget is $500K for the project"
    result = extract_assumptions(text)
    assert len(result) >= 2
    assert all(r["confirmed"] is False for r in result)


def test_extract_assumptions_given_that_prefix():
    text = "Given that users are employees, SSO will be pre-configured."
    result = extract_assumptions(text)
    assert len(result) == 1
    assert "SSO" in result[0]["text"]


def test_extract_assumptions_as_a_baseline_prefix():
    text = "As a baseline, the project budget is $500,000."
    result = extract_assumptions(text)
    assert len(result) == 1
    assert "$500,000" in result[0]["text"]


def test_extract_assumptions_empty_input():
    assert extract_assumptions("") == []


def test_extract_assumptions_confirmed_always_false():
    text = "Assume the infrastructure will be on-premise."
    result = extract_assumptions(text)
    assert result[0]["confirmed"] is False


# ── extract_questions ─────────────────────────────────────────────────────────

def test_extract_questions_question_marks():
    text = (
        "What is the target user base?\n"
        "How many concurrent users are expected?\n"
        "This is a statement with no question mark."
    )
    result = extract_questions(text)
    assert len(result) == 2
    assert all(r["answered"] is False for r in result)
    assert all(r["answer"] is None for r in result)


def test_extract_questions_tbd_lines():
    text = "TBD: payment gateway selection\nTo be determined: data residency requirements"
    result = extract_questions(text)
    assert len(result) >= 1


def test_extract_questions_empty_input():
    assert extract_questions("") == []


def test_extract_questions_category_defaults_to_general():
    text = "What is the budget for the project?"
    result = extract_questions(text)
    assert result[0]["category"] == "general"


def test_extract_questions_answered_always_false():
    text = "Has the compliance review been completed?"
    result = extract_questions(text)
    assert result[0]["answered"] is False


# ── extract_risks ─────────────────────────────────────────────────────────────

def test_extract_risks_risk_prefix():
    text = (
        "Risk: Third-party API may deprecate without notice\n"
        "Risk of data breach due to weak authentication"
    )
    result = extract_risks(text)
    assert len(result) == 2
    assert all(r["mitigation"] == "" for r in result)
    assert all(r["impact"] == "medium" for r in result)


def test_extract_risks_likelihood_inference_high():
    text = "Risk: Vendor lock-in is likely given the tight cloud integration"
    result = extract_risks(text)
    assert len(result) == 1
    assert result[0]["likelihood"] == "high"


def test_extract_risks_likelihood_inference_low():
    text = "Risk: Minor edge case where timeout occurs during low-traffic period"
    result = extract_risks(text)
    assert len(result) >= 1
    assert result[0]["likelihood"] == "low"


def test_extract_risks_likelihood_inference_medium_default():
    text = "Risk: Database migration may take longer than planned"
    result = extract_risks(text)
    assert result[0]["likelihood"] == "medium"


def test_extract_risks_empty_input():
    assert extract_risks("") == []


def test_extract_risks_mitigation_always_empty():
    text = "Risk: Scope creep during development sprints"
    result = extract_risks(text)
    assert result[0]["mitigation"] == ""


# ── summarize_document ────────────────────────────────────────────────────────

def test_summarize_document_with_filename():
    content = "some content " * 20
    extraction = {"requirements": [{}] * 3, "assumptions": [{}] * 1}
    result = summarize_document(content, "requirements.docx", extraction)
    assert "'requirements.docx'" in result
    assert "3 requirements" in result
    assert "1 assumption" in result


def test_summarize_document_no_filename_shows_uploaded_document():
    content = "some content " * 20
    extraction = {"requirements": [{}] * 2, "risks": [{}] * 1}
    result = summarize_document(content, "", extraction)
    assert "uploaded document" in result
    assert "2 requirements" in result


def test_summarize_document_no_extractions_mentions_none():
    content = "some content " * 10
    result = summarize_document(content, "doc.txt", {})
    assert "No structured items" in result


def test_summarize_document_includes_word_count():
    content = "word " * 50
    result = summarize_document(content, "doc.md", {})
    assert "50 words" in result


# ── ingest_document ───────────────────────────────────────────────────────────

def test_ingest_document_full_markdown_brd():
    result = ingest_document(_brd_markdown(), "brd.md")
    assert "sot_patch" in result
    assert "summary_message" in result
    patch = result["sot_patch"]
    assert "requirements" in patch
    assert len(patch["requirements"]) >= 2
    assert "'brd.md'" in result["summary_message"]


def test_ingest_document_empty_content_returns_empty_patch():
    result = ingest_document(_empty_doc())
    assert result["sot_patch"] == {}
    assert result["summary_message"] == ""


def test_ingest_document_whitespace_only_returns_empty():
    result = ingest_document(_whitespace_doc())
    assert result["sot_patch"] == {}
    assert result["summary_message"] == ""


def test_ingest_document_bullet_only_doc_captures_requirements():
    result = ingest_document(_bullet_only_doc())
    patch = result["sot_patch"]
    # Bullet items should be captured as requirements from the full-doc fallback
    assert "requirements" in patch
    assert len(patch["requirements"]) >= 3


def test_ingest_document_no_empty_lists_in_patch():
    """Only non-empty lists appear in sot_patch."""
    # This plain document has no questions and no risks
    content = "## Requirements\n- The system shall support login\n\n## Assumptions\nAssume the client has AD."
    result = ingest_document(content, "simple.md")
    patch = result["sot_patch"]
    # All included lists must be non-empty
    for key, value in patch.items():
        assert len(value) > 0, f"sot_patch['{key}'] should not be empty"


def test_ingest_document_sot_patch_is_apply_patch_compatible():
    """Critical smoke test: verify the patch can be applied to a real ProjectState."""
    from app.sot.state import create_initial_state
    from app.sot.patch import apply_patch

    result = ingest_document(_brd_markdown(), "brd.md")
    patch = result["sot_patch"]

    state = create_initial_state(project_id=1)
    patched = apply_patch(state, patch)

    # Requirements and other fields should be pre-populated
    assert len(patched.requirements) >= 1
    assert all(r.source == "document_upload" for r in patched.requirements)


# ── detect_document_type (Phase 4) ────────────────────────────────────────────

def test_detect_document_type_brd_from_filename():
    assert detect_document_type("any content", filename="project_brd.md") == "brd"


def test_detect_document_type_prd_from_filename():
    assert detect_document_type("any content", filename="product_req_v2.docx") == "prd"


def test_detect_document_type_sow_from_filename():
    assert detect_document_type("any content", filename="statement_of_work_final.pdf") == "sow"


def test_detect_document_type_brd_from_content():
    content = (
        "# Business Requirements Document\n\n"
        "This BRD describes the business objectives and stakeholder requirements "
        "for the enterprise platform upgrade."
    )
    assert detect_document_type(content, filename="requirements.md") == "brd"


def test_detect_document_type_prd_from_content():
    content = (
        "# Product Requirements\n\n"
        "This PRD captures the user stories and acceptance criteria for the "
        "new feature set. The product backlog has been updated accordingly."
    )
    assert detect_document_type(content, filename="spec.md") == "prd"


def test_detect_document_type_sow_from_content():
    content = (
        "# Statement of Work\n\n"
        "This SOW defines the scope of work, deliverables, and payment terms "
        "for the engagement. Milestone payments apply."
    )
    assert detect_document_type(content, filename="doc.md") == "sow"


def test_detect_document_type_unknown_when_insufficient_signals():
    content = "Hello world. This is a generic document with no clear type signals."
    assert detect_document_type(content, filename="notes.txt") == "unknown"


# ── gap_analysis (Phase 4) ─────────────────────────────────────────────────────

def test_gap_analysis_brd_returns_questions_for_missing_sections():
    # Document has Requirements section but nothing else
    sections = extract_sections(
        "## Requirements\n- The system shall support SSO.\n"
    )
    questions = gap_analysis(sections, "brd")
    # Should flag missing: business context, objectives, assumptions, stakeholders, risks
    assert len(questions) >= 3
    assert any("business" in q.lower() or "objective" in q.lower() for q in questions)


def test_gap_analysis_no_gaps_when_all_sections_present():
    content = (
        "## Business Context\nWe are building a CRM.\n\n"
        "## Objectives\nImprove sales by 20%.\n\n"
        "## Requirements\n- SSO required.\n\n"
        "## Assumptions\nAssume client has AD.\n\n"
        "## Stakeholders\nCTO sponsors the project.\n\n"
        "## Risks\nRisk: vendor lock-in.\n"
    )
    sections = extract_sections(content)
    questions = gap_analysis(sections, "brd")
    assert questions == []


def test_gap_analysis_unknown_type_returns_empty_list():
    sections = extract_sections("## Some Section\nContent here.")
    questions = gap_analysis(sections, "unknown")
    assert questions == []


# ── ingest_document phase 4 additions ─────────────────────────────────────────

def test_ingest_document_includes_document_type_in_sot_patch():
    result = ingest_document(_brd_markdown(), "brd.md")
    assert "document_type" in result["sot_patch"]
    assert result["document_type"] == "brd"


def test_ingest_document_includes_followup_questions_for_brd_with_gaps():
    # BRD that is missing many sections — should generate followup_questions
    minimal_brd = (
        "# Business Requirements Document\n\n"
        "## Requirements\n- [R-1] The system shall support multi-tenant architecture.\n"
    )
    result = ingest_document(minimal_brd, "minimal_brd.md")
    # Gap questions should be present since most required BRD sections are missing
    assert "followup_questions" in result["sot_patch"]
    assert len(result["sot_patch"]["followup_questions"]) >= 2


def test_ingest_document_empty_returns_unknown_document_type():
    result = ingest_document("")
    assert result["document_type"] == "unknown"
