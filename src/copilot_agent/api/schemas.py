from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from copilot_agent.backend.models import (
    Approval,
    ApprovalDecision,
    Artifact,
    CostEstimate,
    Project,
    RunEvent,
    RunMetrics,
    RunRecord,
    RunStatus,
    RunTrace,
    TokenUsage,
    ToolCall,
    ToolTraceItem,
)
from copilot_agent.backend.service import ToolReview
from copilot_agent.model_registry import (
    ModelCapabilityProfile,
    ModelPricing,
)
from copilot_agent.sandbox_backend import (
    DEFAULT_DOCKER_IMAGE,
    DEFAULT_SANDBOX_COMMAND_TIMEOUT_SECONDS,
    SandboxBackendSpec,
    parse_docker_exposed_ports,
)
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
    sandbox_command_timeout_seconds: float | None = DEFAULT_SANDBOX_COMMAND_TIMEOUT_SECONDS
    docker_image: str = DEFAULT_DOCKER_IMAGE
    docker_exposed_ports: list[int] = Field(default_factory=list)
    docker_network: str = "bridge"
    docker_memory_limit: str | None = None
    docker_cpus: float | None = None
    require_api_key: bool = True

    def to_options(self) -> RunExecutionOptions:
        docker_exposed_ports = parse_docker_exposed_ports(
            ",".join(str(port) for port in self.docker_exposed_ports)
        )
        return RunExecutionOptions(
            test_cmd=self.test_cmd,
            max_turns=self.max_turns,
            output_dir=Path(self.output_dir),
            memory_enabled=self.memory_enabled,
            host_verify=self.host_verify,
            sandbox_runtime_enabled=self.sandbox_runtime_enabled,
            sandbox_python=self.sandbox_python,
            sandbox_command_timeout_seconds=self.sandbox_command_timeout_seconds,
            docker_image=self.docker_image,
            docker_exposed_ports=docker_exposed_ports,
            docker_network=self.docker_network,
            docker_memory_limit=self.docker_memory_limit,
            docker_cpus=self.docker_cpus,
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
    sandbox_command_timeout_seconds: float | None
    docker_image: str
    docker_exposed_ports: list[int]
    docker_network: str
    docker_memory_limit: str | None
    docker_cpus: float | None

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
            sandbox_command_timeout_seconds=options.sandbox_command_timeout_seconds,
            docker_image=options.docker_image,
            docker_exposed_ports=list(options.docker_exposed_ports),
            docker_network=options.docker_network,
            docker_memory_limit=options.docker_memory_limit,
            docker_cpus=options.docker_cpus,
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


class ModelPricingResponse(BaseModel):
    input_usd_per_million_tokens: float
    output_usd_per_million_tokens: float
    source: str
    source_url: str | None
    updated_at: str

    @classmethod
    def from_domain(cls, pricing: ModelPricing) -> ModelPricingResponse:
        return cls(**pricing.__dict__)


class ModelCapabilityResponse(BaseModel):
    provider: str
    model: str
    display_name: str
    transport: str
    tool_strategy: str
    native_tools: str
    function_tools: str
    filesystem: str
    compaction: str
    hosted_tools: str
    structured_outputs: str
    context_window_tokens: int | None
    cost_tier: str
    stability: str
    pricing: ModelPricingResponse | None
    notes: list[str]

    @classmethod
    def from_domain(cls, profile: ModelCapabilityProfile) -> ModelCapabilityResponse:
        return cls(
            **{
                **profile.__dict__,
                "pricing": (
                    ModelPricingResponse.from_domain(profile.pricing)
                    if profile.pricing
                    else None
                ),
                "notes": list(profile.notes),
            }
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


class PolicyRuleResponse(BaseModel):
    scope: str
    action: str
    risk: str
    description: str
    examples: list[str]


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
    result_summary: str = ""
    duration_ms: float | None = None
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


class TokenUsageResponse(BaseModel):
    requests: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None

    @classmethod
    def from_domain(cls, usage: TokenUsage) -> TokenUsageResponse:
        return cls(**usage.__dict__)


class CostEstimateResponse(BaseModel):
    input_cost_usd: float | None
    output_cost_usd: float | None
    total_cost_usd: float | None
    pricing_source: str
    estimated: bool

    @classmethod
    def from_domain(cls, cost: CostEstimate) -> CostEstimateResponse:
        return cls(**cost.__dict__)


class RunMetricsResponse(BaseModel):
    run_id: str
    status: str
    model_provider: str
    model: str
    tool_strategy: str
    sandbox_backend: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    duration_ms: float | None
    total_events: int
    total_tool_calls: int
    approvals_required: int
    approvals_pending: int
    approvals_approved: int
    approvals_rejected: int
    failed_reason: str | None
    token_usage: TokenUsageResponse
    cost_estimate: CostEstimateResponse

    @classmethod
    def from_domain(cls, metrics: RunMetrics) -> RunMetricsResponse:
        return cls(
            **{
                **metrics.__dict__,
                "token_usage": TokenUsageResponse.from_domain(metrics.token_usage),
                "cost_estimate": CostEstimateResponse.from_domain(
                    metrics.cost_estimate
                ),
            }
        )


class ToolTraceItemResponse(BaseModel):
    tool_call_id: str
    tool_name: str
    action: str
    status: str
    risk: str
    reason: str
    approval_id: str | None
    approval_decision: str | None
    result_summary: str
    duration_ms: float | None
    arguments_redacted: dict[str, Any]
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, item: ToolTraceItem) -> ToolTraceItemResponse:
        return cls(**item.__dict__)


class RunTraceResponse(BaseModel):
    run_id: str
    tool_calls: list[ToolTraceItemResponse]
    events: list[RunEventResponse]

    @classmethod
    def from_domain(cls, trace: RunTrace) -> RunTraceResponse:
        return cls(
            run_id=trace.run_id,
            tool_calls=[
                ToolTraceItemResponse.from_domain(tool_call)
                for tool_call in trace.tool_calls
            ],
            events=[RunEventResponse.from_domain(event) for event in trace.events],
        )


class DiffResponse(BaseModel):
    run_id: str
    diff: str
    source: str | None = None


class ErrorResponse(BaseModel):
    detail: str
