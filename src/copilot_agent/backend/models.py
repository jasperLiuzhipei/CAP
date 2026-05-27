from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

RunStatus = Literal[
    "queued",
    "running",
    "needs_approval",
    "succeeded",
    "failed",
    "cancelled",
]
ApprovalDecision = Literal["pending", "approved", "rejected"]
ArtifactKind = Literal["report", "diff", "log", "summary", "memory", "other"]
ToolAction = Literal["allow", "approval_required", "deny"]
ToolCallStatus = Literal["allowed", "needs_approval", "denied", "completed", "failed"]
RunEventType = Literal[
    "run.queued",
    "run.started",
    "run.needs_approval",
    "run.completed",
    "run.failed",
    "run.cancelled",
    "tool.reviewed",
    "approval.required",
    "approval.decided",
    "artifact.created",
]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    repo_path: str
    memory_path: str | None = None
    default_model_provider: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class RunRecord:
    id: str
    project_id: str
    task: str
    status: RunStatus
    model_provider: str
    model: str
    tool_strategy: str
    sandbox_backend: str = "unix_local"
    saved_dir: str | None = None
    diff_path: str | None = None
    summary: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class Approval:
    id: str
    run_id: str
    tool_name: str
    risk: str
    decision: ApprovalDecision = "pending"
    arguments_redacted: dict[str, Any] = field(default_factory=dict)
    decided_by: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    decided_at: str | None = None


@dataclass(frozen=True)
class ToolCall:
    id: str
    run_id: str
    tool_name: str
    arguments_redacted: dict[str, Any]
    action: ToolAction
    status: ToolCallStatus
    risk: str
    reason: str
    approval_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class Artifact:
    id: str
    run_id: str
    kind: ArtifactKind
    path: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class RunEvent:
    id: str
    run_id: str
    event_type: RunEventType
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
