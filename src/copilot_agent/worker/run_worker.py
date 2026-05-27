from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from copilot_agent.backend.models import Project, RunRecord
from copilot_agent.backend.service import CopilotBackendService
from copilot_agent.model_config import resolve_model_config
from copilot_agent.phase_one import PhaseOneConfig, PhaseOneReport, run_phase_one

PhaseOneRunner = Callable[[PhaseOneConfig], Awaitable[PhaseOneReport]]


@dataclass(frozen=True)
class RunExecutionOptions:
    test_cmd: str | None = None
    max_turns: int = 32
    output_dir: Path = Path("runs")
    memory_enabled: bool | None = None
    host_verify: bool = False
    sandbox_runtime_enabled: bool = True
    sandbox_python: str = "python3"
    require_api_key: bool = True


class RunWorker:
    """Execute queued backend runs with the phase-one Agents SDK runtime."""

    def __init__(
        self,
        service: CopilotBackendService,
        *,
        runner: PhaseOneRunner = run_phase_one,
    ) -> None:
        self.service = service
        self.runner = runner

    def next_queued_run(self) -> RunRecord | None:
        for run in self.service.list_runs():
            if run.status == "queued":
                return run
        return None

    async def execute_next(
        self,
        options: RunExecutionOptions | None = None,
    ) -> RunRecord | None:
        run = self.next_queued_run()
        if run is None:
            return None
        return await self.execute_run(run.id, options)

    async def execute_run(
        self,
        run_id: str,
        options: RunExecutionOptions | None = None,
    ) -> RunRecord:
        options = options or RunExecutionOptions()
        run = self.service.get_run(run_id)
        if run.status != "queued":
            raise ValueError(f"Run {run.id} must be queued before worker execution.")

        project = self.service.get_project(run.project_id)
        self.service.start_run(run.id)
        try:
            config = self.build_phase_one_config(project, run, options)
            report = await self.runner(config)
        except Exception as exc:
            return self.service.finish_run(
                run.id,
                "failed",
                summary=f"Worker execution failed: {exc}",
            )

        return self.service.ingest_phase_one_report(
            project.id,
            report,
            run_id=run.id,
        )

    def build_phase_one_config(
        self,
        project: Project,
        run: RunRecord,
        options: RunExecutionOptions,
    ) -> PhaseOneConfig:
        model_config = resolve_model_config(
            provider=run.model_provider,
            model=run.model,
            tool_strategy=run.tool_strategy,
            require_api_key=options.require_api_key,
        )
        memory_path = Path(project.memory_path) if project.memory_path else None
        memory_enabled = (
            bool(project.memory_path)
            if options.memory_enabled is None
            else options.memory_enabled
        )
        return PhaseOneConfig(
            repo=Path(project.repo_path),
            task=run.task,
            model_config=model_config,
            test_cmd=options.test_cmd,
            max_turns=options.max_turns,
            output_dir=options.output_dir,
            save=True,
            memory_enabled=memory_enabled,
            memory_path=memory_path,
            host_verify=options.host_verify,
            sandbox_runtime_enabled=options.sandbox_runtime_enabled,
            sandbox_python=options.sandbox_python,
        )
