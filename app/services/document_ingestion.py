"""Document ingestion service — extracts structured data from client documents.

Supports BRDs, RFPs, SOWs, or any plain-text/markdown document shared during
a consulting engagement.  Extraction is purely regex/heuristic — no LLM calls —
so it is deterministic, fast, and fully unit-testable.

Extracted data is returned as a ``sot_patch`` dict compatible with
``apply_patch(state, patch)``, pre-populating:
  - requirements   (list[RequirementItem])
  - assumptions    (list[AssumptionItem])
  - open_questions (list[QuestionItem])
  - risks          (list[RiskItem])

Usage::

    from app.services.document_ingestion import ingest_document

    result = ingest_document(content, filename="brd.md")
    # result = {"sot_patch": {...}, "summary_message": "I have reviewed 'brd.md'..."}
"""

from __future__ import annotations

import re

# ── Compiled regex patterns ────────────────────────────────────────────────────

_H1_H2_RE = re.compile(r"^#{1,2}\s+(.+)", re.MULTILINE)
_H3_H6_RE = re.compile(r"^#{3,6}\s+(.+)", re.MULTILINE)
_UPPER_TITLE_RE = re.compile(r"^([A-Z][A-Z\s\-]{3,})$", re.MULTILINE)

_BULLET_RE = re.compile(r"^\s*[-*•]\s+(.+)")
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.+)")
_REQ_ID_RE = re.compile(r"\[R-\d+\]|\bREQ-\d+\b", re.IGNORECASE)
_MODAL_RE = re.compile(r"\b(shall|must|should)\b", re.IGNORECASE)

_ASSUME_RE = re.compile(
    r"(?i)^\s*(assume[sd]?|assuming|as a baseline|given that|it is assumed|we assume)\b\s*[,:]?\s*(.+)"
)

_QUESTION_RE = re.compile(r".+\?$")
_TBD_RE = re.compile(r"\bTBD\b|to be determined", re.IGNORECASE)

_RISK_PREFIX_RE = re.compile(r"(?i)^\s*(risk\s*:|risk of|potential risk|key risk)\s*(.+)")
_RISK_SIGNAL_RE = re.compile(
    r"\b(dependency on|vendor lock|single point of failure|third[- ]party|"
    r"compliance risk|data breach|scope creep|budget overrun)\b",
    re.IGNORECASE,
)

_NFR_RE = re.compile(
    r"\b(performance|security|availability|scalability|reliability|"
    r"uptime|latency|throughput|compliance|audit|backup)\b",
    re.IGNORECASE,
)
_INTEG_RE = re.compile(
    r"\b(api|integration|interface|connector|webhook|sync|feed|import|export)\b",
    re.IGNORECASE,
)

_HIGH_LIKELIHOOD_RE = re.compile(
    r"\b(likely|probable|expected|high risk|critical)\b", re.IGNORECASE
)
_LOW_LIKELIHOOD_RE = re.compile(
    r"\b(unlikely|low risk|minor|edge case)\b", re.IGNORECASE
)

_MAX_TEXT_LEN = 500
_MAX_QUESTION_LEN = 300

# ── Document-type detection patterns ──────────────────────────────────────────

_BRD_SIGNALS_RE = re.compile(
    r"\b(business requirements?|brd|business requirement document|"
    r"project overview|business objective|business case|stakeholder requirements?)\b",
    re.IGNORECASE,
)
_PRD_SIGNALS_RE = re.compile(
    r"\b(product requirements?|prd|product requirement document|"
    r"user stor(?:y|ies)|acceptance criteria|feature specification|"
    r"product backlog|release plan)\b",
    re.IGNORECASE,
)
_SOW_SIGNALS_RE = re.compile(
    r"\b(statement of work|sow|scope of work|engagement terms?|"
    r"payment terms?|professional services agreement|"
    r"project deliverables?|milestone payment)\b",
    re.IGNORECASE,
)
_MARKET_EVAL_SIGNALS_RE = re.compile(
    r"\b(market (analysis|evaluation|assessment|research)|vendor (comparison|assessment|evaluation)|"
    r"build vs\.? buy|buy vs\.? build|make or buy|competitive analysis|"
    r"vendor scoring|vendor selection|market landscape|technology evaluation|"
    r"solution comparison|platform comparison|off[- ]the[- ]shelf)\b",
    re.IGNORECASE,
)
_COMMERCIALS_SIGNALS_RE = re.compile(
    r"\b(pricing (proposal|model|structure|plan)|commercial (proposal|terms|offer)|"
    r"cost (estimate|breakdown|proposal)|rate card|billing (model|schedule)|"
    r"payment schedule|commercial pricing|project (cost|budget estimate)|"
    r"invoice schedule|licensing (fee|cost)|per[- ]seat pricing|"
    r"fixed[- ]price|time and materials|retainer)\b",
    re.IGNORECASE,
)
_TECH_DESIGN_SIGNALS_RE = re.compile(
    r"\b(technical (design|specification|architecture|spec)|system design|"
    r"architecture (document|overview|diagram)|component diagram|"
    r"api design|api specification|openapi|database schema|er diagram|"
    r"entity[- ]relationship|data model|class diagram|sequence diagram|"
    r"implementation plan|tech stack|infrastructure design|"
    r"software architecture|design document|technical blueprint|"
    r"system architecture|microservices|service mesh|deployment architecture)\b",
    re.IGNORECASE,
)

# ── Gap-analysis configuration ─────────────────────────────────────────────────

_REQUIRED_SECTIONS: dict[str, list[str]] = {
    "brd": [
        "business context", "objectives", "requirements",
        "assumptions", "stakeholders", "risks",
    ],
    "prd": [
        "overview", "user stories", "acceptance criteria",
        "non-functional requirements", "timeline",
    ],
    "sow": [
        "scope", "deliverables", "milestones",
        "payment terms", "assumptions", "risks",
    ],
    "technical_design": [
        "architecture", "components", "data model",
        "api", "tech stack", "non-functional requirements",
    ],
    "market_eval": [
        "evaluation criteria", "vendor options", "recommendation",
        "cost comparison", "risks",
    ],
    "commercials": [
        "pricing", "payment schedule", "milestones",
        "rate card", "assumptions",
    ],
}

_GAP_QUESTIONS: dict[str, str] = {
    "business context":           "What is the core business problem this project solves?",
    "objectives":                 "What are the measurable success criteria for this project?",
    "stakeholders":               "Who are the key stakeholders and their roles?",
    "requirements":               "Are there additional functional or non-functional requirements to capture?",
    "user stories":               "Can you provide user stories or use cases for the main workflows?",
    "acceptance criteria":        "What are the acceptance criteria for the key features?",
    "overview":                   "Can you provide a high-level overview and purpose of this product?",
    "non-functional requirements":"What are the performance, security, and scalability requirements?",
    "milestones":                 "What are the key project milestones and target dates?",
    "payment terms":              "What are the proposed payment terms and schedule?",
    "scope":                      "What is explicitly in scope vs. out of scope for this engagement?",
    "deliverables":               "What specific deliverables are expected at each milestone?",
    "timeline":                   "What is the expected project timeline and go-live date?",
    "assumptions":                "What key assumptions underpin this document?",
    "risks":                      "What are the primary risks and proposed mitigations?",
    # Technical design specific
    "architecture":               "Can you describe the overall system architecture and main components?",
    "components":                 "What are the key services/modules and how do they interact?",
    "data model":                 "What are the primary data entities and their relationships?",
    "api":                        "Are there existing APIs or integration points we should be aware of?",
    "tech stack":                 "What is the preferred technology stack (language, framework, database)?",
    # Market evaluation specific
    "evaluation criteria":        "What criteria are most important for the vendor/solution selection?",
    "vendor options":             "Which vendors or solutions have been shortlisted for evaluation?",
    "recommendation":             "What is the recommended build/buy/hybrid decision and rationale?",
    "cost comparison":            "What are the comparative costs across the shortlisted options?",
    # Commercials specific
    "pricing":                    "What are the proposed fees — fixed-price, T&M, or retainer?",
    "payment schedule":           "What are the payment milestones and due dates?",
    "rate card":                  "What are the day/hourly rates for each role in the team?",
}


# ── Private helpers ───────────────────────────────────────────────────────────

def _infer_category(text: str) -> str:
    """Return 'non_functional', 'integration', or 'functional' based on keywords."""
    if _NFR_RE.search(text):
        return "non_functional"
    if _INTEG_RE.search(text):
        return "integration"
    return "functional"


def _infer_likelihood(text: str) -> str:
    """Return 'high', 'low', or 'medium' based on likelihood keywords."""
    if _HIGH_LIKELIHOOD_RE.search(text):
        return "high"
    if _LOW_LIKELIHOOD_RE.search(text):
        return "low"
    return "medium"


def _strip_bullet(line: str) -> str:
    """Remove leading bullet/numbered-list prefix from a line."""
    m = _BULLET_RE.match(line)
    if m:
        return m.group(1).strip()
    m = _NUMBERED_RE.match(line)
    if m:
        return m.group(1).strip()
    return line.strip()


def _truncate(text: str, max_len: int) -> str:
    if len(text) > max_len:
        return text[:max_len] + " [truncated]"
    return text


def _is_meaningful(text: str) -> bool:
    """Return True if the stripped text has at least 3 word-chars."""
    return bool(re.search(r"\w{3}", text))


def _find_section(sections: dict[str, str], candidates: list[str]) -> str | None:
    """Return the body of the first section whose key contains any candidate substring."""
    for candidate in candidates:
        for key, body in sections.items():
            if key == "_full_document":
                continue
            if candidate in key:
                return body
    return None


# ── Section splitter ──────────────────────────────────────────────────────────

def extract_sections(content: str) -> dict[str, str]:
    """Split a document into named sections.

    Heading detection priority:
      1. Markdown H1/H2: ``## Title``
      2. Markdown H3-H6: ``### Title``
      3. ALL-CAPS titles: ``REQUIREMENTS`` (4+ chars)

    Returns a dict mapping normalized heading text (lowercase) to section body.
    The key ``"_full_document"`` always contains the original content.
    """
    sections: dict[str, str] = {"_full_document": content}
    lines = content.splitlines()
    current_key: str | None = None
    current_body: list[str] = []

    for line in lines:
        heading: str | None = None

        m = _H1_H2_RE.match(line)
        if m:
            heading = m.group(1).strip()
        if heading is None:
            m = _H3_H6_RE.match(line)
            if m:
                heading = m.group(1).strip()
        if heading is None:
            m = _UPPER_TITLE_RE.match(line.rstrip())
            if m:
                heading = m.group(1).strip()

        if heading:
            # Save previous section
            if current_key is not None:
                sections[current_key] = "\n".join(current_body).strip()
            current_key = heading.lower()
            current_body = []
        else:
            if current_key is not None:
                current_body.append(line)

    # Save last section
    if current_key is not None:
        sections[current_key] = "\n".join(current_body).strip()

    return sections


# ── Requirements extraction ───────────────────────────────────────────────────

def extract_requirements(text: str) -> list[dict]:
    """Extract requirement items from text.

    Detects:
      - Lines with explicit IDs: ``[R-1]``, ``REQ-001``
      - Bullet / numbered-list items
      - Lines containing modal verbs: shall, must, should

    Returns list of dicts compatible with ``RequirementItem`` constructor.
    Each item has: category, text, source, priority, accepted.
    The ``id`` field is intentionally omitted — Pydantic generates it via
    ``default_factory`` when ``apply_patch`` reconstructs the model.
    """
    if not text or not text.strip():
        return []

    seen: set[str] = set()
    results: list[dict] = []

    for line in text.splitlines():
        raw = line.strip()
        if not raw or not _is_meaningful(raw):
            continue

        # Determine if this line is a requirement candidate
        is_req = False

        if _REQ_ID_RE.search(raw):
            is_req = True
        elif _BULLET_RE.match(line) or _NUMBERED_RE.match(line):
            is_req = True
        elif _MODAL_RE.search(raw):
            is_req = True

        if not is_req:
            continue

        # Strip bullet prefix for cleaner text
        text_clean = _strip_bullet(raw)
        if not _is_meaningful(text_clean):
            continue

        # Deduplicate by normalized text
        key = text_clean.lower().strip()
        if key in seen:
            continue
        seen.add(key)

        results.append({
            "category": _infer_category(text_clean),
            "text": _truncate(text_clean, _MAX_TEXT_LEN),
            "source": "document_upload",
            "priority": "medium",
            "accepted": True,
        })

    return results


# ── Assumptions extraction ────────────────────────────────────────────────────

def extract_assumptions(text: str) -> list[dict]:
    """Extract assumption items from text.

    Detects:
      - Lines beginning with assume/assuming/as a baseline/given that
      - Bullet items in an assumptions section body

    Returns list of dicts compatible with ``AssumptionItem`` constructor.
    """
    if not text or not text.strip():
        return []

    seen: set[str] = set()
    results: list[dict] = []

    for line in text.splitlines():
        raw = line.strip()
        if not raw or not _is_meaningful(raw):
            continue

        assumption_text: str | None = None

        m = _ASSUME_RE.match(raw)
        if m:
            assumption_text = m.group(2).strip()
        elif _BULLET_RE.match(line) or _NUMBERED_RE.match(line):
            # Bullet in what is presumably an assumptions section body
            assumption_text = _strip_bullet(raw)

        if not assumption_text or not _is_meaningful(assumption_text):
            continue

        key = assumption_text.lower().strip()
        if key in seen:
            continue
        seen.add(key)

        results.append({
            "text": _truncate(assumption_text, _MAX_TEXT_LEN),
            "confirmed": False,
        })

    return results


# ── Questions extraction ──────────────────────────────────────────────────────

def extract_questions(text: str) -> list[dict]:
    """Extract open question items from text.

    Detects:
      - Lines ending with ``?``
      - Lines containing ``TBD`` or ``to be determined``

    Returns list of dicts compatible with ``QuestionItem`` constructor.
    """
    if not text or not text.strip():
        return []

    seen: set[str] = set()
    results: list[dict] = []

    for line in text.splitlines():
        raw = line.strip()
        if not raw or not _is_meaningful(raw):
            continue

        question_text: str | None = None

        clean = _strip_bullet(raw)
        if _QUESTION_RE.match(clean):
            question_text = clean
        elif _TBD_RE.search(raw):
            question_text = clean

        if not question_text or not _is_meaningful(question_text):
            continue

        key = question_text.lower().strip()
        if key in seen:
            continue
        seen.add(key)

        results.append({
            "question": _truncate(question_text, _MAX_QUESTION_LEN),
            "category": "general",
            "answered": False,
            "answer": None,
        })

    return results


# ── Risks extraction ──────────────────────────────────────────────────────────

def extract_risks(text: str) -> list[dict]:
    """Extract risk items from text.

    Detects:
      - Lines with explicit risk prefix: ``Risk:``, ``Risk of``, ``Key risk``
      - Lines containing known risk-signal phrases (vendor lock-in, etc.)
      - Bullet items in a risks section body

    Returns list of dicts compatible with ``RiskItem`` constructor.
    """
    if not text or not text.strip():
        return []

    seen: set[str] = set()
    results: list[dict] = []

    for line in text.splitlines():
        raw = line.strip()
        if not raw or not _is_meaningful(raw):
            continue

        risk_desc: str | None = None

        m = _RISK_PREFIX_RE.match(raw)
        if m:
            risk_desc = m.group(2).strip()
        elif _RISK_SIGNAL_RE.search(raw):
            risk_desc = _strip_bullet(raw)
        elif _BULLET_RE.match(line) or _NUMBERED_RE.match(line):
            # Bullet in a risks section body
            risk_desc = _strip_bullet(raw)

        if not risk_desc or not _is_meaningful(risk_desc):
            continue

        key = risk_desc.lower().strip()
        if key in seen:
            continue
        seen.add(key)

        results.append({
            "description": _truncate(risk_desc, _MAX_TEXT_LEN),
            "likelihood": _infer_likelihood(risk_desc),
            "impact": "medium",
            "mitigation": "",
        })

    return results


# ── Document summary ──────────────────────────────────────────────────────────

def summarize_document(
    content: str,
    filename: str,
    extraction_result: dict,
) -> str:
    """Generate a human-readable summary message for ``last_user_message``.

    No LLM — pure string formatting.
    """
    total_words = len(content.split())
    name = f"'{filename}'" if filename else "an uploaded document"

    parts: list[str] = []
    req_count = len(extraction_result.get("requirements", []))
    ass_count = len(extraction_result.get("assumptions", []))
    que_count = len(extraction_result.get("open_questions", []))
    risk_count = len(extraction_result.get("risks", []))

    extracted_parts: list[str] = []
    if req_count:
        extracted_parts.append(f"{req_count} requirement{'s' if req_count != 1 else ''}")
    if ass_count:
        extracted_parts.append(f"{ass_count} assumption{'s' if ass_count != 1 else ''}")
    if que_count:
        extracted_parts.append(f"{que_count} open question{'s' if que_count != 1 else ''}")
    if risk_count:
        extracted_parts.append(f"{risk_count} risk{'s' if risk_count != 1 else ''}")

    parts.append(f"I have reviewed {name} ({total_words} words).")
    if extracted_parts:
        parts.append("Extracted: " + ", ".join(extracted_parts) + ".")
    else:
        parts.append("No structured items were automatically extracted.")
    parts.append("Please review the extracted items and continue discovery.")

    return " ".join(parts)


# ── Document type detection ───────────────────────────────────────────────────

def detect_document_type(content: str, filename: str = "") -> str:
    """Detect document type from filename hint and content signals.

    Returns:
        "brd" | "prd" | "sow" | "unknown"

    Detection priority:
      1. Filename substring match (strongest signal — explicit intent)
      2. Content signal match count (≥2 matches required to classify)
    """
    name_lower = filename.lower()

    # Filename hints
    if "brd" in name_lower or "business_req" in name_lower or "business-req" in name_lower:
        return "brd"
    if "prd" in name_lower or "product_req" in name_lower or "product-req" in name_lower:
        return "prd"
    if "sow" in name_lower or "statement_of_work" in name_lower or "statement-of-work" in name_lower:
        return "sow"

    # Filename hints for technical design
    if any(k in name_lower for k in (
        "tech_design", "technical_design", "tech-design", "architecture",
        "system_design", "system-design", "design_doc", "design-doc",
        "tech_spec", "technical_spec",
    )):
        return "technical_design"

    # Filename hints for market evaluation
    if any(k in name_lower for k in (
        "market_eval", "market-eval", "market_analysis", "market-analysis",
        "vendor_comparison", "vendor-comparison", "build_vs_buy", "build-vs-buy",
    )):
        return "market_eval"

    # Filename hints for commercials
    if any(k in name_lower for k in (
        "commercial", "pricing", "rate_card", "rate-card",
        "cost_estimate", "cost-estimate",
    )):
        return "commercials"

    # Content scoring — count signal matches
    scores: dict[str, int] = {
        "brd": len(_BRD_SIGNALS_RE.findall(content)),
        "prd": len(_PRD_SIGNALS_RE.findall(content)),
        "sow": len(_SOW_SIGNALS_RE.findall(content)),
        "technical_design": len(_TECH_DESIGN_SIGNALS_RE.findall(content)),
        "market_eval": len(_MARKET_EVAL_SIGNALS_RE.findall(content)),
        "commercials": len(_COMMERCIALS_SIGNALS_RE.findall(content)),
    }
    best_type, best_score = max(scores.items(), key=lambda x: x[1])
    return best_type if best_score >= 2 else "unknown"


def gap_analysis(sections: dict[str, str], document_type: str) -> list[str]:
    """Return targeted follow-up questions for sections missing from the document.

    Compares the detected sections against the required sections for the given
    document type.  Returns one question per missing section (in canonical order).

    Args:
        sections:      Output of ``extract_sections()`` — keys are normalised headings.
        document_type: One of "brd" | "prd" | "sow" | "unknown".

    Returns:
        Ordered list of question strings for gaps (empty list if doc type unknown
        or all required sections are present).
    """
    required = _REQUIRED_SECTIONS.get(document_type, [])
    if not required:
        return []

    # Section keys without the synthetic "_full_document" entry
    section_keys = set(sections.keys()) - {"_full_document"}

    questions: list[str] = []
    for section_name in required:
        # A required section is "covered" if any detected key contains it as a substring
        covered = any(section_name in key for key in section_keys)
        if not covered and section_name in _GAP_QUESTIONS:
            questions.append(_GAP_QUESTIONS[section_name])

    return questions


# ── Top-level orchestrator ────────────────────────────────────────────────────

def ingest_document(content: str, filename: str = "") -> dict:
    """Orchestrate full document ingestion.

    Splits the document into sections, routes each extractor to the most
    relevant section body (falling back to the full document), and assembles
    a ``sot_patch`` dict ready for ``apply_patch(state, patch)``.

    Args:
        content:  Raw document text (plain text or markdown).
        filename: Optional original filename (used in the summary message).

    Returns:
        A dict with two keys:
          ``sot_patch``      — dict mapping ProjectState list fields to extracted items.
                               Only non-empty lists are included so that ``apply_patch``
                               does not overwrite an already-populated field with ``[]``.
          ``summary_message``— Human-readable summary for ``last_user_message``.
    """
    if not content or not content.strip():
        return {"sot_patch": {}, "summary_message": "", "document_type": "unknown"}

    sections = extract_sections(content)
    document_type = detect_document_type(content, filename)
    followup_questions = gap_analysis(sections, document_type)

    # Route each extractor to the best-matching section body, fallback to full doc
    req_body = (
        _find_section(
            sections,
            ["requirements", "functional requirements",
             "non-functional requirements", "system requirements", "needs"]
        )
        or content
    )
    ass_body = (
        _find_section(
            sections,
            ["assumptions", "assumptions and constraints", "constraints"]
        )
        or content
    )
    que_body = (
        _find_section(
            sections,
            ["open questions", "open items", "clarifications",
             "tbd", "questions", "to be determined"]
        )
        or content
    )
    risk_body = (
        _find_section(
            sections,
            ["risks", "risk register", "risk factors", "risk assessment"]
        )
        or content
    )

    requirements = extract_requirements(req_body)
    assumptions = extract_assumptions(ass_body)
    questions = extract_questions(que_body)
    risks = extract_risks(risk_body)

    extraction_result = {
        "requirements": requirements,
        "assumptions": assumptions,
        "open_questions": questions,
        "risks": risks,
    }

    # Only include non-empty lists — prevents apply_patch from replacing an
    # already-populated SoT list field with an empty list.
    sot_patch: dict = {
        key: value
        for key, value in extraction_result.items()
        if value
    }

    # Always include document_type so agents can branch on it
    sot_patch["document_type"] = document_type

    # Include gap follow-up questions only when we have some
    if followup_questions:
        sot_patch["followup_questions"] = followup_questions

    summary_message = summarize_document(content, filename, extraction_result)

    return {
        "sot_patch": sot_patch,
        "summary_message": summary_message,
        "document_type": document_type,
    }
