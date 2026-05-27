from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

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


@dataclass(frozen=True)
class SandboxSessionHandle:
    """Owns the SDK sandbox client/session pair for one Copilot run."""

    backend_id: str
    client: Any
    sandbox: Any


@runtime_checkable
class SandboxBackend(Protocol):
    """Backend adapter boundary for workspace sandbox lifecycle operations."""

    @property
    def spec(self) -> SandboxBackendSpec:
        """Return user-facing backend metadata exposed by the API and UI."""

    def build_manifest(
        self,
        sdk: dict[str, Any],
        *,
        repo: Path,
        runtime_grant_paths: Sequence[Path],
    ) -> Any:
        """Build the OpenAI Agents SDK manifest for a run workspace."""

    async def create_session(
        self,
        sdk: dict[str, Any],
        *,
        manifest: Any,
    ) -> SandboxSessionHandle:
        """Create one sandbox session using the supplied SDK manifest."""

    async def delete_session(self, handle: SandboxSessionHandle) -> None:
        """Release resources owned by a sandbox session."""


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


class UnixLocalSandboxBackend:
    """OpenAI Agents SDK Unix local backend used for local development."""

    @property
    def spec(self) -> SandboxBackendSpec:
        return SANDBOX_BACKENDS["unix_local"]

    def build_manifest(
        self,
        sdk: dict[str, Any],
        *,
        repo: Path,
        runtime_grant_paths: Sequence[Path],
    ) -> Any:
        runtime_grants = [
            sdk["SandboxPathGrant"](path=path, read_only=True) for path in runtime_grant_paths
        ]
        return sdk["Manifest"](
            entries={
                "repo": sdk["LocalDir"](src=repo),
            },
            extra_path_grants=tuple(runtime_grants),
        )

    async def create_session(
        self,
        sdk: dict[str, Any],
        *,
        manifest: Any,
    ) -> SandboxSessionHandle:
        client = sdk["UnixLocalSandboxClient"]()
        sandbox = await client.create(manifest=manifest)
        return SandboxSessionHandle(
            backend_id=self.spec.id,
            client=client,
            sandbox=sandbox,
        )

    async def delete_session(self, handle: SandboxSessionHandle) -> None:
        await handle.client.delete(handle.sandbox)


@dataclass(frozen=True)
class PlannedSandboxBackend:
    """Placeholder adapter for visible but not-yet-executable backend specs."""

    spec: SandboxBackendSpec

    def build_manifest(
        self,
        sdk: dict[str, Any],
        *,
        repo: Path,
        runtime_grant_paths: Sequence[Path],
    ) -> Any:
        raise NotImplementedError(
            f"Sandbox backend `{self.spec.id}` is {self.spec.status}; "
            "select an available backend before running a task."
        )

    async def create_session(
        self,
        sdk: dict[str, Any],
        *,
        manifest: Any,
    ) -> SandboxSessionHandle:
        raise NotImplementedError(
            f"Sandbox backend `{self.spec.id}` is {self.spec.status}; "
            "select an available backend before running a task."
        )

    async def delete_session(self, handle: SandboxSessionHandle) -> None:
        return None


SANDBOX_BACKEND_ADAPTERS: dict[str, SandboxBackend] = {
    "unix_local": UnixLocalSandboxBackend(),
    "docker": PlannedSandboxBackend(SANDBOX_BACKENDS["docker"]),
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


def get_sandbox_backend_adapter(
    backend_id: str,
    *,
    require_available: bool = True,
) -> SandboxBackend:
    validate_sandbox_backend(backend_id, require_available=require_available)
    return SANDBOX_BACKEND_ADAPTERS[backend_id]
