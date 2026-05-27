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
from copilot_agent.sandbox_backend import SandboxBackendSpec
from copilot_agent.worker import BackgroundWorkerStatus, RunExecutionOptions


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
    model_provider: str | None = None
    model: str | None = None
    tool_strategy: str | None = None
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
    sandbox_runtime_enabled: bool = True
    sandbox_python: str = "python3"
    require_api_key: bool = True

    def to_options(self) -> RunExecutionOptions:
        return RunExecutionOptions(
            test_cmd=self.test_cmd,
            max_turns=self.max_turns,
            output_dir=Path(self.output_dir),
            memory_enabled=self.memory_enabled,
            host_verify=self.host_verify,
            sandbox_runtime_enabled=self.sandbox_runtime_enabled,
            sandbox_python=self.sandbox_python,
            require_api_key=self.require_api_key,
        )


class WorkerStatusResponse(BaseModel):
    running: bool
    queue_size: int
    active_run_id: str | None
    processed_count: int
    failed_count: int

    @classmethod
    def from_domain(cls, status: BackgroundWorkerStatus) -> WorkerStatusResponse:
        return cls(**status.__dict__)


class RuntimeConfigResponse(BaseModel):
    db_path: str | None
    auto_start_background_worker: bool
    worker_test_cmd: str | None
    worker_max_turns: int
    worker_output_dir: str
    worker_memory_enabled: bool | None
    worker_host_verify: bool
    worker_require_api_key: bool
    sandbox_runtime_enabled: bool
    sandbox_python: str

    @classmethod
    def from_worker_options(
        cls,
        *,
        runtime_config: dict[str, Any],
        options: RunExecutionOptions,
    ) -> RuntimeConfigResponse:
        return cls(
            db_path=runtime_config.get("db_path") if runtime_config else None,
            auto_start_background_worker=bool(
                runtime_config.get("auto_start_background_worker", False)
            ),
            worker_test_cmd=options.test_cmd,
            worker_max_turns=options.max_turns,
            worker_output_dir=str(options.output_dir),
            worker_memory_enabled=options.memory_enabled,
            worker_host_verify=options.host_verify,
            worker_require_api_key=options.require_api_key,
            sandbox_runtime_enabled=options.sandbox_runtime_enabled,
            sandbox_python=options.sandbox_python,
        )


class SandboxBackendResponse(BaseModel):
    id: str
    display_name: str
    status: str
    available: bool
    isolation: str
    execution_model: str
    supports_path_grants: bool
    supports_python_runtime_provisioning: bool
    notes: str

    @classmethod
    def from_domain(cls, backend: SandboxBackendSpec) -> SandboxBackendResponse:
        return cls(
            id=backend.id,
            display_name=backend.display_name,
            status=backend.status,
            available=backend.available,
            isolation=backend.isolation,
            execution_model=backend.execution_model,
            supports_path_grants=backend.supports_path_grants,
            supports_python_runtime_provisioning=backend.supports_python_runtime_provisioning,
            notes=backend.notes,
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


class RunDispatchResponse(BaseModel):
    run: RunResponse
    worker: WorkerStatusResponse


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
