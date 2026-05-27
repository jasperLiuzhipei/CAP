from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from copilot_agent.sandbox_backend import (
    DEFAULT_DOCKER_IMAGE,
    SandboxBackendRunOptions,
    get_sandbox_backend_adapter,
    parse_docker_exposed_ports,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke test the real Docker sandbox backend.")
    parser.add_argument("--repo", type=Path, default=Path("examples/sample_repo"))
    parser.add_argument("--image", default=DEFAULT_DOCKER_IMAGE)
    parser.add_argument("--network", choices=("bridge", "none", "host"), default="bridge")
    parser.add_argument("--memory-limit", default=None)
    parser.add_argument("--cpus", type=float, default=None)
    parser.add_argument("--exposed-ports", default=None)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--command", default="python -m pytest tests")
    return parser


async def run(args: argparse.Namespace) -> int:
    from agents.sandbox import Manifest
    from agents.sandbox.entries import LocalDir

    backend = get_sandbox_backend_adapter("docker")
    manifest = Manifest(entries={"repo": LocalDir(src=args.repo.resolve())})
    handle = await backend.create_session(
        {},
        manifest=manifest,
        options=SandboxBackendRunOptions(
            docker_image=args.image,
            docker_exposed_ports=parse_docker_exposed_ports(args.exposed_ports),
            docker_network=args.network,
            docker_memory_limit=args.memory_limit,
            docker_cpus=args.cpus,
        ),
    )
    try:
        async with handle.sandbox:
            result = await handle.sandbox.exec(
                f"cd repo && {args.command}",
                shell=True,
                timeout=args.timeout,
            )
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")
            print(f"exit_code={result.exit_code}")
            print(stdout, end="")
            print(stderr, end="")
            return int(result.exit_code)
    finally:
        await backend.delete_session(handle)


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
