from __future__ import annotations

import asyncio
from pathlib import Path

from copilot_agent.backend.service import CopilotBackendService
from copilot_agent.backend.store import SQLiteBackendStore
from copilot_agent.phase_one import PhaseOneConfig, PhaseOneReport
from copilot_agent.worker import BackgroundRunWorker, RunExecutionOptions, RunWorker


def build_service(tmp_path: Path) -> CopilotBackendService:
    service = CopilotBackendService(SQLiteBackendStore(tmp_path / "control.sqlite"))
    service.initialize()
    return service


def create_queued_run(service: CopilotBackendService, tmp_path: Path, task: str = "Fix bug"):
    project = service.create_project(name=f"Project {task}", repo_path=tmp_path / "repo")
    run = service.queue_run(
        project_id=project.id,
        task=task,
        model_provider="deepseek",
        model="deepseek-v4-flash",
        tool_strategy="compat_functions",
    )
    return project, run


def write_report_files(saved_dir: Path) -> None:
    saved_dir.mkdir(parents=True)
    (saved_dir / "report.json").write_text("{}", encoding="utf-8")
    (saved_dir / "final.md").write_text("done", encoding="utf-8")
    (saved_dir / "diff.patch").write_text("--- repo/a.py\n+++ repo/a.py\n", encoding="utf-8")


def test_background_worker_runs_queued_job_until_idle(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = build_service(tmp_path)
        _, run = create_queued_run(service, tmp_path)
        runner_started = asyncio.Event()
        release_runner = asyncio.Event()

        async def fake_runner(config: PhaseOneConfig) -> PhaseOneReport:
            runner_started.set()
            await release_runner.wait()
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

        background = BackgroundRunWorker(
            RunWorker(service, runner=fake_runner),
            default_options=RunExecutionOptions(require_api_key=False),
        )
        await background.start()
        await background.enqueue(run.id)
        await asyncio.wait_for(runner_started.wait(), timeout=1)

        active_status = background.status()
        assert active_status.running
        assert active_status.active_run_id == run.id

        release_runner.set()
        final_status = await background.wait_until_idle()
        await background.stop()

        assert final_status.processed_count == 1
        assert final_status.failed_count == 0
        assert service.get_run(run.id).status == "succeeded"

    asyncio.run(scenario())


def test_background_worker_start_enqueues_existing_queued_runs(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = build_service(tmp_path)
        _, first = create_queued_run(service, tmp_path, "First")
        _, second = create_queued_run(service, tmp_path, "Second")

        async def fake_runner(config: PhaseOneConfig) -> PhaseOneReport:
            saved_dir = tmp_path / "runs" / config.task
            write_report_files(saved_dir)
            return PhaseOneReport(
                run_id=f"sdk_{config.task}",
                repo=str(config.repo),
                task=config.task,
                model=config.model_config.model,
                model_provider=config.model_config.provider,
                model_transport=config.model_config.transport,
                tool_strategy=config.model_config.tool_strategy,
                model_base_url=config.model_config.base_url,
                prompt="prompt",
                final_output=config.task,
                saved_dir=str(saved_dir),
            )

        background = BackgroundRunWorker(
            RunWorker(service, runner=fake_runner),
            default_options=RunExecutionOptions(require_api_key=False),
        )
        start_status = await background.start()
        final_status = await background.wait_until_idle()
        await background.stop()

        assert start_status.running
        assert final_status.processed_count == 2
        assert service.get_run(first.id).status == "succeeded"
        assert service.get_run(second.id).status == "succeeded"

    asyncio.run(scenario())


def test_background_worker_rejects_dispatch_when_not_running(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = build_service(tmp_path)
        _, run = create_queued_run(service, tmp_path)
        background = BackgroundRunWorker(
            RunWorker(service),
            default_options=RunExecutionOptions(require_api_key=False),
        )

        try:
            await background.enqueue(run.id)
        except RuntimeError as exc:
            assert "not running" in str(exc)
        else:  # pragma: no cover - defensive assertion
            raise AssertionError("Expected enqueue to fail when worker is stopped.")

    asyncio.run(scenario())


def test_background_worker_covers_duplicate_nonqueued_and_failed_jobs(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = build_service(tmp_path)
        _, first = create_queued_run(service, tmp_path, "First")
        _, second = create_queued_run(service, tmp_path, "Second")
        runner_started = asyncio.Event()
        release_runner = asyncio.Event()

        async def fake_runner(config: PhaseOneConfig) -> PhaseOneReport:
            if config.task == "First":
                runner_started.set()
                await release_runner.wait()
                saved_dir = tmp_path / "runs" / "first"
                write_report_files(saved_dir)
                return PhaseOneReport(
                    run_id="first",
                    repo=str(config.repo),
                    task=config.task,
                    model=config.model_config.model,
                    model_provider=config.model_config.provider,
                    model_transport=config.model_config.transport,
                    tool_strategy=config.model_config.tool_strategy,
                    model_base_url=config.model_config.base_url,
                    prompt="prompt",
                    final_output="first",
                    saved_dir=str(saved_dir),
                )
            raise RuntimeError("boom")

        background = BackgroundRunWorker(
            RunWorker(service, runner=fake_runner),
            default_options=RunExecutionOptions(require_api_key=False),
        )
        assert not (await background.stop()).running
        assert not (await background.wait_until_idle()).running

        await background.start()
        await background.enqueue(first.id)
        await background.enqueue(first.id)
        await background.enqueue(second.id)
        await asyncio.wait_for(runner_started.wait(), timeout=1)

        with_status = background.status()
        assert with_status.active_run_id == first.id
        assert with_status.queue_size == 1

        release_runner.set()
        final_status = await background.wait_until_idle()
        await background.stop()

        assert service.get_run(first.id).status == "succeeded"
        assert service.get_run(second.id).status == "failed"
        assert final_status.processed_count == 2
        assert final_status.failed_count == 1

    asyncio.run(scenario())


def test_background_worker_rejects_non_queued_run(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = build_service(tmp_path)
        _, run = create_queued_run(service, tmp_path)
        service.start_run(run.id)
        background = BackgroundRunWorker(
            RunWorker(service),
            default_options=RunExecutionOptions(require_api_key=False),
        )
        await background.start()
        try:
            await background.enqueue(run.id)
        except ValueError as exc:
            assert "must be queued" in str(exc)
        else:  # pragma: no cover - defensive assertion
            raise AssertionError("Expected non-queued run dispatch to fail.")
        await background.stop()

    asyncio.run(scenario())
