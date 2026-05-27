from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SandboxBackendStatus = Literal["available", "planned"]


@dataclass(frozen=True)
class SandboxBackendSpec:
    id: str
    display_name: str
    status: SandboxBackendStatus
    isolation: str
    execution_model: str
    supports_path_grants: bool
    supports_python_runtime_provisioning: bool
    notes: str

    @property
    def available(self) -> bool:
        return self.status == "available"


SANDBOX_BACKENDS: dict[str, SandboxBackendSpec] = {
    "unix_local": SandboxBackendSpec(
        id="unix_local",
        display_name="Unix Local Sandbox",
        status="available",
        isolation="macOS sandbox-exec / local temporary workspace",
        execution_model="OpenAI Agents SDK UnixLocalSandboxClient",
        supports_path_grants=True,
        supports_python_runtime_provisioning=True,
        notes=(
            "Best for local development. It uses the SDK sandbox lifecycle and our runtime "
            "path grants, but it is not the final multi-tenant production isolation boundary."
        ),
    ),
    "docker": SandboxBackendSpec(
        id="docker",
        display_name="Docker Sandbox",
        status="planned",
        isolation="container filesystem, network, process, and resource limits",
        execution_model="future SandboxBackend implementation",
        supports_path_grants=False,
        supports_python_runtime_provisioning=True,
        notes=(
            "Planned production-oriented backend. It will reuse the same Copilot run, "
            "artifact, verification, and RunEvent contracts."
        ),
    ),
}


def list_sandbox_backends() -> list[SandboxBackendSpec]:
    return list(SANDBOX_BACKENDS.values())


def get_sandbox_backend(backend_id: str) -> SandboxBackendSpec:
    try:
        return SANDBOX_BACKENDS[backend_id]
    except KeyError as exc:
        supported = ", ".join(sorted(SANDBOX_BACKENDS))
        raise ValueError(
            f"Unsupported sandbox backend `{backend_id}`. Choose one of: {supported}."
        ) from exc


def validate_sandbox_backend(
    backend_id: str,
    *,
    require_available: bool = True,
) -> SandboxBackendSpec:
    backend = get_sandbox_backend(backend_id)
    if require_available and not backend.available:
        raise ValueError(
            f"Sandbox backend `{backend.id}` is {backend.status}; use an available backend."
        )
    return backend
