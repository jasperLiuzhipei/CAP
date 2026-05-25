from __future__ import annotations

import json
import difflib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .model_config import DEFAULT_OPENAI_MODEL, ResolvedModelConfig, resolve_model_config

DEFAULT_MODEL = DEFAULT_OPENAI_MODEL
DEFAULT_WORKFLOW_NAME = "Copilot phase-one local coding task"
SNAPSHOT_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}
SNAPSHOT_MAX_FILE_BYTES = 1_000_000


@dataclass(frozen=True)
class PhaseOneConfig:
    """Configuration for the first local Copilot vertical slice."""

    repo: Path
    task: str
    model_config: ResolvedModelConfig = field(
        default_factory=lambda: resolve_model_config(require_api_key=False)
    )
    test_cmd: str | None = None
    max_turns: int = 16
    output_dir: Path = Path("runs")
    save: bool = True


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        if self.stderr:
            return f"{self.stdout}{self.stderr}"
        return self.stdout


@dataclass
class PhaseOneReport:
    run_id: str
    repo: str
    task: str
    model: str
    model_provider: str
    model_transport: str
    model_base_url: str | None
    prompt: str
    final_output: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    git_baseline_created: bool = False
    git_baseline_log: str = ""
    git_status: str = ""
    diff: str = ""
    verification: CommandResult | None = None
    saved_dir: str | None = None


@dataclass(frozen=True)
class FileSnapshot:
    files: dict[str, str]


def validate_config(config: PhaseOneConfig) -> None:
    if not config.repo.exists():
        raise ValueError(f"Repository path does not exist: {config.repo}")
    if not config.repo.is_dir():
        raise ValueError(f"Repository path is not a directory: {config.repo}")
    if not config.task.strip():
        raise ValueError("Task must not be empty.")
    if config.max_turns < 1:
        raise ValueError("max_turns must be at least 1.")


def build_phase_one_prompt(config: PhaseOneConfig) -> str:
    verification = (
        f"Run this exact verification command from `repo/`: `{config.test_cmd}`."
        if config.test_cmd
        else "Infer and run the most relevant lightweight verification command if the repo provides one."
    )
    edit_instruction = (
        "Use the available shell tool to inspect and edit files. Do not call apply_patch; "
        "this provider route exposes shell tools only."
        if config.model_config.transport == "chat_completions"
        else "When using apply_patch, paths are relative to the sandbox workspace root, so edit `repo/...` paths."
    )

    return "\n".join(
        [
            "You are the phase-one Copilot coding agent.",
            "",
            "Workspace contract:",
            "- The target repository is mounted at `repo/` inside the sandbox workspace.",
            "- Inspect the repository before editing.",
            "- Make the smallest correct change that satisfies the task.",
            f"- {edit_instruction}",
            "- Preserve existing behavior unless the user explicitly asks for a broader change.",
            f"- {verification}",
            "- In your final answer, summarize changed files, verification results, and remaining risks.",
            "",
            "User task:",
            config.task.strip(),
        ]
    )


def _dependency_help(missing_name: str) -> str:
    return (
        f"Missing Python dependency `{missing_name}`. Install the phase-one runtime first:\n"
        "\n"
        "  python3 -m venv .venv\n"
        "  source .venv/bin/activate\n"
        "  python -m pip install -e openai-agents-python\n"
        "  python -m pip install -e .\n"
        "\n"
        "Then configure `.env` with COPILOT_MODEL_PROVIDER and the matching API key. "
        "See `.env.example` for provider presets."
    )


def _load_agents_sdk() -> dict[str, Any]:
    """Import OpenAI Agents SDK lazily so dry-run and tests do not require API deps."""

    try:
        from agents import (
            AsyncOpenAI,
            ModelSettings,
            OpenAIChatCompletionsModel,
            Runner,
            set_tracing_disabled,
        )
        from agents.run import RunConfig
        from agents.sandbox import Manifest, SandboxAgent, SandboxRunConfig
        from agents.sandbox.capabilities.capabilities import Capabilities
        from agents.sandbox.capabilities.shell import Shell
        from agents.sandbox.entries import LocalDir
        from agents.sandbox.sandboxes.unix_local import UnixLocalSandboxClient
    except ModuleNotFoundError as exc:
        raise RuntimeError(_dependency_help(exc.name or "unknown")) from exc

    return {
        "AsyncOpenAI": AsyncOpenAI,
        "Capabilities": Capabilities,
        "LocalDir": LocalDir,
        "Manifest": Manifest,
        "ModelSettings": ModelSettings,
        "OpenAIChatCompletionsModel": OpenAIChatCompletionsModel,
        "RunConfig": RunConfig,
        "Runner": Runner,
        "SandboxAgent": SandboxAgent,
        "SandboxRunConfig": SandboxRunConfig,
        "Shell": Shell,
        "UnixLocalSandboxClient": UnixLocalSandboxClient,
        "set_tracing_disabled": set_tracing_disabled,
    }


def _build_agent_model(config: PhaseOneConfig, sdk: dict[str, Any]) -> Any:
    """Return the SDK-native model object for the resolved provider route."""

    model_config = config.model_config
    if model_config.transport == "native":
        return model_config.model

    client_kwargs: dict[str, Any] = {
        "api_key": model_config.api_key,
    }
    if model_config.base_url:
        client_kwargs["base_url"] = model_config.base_url

    client = sdk["AsyncOpenAI"](**client_kwargs)
    return sdk["OpenAIChatCompletionsModel"](
        model=model_config.model,
        openai_client=client,
    )


def _build_agent(config: PhaseOneConfig, sdk: dict[str, Any]) -> Any:
    manifest = sdk["Manifest"](
        entries={
            "repo": sdk["LocalDir"](src=config.repo),
        }
    )

    if config.model_config.transport == "chat_completions":
        capabilities = [
            sdk["Shell"](),
        ]
    else:
        capabilities = sdk["Capabilities"].default()

    tool_choice = "auto" if config.model_config.transport == "chat_completions" else "required"

    return sdk["SandboxAgent"](
        name="Phase One Coding Agent",
        model=_build_agent_model(config, sdk),
        instructions=(
            "You are a careful workspace coding agent. Work only inside the mounted repository. "
            "Read before editing, prefer minimal patches, and verify your work. If validation is "
            "blocked by missing tools or environment problems, explain the blocker clearly."
        ),
        default_manifest=manifest,
        capabilities=capabilities,
        model_settings=sdk["ModelSettings"](tool_choice=tool_choice),
    )


async def _exec_text(sandbox: Any, command: str) -> CommandResult:
    result = await sandbox.exec(command, shell=True)
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    return CommandResult(
        command=command,
        exit_code=result.exit_code,
        stdout=stdout,
        stderr=stderr,
    )


async def _ensure_git_baseline(sandbox: Any) -> tuple[bool, str]:
    """Ensure `repo/` can produce a diff even when the source folder is not a git repo."""

    check = await _exec_text(sandbox, "git -C repo rev-parse --is-inside-work-tree")
    if check.exit_code == 0:
        return False, check.combined_output

    init_commands = " && ".join(
        [
            "git -C repo init",
            "git -C repo config user.email phase-one@example.local",
            "git -C repo config user.name 'Phase One Baseline'",
            "git -C repo add -A",
            "git -C repo commit -m 'phase-one baseline' --no-gpg-sign",
        ]
    )
    baseline = await _exec_text(sandbox, init_commands)
    return baseline.exit_code == 0, baseline.combined_output


def _should_snapshot_file(path: Path, root: Path) -> bool:
    rel_parts = path.relative_to(root).parts
    if any(part in SNAPSHOT_SKIP_DIRS for part in rel_parts):
        return False
    if not path.is_file():
        return False
    try:
        if path.stat().st_size > SNAPSHOT_MAX_FILE_BYTES:
            return False
    except OSError:
        return False
    return True


def _snapshot_local_tree(root: Path) -> FileSnapshot:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not _should_snapshot_file(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        try:
            files[rel] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    return FileSnapshot(files=files)


async def _read_sandbox_text(sandbox: Any, path: Path) -> str | None:
    try:
        stream = await sandbox.read(path)
    except FileNotFoundError:
        return None
    try:
        data = stream.read()
    finally:
        stream.close()
    if isinstance(data, str):
        return data
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


async def _snapshot_sandbox_tree(sandbox: Any, root: str = "repo") -> FileSnapshot:
    find = await _exec_text(
        sandbox,
        f"find {root} -type f "
        "! -path '*/.git/*' "
        "! -path '*/.venv/*' "
        "! -path '*/__pycache__/*' "
        "! -path '*/node_modules/*' "
        "! -path '*/.pytest_cache/*' "
        "! -path '*/.mypy_cache/*' "
        "! -path '*/.ruff_cache/*' "
        "! -path '*/venv/*' "
        "-size -1000000c",
    )
    if find.exit_code != 0:
        return FileSnapshot(files={})

    files: dict[str, str] = {}
    root_prefix = f"{root}/"
    for raw_path in find.stdout.splitlines():
        if not raw_path.startswith(root_prefix):
            continue
        rel = raw_path.removeprefix(root_prefix)
        text = await _read_sandbox_text(sandbox, Path(raw_path))
        if text is not None:
            files[rel] = text
    return FileSnapshot(files=files)


def _diff_snapshots(before: FileSnapshot, after: FileSnapshot) -> tuple[str, str]:
    diff_chunks: list[str] = []
    changed_paths: list[str] = []
    all_paths = sorted(set(before.files) | set(after.files))

    for rel in all_paths:
        before_text = before.files.get(rel)
        after_text = after.files.get(rel)
        if before_text == after_text:
            continue

        changed_paths.append(rel)
        before_lines = [] if before_text is None else before_text.splitlines(keepends=True)
        after_lines = [] if after_text is None else after_text.splitlines(keepends=True)
        diff_chunks.extend(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"repo/{rel}",
                tofile=f"repo/{rel}",
            )
        )

    status = "\n".join(f"M {path}" for path in changed_paths)
    return status, "".join(diff_chunks)


def _extract_tool_calls(items: list[Any]) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []

    for item in items:
        raw_item = getattr(item, "raw_item", None)
        if raw_item is None:
            continue

        if isinstance(raw_item, dict):
            raw_type = raw_item.get("type")
            name = raw_item.get("name") or raw_type
            arguments = raw_item.get("arguments")
        else:
            raw_type = getattr(raw_item, "type", None)
            name = getattr(raw_item, "name", None) or raw_type
            arguments = getattr(raw_item, "arguments", None)

        if not isinstance(name, str):
            continue
        if "call" not in name and raw_type != "apply_patch_call":
            continue

        parsed_arguments: Any = arguments
        if isinstance(arguments, str) and arguments:
            try:
                parsed_arguments = json.loads(arguments)
            except json.JSONDecodeError:
                parsed_arguments = arguments

        if raw_type == "apply_patch_call":
            name = "apply_patch"

        tool_calls.append(
            {
                "name": name,
                "arguments": parsed_arguments,
            }
        )

    return tool_calls


def _report_to_json(report: PhaseOneReport) -> dict[str, Any]:
    payload = asdict(report)
    if report.verification is not None:
        payload["verification"] = asdict(report.verification)
    return payload


def save_report(report: PhaseOneReport, output_dir: Path) -> Path:
    run_dir = output_dir / report.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    report.saved_dir = str(run_dir)

    (run_dir / "report.json").write_text(
        json.dumps(_report_to_json(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "final.md").write_text(report.final_output, encoding="utf-8")
    (run_dir / "diff.patch").write_text(report.diff, encoding="utf-8")
    (run_dir / "git_status.txt").write_text(report.git_status, encoding="utf-8")
    if report.verification is not None:
        (run_dir / "verification.log").write_text(
            report.verification.combined_output,
            encoding="utf-8",
        )

    return run_dir


async def run_phase_one(config: PhaseOneConfig) -> PhaseOneReport:
    validate_config(config)

    sdk = _load_agents_sdk()
    sdk["set_tracing_disabled"](config.model_config.tracing_disabled)
    prompt = build_phase_one_prompt(config)
    agent = _build_agent(config, sdk)
    before_snapshot = _snapshot_local_tree(config.repo)
    client = sdk["UnixLocalSandboxClient"]()
    sandbox = await client.create(manifest=agent.default_manifest)
    run_id = datetime.now(UTC).strftime("run_%Y%m%d_%H%M%S_%f")

    try:
        async with sandbox:
            baseline_created, baseline_log = (
                (False, "skipped git baseline; using snapshot diff for Chat Completions route")
                if config.model_config.transport == "chat_completions"
                else await _ensure_git_baseline(sandbox)
            )
            result = await sdk["Runner"].run(
                agent,
                prompt,
                max_turns=config.max_turns,
                run_config=sdk["RunConfig"](
                    sandbox=sdk["SandboxRunConfig"](session=sandbox),
                    tracing_disabled=config.model_config.tracing_disabled,
                    workflow_name=DEFAULT_WORKFLOW_NAME,
                ),
            )

            after_snapshot = await _snapshot_sandbox_tree(sandbox)
            snapshot_status, snapshot_diff = _diff_snapshots(before_snapshot, after_snapshot)

            if config.model_config.transport == "chat_completions":
                git_status_text = snapshot_status
                diff_text = snapshot_diff
            else:
                git_status = await _exec_text(sandbox, "git -C repo status --short")
                diff = await _exec_text(sandbox, "git -C repo diff --")
                git_status_text = git_status.combined_output or snapshot_status
                diff_text = diff.combined_output or snapshot_diff

            verification = None
            if config.test_cmd:
                verification = await _exec_text(sandbox, f"cd repo && {config.test_cmd}")

            report = PhaseOneReport(
                run_id=run_id,
                repo=str(config.repo),
                task=config.task,
                model=config.model_config.model,
                model_provider=config.model_config.provider,
                model_transport=config.model_config.transport,
                model_base_url=config.model_config.base_url,
                prompt=prompt,
                final_output=str(result.final_output),
                tool_calls=_extract_tool_calls(list(result.new_items)),
                git_baseline_created=baseline_created,
                git_baseline_log=baseline_log,
                git_status=git_status_text,
                diff=diff_text,
                verification=verification,
            )
    finally:
        await client.delete(sandbox)

    if config.save:
        save_report(report, config.output_dir)

    return report
