from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .env import load_dotenv
from .memory import ensure_memory_file, memory_is_enabled, resolve_memory_path
from .model_config import ResolvedModelConfig, provider_choices, resolve_model_config
from .phase_one import (
    DEFAULT_MODEL,
    PhaseOneConfig,
    build_phase_one_prompt,
    run_phase_one,
    validate_config,
)
from .runs import apply_run_patch, list_runs, load_report, read_run_text, resolve_run_dir


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="copilot-agent",
        description="Phase-one Copilot CLI built on openai-agents-python.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser(
        "run",
        help="Run the phase-one local sandbox coding workflow.",
    )
    run.add_argument("--repo", required=True, type=Path, help="Path to the target repository.")
    run.add_argument("--task", required=True, help="Coding task to perform.")
    run.add_argument(
        "--provider",
        default=None,
        choices=provider_choices(),
        help="Model provider route. Defaults to COPILOT_MODEL_PROVIDER or openai.",
    )
    run.add_argument(
        "--model",
        default=None,
        help=(
            "Model to use. Defaults to COPILOT_MODEL, provider-specific defaults, "
            f"or {DEFAULT_MODEL}."
        ),
    )
    run.add_argument(
        "--base-url",
        default=None,
        help="Override the OpenAI-compatible base URL for this run.",
    )
    run.add_argument(
        "--api-key-env",
        default=None,
        help="Environment variable that contains the provider API key.",
    )
    run.add_argument(
        "--model-transport",
        default=None,
        choices=("native", "chat_completions"),
        help="Advanced: force the SDK model transport for this run.",
    )
    run.add_argument(
        "--tool-strategy",
        default=None,
        choices=("native", "compat_functions", "shell_only"),
        help=(
            "Advanced: choose sandbox tool exposure. OpenAI native uses native; "
            "Chat Completions providers default to compat_functions."
        ),
    )
    run.add_argument(
        "--test-cmd",
        default=None,
        help="Optional verification command to run from repo/ after the agent finishes.",
    )
    run.add_argument(
        "--memory",
        action="store_true",
        help="Enable project memory for this run, creating it after the run if needed.",
    )
    run.add_argument(
        "--no-memory",
        action="store_true",
        help="Disable project memory even if .copilot/memory.md exists.",
    )
    run.add_argument(
        "--memory-path",
        default=None,
        type=Path,
        help="Project memory path, relative to --repo unless absolute.",
    )
    run.add_argument(
        "--host-verify",
        action="store_true",
        help=(
            "Also run the verification command on a temporary host-side copy after applying "
            "the sandbox diff. Useful when local sandbox runtimes cannot run Python."
        ),
    )
    run.add_argument("--max-turns", default=32, type=int, help="Maximum agent turns.")
    run.add_argument(
        "--output-dir",
        default=Path("runs"),
        type=Path,
        help="Directory where reports are saved.",
    )
    run.add_argument("--no-save", action="store_true", help="Do not save run artifacts.")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate config and print the generated prompt without importing the Agents SDK.",
    )

    init = subparsers.add_parser(
        "init",
        help="Initialize Copilot project metadata in a target repository.",
    )
    init.add_argument("--repo", required=True, type=Path, help="Path to the target repository.")
    init.add_argument("--force", action="store_true", help="Overwrite existing config file.")

    runs = subparsers.add_parser("runs", help="List saved Copilot runs.")
    runs.add_argument("--output-dir", default=Path("runs"), type=Path)
    runs.add_argument("--limit", default=20, type=int)

    show = subparsers.add_parser("show-run", help="Show a saved Copilot run.")
    show.add_argument("--run", required=True, help="Run id or run directory path.")
    show.add_argument("--output-dir", default=Path("runs"), type=Path)
    show.add_argument("--diff", action="store_true", help="Print the saved diff.")
    show.add_argument("--final", action="store_true", help="Print the final agent output.")

    apply = subparsers.add_parser(
        "apply-run",
        help="Apply a saved sandbox diff back to the real repository.",
    )
    apply.add_argument("--run", required=True, help="Run id or run directory path.")
    apply.add_argument("--output-dir", default=Path("runs"), type=Path)
    apply.add_argument("--repo", default=None, type=Path, help="Override target repository path.")
    apply.add_argument("--check", action="store_true", help="Only check whether the patch applies.")

    return parser


def _model_config_from_args(
    args: argparse.Namespace,
    *,
    require_api_key: bool,
) -> ResolvedModelConfig:
    return resolve_model_config(
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        transport=args.model_transport,
        tool_strategy=args.tool_strategy,
        require_api_key=require_api_key,
    )


def _config_from_args(
    args: argparse.Namespace,
    model_config: ResolvedModelConfig,
) -> PhaseOneConfig:
    return PhaseOneConfig(
        repo=args.repo.resolve(),
        task=args.task,
        model_config=model_config,
        test_cmd=args.test_cmd,
        max_turns=args.max_turns,
        output_dir=args.output_dir,
        save=not args.no_save,
        memory_enabled=memory_is_enabled(
            args.repo.resolve(),
            args.memory_path,
            forced=args.memory,
            disabled=args.no_memory,
        ),
        memory_path=args.memory_path,
        host_verify=args.host_verify,
    )


async def _run(args: argparse.Namespace) -> int:
    load_dotenv()
    model_config = _model_config_from_args(args, require_api_key=not args.dry_run)
    config = _config_from_args(args, model_config)
    validate_config(config)

    if args.dry_run:
        print("Phase-one config is valid.\n")
        print("Model route:")
        print(config.model_config.safe_summary())
        print()
        print(
            "Project memory:",
            str(resolve_memory_path(config.repo, config.memory_path))
            if config.memory_enabled
            else "disabled",
        )
        print("Host verification:", "enabled" if config.host_verify else "disabled")
        print()
        print("Generated agent prompt:\n")
        print(build_phase_one_prompt(config))
        return 0

    report = await run_phase_one(config)
    print("\n=== Final output ===")
    print(report.final_output)
    print("\n=== Git status ===")
    print(report.git_status or "(clean)")
    print("\n=== Diff ===")
    print(report.diff or "(no diff)")
    if report.verification is not None:
        print("\n=== Verification ===")
        print(f"$ {report.verification.command}")
        print(report.verification.combined_output)
        print(f"exit_code={report.verification.exit_code}")
    if report.host_verification is not None:
        print("\n=== Host verification ===")
        print(f"$ {report.host_verification.command}")
        print(report.host_verification.combined_output)
        print(f"exit_code={report.host_verification.exit_code}")
    if report.saved_dir:
        print(f"\nSaved run artifacts to: {report.saved_dir}")
    if report.memory_path:
        print(f"Updated project memory: {report.memory_path}")
    return 0


def _init_project(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    if not repo.exists() or not repo.is_dir():
        raise ValueError(f"Repository path does not exist or is not a directory: {repo}")

    copilot_dir = repo / ".copilot"
    copilot_dir.mkdir(parents=True, exist_ok=True)
    config_path = copilot_dir / "config.json"
    if config_path.exists() and not args.force:
        raise FileExistsError(f"Config already exists: {config_path}. Use --force to overwrite.")

    memory_path = ensure_memory_file(repo)
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "memory_path": ".copilot/memory.md",
                "default_output_dir": "runs",
                "model_provider_env": "COPILOT_MODEL_PROVIDER",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Initialized Copilot project metadata in: {copilot_dir}")
    print(f"Config: {config_path}")
    print(f"Memory: {memory_path}")
    return 0


def _list_runs(args: argparse.Namespace) -> int:
    records = list_runs(args.output_dir, limit=args.limit)
    if not records:
        print(f"No saved runs found in {args.output_dir}.")
        return 0

    for record in records:
        changed = "changed" if record.changed else "clean"
        model = f"{record.model_provider}/{record.model}".strip("/")
        print(f"{record.run_id}  {changed}  {model}  {record.task}")
    return 0


def _show_run(args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args.run, args.output_dir)
    report = load_report(run_dir)
    print(f"Run: {report.get('run_id', run_dir.name)}")
    print(f"Repo: {report.get('repo', '')}")
    print(f"Task: {report.get('task', '')}")
    print(f"Model: {report.get('model_provider', '')}/{report.get('model', '')}")
    print(f"Tool strategy: {report.get('tool_strategy', '')}")
    print(f"Git status:\n{read_run_text(run_dir, 'git_status.txt') or '(clean)'}")

    if args.final:
        print("\n=== Final output ===")
        print(read_run_text(run_dir, "final.md") or report.get("final_output", ""))
    if args.diff:
        print("\n=== Diff ===")
        print(read_run_text(run_dir, "diff.patch") or "(no diff)")
    return 0


def _apply_run(args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args.run, args.output_dir)
    result = apply_run_patch(run_dir, repo=args.repo, check_only=args.check)
    print("$ " + " ".join(result.command))
    if result.combined_output:
        print(result.combined_output)
    if args.check:
        print("Patch check passed." if result.exit_code == 0 else "Patch check failed.")
    else:
        print("Patch applied." if result.applied else "Patch was not applied.")
    return result.exit_code


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            return asyncio.run(_run(args))
        if args.command == "init":
            return _init_project(args)
        if args.command == "runs":
            return _list_runs(args)
        if args.command == "show-run":
            return _show_run(args)
        if args.command == "apply-run":
            return _apply_run(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unknown command: {args.command}")
    return 2
