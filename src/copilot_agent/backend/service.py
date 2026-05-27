from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from copilot_agent.phase_one import PhaseOneReport
from copilot_agent.sandbox_backend import validate_sandbox_backend

from .models import (
    Approval,
    Artifact,
    Project,
    RunEvent,
    RunEventType,
    RunRecord,
    RunStatus,
    ToolCall,
)
from .policy import ToolDecision, ToolPolicyEngine
from .store import SQLiteBackendStore

SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)
SECRET_VALUE_PATTERN = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|[A-Za-z0-9_-]{24,})\b")


@dataclass(frozen=True)
class ToolReview:
    decision: ToolDecision
    tool_call: ToolCall
    approval: Approval | None = None


class CopilotBackendService:
    """Application service for the Copilot product control plane."""

    def __init__(
        self,
        store: SQLiteBackendStore,
        policy: ToolPolicyEngine | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or ToolPolicyEngine()

    def initialize(self) -> None:
        self.store.initialize()

    def create_project(
        self,
        *,
        name: str,
        repo_path: str | Path,
        memory_path: str | Path | None = None,
        default_model_provider: str | None = None,
    ) -> Project:
        project = Project(
            id=_new_id("proj"),
            name=name.strip(),
            repo_path=str(Path(repo_path).resolve()),
            memory_path=str(Path(memory_path).resolve()) if memory_path else None,
            default_model_provider=default_model_provider,
        )
        if not project.name:
            raise ValueError("Project name must not be empty.")
        return self.store.create_project(project)

    def get_project(self, project_id: str) -> Project:
        project = self.store.get_project(project_id)
        if project is None:
            raise FileNotFoundError(f"Project not found: {project_id}")
        return project

    def list_projects(self) -> list[Project]:
        return self.store.list_projects()

    def queue_run(
        self,
        *,
        project_id: str,
        task: str,
        model_provider: str,
        model: str,
        tool_strategy: str,
        sandbox_backend: str = "unix_local",
    ) -> RunRecord:
        if self.store.get_project(project_id) is None:
            raise FileNotFoundError(f"Project not found: {project_id}")
        if not task.strip():
            raise ValueError("Run task must not be empty.")
        validate_sandbox_backend(sandbox_backend)

        run = self.store.create_run(
            RunRecord(
                id=_new_id("run"),
                project_id=project_id,
                task=task.strip(),
                status="queued",
                model_provider=model_provider,
                model=model,
                tool_strategy=tool_strategy,
                sandbox_backend=sandbox_backend,
            )
        )
        self.record_event(
            run.id,
            "run.queued",
            {
                "project_id": project_id,
                "model_provider": model_provider,
                "model": model,
                "tool_strategy": tool_strategy,
                "sandbox_backend": sandbox_backend,
            },
        )
        return run

    def get_run(self, run_id: str) -> RunRecord:
        run = self.store.get_run(run_id)
        if run is None:
            raise FileNotFoundError(f"Run not found: {run_id}")
        return run

    def list_runs(self, project_id: str | None = None) -> list[RunRecord]:
        if project_id is not None and self.store.get_project(project_id) is None:
            raise FileNotFoundError(f"Project not found: {project_id}")
        return self.store.list_runs(project_id)

    def start_run(self, run_id: str) -> RunRecord:
        run = self.store.update_run_status(run_id, "running")
        self.record_event(run.id, "run.started", {"status": run.status})
        return run

    def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        *,
        summary: str = "",
        saved_dir: str | Path | None = None,
        diff_path: str | Path | None = None,
    ) -> RunRecord:
        run = self.store.update_run_status(
            run_id,
            status,
            summary=summary,
            saved_dir=str(saved_dir) if saved_dir else None,
            diff_path=str(diff_path) if diff_path else None,
        )
        self.record_event(
            run.id,
            _event_type_for_status(status),
            {
                "status": status,
                "saved_dir": run.saved_dir,
                "diff_path": run.diff_path,
                "summary": run.summary,
            },
        )
        return run

    def record_tool_decision(
        self,
        *,
        run_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ToolReview:
        if self.store.get_run(run_id) is None:
            raise FileNotFoundError(f"Run not found: {run_id}")

        redacted_args = redact_secrets(arguments or {})
        decision = self.policy.decide(tool_name, redacted_args)
        approval = None
        if decision.requires_approval:
            approval = self.store.create_approval(
                Approval(
                    id=_new_id("appr"),
                    run_id=run_id,
                    tool_name=tool_name,
                    risk=decision.risk,
                    arguments_redacted=redacted_args,
                )
            )
            status = "needs_approval"
        elif decision.action == "deny":
            status = "denied"
        else:
            status = "allowed"

        tool_call = self.store.create_tool_call(
            ToolCall(
                id=_new_id("tool"),
                run_id=run_id,
                tool_name=tool_name,
                arguments_redacted=redacted_args,
                action=decision.action,
                status=status,
                risk=decision.risk,
                reason=decision.reason,
                approval_id=approval.id if approval else None,
            )
        )
        self.record_event(
            run_id,
            "tool.reviewed",
            {
                "tool_call_id": tool_call.id,
                "tool_name": tool_name,
                "action": decision.action,
                "risk": decision.risk,
                "approval_id": approval.id if approval else None,
            },
        )
        if approval is not None:
            self.store.update_run_status(run_id, "needs_approval")
            self.record_event(
                run_id,
                "approval.required",
                {
                    "approval_id": approval.id,
                    "tool_name": tool_name,
                    "risk": decision.risk,
                },
            )
            self.record_event(run_id, "run.needs_approval", {"status": "needs_approval"})
        return ToolReview(decision=decision, tool_call=tool_call, approval=approval)

    def list_tool_calls(self, run_id: str) -> list[ToolCall]:
        self.get_run(run_id)
        return self.store.list_tool_calls(run_id)

    def decide_approval(
        self,
        approval_id: str,
        *,
        approved: bool,
        decided_by: str,
    ) -> Approval:
        decision = "approved" if approved else "rejected"
        approval = self.store.decide_approval(
            approval_id,
            decision,
            decided_by=decided_by,
        )
        self.record_event(
            approval.run_id,
            "approval.decided",
            {
                "approval_id": approval.id,
                "decision": approval.decision,
                "decided_by": approval.decided_by,
            },
        )
        return approval

    def list_approvals(self, run_id: str) -> list[Approval]:
        self.get_run(run_id)
        return self.store.list_approvals(run_id)

    def list_artifacts(self, run_id: str) -> list[Artifact]:
        self.get_run(run_id)
        return self.store.list_artifacts(run_id)

    def list_events(self, run_id: str) -> list[RunEvent]:
        self.get_run(run_id)
        return self.store.list_events(run_id)

    def record_event(
        self,
        run_id: str,
        event_type: RunEventType,
        payload: dict[str, Any] | None = None,
    ) -> RunEvent:
        return self.store.create_event(
            RunEvent(
                id=_new_id("evt"),
                run_id=run_id,
                event_type=event_type,
                payload=payload or {},
            )
        )

    def ingest_phase_one_report(
        self,
        project_id: str,
        report: PhaseOneReport,
        *,
        run_id: str | None = None,
    ) -> RunRecord:
        """Persist a completed phase-one CLI report as backend run state."""

        if self.store.get_project(project_id) is None:
            raise FileNotFoundError(f"Project not found: {project_id}")

        target_run_id = run_id or report.run_id
        status = _status_from_report(report)
        diff_path = Path(report.saved_dir) / "diff.patch" if report.saved_dir else None
        existing = self.store.get_run(target_run_id)
        if existing is None:
            run = self.store.create_run(
                RunRecord(
                    id=target_run_id,
                    project_id=project_id,
                    task=report.task,
                    status="running",
                    model_provider=report.model_provider,
                    model=report.model,
                    tool_strategy=report.tool_strategy,
                    sandbox_backend=report.sandbox_backend,
                )
            )
        else:
            run = existing
        self._record_report_runtime_events(run.id, report)

        if report.saved_dir:
            self._record_report_artifacts(run.id, Path(report.saved_dir), report)

        run = self.store.update_run_status(
            run.id,
            status,
            summary=report.final_output,
            saved_dir=report.saved_dir,
            diff_path=str(diff_path) if diff_path else None,
        )
        self.record_event(
            run.id,
            _event_type_for_status(status),
            {
                "status": status,
                "saved_dir": run.saved_dir,
                "diff_path": run.diff_path,
                "summary": run.summary,
                "source_run_id": report.run_id,
            },
        )
        return run

    def _record_report_runtime_events(self, run_id: str, report: PhaseOneReport) -> None:
        if report.sandbox_runtime is not None:
            runtime = report.sandbox_runtime
            self.record_event(
                run_id,
                "sandbox.runtime_checked",
                {
                    "enabled": runtime.enabled,
                    "python_command": runtime.python_command,
                    "sandbox_test_cmd": runtime.sandbox_test_cmd,
                    "python_check_exit_code": (
                        runtime.python_check.exit_code if runtime.python_check else None
                    ),
                    "pytest_check_exit_code": (
                        runtime.pytest_check.exit_code if runtime.pytest_check else None
                    ),
                    "dependency_install_exit_code": (
                        runtime.dependency_install.exit_code
                        if runtime.dependency_install
                        else None
                    ),
                    "notes": runtime.notes,
                },
            )
        for kind, result in (
            ("sandbox", report.verification),
            ("host", report.host_verification),
        ):
            if result is None:
                continue
            self.record_event(
                run_id,
                "verification.completed",
                {
                    "kind": kind,
                    "command": result.command,
                    "exit_code": result.exit_code,
                },
            )

    def _record_report_artifacts(
        self,
        run_id: str,
        saved_dir: Path,
        report: PhaseOneReport,
    ) -> None:
        candidates = [
            ("report", saved_dir / "report.json", {}),
            ("summary", saved_dir / "final.md", {}),
            ("diff", saved_dir / "diff.patch", {"changed": bool(report.diff.strip())}),
            ("log", saved_dir / "sandbox_runtime.log", {"kind": "sandbox_runtime"}),
            ("log", saved_dir / "verification.log", {"kind": "sandbox_verification"}),
            ("log", saved_dir / "host_verification.log", {"kind": "host_verification"}),
        ]
        for kind, path, metadata in candidates:
            if path.exists():
                artifact = self.store.create_artifact(
                    Artifact(
                        id=_new_id("art"),
                        run_id=run_id,
                        kind=kind,
                        path=str(path),
                        metadata=metadata,
                    )
                )
                self.record_event(
                    run_id,
                    "artifact.created",
                    {
                        "artifact_id": artifact.id,
                        "kind": artifact.kind,
                        "path": artifact.path,
                    },
                )


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>" if _is_secret_key(key) else redact_secrets(inner)
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return SECRET_VALUE_PATTERN.sub("<redacted>", value)
    return value


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SECRET_KEY_PARTS)


def _status_from_report(report: PhaseOneReport) -> RunStatus:
    if report.host_verification is not None:
        return "succeeded" if report.host_verification.exit_code == 0 else "failed"
    if report.verification is not None:
        return "succeeded" if report.verification.exit_code == 0 else "failed"
    return "succeeded"


def _event_type_for_status(status: RunStatus) -> RunEventType:
    if status == "succeeded":
        return "run.completed"
    if status == "running":
        return "run.started"
    return f"run.{status}"


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"
