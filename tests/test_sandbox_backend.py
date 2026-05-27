from __future__ import annotations

import pytest

from copilot_agent.sandbox_backend import (
    get_sandbox_backend,
    list_sandbox_backends,
    validate_sandbox_backend,
)


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
