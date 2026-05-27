from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from copilot_agent.backend.service import CopilotBackendService
from copilot_agent.backend.store import SQLiteBackendStore
from copilot_agent.phase_one import CommandResult, PhaseOneConfig, PhaseOneReport
from copilot_agent.worker import RunExecutionOptions, RunWorker


def build_service(tmp_path: Path) -> CopilotBackendService:
    service = CopilotBackendService(SQLiteBackendStore(tmp_path / "control.sqlite"))
    service.initialize()
    return service


def create_queued_run(service: CopilotBackendService, tmp_path: Path):
    project = service.create_project(
        name="Sample",
        repo_path=tmp_path / "repo",
        memory_path=tmp_path / "repo" / ".copilot" / "memory.md",
        default_model_provider="deepseek",
    )
    run = service.queue_run(
        project_id=project.id,
        task="Fix bug",
        model_provider="deepseek",
        model="deepseek-v4-flash",
        tool_strategy="compat_functions",
    )
    return project, run


def write_report_files(saved_dir: Path) -> None:
    saved_dir.mkdir(parents=True)
    (saved_dir / "report.json").write_text("{}", encoding="utf-8")
    (saved_dir / "final.md").write_text("fixed", encoding="utf-8")
    (saved_dir / "diff.patch").write_text("--- repo/a.py\n+++ repo/a.py\n", encoding="utf-8")
    (saved_dir / "verification.log").write_text("ok", encoding="utf-8")


def test_run_worker_executes_queued_run_and_updates_existing_record(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    project, run = create_queued_run(service, tmp_path)
    captured_configs: list[PhaseOneConfig] = []

    async def fake_runner(config: PhaseOneConfig) -> PhaseOneReport:
        captured_configs.append(config)
        saved_dir = tmp_path / "runs" / "sdk_generated_run"
        write_report_files(saved_dir)
        return PhaseOneReport(
            run_id="sdk_generated_run",
            repo=str(config.repo),
            task=config.task,
            model=config.model_config.model,
            model_provider=config.model_config.provider,
            model_transport=config.model_config.transport,
            tool_strategy=config.model_config.tool_strategy,
            model_base_url=config.model_config.base_url,
            prompt="prompt",
            final_output="fixed",
            diff="--- repo/a.py\n+++ repo/a.py\n",
            verification=CommandResult("pytest", 0, "ok", ""),
            saved_dir=str(saved_dir),
        )

    worker = RunWorker(service, runner=fake_runner)
    result = asyncio.run(
        worker.execute_run(
            run.id,
            RunExecutionOptions(
                test_cmd="pytest tests",
                output_dir=tmp_path / "runs",
                sandbox_python="python3.13",
                sandbox_runtime_enabled=False,
                require_api_key=False,
            ),
        )
    )

    assert result.id == run.id
    assert result.status == "succeeded"
    assert service.store.get_run("sdk_generated_run") is None
    assert service.get_run(run.id).summary == "fixed"
    assert len(service.list_artifacts(run.id)) == 4
    assert [event.event_type for event in service.list_events(run.id)] == [
        "run.queued",
        "run.started",
        "verification.completed",
        "artifact.created",
        "artifact.created",
        "artifact.created",
        "artifact.created",
        "run.completed",
    ]

    config = captured_configs[0]
    assert config.repo == Path(project.repo_path)
    assert config.task == "Fix bug"
    assert config.model_config.provider == "deepseek"
    assert config.model_config.tool_strategy == "compat_functions"
    assert config.sandbox_backend == "unix_local"
    assert config.test_cmd == "pytest tests"
    assert not config.sandbox_runtime_enabled
    assert config.sandbox_python == "python3.13"
    assert config.memory_enabled
    assert config.memory_path == Path(project.memory_path)


def test_run_worker_executes_next_queued_run_and_handles_empty_queue(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    _, run = create_queued_run(service, tmp_path)

    async def fake_runner(config: PhaseOneConfig) -> PhaseOneReport:
        saved_dir = tmp_path / "runs" / "sdk_run"
        write_report_files(saved_dir)
        return PhaseOneReport(
            run_id="sdk_run",
            repo=str(config.repo),
            task=config.task,
            model=config.model_config.model,
            model_provider=config.model_config.provider,
            model_transport=config.model_config.transport,
            tool_strategy=config.model_config.tool_strategy,
            model_base_url=config.model_config.base_url,
            prompt="prompt",
            final_output="done",
            saved_dir=str(saved_dir),
        )

    worker = RunWorker(service, runner=fake_runner)
    executed = asyncio.run(
        worker.execute_next(RunExecutionOptions(require_api_key=False))
    )
    empty = asyncio.run(worker.execute_next(RunExecutionOptions(require_api_key=False)))

    assert executed.id == run.id
    assert executed.status == "succeeded"
    assert empty is None


def test_run_worker_marks_run_failed_when_runner_raises(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    _, run = create_queued_run(service, tmp_path)

    async def failing_runner(config: PhaseOneConfig) -> PhaseOneReport:
        _ = config
        raise RuntimeError("model unavailable")

    worker = RunWorker(service, runner=failing_runner)
    result = asyncio.run(
        worker.execute_run(run.id, RunExecutionOptions(require_api_key=False))
    )

    assert result.status == "failed"
    assert "model unavailable" in result.summary
    assert [event.event_type for event in service.list_events(run.id)] == [
        "run.queued",
        "run.started",
        "run.failed",
    ]


def test_run_worker_rejects_non_queued_run(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    _, run = create_queued_run(service, tmp_path)
    service.start_run(run.id)
    worker = RunWorker(service)

    with pytest.raises(ValueError, match="must be queued"):
        asyncio.run(worker.execute_run(run.id, RunExecutionOptions(require_api_key=False)))
