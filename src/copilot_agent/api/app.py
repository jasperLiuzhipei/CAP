from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from copilot_agent.backend.models import Artifact, RunEvent
from copilot_agent.backend.service import CopilotBackendService
from copilot_agent.backend.store import SQLiteBackendStore
from copilot_agent.worker import BackgroundRunWorker, RunWorker

from .schemas import (
    ApprovalDecisionCreate,
    ApprovalResponse,
    ArtifactResponse,
    DiffResponse,
    ProjectCreate,
    ProjectResponse,
    RunCreate,
    RunDispatchResponse,
    RunEventResponse,
    RunExecute,
    RunFinish,
    RunResponse,
    ToolCallResponse,
    ToolReviewCreate,
    ToolReviewResponse,
    WorkerStatusResponse,
)

TERMINAL_RUN_STATUSES = {"cancelled", "failed", "succeeded"}


def create_app(
    *,
    db_path: str | Path = ".copilot/control.sqlite",
    service: CopilotBackendService | None = None,
    worker: RunWorker | None = None,
    background_worker: BackgroundRunWorker | None = None,
    auto_start_background_worker: bool = False,
) -> FastAPI:
    """Build the FastAPI app for the Copilot control plane."""

    resolved_service = service or CopilotBackendService(SQLiteBackendStore(db_path))
    resolved_service.initialize()

    app = FastAPI(
        title="Copilot Agent Platform API",
        version="0.1.0",
        description="Backend control-plane API for projects, runs, approvals, and artifacts.",
        lifespan=_build_lifespan(auto_start_background_worker),
    )
    app.state.copilot_service = resolved_service
    resolved_worker = worker or RunWorker(resolved_service)
    app.state.copilot_worker = resolved_worker
    app.state.copilot_background_worker = (
        background_worker or BackgroundRunWorker(resolved_worker)
    )

    app.include_router(_build_router())
    return app


def _build_lifespan(auto_start_background_worker: bool) -> Callable[[FastAPI], AsyncIterator[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if auto_start_background_worker:
            await app.state.copilot_background_worker.start()
        try:
            yield
        finally:
            if auto_start_background_worker:
                await app.state.copilot_background_worker.stop()

    return lifespan


def get_service(request: Request) -> CopilotBackendService:
    service = getattr(request.app.state, "copilot_service", None)
    if not isinstance(service, CopilotBackendService):
        raise RuntimeError("Copilot backend service is not configured.")
    return service


def get_worker(request: Request) -> RunWorker:
    worker = getattr(request.app.state, "copilot_worker", None)
    if not isinstance(worker, RunWorker):
        raise RuntimeError("Copilot run worker is not configured.")
    return worker


def get_background_worker(request: Request) -> BackgroundRunWorker:
    worker = getattr(request.app.state, "copilot_background_worker", None)
    if not isinstance(worker, BackgroundRunWorker):
        raise RuntimeError("Copilot background worker is not configured.")
    return worker


SERVICE_DEPENDENCY = Depends(get_service)
WORKER_DEPENDENCY = Depends(get_worker)
BACKGROUND_WORKER_DEPENDENCY = Depends(get_background_worker)


def _build_router():
    router = APIRouter(prefix="/api/v1")

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.post(
        "/projects",
        response_model=ProjectResponse,
        responses={400: {"description": "Invalid project payload"}},
    )
    def create_project(
        payload: ProjectCreate,
        service: CopilotBackendService = SERVICE_DEPENDENCY,
    ) -> ProjectResponse:
        try:
            project = service.create_project(
                name=payload.name,
                repo_path=payload.repo_path,
                memory_path=payload.memory_path,
                default_model_provider=payload.default_model_provider,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ProjectResponse.from_domain(project)

    @router.get("/projects", response_model=list[ProjectResponse])
    def list_projects(
        service: CopilotBackendService = SERVICE_DEPENDENCY,
    ) -> list[ProjectResponse]:
        return [ProjectResponse.from_domain(project) for project in service.list_projects()]

    @router.get(
        "/projects/{project_id}",
        response_model=ProjectResponse,
        responses={404: {"description": "Project not found"}},
    )
    def get_project(
        project_id: str,
        service: CopilotBackendService = SERVICE_DEPENDENCY,
    ) -> ProjectResponse:
        try:
            return ProjectResponse.from_domain(service.get_project(project_id))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post(
        "/runs",
        response_model=RunResponse,
        responses={
            400: {"description": "Invalid run payload"},
            404: {"description": "Project not found"},
        },
    )
    async def queue_run(
        payload: RunCreate,
        service: CopilotBackendService = SERVICE_DEPENDENCY,
        background_worker: BackgroundRunWorker = BACKGROUND_WORKER_DEPENDENCY,
    ) -> RunResponse:
        try:
            run = service.queue_run(
                project_id=payload.project_id,
                task=payload.task,
                model_provider=payload.model_provider,
                model=payload.model,
                tool_strategy=payload.tool_strategy,
                sandbox_backend=payload.sandbox_backend,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if background_worker.running:
            await background_worker.enqueue(run.id)
        return RunResponse.from_domain(run)

    @router.get("/worker/status", response_model=WorkerStatusResponse)
    def get_worker_status(
        background_worker: BackgroundRunWorker = BACKGROUND_WORKER_DEPENDENCY,
    ) -> WorkerStatusResponse:
        return WorkerStatusResponse.from_domain(background_worker.status())

    @router.post("/worker/start", response_model=WorkerStatusResponse)
    async def start_worker(
        background_worker: BackgroundRunWorker = BACKGROUND_WORKER_DEPENDENCY,
    ) -> WorkerStatusResponse:
        status = await background_worker.start()
        return WorkerStatusResponse.from_domain(status)

    @router.post("/worker/stop", response_model=WorkerStatusResponse)
    async def stop_worker(
        background_worker: BackgroundRunWorker = BACKGROUND_WORKER_DEPENDENCY,
    ) -> WorkerStatusResponse:
        status = await background_worker.stop()
        return WorkerStatusResponse.from_domain(status)

    @router.get("/runs", response_model=list[RunResponse])
    def list_runs(
        service: CopilotBackendService = SERVICE_DEPENDENCY,
        project_id: str | None = Query(default=None),
    ) -> list[RunResponse]:
        try:
            runs = service.list_runs(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return [RunResponse.from_domain(run) for run in runs]

    @router.get(
        "/runs/{run_id}",
        response_model=RunResponse,
        responses={404: {"description": "Run not found"}},
    )
    def get_run(
        run_id: str,
        service: CopilotBackendService = SERVICE_DEPENDENCY,
    ) -> RunResponse:
        try:
            return RunResponse.from_domain(service.get_run(run_id))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post(
        "/runs/{run_id}/start",
        response_model=RunResponse,
        responses={404: {"description": "Run not found"}},
    )
    def start_run(
        run_id: str,
        service: CopilotBackendService = SERVICE_DEPENDENCY,
    ) -> RunResponse:
        try:
            return RunResponse.from_domain(service.start_run(run_id))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post(
        "/runs/{run_id}/finish",
        response_model=RunResponse,
        responses={404: {"description": "Run not found"}},
    )
    def finish_run(
        run_id: str,
        payload: RunFinish,
        service: CopilotBackendService = SERVICE_DEPENDENCY,
    ) -> RunResponse:
        try:
            run = service.finish_run(
                run_id,
                payload.status,
                summary=payload.summary,
                saved_dir=payload.saved_dir,
                diff_path=payload.diff_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RunResponse.from_domain(run)

    @router.post(
        "/runs/{run_id}/execute",
        response_model=RunResponse,
        responses={
            404: {"description": "Run not found"},
            409: {"description": "Run is not queued"},
        },
    )
    async def execute_run(
        run_id: str,
        payload: RunExecute,
        worker: RunWorker = WORKER_DEPENDENCY,
    ) -> RunResponse:
        try:
            run = await worker.execute_run(run_id, payload.to_options())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RunResponse.from_domain(run)

    @router.post(
        "/runs/{run_id}/dispatch",
        response_model=RunDispatchResponse,
        responses={
            404: {"description": "Run not found"},
            409: {"description": "Run is not queued"},
        },
    )
    async def dispatch_run(
        run_id: str,
        payload: RunExecute,
        service: CopilotBackendService = SERVICE_DEPENDENCY,
        background_worker: BackgroundRunWorker = BACKGROUND_WORKER_DEPENDENCY,
    ) -> RunDispatchResponse:
        try:
            run = service.get_run(run_id)
            if not background_worker.running:
                await background_worker.start()
            status = await background_worker.enqueue(run_id, payload.to_options())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RunDispatchResponse(
            run=RunResponse.from_domain(run),
            worker=WorkerStatusResponse.from_domain(status),
        )

    @router.post(
        "/runs/{run_id}/tool-calls/review",
        response_model=ToolReviewResponse,
        responses={404: {"description": "Run not found"}},
    )
    def review_tool_call(
        run_id: str,
        payload: ToolReviewCreate,
        service: CopilotBackendService = SERVICE_DEPENDENCY,
    ) -> ToolReviewResponse:
        try:
            review = service.record_tool_decision(
                run_id=run_id,
                tool_name=payload.tool_name,
                arguments=payload.arguments,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ToolReviewResponse.from_domain(review)

    @router.get(
        "/runs/{run_id}/tool-calls",
        response_model=list[ToolCallResponse],
        responses={404: {"description": "Run not found"}},
    )
    def list_tool_calls(
        run_id: str,
        service: CopilotBackendService = SERVICE_DEPENDENCY,
    ) -> list[ToolCallResponse]:
        try:
            tool_calls = service.list_tool_calls(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return [ToolCallResponse.from_domain(tool_call) for tool_call in tool_calls]

    @router.get(
        "/runs/{run_id}/approvals",
        response_model=list[ApprovalResponse],
        responses={404: {"description": "Run not found"}},
    )
    def list_approvals(
        run_id: str,
        service: CopilotBackendService = SERVICE_DEPENDENCY,
    ) -> list[ApprovalResponse]:
        try:
            approvals = service.list_approvals(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return [ApprovalResponse.from_domain(approval) for approval in approvals]

    @router.post(
        "/approvals/{approval_id}/decide",
        response_model=ApprovalResponse,
        responses={404: {"description": "Approval not found"}},
    )
    def decide_approval(
        approval_id: str,
        payload: ApprovalDecisionCreate,
        service: CopilotBackendService = SERVICE_DEPENDENCY,
    ) -> ApprovalResponse:
        try:
            approval = service.decide_approval(
                approval_id,
                approved=payload.approved,
                decided_by=payload.decided_by,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ApprovalResponse.from_domain(approval)

    @router.get(
        "/runs/{run_id}/artifacts",
        response_model=list[ArtifactResponse],
        responses={404: {"description": "Run not found"}},
    )
    def list_artifacts(
        run_id: str,
        service: CopilotBackendService = SERVICE_DEPENDENCY,
    ) -> list[ArtifactResponse]:
        try:
            artifacts = service.list_artifacts(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return [ArtifactResponse.from_domain(artifact) for artifact in artifacts]

    @router.get(
        "/runs/{run_id}/events",
        response_model=list[RunEventResponse],
        responses={404: {"description": "Run not found"}},
    )
    def list_events(
        run_id: str,
        service: CopilotBackendService = SERVICE_DEPENDENCY,
    ) -> list[RunEventResponse]:
        try:
            events = service.list_events(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return [RunEventResponse.from_domain(event) for event in events]

    @router.get(
        "/runs/{run_id}/events/stream",
        responses={404: {"description": "Run not found"}},
    )
    def stream_events(
        run_id: str,
        follow: bool = Query(default=False),
        poll_interval_seconds: float = Query(default=0.25, ge=0.01, le=5.0),
        idle_timeout_seconds: float = Query(default=30.0, ge=0.1, le=300.0),
        service: CopilotBackendService = SERVICE_DEPENDENCY,
    ) -> StreamingResponse:
        try:
            events = service.list_events(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if follow:
            stream = _sse_events_follow(
                service,
                run_id,
                initial_events=events,
                poll_interval_seconds=poll_interval_seconds,
                idle_timeout_seconds=idle_timeout_seconds,
            )
            return StreamingResponse(stream, media_type="text/event-stream")
        return StreamingResponse(_sse_events(events), media_type="text/event-stream")

    @router.get(
        "/runs/{run_id}/diff",
        response_model=DiffResponse,
        responses={404: {"description": "Run or diff not found"}},
    )
    def get_run_diff(
        run_id: str,
        service: CopilotBackendService = SERVICE_DEPENDENCY,
    ) -> DiffResponse:
        try:
            run = service.get_run(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        diff_path = _resolve_diff_path(run.diff_path, service.list_artifacts(run_id))
        if diff_path is None or not diff_path.exists():
            raise HTTPException(status_code=404, detail=f"Diff not found for run: {run_id}")
        return DiffResponse(
            run_id=run_id,
            diff=diff_path.read_text(encoding="utf-8"),
            source=str(diff_path),
        )

    return router


def _resolve_diff_path(diff_path: str | None, artifacts: list[Artifact]) -> Path | None:
    if diff_path:
        return Path(diff_path)
    for artifact in artifacts:
        if artifact.kind == "diff":
            return Path(artifact.path)
    return None


def _sse_events(events: Iterable[RunEvent]) -> Iterable[str]:
    for event in events:
        yield _format_sse_event(event)


async def _sse_events_follow(
    service: CopilotBackendService,
    run_id: str,
    *,
    initial_events: list[RunEvent],
    poll_interval_seconds: float,
    idle_timeout_seconds: float,
):
    sent_ids: set[str] = set()
    last_activity = time.monotonic()

    for event in initial_events:
        sent_ids.add(event.id)
        yield _format_sse_event(event)

    while True:
        run = service.get_run(run_id)
        events = service.list_events(run_id)
        emitted = False
        for event in events:
            if event.id in sent_ids:
                continue
            sent_ids.add(event.id)
            emitted = True
            yield _format_sse_event(event)

        if emitted:
            last_activity = time.monotonic()
        if run.status in TERMINAL_RUN_STATUSES:
            return
        if time.monotonic() - last_activity >= idle_timeout_seconds:
            return
        await asyncio.sleep(poll_interval_seconds)


def _format_sse_event(event: RunEvent) -> str:
    payload = RunEventResponse.from_domain(event).model_dump_json()
    return f"event: {event.event_type}\ndata: {payload}\n\n"
