from __future__ import annotations

import asyncio
import builtins
from pathlib import Path

import pytest

from copilot_agent.sandbox_backend import (
    DEFAULT_DOCKER_IMAGE,
    DockerSandboxBackend,
    SandboxBackend,
    SandboxBackendRunOptions,
    UnixLocalSandboxBackend,
    _resolve_docker_sdk,
    docker_create_kwargs,
    get_sandbox_backend,
    get_sandbox_backend_adapter,
    list_sandbox_backends,
    parse_docker_exposed_ports,
    validate_sandbox_backend,
    validate_sandbox_backend_run_options,
)


class FakeSandboxPathGrant:
    def __init__(self, *, path: Path, read_only: bool) -> None:
        self.path = path
        self.read_only = read_only


class FakeLocalDir:
    def __init__(self, *, src: Path) -> None:
        self.src = src


class FakeManifest:
    def __init__(
        self,
        *,
        entries: dict[str, object],
        extra_path_grants: tuple[object, ...],
    ) -> None:
        self.entries = entries
        self.extra_path_grants = extra_path_grants


class FakeUnixLocalSandboxClient:
    def __init__(self) -> None:
        self.created_manifest: object | None = None
        self.deleted_sandbox: object | None = None

    async def create(self, *, manifest: object) -> object:
        self.created_manifest = manifest
        return {"manifest": manifest}

    async def delete(self, sandbox: object) -> None:
        self.deleted_sandbox = sandbox


class FakeDockerContainers:
    def __init__(self) -> None:
        self.create_kwargs: dict[str, object] | None = None

    def create(self, **kwargs: object) -> object:
        self.create_kwargs = kwargs
        return object()


class FakeDockerSDKClient:
    def __init__(self) -> None:
        self.containers = FakeDockerContainers()
        self.images = object()
        self.volumes = object()


class FakeDockerSandboxClientOptions:
    def __init__(
        self,
        *,
        image: str,
        exposed_ports: tuple[int, ...] = (),
    ) -> None:
        self.image = image
        self.exposed_ports = exposed_ports


class FakeDockerSandboxClient:
    def __init__(self, docker_client: object) -> None:
        self.docker_client = docker_client
        self.created_manifest: object | None = None
        self.created_options: FakeDockerSandboxClientOptions | None = None
        self.created_container: object | None = None
        self.deleted_sandbox: object | None = None

    async def create(
        self,
        *,
        manifest: object,
        options: FakeDockerSandboxClientOptions,
    ) -> object:
        self.created_manifest = manifest
        self.created_options = options
        self.created_container = self.docker_client.containers.create(image=options.image)
        return {"manifest": manifest, "image": options.image}

    async def delete(self, sandbox: object) -> None:
        self.deleted_sandbox = sandbox


FAKE_SDK = {
    "LocalDir": FakeLocalDir,
    "Manifest": FakeManifest,
    "SandboxPathGrant": FakeSandboxPathGrant,
    "UnixLocalSandboxClient": FakeUnixLocalSandboxClient,
    "docker_from_env": FakeDockerSDKClient,
    "DockerSandboxClient": FakeDockerSandboxClient,
    "DockerSandboxClientOptions": FakeDockerSandboxClientOptions,
}


def test_sandbox_backend_registry_exposes_available_and_planned_backends() -> None:
    backends = {backend.id: backend for backend in list_sandbox_backends()}

    assert backends["unix_local"].available
    assert backends["unix_local"].supports_path_grants
    assert backends["docker"].status == "available"
    assert backends["docker"].available
    assert not backends["docker"].supports_path_grants


def test_sandbox_backend_validation_rejects_unknown_backends() -> None:
    assert validate_sandbox_backend("unix_local").id == "unix_local"
    assert validate_sandbox_backend("docker").id == "docker"

    with pytest.raises(ValueError, match="Unsupported sandbox backend"):
        get_sandbox_backend("space_station")


def test_unix_local_backend_builds_openai_agents_manifest(tmp_path: Path) -> None:
    backend = get_sandbox_backend_adapter("unix_local")
    runtime_root = tmp_path / "python"
    runtime_root.mkdir()

    manifest = backend.build_manifest(
        FAKE_SDK,
        repo=tmp_path,
        runtime_grant_paths=[runtime_root],
    )

    assert isinstance(backend, SandboxBackend)
    assert isinstance(backend, UnixLocalSandboxBackend)
    assert isinstance(manifest, FakeManifest)
    assert isinstance(manifest.entries["repo"], FakeLocalDir)
    assert manifest.entries["repo"].src == tmp_path
    assert len(manifest.extra_path_grants) == 1
    assert manifest.extra_path_grants[0].path == runtime_root
    assert manifest.extra_path_grants[0].read_only


def test_unix_local_backend_owns_session_lifecycle(tmp_path: Path) -> None:
    async def run_lifecycle() -> None:
        backend = get_sandbox_backend_adapter("unix_local")
        manifest = FakeManifest(entries={}, extra_path_grants=())

        handle = await backend.create_session(FAKE_SDK, manifest=manifest)
        await backend.delete_session(handle)

        assert handle.backend_id == "unix_local"
        assert isinstance(handle.client, FakeUnixLocalSandboxClient)
        assert handle.client.created_manifest is manifest
        assert handle.sandbox == {"manifest": manifest}
        assert handle.client.deleted_sandbox == handle.sandbox

    asyncio.run(run_lifecycle())


def test_docker_backend_builds_manifest_without_host_runtime_grants(tmp_path: Path) -> None:
    backend = get_sandbox_backend_adapter("docker")
    runtime_root = tmp_path / "python"
    runtime_root.mkdir()

    manifest = backend.build_manifest(
        FAKE_SDK,
        repo=tmp_path,
        runtime_grant_paths=[runtime_root],
    )

    assert isinstance(backend, DockerSandboxBackend)
    assert isinstance(manifest.entries["repo"], FakeLocalDir)
    assert manifest.entries["repo"].src == tmp_path
    assert manifest.extra_path_grants == ()


def test_docker_backend_owns_session_lifecycle(tmp_path: Path) -> None:
    async def run_lifecycle() -> None:
        backend = get_sandbox_backend_adapter("docker")
        manifest = FakeManifest(entries={}, extra_path_grants=())

        handle = await backend.create_session(
            FAKE_SDK,
            manifest=manifest,
            options=SandboxBackendRunOptions(
                docker_image="copilot-test:latest",
                docker_exposed_ports=(8000, 5173),
                docker_network="none",
                docker_memory_limit="512m",
                docker_cpus=1.5,
            ),
        )
        await backend.delete_session(handle)

        assert handle.backend_id == "docker"
        assert isinstance(handle.client, FakeDockerSandboxClient)
        assert handle.client.docker_client.images is not None
        assert handle.client.created_manifest is manifest
        assert handle.client.created_options is not None
        assert handle.client.created_options.image == "copilot-test:latest"
        assert handle.client.created_options.exposed_ports == (8000, 5173)
        inner_containers = handle.client.docker_client.containers._containers
        assert inner_containers.create_kwargs == {
            "image": "copilot-test:latest",
            "network_mode": "none",
            "mem_limit": "512m",
            "nano_cpus": 1_500_000_000,
        }
        assert handle.sandbox == {"manifest": manifest, "image": "copilot-test:latest"}
        assert handle.client.deleted_sandbox == handle.sandbox

    asyncio.run(run_lifecycle())


def test_docker_backend_wraps_daemon_connection_errors() -> None:
    async def run_lifecycle() -> None:
        def failing_docker_from_env() -> object:
            raise RuntimeError("socket unavailable")

        sdk = {
            **FAKE_SDK,
            "docker_from_env": failing_docker_from_env,
        }
        backend = get_sandbox_backend_adapter("docker")
        manifest = FakeManifest(entries={}, extra_path_grants=())

        with pytest.raises(RuntimeError, match="could not connect to the Docker daemon"):
            await backend.create_session(sdk, manifest=manifest)

    asyncio.run(run_lifecycle())


def test_docker_backend_defaults_and_port_parsing() -> None:
    assert SandboxBackendRunOptions().docker_image == DEFAULT_DOCKER_IMAGE
    assert parse_docker_exposed_ports(None) == ()
    assert parse_docker_exposed_ports("8000, 5173,8000") == (8000, 5173)

    with pytest.raises(ValueError, match="integers"):
        parse_docker_exposed_ports("abc")
    with pytest.raises(ValueError, match="between"):
        parse_docker_exposed_ports("70000")


def test_docker_create_kwargs_for_resource_limits() -> None:
    assert docker_create_kwargs(SandboxBackendRunOptions()) == {}
    assert docker_create_kwargs(
        SandboxBackendRunOptions(
            docker_network="none",
            docker_memory_limit="1g",
            docker_cpus=2.5,
        )
    ) == {
        "network_mode": "none",
        "mem_limit": "1g",
        "nano_cpus": 2_500_000_000,
    }


def test_docker_backend_missing_dependency_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "agents.sandbox.sandboxes.docker":
            raise ImportError("missing docker support")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="Docker sandbox backend requires Docker support"):
        _resolve_docker_sdk({})


def test_sandbox_backend_run_options_validation() -> None:
    validate_sandbox_backend_run_options(SandboxBackendRunOptions())

    with pytest.raises(ValueError, match="Docker image"):
        validate_sandbox_backend_run_options(SandboxBackendRunOptions(docker_image=" "))
    with pytest.raises(ValueError, match="between"):
        validate_sandbox_backend_run_options(
            SandboxBackendRunOptions(docker_exposed_ports=(0,))
        )
    with pytest.raises(ValueError, match="Docker network"):
        validate_sandbox_backend_run_options(
            SandboxBackendRunOptions(docker_network="space")  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="Docker memory"):
        validate_sandbox_backend_run_options(
            SandboxBackendRunOptions(docker_memory_limit=" ")
        )
    with pytest.raises(ValueError, match="CPU"):
        validate_sandbox_backend_run_options(SandboxBackendRunOptions(docker_cpus=0))
