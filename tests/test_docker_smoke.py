from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.getenv("COPILOT_RUN_DOCKER_SMOKE") != "1",
    reason="set COPILOT_RUN_DOCKER_SMOKE=1 to run real Docker smoke test",
)
def test_real_docker_backend_smoke() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is not installed")

    repo_root = Path(__file__).resolve().parents[1]
    image = os.getenv("COPILOT_DOCKER_IMAGE", "python:3.13-slim")
    network = os.getenv("COPILOT_DOCKER_NETWORK", "bridge")
    memory_limit = os.getenv("COPILOT_DOCKER_MEMORY_LIMIT")
    cpus = os.getenv("COPILOT_DOCKER_CPUS")
    command = os.getenv(
        "COPILOT_DOCKER_SMOKE_COMMAND",
        "python -c \"from pathlib import Path; assert Path('pyproject.toml').exists()\"",
    )

    args = [
        sys.executable,
        "scripts/smoke_docker_backend.py",
        "--repo",
        "examples/sample_repo",
        "--image",
        image,
        "--network",
        network,
        "--command",
        command,
    ]
    if memory_limit:
        args.extend(["--memory-limit", memory_limit])
    if cpus:
        args.extend(["--cpus", cpus])

    completed = subprocess.run(
        args,
        cwd=repo_root,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
