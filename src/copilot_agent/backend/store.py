from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import (
    Approval,
    ApprovalDecision,
    Artifact,
    Project,
    RunRecord,
    RunStatus,
    ToolCall,
    ToolCallStatus,
    utc_now_iso,
)

SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        repo_path TEXT NOT NULL,
        memory_path TEXT,
        default_model_provider TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        task TEXT NOT NULL,
        status TEXT NOT NULL,
        model_provider TEXT NOT NULL,
        model TEXT NOT NULL,
        tool_strategy TEXT NOT NULL,
        sandbox_backend TEXT NOT NULL,
        saved_dir TEXT,
        diff_path TEXT,
        summary TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        tool_name TEXT NOT NULL,
        risk TEXT NOT NULL,
        decision TEXT NOT NULL,
        arguments_redacted_json TEXT NOT NULL,
        decided_by TEXT,
        created_at TEXT NOT NULL,
        decided_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_calls (
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
    """,
    """
    CREATE TABLE IF NOT EXISTS artifacts (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        path TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
)


class SQLiteBackendStore:
    """Small SQLite repository for the product control-plane state."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)

    def initialize(self) -> None:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            for statement in SCHEMA:
                conn.execute(statement)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create_project(self, project: Project) -> Project:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO projects (
                    id, name, repo_path, memory_path, default_model_provider,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project.id,
                    project.name,
                    project.repo_path,
                    project.memory_path,
                    project.default_model_provider,
                    project.created_at,
                    project.updated_at,
                ),
            )
        return project

    def get_project(self, project_id: str) -> Project | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return _row_to_project(row) if row else None

    def list_projects(self) -> list[Project]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at").fetchall()
        return [_row_to_project(row) for row in rows]

    def create_run(self, run: RunRecord) -> RunRecord:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    id, project_id, task, status, model_provider, model, tool_strategy,
                    sandbox_backend, saved_dir, diff_path, summary, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.project_id,
                    run.task,
                    run.status,
                    run.model_provider,
                    run.model,
                    run.tool_strategy,
                    run.sandbox_backend,
                    run.saved_dir,
                    run.diff_path,
                    run.summary,
                    run.created_at,
                    run.updated_at,
                ),
            )
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _row_to_run(row) if row else None

    def list_runs(self, project_id: str | None = None) -> list[RunRecord]:
        with self._connect() as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE project_id = ? ORDER BY created_at",
                    (project_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM runs ORDER BY created_at").fetchall()
        return [_row_to_run(row) for row in rows]

    def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        summary: str | None = None,
        saved_dir: str | None = None,
        diff_path: str | None = None,
    ) -> RunRecord:
        existing = self.get_run(run_id)
        if existing is None:
            raise FileNotFoundError(f"Run not found: {run_id}")

        updated = replace(
            existing,
            status=status,
            summary=existing.summary if summary is None else summary,
            saved_dir=existing.saved_dir if saved_dir is None else saved_dir,
            diff_path=existing.diff_path if diff_path is None else diff_path,
            updated_at=utc_now_iso(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status = ?, summary = ?, saved_dir = ?, diff_path = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updated.status,
                    updated.summary,
                    updated.saved_dir,
                    updated.diff_path,
                    updated.updated_at,
                    updated.id,
                ),
            )
        return updated

    def create_approval(self, approval: Approval) -> Approval:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals (
                    id, run_id, tool_name, risk, decision, arguments_redacted_json,
                    decided_by, created_at, decided_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval.id,
                    approval.run_id,
                    approval.tool_name,
                    approval.risk,
                    approval.decision,
                    _json_dumps(approval.arguments_redacted),
                    approval.decided_by,
                    approval.created_at,
                    approval.decided_at,
                ),
            )
        return approval

    def get_approval(self, approval_id: str) -> Approval | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE id = ?",
                (approval_id,),
            ).fetchone()
        return _row_to_approval(row) if row else None

    def list_approvals(self, run_id: str) -> list[Approval]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM approvals WHERE run_id = ? ORDER BY created_at",
                (run_id,),
            ).fetchall()
        return [_row_to_approval(row) for row in rows]

    def decide_approval(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        *,
        decided_by: str,
    ) -> Approval:
        existing = self.get_approval(approval_id)
        if existing is None:
            raise FileNotFoundError(f"Approval not found: {approval_id}")

        decided_at = utc_now_iso() if decision != "pending" else None
        updated = replace(
            existing,
            decision=decision,
            decided_by=decided_by if decision != "pending" else None,
            decided_at=decided_at,
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE approvals
                SET decision = ?, decided_by = ?, decided_at = ?
                WHERE id = ?
                """,
                (updated.decision, updated.decided_by, updated.decided_at, updated.id),
            )
        return updated

    def create_tool_call(self, tool_call: ToolCall) -> ToolCall:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_calls (
                    id, run_id, tool_name, arguments_redacted_json, action, status,
                    risk, reason, approval_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_call.id,
                    tool_call.run_id,
                    tool_call.tool_name,
                    _json_dumps(tool_call.arguments_redacted),
                    tool_call.action,
                    tool_call.status,
                    tool_call.risk,
                    tool_call.reason,
                    tool_call.approval_id,
                    tool_call.created_at,
                    tool_call.updated_at,
                ),
            )
        return tool_call

    def list_tool_calls(self, run_id: str) -> list[ToolCall]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY created_at",
                (run_id,),
            ).fetchall()
        return [_row_to_tool_call(row) for row in rows]

    def update_tool_call_status(
        self,
        tool_call_id: str,
        status: ToolCallStatus,
    ) -> ToolCall:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tool_calls WHERE id = ?",
                (tool_call_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Tool call not found: {tool_call_id}")

        updated = replace(_row_to_tool_call(row), status=status, updated_at=utc_now_iso())
        with self._connect() as conn:
            conn.execute(
                "UPDATE tool_calls SET status = ?, updated_at = ? WHERE id = ?",
                (updated.status, updated.updated_at, updated.id),
            )
        return updated

    def create_artifact(self, artifact: Artifact) -> Artifact:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (id, run_id, kind, path, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.id,
                    artifact.run_id,
                    artifact.kind,
                    artifact.path,
                    _json_dumps(artifact.metadata),
                    artifact.created_at,
                ),
            )
        return artifact

    def list_artifacts(self, run_id: str) -> list[Artifact]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at",
                (run_id,),
            ).fetchall()
        return [_row_to_artifact(row) for row in rows]


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _json_loads(payload: str) -> dict[str, Any]:
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        return {}
    return decoded


def _row_to_project(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        repo_path=row["repo_path"],
        memory_path=row["memory_path"],
        default_model_provider=row["default_model_provider"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_run(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        id=row["id"],
        project_id=row["project_id"],
        task=row["task"],
        status=row["status"],
        model_provider=row["model_provider"],
        model=row["model"],
        tool_strategy=row["tool_strategy"],
        sandbox_backend=row["sandbox_backend"],
        saved_dir=row["saved_dir"],
        diff_path=row["diff_path"],
        summary=row["summary"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_approval(row: sqlite3.Row) -> Approval:
    return Approval(
        id=row["id"],
        run_id=row["run_id"],
        tool_name=row["tool_name"],
        risk=row["risk"],
        decision=row["decision"],
        arguments_redacted=_json_loads(row["arguments_redacted_json"]),
        decided_by=row["decided_by"],
        created_at=row["created_at"],
        decided_at=row["decided_at"],
    )


def _row_to_tool_call(row: sqlite3.Row) -> ToolCall:
    return ToolCall(
        id=row["id"],
        run_id=row["run_id"],
        tool_name=row["tool_name"],
        arguments_redacted=_json_loads(row["arguments_redacted_json"]),
        action=row["action"],
        status=row["status"],
        risk=row["risk"],
        reason=row["reason"],
        approval_id=row["approval_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_artifact(row: sqlite3.Row) -> Artifact:
    return Artifact(
        id=row["id"],
        run_id=row["run_id"],
        kind=row["kind"],
        path=row["path"],
        metadata=_json_loads(row["metadata_json"]),
        created_at=row["created_at"],
    )
