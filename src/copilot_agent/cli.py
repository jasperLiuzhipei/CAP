from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .env import load_dotenv
from .model_config import ResolvedModelConfig, provider_choices, resolve_model_config
from .phase_one import (
    DEFAULT_MODEL,
    PhaseOneConfig,
    build_phase_one_prompt,
    run_phase_one,
    validate_config,
)


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
        help=f"Model to use. Defaults to COPILOT_MODEL, provider-specific defaults, or {DEFAULT_MODEL}.",
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
        "--test-cmd",
        default=None,
        help="Optional verification command to run from repo/ after the agent finishes.",
    )
    run.add_argument("--max-turns", default=16, type=int, help="Maximum agent turns.")
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
    if report.saved_dir:
        print(f"\nSaved run artifacts to: {report.saved_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unknown command: {args.command}")
    return 2
