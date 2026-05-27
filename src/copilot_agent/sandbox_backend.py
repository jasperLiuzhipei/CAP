from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

SandboxBackendStatus = Literal["available", "planned"]
DEFAULT_DOCKER_IMAGE = "python:3.13-slim"


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


@dataclass(frozen=True)
class SandboxBackendRunOptions:
    """Backend-specific execution options shared by CLI and worker entrypoints."""

    docker_image: str = DEFAULT_DOCKER_IMAGE
    docker_exposed_ports: tuple[int, ...] = ()


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
        options: SandboxBackendRunOptions | None = None,
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
        status="available",
        isolation="container filesystem, network, process, and resource limits",
        execution_model="OpenAI Agents SDK DockerSandboxClient",
        supports_path_grants=False,
        supports_python_runtime_provisioning=True,
        notes=(
            "Production-oriented local backend. Requires Docker, the Python docker package, "
            "and an image that contains the runtime tools your verification command needs."
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
        options: SandboxBackendRunOptions | None = None,
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


class DockerSandboxBackend:
    """OpenAI Agents SDK Docker backend for stronger workspace isolation."""

    @property
    def spec(self) -> SandboxBackendSpec:
        return SANDBOX_BACKENDS["docker"]

    def build_manifest(
        self,
        sdk: dict[str, Any],
        *,
        repo: Path,
        runtime_grant_paths: Sequence[Path],
    ) -> Any:
        _ = runtime_grant_paths
        return sdk["Manifest"](
            entries={
                "repo": sdk["LocalDir"](src=repo),
            },
            extra_path_grants=(),
        )

    async def create_session(
        self,
        sdk: dict[str, Any],
        *,
        manifest: Any,
        options: SandboxBackendRunOptions | None = None,
    ) -> SandboxSessionHandle:
        options = options or SandboxBackendRunOptions()
        docker_from_env, docker_client_cls, docker_options_cls = _resolve_docker_sdk(sdk)
        try:
            docker_sdk_client = docker_from_env()
        except Exception as exc:
            raise RuntimeError(
                "Docker sandbox backend could not connect to the Docker daemon. "
                "Start Docker Desktop or your Docker daemon, then retry the run."
            ) from exc

        client = docker_client_cls(docker_sdk_client)
        sandbox = await client.create(
            manifest=manifest,
            options=docker_options_cls(
                image=options.docker_image,
                exposed_ports=options.docker_exposed_ports,
            ),
        )
        return SandboxSessionHandle(
            backend_id=self.spec.id,
            client=client,
            sandbox=sandbox,
        )

    async def delete_session(self, handle: SandboxSessionHandle) -> None:
        await handle.client.delete(handle.sandbox)


SANDBOX_BACKEND_ADAPTERS: dict[str, SandboxBackend] = {
    "unix_local": UnixLocalSandboxBackend(),
    "docker": DockerSandboxBackend(),
}


def _resolve_docker_sdk(sdk: dict[str, Any]) -> tuple[Any, Any, Any]:
    docker_from_env = sdk.get("docker_from_env")
    docker_client_cls = sdk.get("DockerSandboxClient")
    docker_options_cls = sdk.get("DockerSandboxClientOptions")
    if docker_from_env and docker_client_cls and docker_options_cls:
        return docker_from_env, docker_client_cls, docker_options_cls

    try:
        from agents.sandbox.sandboxes.docker import (  # type: ignore[import-untyped]
            DockerSandboxClient,
            DockerSandboxClientOptions,
        )
        from docker import from_env as docker_from_env  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "Docker sandbox backend requires Docker support. Install optional dependencies "
            "with `pip install -e '.[docker]'` and make sure Docker Desktop or the Docker "
            "daemon is running."
        ) from exc

    return docker_from_env, DockerSandboxClient, DockerSandboxClientOptions


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


def parse_docker_exposed_ports(raw_value: str | None) -> tuple[int, ...]:
    if raw_value is None or not raw_value.strip():
        return ()

    ports: list[int] = []
    for raw_part in raw_value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            port = int(part)
        except ValueError as exc:
            raise ValueError("Docker exposed ports must be comma-separated integers.") from exc
        if port < 1 or port > 65535:
            raise ValueError("Docker exposed ports must be between 1 and 65535.")
        if port not in ports:
            ports.append(port)
    return tuple(ports)


def validate_sandbox_backend_run_options(options: SandboxBackendRunOptions) -> None:
    if not options.docker_image.strip():
        raise ValueError("Docker image must not be empty.")
    for port in options.docker_exposed_ports:
        if port < 1 or port > 65535:
            raise ValueError("Docker exposed ports must be between 1 and 65535.")
