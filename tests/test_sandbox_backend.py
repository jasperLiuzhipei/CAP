from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from copilot_agent.sandbox_backend import (
    SandboxBackend,
    UnixLocalSandboxBackend,
    get_sandbox_backend,
    get_sandbox_backend_adapter,
    list_sandbox_backends,
    validate_sandbox_backend,
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


FAKE_SDK = {
    "LocalDir": FakeLocalDir,
    "Manifest": FakeManifest,
    "SandboxPathGrant": FakeSandboxPathGrant,
    "UnixLocalSandboxClient": FakeUnixLocalSandboxClient,
}


def test_sandbox_backend_registry_exposes_available_and_planned_backends() -> None:
    backends = {backend.id: backend for backend in list_sandbox_backends()}

    assert backends["unix_local"].available
    assert backends["unix_local"].supports_path_grants
    assert backends["docker"].status == "planned"
    assert not backends["docker"].available


def test_sandbox_backend_validation_rejects_unknown_or_unavailable_backends() -> None:
    assert validate_sandbox_backend("unix_local").id == "unix_local"
    assert validate_sandbox_backend("docker", require_available=False).id == "docker"

    with pytest.raises(ValueError, match="Unsupported sandbox backend"):
        get_sandbox_backend("space_station")
    with pytest.raises(ValueError, match="planned"):
        validate_sandbox_backend("docker")


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


def test_planned_backend_is_visible_but_not_executable(tmp_path: Path) -> None:
    backend = get_sandbox_backend_adapter("docker", require_available=False)

    assert backend.spec.status == "planned"
    with pytest.raises(NotImplementedError, match="planned"):
        backend.build_manifest(FAKE_SDK, repo=tmp_path, runtime_grant_paths=[])
