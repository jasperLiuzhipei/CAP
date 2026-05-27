from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from copilot_agent.api import create_app
from copilot_agent.backend.models import Artifact
from copilot_agent.backend.service import CopilotBackendService
from copilot_agent.backend.store import SQLiteBackendStore
from copilot_agent.phase_one import PhaseOneConfig, PhaseOneReport
from copilot_agent.worker import RunWorker


def build_client(tmp_path: Path) -> tuple[TestClient, CopilotBackendService]:
    service = CopilotBackendService(SQLiteBackendStore(tmp_path / "control.sqlite"))
    app = create_app(service=service)
    return TestClient(app), service


def create_project(client: TestClient, tmp_path: Path) -> dict[str, object]:
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "Sample",
            "repo_path": str(tmp_path / "repo"),
            "memory_path": str(tmp_path / "repo" / ".copilot" / "memory.md"),
            "default_model_provider": "deepseek",
        },
    )
    assert response.status_code == 200
    return response.json()


def create_run(client: TestClient, project_id: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/runs",
        json={
            "project_id": project_id,
            "task": "Fix bug",
            "model_provider": "deepseek",
            "model": "deepseek-v4-flash",
            "tool_strategy": "compat_functions",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_api_project_and_run_lifecycle(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)

    assert client.get("/api/v1/health").json() == {"status": "ok"}

    project = create_project(client, tmp_path)
    assert project["name"] == "Sample"
    assert client.get("/api/v1/projects").json() == [project]
    assert client.get(f"/api/v1/projects/{project['id']}").json() == project

    run = create_run(client, str(project["id"]))
    assert run["status"] == "queued"
    assert client.get("/api/v1/runs").json() == [run]
    assert client.get(f"/api/v1/runs?project_id={project['id']}").json() == [run]
    assert client.get(f"/api/v1/runs/{run['id']}").json() == run

    started = client.post(f"/api/v1/runs/{run['id']}/start").json()
    assert started["status"] == "running"

    finished = client.post(
        f"/api/v1/runs/{run['id']}/finish",
        json={
            "status": "succeeded",
            "summary": "done",
            "saved_dir": str(tmp_path / "runs" / str(run["id"])),
        },
    ).json()
    assert finished["status"] == "succeeded"
    assert finished["summary"] == "done"


def test_api_tool_review_approval_and_listing(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)
    project = create_project(client, tmp_path)
    run = create_run(client, str(project["id"]))

    allowed = client.post(
        f"/api/v1/runs/{run['id']}/tool-calls/review",
        json={"tool_name": "shell.exec", "arguments": {"cmd": "rg sample"}},
    ).json()
    review = client.post(
        f"/api/v1/runs/{run['id']}/tool-calls/review",
        json={
            "tool_name": "apply_patch",
            "arguments": {"patch": "*** Begin Patch", "token": "secret-token"},
        },
    ).json()

    assert allowed["decision"] == "allow"
    assert allowed["approval"] is None
    assert review["decision"] == "approval_required"
    assert review["approval"]["arguments_redacted"]["token"] == "<redacted>"

    decided = client.post(
        f"/api/v1/approvals/{review['approval']['id']}/decide",
        json={"approved": True, "decided_by": "jasper"},
    ).json()
    assert decided["decision"] == "approved"

    tool_calls = client.get(f"/api/v1/runs/{run['id']}/tool-calls").json()
    approvals = client.get(f"/api/v1/runs/{run['id']}/approvals").json()
    assert len(tool_calls) == 2
    assert approvals == [decided]


def test_api_artifacts_and_diff_endpoint(tmp_path: Path) -> None:
    client, service = build_client(tmp_path)
    project = create_project(client, tmp_path)
    run = create_run(client, str(project["id"]))
    diff_path = tmp_path / "runs" / str(run["id"]) / "diff.patch"
    diff_path.parent.mkdir(parents=True)
    diff_path.write_text("--- repo/a.py\n+++ repo/a.py\n", encoding="utf-8")

    service.store.create_artifact(
        Artifact(
            id="art_1",
            run_id=str(run["id"]),
            kind="diff",
            path=str(diff_path),
            metadata={"changed": True},
        )
    )

    artifacts = client.get(f"/api/v1/runs/{run['id']}/artifacts").json()
    diff = client.get(f"/api/v1/runs/{run['id']}/diff").json()

    assert artifacts[0]["kind"] == "diff"
    assert diff["diff"] == "--- repo/a.py\n+++ repo/a.py\n"
    assert diff["source"] == str(diff_path)


def test_api_execute_run_uses_worker_and_returns_updated_run(tmp_path: Path) -> None:
    service = CopilotBackendService(SQLiteBackendStore(tmp_path / "control.sqlite"))

    async def fake_runner(config: PhaseOneConfig) -> PhaseOneReport:
        saved_dir = tmp_path / "runs" / "sdk_run"
        saved_dir.mkdir(parents=True)
        (saved_dir / "report.json").write_text("{}", encoding="utf-8")
        (saved_dir / "final.md").write_text("done", encoding="utf-8")
        (saved_dir / "diff.patch").write_text("--- repo/a.py\n+++ repo/a.py\n", encoding="utf-8")
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
            diff="--- repo/a.py\n+++ repo/a.py\n",
            saved_dir=str(saved_dir),
        )

    worker = RunWorker(service, runner=fake_runner)
    client = TestClient(create_app(service=service, worker=worker))
    project = create_project(client, tmp_path)
    run = create_run(client, str(project["id"]))

    executed = client.post(
        f"/api/v1/runs/{run['id']}/execute",
        json={
            "output_dir": str(tmp_path / "runs"),
            "require_api_key": False,
        },
    ).json()
    diff = client.get(f"/api/v1/runs/{run['id']}/diff").json()

    assert executed["id"] == run["id"]
    assert executed["status"] == "succeeded"
    assert executed["summary"] == "done"
    assert diff["diff"] == "--- repo/a.py\n+++ repo/a.py\n"


def test_api_maps_invalid_requests_to_http_errors(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)

    assert client.post("/api/v1/projects", json={"name": " ", "repo_path": "."}).status_code == 400
    assert client.get("/api/v1/projects/missing").status_code == 404
    assert client.get("/api/v1/runs/missing").status_code == 404
    assert client.get("/api/v1/runs?project_id=missing").status_code == 404
    assert client.post(
        "/api/v1/runs",
        json={
            "project_id": "missing",
            "task": "Fix",
            "model_provider": "openai",
            "model": "gpt-5.5",
            "tool_strategy": "native",
        },
    ).status_code == 404
    assert client.post(
        "/api/v1/runs/missing/tool-calls/review",
        json={"tool_name": "shell.exec", "arguments": {}},
    ).status_code == 404
    assert client.get("/api/v1/runs/missing/artifacts").status_code == 404
    assert client.get("/api/v1/runs/missing/diff").status_code == 404
    assert client.post("/api/v1/runs/missing/execute", json={}).status_code == 404
    assert client.post(
        "/api/v1/approvals/missing/decide",
        json={"approved": False, "decided_by": "jasper"},
    ).status_code == 404
