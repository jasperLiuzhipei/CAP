from __future__ import annotations

import pytest

from copilot_agent.backend.models import Approval, Artifact, Project, RunEvent, RunRecord, ToolCall
from copilot_agent.backend.store import SQLiteBackendStore


def test_sqlite_store_round_trips_control_plane_records(tmp_path) -> None:
    store = SQLiteBackendStore(tmp_path / "control.sqlite")
    store.initialize()

    project = store.create_project(
        Project(
            id="proj_1",
            name="Sample",
            repo_path=str(tmp_path / "repo"),
            memory_path=str(tmp_path / "repo" / ".copilot" / "memory.md"),
            default_model_provider="deepseek",
        )
    )
    run = store.create_run(
        RunRecord(
            id="run_1",
            project_id=project.id,
            task="Fix bug",
            status="queued",
            model_provider="deepseek",
            model="deepseek-v4-flash",
            tool_strategy="compat_functions",
        )
    )
    approval = store.create_approval(
        Approval(
            id="appr_1",
            run_id=run.id,
            tool_name="apply_patch",
            risk="R1",
            arguments_redacted={"patch": "*** Begin Patch"},
        )
    )
    tool_call = store.create_tool_call(
        ToolCall(
            id="tool_1",
            run_id=run.id,
            tool_name="apply_patch",
            arguments_redacted={"patch": "*** Begin Patch"},
            action="approval_required",
            status="needs_approval",
            risk="R1",
            reason="review",
            approval_id=approval.id,
            result_summary="pending approval: review",
            duration_ms=12.5,
        )
    )
    artifact = store.create_artifact(
        Artifact(
            id="art_1",
            run_id=run.id,
            kind="diff",
            path=str(tmp_path / "diff.patch"),
            metadata={"changed": True},
        )
    )
    queued_event = store.create_event(
        RunEvent(
            id="evt_1",
            run_id=run.id,
            event_type="run.queued",
            payload={"task": run.task},
        )
    )
    completed_event = store.create_event(
        RunEvent(
            id="evt_2",
            run_id=run.id,
            event_type="run.completed",
            payload={"summary": "done"},
        )
    )

    updated_run = store.update_run_status(
        run.id,
        "succeeded",
        summary="done",
        saved_dir=str(tmp_path / "runs" / run.id),
        diff_path=artifact.path,
    )
    decided = store.decide_approval(approval.id, "approved", decided_by="jasper")
    completed_tool = store.update_tool_call_status(
        tool_call.id,
        "completed",
        result_summary="approved by jasper",
    )

    assert store.get_project(project.id) == project
    assert store.list_projects() == [project]
    assert store.list_runs(project.id) == [updated_run]
    assert store.get_run(run.id) == updated_run
    assert updated_run.status == "succeeded"
    assert decided.decision == "approved"
    assert decided.decided_by == "jasper"
    assert decided.decided_at is not None
    assert store.list_approvals(run.id) == [decided]
    assert completed_tool.status == "completed"
    assert completed_tool.result_summary == "approved by jasper"
    assert completed_tool.duration_ms == 12.5
    assert store.list_tool_calls(run.id) == [completed_tool]
    assert store.list_artifacts(run.id) == [artifact]
    assert store.list_events(run.id) == [queued_event, completed_event]


def test_sqlite_store_missing_records_raise_clear_errors(tmp_path) -> None:
    store = SQLiteBackendStore(tmp_path / "control.sqlite")
    store.initialize()

    with pytest.raises(FileNotFoundError, match="Run not found"):
        store.update_run_status("missing", "failed")
    with pytest.raises(FileNotFoundError, match="Approval not found"):
        store.decide_approval("missing", "rejected", decided_by="jasper")
    with pytest.raises(FileNotFoundError, match="Tool call not found"):
        store.update_tool_call_status("missing", "failed")


def test_sqlite_store_migrates_tool_trace_columns(tmp_path) -> None:
    db_path = tmp_path / "legacy.sqlite"
    store = SQLiteBackendStore(db_path)
    store.initialize()

    with store._connect() as conn:
        conn.execute("ALTER TABLE tool_calls RENAME TO tool_calls_old")
        conn.execute(
            """
            CREATE TABLE tool_calls (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                tool_name TEXT NOT NULL,
                arguments_redacted_json TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                risk TEXT NOT NULL,
                reason TEXT NOT NULL,
                approval_id TEXT REFERENCES approvals(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("DROP TABLE tool_calls_old")

    store.initialize()

    with store._connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(tool_calls)")}
    assert {"result_summary", "duration_ms"}.issubset(columns)
