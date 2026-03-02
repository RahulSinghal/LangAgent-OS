from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def test_extract_and_save_returns_artifact_metadata_when_persisted() -> None:
    from app.main import create_app

    fake_artifact = SimpleNamespace(id=123, type="input_document", version=1)

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    with patch("app.db.session.SessionLocal", return_value=FakeSession()):
        with patch("app.services.artifacts.create_text_artifact", return_value=fake_artifact):
            client = TestClient(create_app())
            files = {"file": ("x.txt", b"hello", "text/plain")}
            data = {"project_id": "1"}
            r = client.post("/api/v1/documents/extract_and_save", files=files, data=data)

    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "hello"
    assert body["artifact_id"] == 123
    assert body["artifact_type"] == "input_document"
    assert body["artifact_version"] == 1


def test_start_run_persists_user_message_and_bot_response() -> None:
    """Unit-test the persistence hooks without a real DB/workflow."""
    from app.services import runs as run_svc

    db = MagicMock()
    db.refresh = MagicMock()

    # Fake run row
    run_obj = SimpleNamespace(id=10, project_id=1, session_id=55, status="running", current_node=None)
    db.get.side_effect = lambda model, _id: run_obj if getattr(model, "__name__", "") == "Run" else None

    class FakeWorkflow:
        def invoke(self, wf_state):
            sot = wf_state["sot"]
            # Return a pause with bot_response so run engine persists assistant message
            return {
                "sot": sot,
                "pause_reason": "waiting_user",
                "bot_response": "Next question?",
                "approval_id": None,
            }

    with patch("app.services.runs.create_run", return_value=run_obj):
        with patch("app.workflow.graph.get_workflow", return_value=FakeWorkflow()):
            with patch("app.services.snapshots.save_snapshot"):
                with patch("app.services.runs.update_run_status", return_value=run_obj):
                    with patch("app.services.sessions.add_message") as add_msg:
                        run = run_svc.start_run(
                            db,
                            project_id=1,
                            session_id=55,
                            user_message="Hello",
                            document_content=None,
                            document_filename=None,
                        )

    assert run.id == 10
    # User message persisted
    add_msg.assert_any_call(db, session_id=55, role="user", content="Hello")
    # Assistant bot_response persisted
    add_msg.assert_any_call(db, session_id=55, role="assistant", content="Next question?")


def test_resolve_approval_persists_system_message() -> None:
    from app.services import approvals as approval_svc

    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()

    approval = SimpleNamespace(
        id=1,
        run_id=99,
        type="prd",
        status="pending",
        resolved_by=None,
        comments=None,
        resolved_at=None,
    )
    run = SimpleNamespace(id=99, session_id=77)

    def _get(model, _id):
        if getattr(model, "__name__", "") == "Approval":
            return approval
        if getattr(model, "__name__", "") == "Run":
            return run
        return None

    db.get.side_effect = _get

    with patch("app.services.sessions.add_message") as add_msg:
        with patch("app.services.runs.resume_run"):
            approval_svc.resolve_approval(
                db,
                approval_id=1,
                decision="approved",
                resolved_by="alice",
                comments="Looks good",
            )

    add_msg.assert_any_call(
        db,
        session_id=77,
        role="system",
        content="Approval resolved: type=prd, decision=approved.\nComments: Looks good",
    )

