"""Document helper routes — UI upload support.

Endpoints:
  POST /documents/extract — upload a document and extract plain text
"""

from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

router = APIRouter(prefix="/documents", tags=["documents"])


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=422,
            detail="PDF support requires 'pypdf' dependency.",
        ) from exc

    reader = PdfReader(BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _extract_docx(data: bytes) -> str:
    try:
        import docx  # python-docx
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=422,
            detail="DOCX support requires 'python-docx' dependency.",
        ) from exc

    document = docx.Document(BytesIO(data))
    paras = [p.text.strip() for p in document.paragraphs if p.text and p.text.strip()]
    return "\n".join(paras)


@router.post("/extract")
async def extract_document_text(file: UploadFile = File(...)) -> dict:
    """Extract plain text from an uploaded file.

    Supported:
      - text/*, .txt, .md, .csv, .json
      - application/pdf
      - .docx (Office Open XML)

    Images are accepted but will return empty text (OCR is not enabled yet).
    """
    filename = file.filename or "upload"
    content_type = file.content_type or "application/octet-stream"
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty file upload")

    name_lower = filename.lower()

    # Images: accept, but no OCR for now
    if content_type.startswith("image/") or name_lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return {
            "filename": filename,
            "content_type": content_type,
            "text": "",
            "warnings": ["Image received. OCR/vision extraction not enabled yet."],
        }

    # PDF
    if content_type == "application/pdf" or name_lower.endswith(".pdf"):
        return {
            "filename": filename,
            "content_type": content_type,
            "text": _extract_pdf(data),
            "warnings": [],
        }

    # DOCX
    if (
        content_type
        in (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        )
        or name_lower.endswith(".docx")
    ):
        return {
            "filename": filename,
            "content_type": content_type,
            "text": _extract_docx(data),
            "warnings": [],
        }

    # Text-ish fallbacks
    if (
        content_type.startswith("text/")
        or name_lower.endswith((".txt", ".md", ".markdown", ".csv", ".json", ".log", ".yaml", ".yml"))
    ):
        return {
            "filename": filename,
            "content_type": content_type,
            "text": _decode_text(data),
            "warnings": [],
        }

    raise HTTPException(
        status_code=415,
        detail=f"Unsupported file type for text extraction: {content_type} ({filename})",
    )


@router.post("/extract_and_save")
async def extract_and_save(
    file: UploadFile = File(...),
    project_id: int = Form(...),
    run_id: int | None = Form(None),
) -> dict:
    """Extract plain text and persist it as an artifact for the project.

    Persists extracted text (UTF-8) as a text file artifact so it can be listed
    and retrieved later via the artifacts endpoints.
    """
    extracted = await extract_document_text(file=file)
    text = extracted.get("text", "")

    # Lazy DB usage: only for persistence
    try:
        from app.db.session import SessionLocal
        from app.services.artifacts import create_text_artifact
        with SessionLocal() as db:
            artifact = create_text_artifact(
                db,
                project_id=project_id,
                artifact_type="input_document",
                content=text or "",
                source_filename=extracted.get("filename") or "",
            )
        extracted["artifact_id"] = artifact.id
        extracted["artifact_type"] = artifact.type
        extracted["artifact_version"] = artifact.version
        extracted["run_id"] = run_id
    except Exception as exc:  # noqa: BLE001
        extracted.setdefault("warnings", [])
        extracted["warnings"].append(f"Could not persist upload artifact: {exc}")

    return extracted

