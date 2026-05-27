from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from copilot_agent.api.runtime import ApiRuntimeConfig, create_app_from_env


def test_api_runtime_config_reads_worker_env(tmp_path: Path) -> None:
    env = {
        "COPILOT_API_DB_PATH": str(tmp_path / "control.sqlite"),
        "COPILOT_API_AUTO_START_WORKER": "true",
        "COPILOT_WORKER_TEST_CMD": "python -m pytest tests",
        "COPILOT_WORKER_MAX_TURNS": "12",
        "COPILOT_WORKER_OUTPUT_DIR": str(tmp_path / "runs"),
        "COPILOT_WORKER_MEMORY_ENABLED": "false",
        "COPILOT_WORKER_HOST_VERIFY": "yes",
        "COPILOT_SANDBOX_RUNTIME_ENABLED": "0",
        "COPILOT_SANDBOX_PYTHON": "python3.13",
        "COPILOT_WORKER_REQUIRE_API_KEY": "no",
    }

    config = ApiRuntimeConfig.from_env(env=env, load_env=False)

    assert config.db_path == tmp_path / "control.sqlite"
    assert config.auto_start_background_worker is True
    assert config.worker_options.test_cmd == "python -m pytest tests"
    assert config.worker_options.max_turns == 12
    assert config.worker_options.output_dir == tmp_path / "runs"
    assert config.worker_options.memory_enabled is False
    assert config.worker_options.host_verify is True
    assert config.worker_options.sandbox_runtime_enabled is False
    assert config.worker_options.sandbox_python == "python3.13"
    assert config.worker_options.require_api_key is False


def test_create_app_from_env_exposes_runtime_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COPILOT_API_DB_PATH", str(tmp_path / "control.sqlite"))
    monkeypatch.setenv("COPILOT_API_AUTO_START_WORKER", "true")
    monkeypatch.setenv("COPILOT_WORKER_TEST_CMD", "python -m pytest tests")
    monkeypatch.setenv("COPILOT_WORKER_REQUIRE_API_KEY", "false")

    app = create_app_from_env(load_env=False)

    with TestClient(app) as client:
        runtime_config = client.get("/api/v1/runtime/config").json()
        worker_status = client.get("/api/v1/worker/status").json()

    assert runtime_config["db_path"] == str(tmp_path / "control.sqlite")
    assert runtime_config["auto_start_background_worker"] is True
    assert runtime_config["worker_test_cmd"] == "python -m pytest tests"
    assert runtime_config["worker_require_api_key"] is False
    assert worker_status["running"] is True


def test_api_runtime_config_rejects_invalid_env() -> None:
    with pytest.raises(ValueError, match="COPILOT_WORKER_MAX_TURNS"):
        ApiRuntimeConfig.from_env(
            env={"COPILOT_WORKER_MAX_TURNS": "zero"},
            load_env=False,
        )

    with pytest.raises(ValueError, match="COPILOT_API_AUTO_START_WORKER"):
        ApiRuntimeConfig.from_env(
            env={"COPILOT_API_AUTO_START_WORKER": "sometimes"},
            load_env=False,
        )
