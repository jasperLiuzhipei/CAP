from __future__ import annotations

import asyncio
from dataclasses import dataclass

from copilot_agent.backend.models import RunRecord

from .run_worker import RunExecutionOptions, RunWorker

TERMINAL_RUN_STATUSES = {"cancelled", "failed", "succeeded"}


@dataclass(frozen=True)
class BackgroundWorkerStatus:
    running: bool
    queue_size: int
    active_run_id: str | None
    processed_count: int
    failed_count: int


@dataclass(frozen=True)
class BackgroundRunJob:
    run_id: str
    options: RunExecutionOptions


class BackgroundRunWorker:
    """Small in-process queue that turns queued runs into completed run records."""

    def __init__(
        self,
        worker: RunWorker,
        *,
        default_options: RunExecutionOptions | None = None,
    ) -> None:
        self.worker = worker
        self.default_options = default_options or RunExecutionOptions()
        self._queue: asyncio.Queue[BackgroundRunJob | None] | None = None
        self._task: asyncio.Task[None] | None = None
        self._queued_run_ids: set[str] = set()
        self._active_run_id: str | None = None
        self._processed_count = 0
        self._failed_count = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> BackgroundWorkerStatus:
        return BackgroundWorkerStatus(
            running=self.running,
            queue_size=self._queue.qsize() if self._queue else 0,
            active_run_id=self._active_run_id,
            processed_count=self._processed_count,
            failed_count=self._failed_count,
        )

    async def start(self) -> BackgroundWorkerStatus:
        if not self.running:
            self._queue = asyncio.Queue()
            self._task = asyncio.create_task(self._run_loop())
        await self.enqueue_existing()
        return self.status()

    async def stop(self) -> BackgroundWorkerStatus:
        if self._queue is not None and self.running:
            await self._queue.put(None)
            if self._task is not None:
                await self._task
        self._task = None
        self._queue = None
        self._queued_run_ids.clear()
        return self.status()

    async def enqueue_existing(self) -> list[str]:
        enqueued: list[str] = []
        for run in self.worker.service.list_runs():
            if run.status == "queued":
                await self.enqueue(run.id)
                enqueued.append(run.id)
        return enqueued

    async def enqueue(
        self,
        run_id: str,
        options: RunExecutionOptions | None = None,
    ) -> BackgroundWorkerStatus:
        if not self.running or self._queue is None:
            raise RuntimeError("Background run worker is not running.")

        run = self.worker.service.get_run(run_id)
        if run.status != "queued":
            raise ValueError(f"Run {run.id} must be queued before background dispatch.")
        if run.id in self._queued_run_ids or run.id == self._active_run_id:
            return self.status()

        self._queued_run_ids.add(run.id)
        await self._queue.put(BackgroundRunJob(run.id, options or self.default_options))
        return self.status()

    async def wait_until_idle(self) -> BackgroundWorkerStatus:
        if self._queue is not None:
            await self._queue.join()
        return self.status()

    async def _run_loop(self) -> None:
        assert self._queue is not None
        while True:
            job = await self._queue.get()
            try:
                if job is None:
                    return
                await self._execute_job(job)
            finally:
                self._queue.task_done()

    async def _execute_job(self, job: BackgroundRunJob) -> RunRecord | None:
        self._active_run_id = job.run_id
        self._queued_run_ids.discard(job.run_id)
        try:
            run = await self.worker.execute_run(job.run_id, job.options)
            self._processed_count += 1
            if run.status in {"failed", "cancelled"}:
                self._failed_count += 1
            return run
        except ValueError:
            self._processed_count += 1
            return None
        except Exception:
            self._processed_count += 1
            self._failed_count += 1
            raise
        finally:
            self._active_run_id = None
