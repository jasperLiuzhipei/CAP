from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from copilot_agent.backend.service import CopilotBackendService
from copilot_agent.backend.store import SQLiteBackendStore
from copilot_agent.env import load_dotenv
from copilot_agent.sandbox_backend import (
    DEFAULT_DOCKER_IMAGE,
    DEFAULT_SANDBOX_COMMAND_TIMEOUT_SECONDS,
    parse_docker_exposed_ports,
    parse_optional_float,
    parse_optional_timeout,
)
from copilot_agent.worker import BackgroundRunWorker, RunExecutionOptions, RunWorker

from .app import create_app


@dataclass(frozen=True)
class ApiRuntimeConfig:
    db_path: Path
    auto_start_background_worker: bool
    worker_options: RunExecutionOptions

    @classmethod
    def from_env(
        cls,
        *,
        env: Mapping[str, str] | None = None,
        dotenv_path: Path = Path(".env"),
        load_env: bool = True,
    ) -> ApiRuntimeConfig:
        if load_env:
            load_dotenv(dotenv_path)

        source = env or os.environ
        return cls(
            db_path=Path(source.get("COPILOT_API_DB_PATH", ".copilot/control.sqlite")),
            auto_start_background_worker=_env_bool(
                source,
                "COPILOT_API_AUTO_START_WORKER",
                default=False,
            ),
            worker_options=RunExecutionOptions(
                test_cmd=_env_optional(source, "COPILOT_WORKER_TEST_CMD"),
                max_turns=_env_int(source, "COPILOT_WORKER_MAX_TURNS", default=32),
                output_dir=Path(source.get("COPILOT_WORKER_OUTPUT_DIR", "runs")),
                memory_enabled=_env_optional_bool(source, "COPILOT_WORKER_MEMORY_ENABLED"),
                host_verify=_env_bool(source, "COPILOT_WORKER_HOST_VERIFY", default=False),
                sandbox_runtime_enabled=_env_bool(
                    source,
                    "COPILOT_SANDBOX_RUNTIME_ENABLED",
                    default=True,
                ),
                sandbox_python=source.get("COPILOT_SANDBOX_PYTHON", "python3"),
                sandbox_command_timeout_seconds=(
                    parse_optional_timeout(source.get("COPILOT_SANDBOX_COMMAND_TIMEOUT_SECONDS"))
                    or DEFAULT_SANDBOX_COMMAND_TIMEOUT_SECONDS
                ),
                docker_image=source.get("COPILOT_DOCKER_IMAGE", DEFAULT_DOCKER_IMAGE),
                docker_exposed_ports=parse_docker_exposed_ports(
                    source.get("COPILOT_DOCKER_EXPOSED_PORTS")
                ),
                docker_network=source.get("COPILOT_DOCKER_NETWORK", "bridge"),
                docker_memory_limit=_env_optional(source, "COPILOT_DOCKER_MEMORY_LIMIT"),
                docker_cpus=parse_optional_float(
                    source.get("COPILOT_DOCKER_CPUS"),
                    name="COPILOT_DOCKER_CPUS",
                ),
                require_api_key=_env_bool(source, "COPILOT_WORKER_REQUIRE_API_KEY", default=True),
            ),
        )

    def public_dict(self) -> dict[str, object]:
        return {
            "db_path": str(self.db_path),
            "auto_start_background_worker": self.auto_start_background_worker,
        }


def create_app_from_env(
    *,
    dotenv_path: Path = Path(".env"),
    load_env: bool = True,
) -> FastAPI:
    config = ApiRuntimeConfig.from_env(dotenv_path=dotenv_path, load_env=load_env)
    service = CopilotBackendService(SQLiteBackendStore(config.db_path))
    worker = RunWorker(service)
    background_worker = BackgroundRunWorker(
        worker,
        default_options=config.worker_options,
    )
    return create_app(
        service=service,
        worker=worker,
        background_worker=background_worker,
        auto_start_background_worker=config.auto_start_background_worker,
        runtime_config=config.public_dict(),
    )


def _env_optional(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _env_int(env: Mapping[str, str], name: str, *, default: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value < 1:
        raise ValueError(f"{name} must be at least 1.")
    return value


def _env_optional_bool(env: Mapping[str, str], name: str) -> bool | None:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return None
    return _parse_bool(name, raw)


def _env_bool(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    return _parse_bool(name, raw)


def _parse_bool(name: str, raw: str) -> bool:
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on", "enabled", "enable"}:
        return True
    if value in {"0", "false", "no", "n", "off", "disabled", "disable"}:
        return False
    raise ValueError(f"{name} must be a boolean value such as true/false, yes/no, or 1/0.")
