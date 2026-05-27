from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from copilot_agent.backend.models import (
    Approval,
    ApprovalDecision,
    Artifact,
    Project,
    RunEvent,
    RunRecord,
    RunStatus,
    ToolCall,
)
from copilot_agent.backend.service import ToolReview
from copilot_agent.worker import RunExecutionOptions


class ProjectCreate(BaseModel):
    name: str
    repo_path: str
    memory_path: str | None = None
    default_model_provider: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    repo_path: str
    memory_path: str | None
    default_model_provider: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, project: Project) -> ProjectResponse:
        return cls(**project.__dict__)


class RunCreate(BaseModel):
    project_id: str
    task: str
    model_provider: str
    model: str
    tool_strategy: str
    sandbox_backend: str = "unix_local"


class RunFinish(BaseModel):
    status: RunStatus
    summary: str = ""
    saved_dir: str | None = None
    diff_path: str | None = None


class RunExecute(BaseModel):
    test_cmd: str | None = None
    max_turns: int = 32
    output_dir: str = "runs"
    memory_enabled: bool | None = None
    host_verify: bool = False
    require_api_key: bool = True

    def to_options(self) -> RunExecutionOptions:
        return RunExecutionOptions(
            test_cmd=self.test_cmd,
            max_turns=self.max_turns,
            output_dir=Path(self.output_dir),
            memory_enabled=self.memory_enabled,
            host_verify=self.host_verify,
            require_api_key=self.require_api_key,
        )


class RunResponse(BaseModel):
    id: str
    project_id: str
    task: str
    status: RunStatus
    model_provider: str
    model: str
    tool_strategy: str
    sandbox_backend: str
    saved_dir: str | None
    diff_path: str | None
    summary: str
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, run: RunRecord) -> RunResponse:
        return cls(**run.__dict__)


class ToolReviewCreate(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallResponse(BaseModel):
    id: str
    run_id: str
    tool_name: str
    arguments_redacted: dict[str, Any]
    action: str
    status: str
    risk: str
    reason: str
    approval_id: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, tool_call: ToolCall) -> ToolCallResponse:
        return cls(**tool_call.__dict__)


class ApprovalResponse(BaseModel):
    id: str
    run_id: str
    tool_name: str
    risk: str
    decision: ApprovalDecision
    arguments_redacted: dict[str, Any]
    decided_by: str | None
    created_at: str
    decided_at: str | None

    @classmethod
    def from_domain(cls, approval: Approval) -> ApprovalResponse:
        return cls(**approval.__dict__)


class ToolReviewResponse(BaseModel):
    decision: str
    risk: str
    reason: str
    tool_call: ToolCallResponse
    approval: ApprovalResponse | None

    @classmethod
    def from_domain(cls, review: ToolReview) -> ToolReviewResponse:
        return cls(
            decision=review.decision.action,
            risk=review.decision.risk,
            reason=review.decision.reason,
            tool_call=ToolCallResponse.from_domain(review.tool_call),
            approval=(
                ApprovalResponse.from_domain(review.approval)
                if review.approval is not None
                else None
            ),
        )


class ApprovalDecisionCreate(BaseModel):
    approved: bool
    decided_by: str


class ArtifactResponse(BaseModel):
    id: str
    run_id: str
    kind: str
    path: str
    metadata: dict[str, Any]
    created_at: str

    @classmethod
    def from_domain(cls, artifact: Artifact) -> ArtifactResponse:
        return cls(**artifact.__dict__)


class RunEventResponse(BaseModel):
    id: str
    run_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str

    @classmethod
    def from_domain(cls, event: RunEvent) -> RunEventResponse:
        return cls(**event.__dict__)


class DiffResponse(BaseModel):
    run_id: str
    diff: str
    source: str | None = None


class ErrorResponse(BaseModel):
    detail: str
