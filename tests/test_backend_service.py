from __future__ import annotations

from pathlib import Path

import pytest

from copilot_agent.backend.service import CopilotBackendService, redact_secrets
from copilot_agent.backend.store import SQLiteBackendStore
from copilot_agent.phase_one import CommandResult, PhaseOneReport, SandboxRuntimeReport


def build_service(tmp_path: Path) -> CopilotBackendService:
    service = CopilotBackendService(SQLiteBackendStore(tmp_path / "control.sqlite"))
    service.initialize()
    return service


def test_backend_service_manages_project_run_and_tool_review(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    project = service.create_project(
        name="Sample",
        repo_path=tmp_path / "repo",
        default_model_provider="deepseek",
    )
    run = service.queue_run(
        project_id=project.id,
        task="Fix bug",
        model_provider="deepseek",
        model="deepseek-v4-flash",
        tool_strategy="compat_functions",
    )

    started = service.start_run(run.id)
    allowed = service.record_tool_decision(
        run_id=run.id,
        tool_name="shell.exec",
        arguments={"cmd": "cd repo && PYTHONPATH=src python3 -m pytest tests"},
    )
    review = service.record_tool_decision(
        run_id=run.id,
        tool_name="apply_patch",
        arguments={"patch": "*** Begin Patch", "api_key": "sk-secretvalue"},
    )
    decided = service.decide_approval(review.approval.id, approved=True, decided_by="jasper")
    finished = service.finish_run(run.id, "succeeded", summary="done")
    events = service.list_events(run.id)

    assert started.status == "running"
    assert allowed.approval is None
    assert allowed.tool_call.status == "allowed"
    assert review.approval is not None
    assert review.approval.arguments_redacted["api_key"] == "<redacted>"
    assert review.tool_call.approval_id == review.approval.id
    assert service.store.get_run(run.id).status == "succeeded"
    assert decided.decision == "approved"
    assert finished.summary == "done"
    assert [event.event_type for event in events] == [
        "run.queued",
        "run.started",
        "tool.reviewed",
        "tool.reviewed",
        "approval.required",
        "run.needs_approval",
        "approval.decided",
        "run.completed",
    ]
    assert events[3].payload["approval_id"] == review.approval.id


def test_backend_service_rejects_invalid_project_or_run(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    with pytest.raises(ValueError, match="Project name"):
        service.create_project(name=" ", repo_path=tmp_path)
    with pytest.raises(FileNotFoundError, match="Project not found"):
        service.queue_run(
            project_id="missing",
            task="Fix bug",
            model_provider="openai",
            model="gpt-5.5",
            tool_strategy="native",
        )

    project = service.create_project(name="Sample", repo_path=tmp_path / "repo")
    with pytest.raises(ValueError, match="Run task"):
        service.queue_run(
            project_id=project.id,
            task=" ",
            model_provider="openai",
            model="gpt-5.5",
            tool_strategy="native",
        )
    with pytest.raises(FileNotFoundError, match="Run not found"):
        service.record_tool_decision(run_id="missing", tool_name="shell.exec", arguments={})


def test_backend_service_ingests_phase_one_report_artifacts(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    project = service.create_project(name="Sample", repo_path=tmp_path / "repo")
    saved_dir = tmp_path / "runs" / "run_phase_one"
    saved_dir.mkdir(parents=True)
    for filename in (
        "report.json",
        "final.md",
        "diff.patch",
        "sandbox_runtime.log",
        "verification.log",
        "host_verification.log",
    ):
        (saved_dir / filename).write_text(filename, encoding="utf-8")

    report = PhaseOneReport(
        run_id="run_phase_one",
        repo=str(tmp_path / "repo"),
        task="Fix bug",
        model="deepseek-v4-flash",
        model_provider="deepseek",
        model_transport="chat_completions",
        tool_strategy="compat_functions",
        model_base_url="https://api.deepseek.com",
        prompt="prompt",
        final_output="fixed",
        diff="--- repo/a.py\n+++ repo/a.py\n",
        sandbox_runtime=SandboxRuntimeReport(
            enabled=True,
            python_command="python3",
            original_test_cmd="python -m pytest tests",
            sandbox_test_cmd="PYTEST_ADDOPTS='-p no:debugging' python -m pytest tests",
            python_check=CommandResult("python3 -c check", 0, "ok", ""),
            notes=["runtime ok"],
        ),
        verification=CommandResult("pytest", 1, "", "sandbox failed"),
        host_verification=CommandResult("pytest", 0, "host passed", ""),
        saved_dir=str(saved_dir),
    )

    run = service.ingest_phase_one_report(project.id, report)
    artifacts = service.store.list_artifacts(run.id)
    events = service.list_events(run.id)

    assert run.status == "succeeded"
    assert run.diff_path == str(saved_dir / "diff.patch")
    assert len(artifacts) == 6
    assert {artifact.kind for artifact in artifacts} == {"diff", "log", "report", "summary"}
    assert [event.event_type for event in events].count("artifact.created") == 6
    assert [event.event_type for event in events] == [
        "sandbox.runtime_checked",
        "verification.completed",
        "verification.completed",
        "artifact.created",
        "artifact.created",
        "artifact.created",
        "artifact.created",
        "artifact.created",
        "artifact.created",
        "run.completed",
    ]
    assert [event.event_type for event in events].count("verification.completed") == 2


def test_backend_service_ingest_requires_existing_project(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    report = PhaseOneReport(
        run_id="run_missing_project",
        repo=str(tmp_path / "repo"),
        task="Fix bug",
        model="gpt-5.5",
        model_provider="openai",
        model_transport="native",
        tool_strategy="native",
        model_base_url=None,
        prompt="prompt",
        final_output="done",
    )

    with pytest.raises(FileNotFoundError, match="Project not found"):
        service.ingest_phase_one_report("missing", report)


def test_redact_secrets_handles_nested_payloads_and_secret_like_values() -> None:
    redacted = redact_secrets(
        {
            "token": "abc",
            "nested": {"cmd": "echo sk-1234567890"},
            "items": ["safe", "abcdefghijklmnopqrstuvwxyz"],
        }
    )

    assert redacted["token"] == "<redacted>"
    assert redacted["nested"]["cmd"] == "echo <redacted>"
    assert redacted["items"] == ["safe", "<redacted>"]
