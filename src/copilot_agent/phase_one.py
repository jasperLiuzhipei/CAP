from __future__ import annotations

import difflib
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .memory import append_run_memory, load_memory_text, resolve_memory_path
from .model_config import DEFAULT_OPENAI_MODEL, ResolvedModelConfig, resolve_model_config
from .sandbox_backend import (
    DEFAULT_DOCKER_IMAGE,
    SandboxBackendRunOptions,
    get_sandbox_backend_adapter,
    validate_sandbox_backend,
    validate_sandbox_backend_run_options,
)

DEFAULT_MODEL = DEFAULT_OPENAI_MODEL
DEFAULT_WORKFLOW_NAME = "Copilot phase-one local coding task"
SNAPSHOT_SKIP_DIRS = {
    ".git",
    ".copilot-runtime",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".copilot",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}
SNAPSHOT_MAX_FILE_BYTES = 1_000_000
SANDBOX_RUNTIME_DIR = ".copilot-runtime"
SANDBOX_RUNTIME_SITE = f"{SANDBOX_RUNTIME_DIR}/site"
ABSOLUTE_PYTHON_RE = re.compile(
    r"(?<!\S)(/[^\s'\";&|]+/bin/python(?:\d+(?:\.\d+)?)?)(?=\s|$)"
)
PYTHON_EXECUTABLE_RE = re.compile(r"python(?:\d+(?:\.\d+)?)?$")


@dataclass(frozen=True)
class PhaseOneConfig:
    """Configuration for the first local Copilot vertical slice."""

    repo: Path
    task: str
    model_config: ResolvedModelConfig = field(
        default_factory=lambda: resolve_model_config(require_api_key=False)
    )
    test_cmd: str | None = None
    max_turns: int = 32
    output_dir: Path = Path("runs")
    save: bool = True
    memory_enabled: bool = False
    memory_path: Path | None = None
    host_verify: bool = False
    sandbox_backend: str = "unix_local"
    sandbox_runtime_enabled: bool = True
    sandbox_python: str = "python3"
    docker_image: str = DEFAULT_DOCKER_IMAGE
    docker_exposed_ports: tuple[int, ...] = ()


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
class SandboxRuntimeReport:
    enabled: bool
    python_command: str
    original_test_cmd: str | None = None
    sandbox_test_cmd: str | None = None
    python_check: CommandResult | None = None
    pytest_check: CommandResult | None = None
    dependency_install: CommandResult | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class PhaseOneReport:
    run_id: str
    repo: str
    task: str
    model: str
    model_provider: str
    model_transport: str
    tool_strategy: str
    model_base_url: str | None
    prompt: str
    final_output: str
    sandbox_backend: str = "unix_local"
    memory_enabled: bool = False
    memory_path: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    git_baseline_created: bool = False
    git_baseline_log: str = ""
    git_status: str = ""
    diff: str = ""
    sandbox_runtime: SandboxRuntimeReport | None = None
    verification: CommandResult | None = None
    host_verification: CommandResult | None = None
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
    validate_sandbox_backend(config.sandbox_backend)
    validate_sandbox_backend_run_options(
        SandboxBackendRunOptions(
            docker_image=config.docker_image,
            docker_exposed_ports=config.docker_exposed_ports,
        )
    )


def build_phase_one_prompt(config: PhaseOneConfig) -> str:
    sandbox_test_cmd, sandbox_notes = _build_sandbox_test_command(config)
    verification = (
        f"Run this sandbox-safe verification command from `repo/`: `{sandbox_test_cmd}`."
        if config.test_cmd
        else (
            "Infer and run the most relevant lightweight verification command "
            "if the repo provides one."
        )
    )
    if config.model_config.tool_strategy == "native":
        edit_instruction = (
            "When using apply_patch, paths are relative to the sandbox workspace root, "
            "so edit `repo/...` paths."
        )
    elif config.model_config.tool_strategy == "compat_functions":
        edit_instruction = (
            "Use the available `apply_patch` function tool for file edits when possible. "
            "Pass a JSON argument with a `patch` string that starts with `*** Begin Patch`; "
            "paths are relative to the sandbox workspace root, so edit `repo/...` paths. "
            "Use shell for inspection and verification."
        )
    else:
        edit_instruction = (
            "Use the available shell tool to inspect and edit files. Do not call apply_patch; "
            "this provider route exposes shell tools only."
        )
    loop_instruction = (
        "For Chat Completions compatibility, keep the loop short: inspect only the relevant "
        "files, apply the minimal patch, run verification once, then produce the final answer."
        if config.model_config.transport == "chat_completions"
        else "Use the SDK-native sandbox tools directly and stop after verification is complete."
    )

    prompt_parts = [
        "You are the phase-one Copilot coding agent.",
        "",
        "Workspace contract:",
        "- The target repository is mounted at `repo/` inside the sandbox workspace.",
        "- Inspect the repository before editing.",
        "- Make the smallest correct change that satisfies the task.",
        f"- {edit_instruction}",
        f"- {loop_instruction}",
        "- Preserve existing behavior unless the user explicitly asks for a broader change.",
        f"- {verification}",
        (
            "- In your final answer, summarize changed files, verification results, "
            "and remaining risks."
        ),
    ]

    if sandbox_notes:
        prompt_parts.extend(
            [
                "- The verification command was normalized for the sandbox runtime:",
                *[f"  - {note}" for note in sandbox_notes],
            ]
        )

    if config.memory_enabled:
        memory_text = load_memory_text(config.repo, config.memory_path)
        if memory_text:
            prompt_parts.extend(
                [
                    "",
                    "Project memory:",
                    memory_text,
                    "",
                    (
                        "Use project memory as background context, but prefer current "
                        "repository files when they disagree."
                    ),
                ]
            )

    prompt_parts.extend(["", "User task:", config.task.strip()])
    return "\n".join(prompt_parts)


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


def _load_agents_sdk() -> dict[str, Any]:  # pragma: no cover
    """Import OpenAI Agents SDK lazily so dry-run and tests do not require API deps."""

    try:
        from agents import (
            AsyncOpenAI,
            FunctionTool,
            ModelSettings,
            OpenAIChatCompletionsModel,
            Runner,
            set_tracing_disabled,
        )
        from agents.run import RunConfig
        from agents.sandbox import Manifest, SandboxAgent, SandboxRunConfig
        from agents.sandbox.capabilities.capabilities import Capabilities
        from agents.sandbox.capabilities.capability import Capability
        from agents.sandbox.capabilities.shell import Shell
        from agents.sandbox.capabilities.tools.apply_patch_tool import SandboxApplyPatchTool
        from agents.sandbox.entries import LocalDir
        from agents.sandbox.sandboxes.unix_local import UnixLocalSandboxClient
        from agents.sandbox.workspace_paths import SandboxPathGrant
    except ModuleNotFoundError as exc:
        raise RuntimeError(_dependency_help(exc.name or "unknown")) from exc

    return {
        "AsyncOpenAI": AsyncOpenAI,
        "Capability": Capability,
        "Capabilities": Capabilities,
        "FunctionTool": FunctionTool,
        "LocalDir": LocalDir,
        "Manifest": Manifest,
        "ModelSettings": ModelSettings,
        "OpenAIChatCompletionsModel": OpenAIChatCompletionsModel,
        "RunConfig": RunConfig,
        "Runner": Runner,
        "SandboxAgent": SandboxAgent,
        "SandboxApplyPatchTool": SandboxApplyPatchTool,
        "SandboxRunConfig": SandboxRunConfig,
        "SandboxPathGrant": SandboxPathGrant,
        "Shell": Shell,
        "UnixLocalSandboxClient": UnixLocalSandboxClient,
        "set_tracing_disabled": set_tracing_disabled,
    }


def _build_agent_model(config: PhaseOneConfig, sdk: dict[str, Any]) -> Any:  # pragma: no cover
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


def _build_chat_completions_filesystem_capability(sdk: dict[str, Any]) -> Any:  # pragma: no cover
    """Expose an apply_patch-like function tool for Chat Completions providers."""

    class ChatCompletionsFilesystem(sdk["Capability"]):  # type: ignore[misc, valid-type]
        type: Literal["chat_completions_filesystem"] = "chat_completions_filesystem"

        def tools(self) -> list[Any]:
            if self.session is None:
                raise ValueError("ChatCompletionsFilesystem capability is not bound to a session.")

            patch_tool = sdk["SandboxApplyPatchTool"](session=self.session, user=self.run_as)

            async def invoke_apply_patch(ctx: Any, raw_input: str) -> str:
                try:
                    payload = json.loads(raw_input)
                except json.JSONDecodeError as exc:
                    return f"apply_patch failed: expected JSON arguments. {exc}"

                patch = payload.get("patch")
                if not isinstance(patch, str) or not patch.strip():
                    return "apply_patch failed: argument `patch` must be a non-empty string."

                try:
                    return await patch_tool._on_invoke_tool(ctx, patch)
                except Exception as exc:  # Let the model recover from malformed patches.
                    return f"apply_patch failed: {exc}"

            return [
                sdk["FunctionTool"](
                    name="apply_patch",
                    description=(
                        "Apply a patch inside the sandbox workspace. The single `patch` "
                        "argument must use the same workspace-root-relative patch envelope as "
                        "OpenAI native apply_patch: begin with `*** Begin Patch`, include one "
                        "or more file operations, and end with `*** End Patch`."
                    ),
                    params_json_schema={
                        "type": "object",
                        "properties": {
                            "patch": {
                                "type": "string",
                                "description": (
                                    "Patch text using the OpenAI apply_patch envelope. "
                                    "Paths must be relative to the sandbox workspace root, "
                                    "for example repo/src/app.py."
                                ),
                            }
                        },
                        "required": ["patch"],
                        "additionalProperties": False,
                    },
                    on_invoke_tool=invoke_apply_patch,
                    strict_json_schema=False,
                )
            ]

        async def instructions(self, manifest: Any) -> str | None:
            _ = manifest
            return (
                "When editing files, prefer the `apply_patch` function tool. Its JSON arguments "
                "must contain one field named `patch`, whose value is the normal apply_patch "
                "text envelope. Patch paths are relative to the sandbox workspace root."
            )

    return ChatCompletionsFilesystem()


def _build_sandbox_test_command(config: PhaseOneConfig) -> tuple[str | None, list[str]]:
    """Return the verification command that should run inside the SDK sandbox."""

    if config.test_cmd is None:
        return None, []
    if not config.sandbox_runtime_enabled:
        return config.test_cmd, ["sandbox runtime provisioning disabled"]

    command, notes = _rewrite_absolute_python_executables(
        config.test_cmd,
        sandbox_python=config.sandbox_python,
    )
    if _command_uses_pytest(command):
        command = (
            'PYTEST_ADDOPTS="-p no:debugging ${PYTEST_ADDOPTS:-}" '
            f'PYTHONPATH="../{SANDBOX_RUNTIME_SITE}:${{PYTHONPATH:-}}" '
            f"sh -c {shlex.quote(command)}"
        )
        notes.append(
            "pytest debugging plugin is disabled in the sandbox to avoid macOS "
            "pdb/readline crashes"
        )
    return command, notes


def _rewrite_absolute_python_executables(
    command: str,
    *,
    sandbox_python: str,
) -> tuple[str, list[str]]:
    notes: list[str] = []
    quoted_sandbox_python = shlex.quote(sandbox_python)

    def replace(match: re.Match[str]) -> str:
        original = match.group(1)
        if original == sandbox_python:
            return original
        notes.append(
            f"absolute host Python `{original}` was replaced with sandbox Python "
            f"`{sandbox_python}`"
        )
        return quoted_sandbox_python

    return ABSOLUTE_PYTHON_RE.sub(replace, command), notes


def _command_uses_pytest(command: str | None) -> bool:
    if not command:
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    return any(Path(token).name == "pytest" for token in tokens) or " -m pytest" in command


def _command_needs_python(command: str | None) -> bool:
    if not command:
        return False
    if _command_uses_pytest(command):
        return True
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    return any(_looks_like_python_executable(token) for token in tokens)


def _looks_like_python_executable(token: str) -> bool:
    return PYTHON_EXECUTABLE_RE.fullmatch(Path(token).name) is not None


def _python_executables_from_test_cmd(test_cmd: str | None) -> list[str]:
    if not test_cmd:
        return []

    candidates: list[str] = []
    try:
        tokens = shlex.split(test_cmd)
    except ValueError:
        tokens = test_cmd.split()
    for token in tokens:
        if _looks_like_python_executable(token):
            candidates.append(token)
    candidates.extend(match.group(1) for match in ABSOLUTE_PYTHON_RE.finditer(test_cmd))
    return _unique_strings(candidates)


def _sandbox_runtime_grant_paths(config: PhaseOneConfig) -> list[Path]:
    if not config.sandbox_runtime_enabled:
        return []

    paths: list[Path] = [
        Path(sys.prefix),
        Path(sys.base_prefix),
        Path(sys.exec_prefix),
        Path(sys.base_exec_prefix),
    ]
    executables = [config.sandbox_python, *_python_executables_from_test_cmd(config.test_cmd)]
    for executable in executables:
        paths.extend(_python_runtime_roots(executable))
    return _safe_unique_paths(paths)


def _python_runtime_roots(executable: str) -> list[Path]:
    resolved = _resolve_executable(executable)
    if resolved is None:
        return []

    roots: list[Path] = []
    executable_path = Path(resolved)
    if executable_path.parent.name == "bin":
        roots.append(executable_path.parent.parent)

    roots.extend(_python_prefixes_from_host(executable_path))
    roots.extend(_pyvenv_home_roots(executable_path))
    return roots


def _resolve_executable(executable: str) -> Path | None:
    try:
        parts = shlex.split(executable)
    except ValueError:
        parts = executable.split()
    if not parts:
        return None

    candidate = Path(parts[0]).expanduser()
    if candidate.is_absolute():
        return candidate
    resolved = shutil.which(parts[0])
    return Path(resolved) if resolved else None


def _python_prefixes_from_host(executable: Path) -> list[Path]:
    code = (
        "import json, sys; "
        "print(json.dumps([sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix]))"
    )
    try:
        completed = subprocess.run(
            [str(executable), "-c", code],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []

    try:
        values = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    return [Path(value) for value in values if isinstance(value, str) and value]


def _pyvenv_home_roots(executable: Path) -> list[Path]:
    roots: list[Path] = []
    venv_root = executable.parent.parent if executable.parent.name == "bin" else executable.parent
    pyvenv = venv_root / "pyvenv.cfg"
    if not pyvenv.exists():
        return roots

    for line in pyvenv.read_text(encoding="utf-8", errors="ignore").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip().lower() == "home":
            home = Path(value.strip()).expanduser()
            roots.append(home.parent if home.name == "bin" else home)
    return roots


def _safe_unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.expanduser().resolve(strict=False)
        except OSError:
            resolved = path.expanduser()
        if not resolved.is_absolute() or resolved.parent == resolved:
            continue
        if not resolved.exists():
            continue
        key = resolved.as_posix()
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def _unique_strings(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _build_sandbox_manifest(config: PhaseOneConfig, sdk: dict[str, Any]) -> Any:  # pragma: no cover
    backend = get_sandbox_backend_adapter(config.sandbox_backend)
    return backend.build_manifest(
        sdk,
        repo=config.repo,
        runtime_grant_paths=_sandbox_runtime_grant_paths(config),
    )


def _build_agent(config: PhaseOneConfig, sdk: dict[str, Any]) -> Any:  # pragma: no cover
    manifest = _build_sandbox_manifest(config, sdk)

    if config.model_config.transport == "chat_completions":
        capabilities = [
            sdk["Shell"](),
        ]
        if config.model_config.tool_strategy == "compat_functions":
            capabilities.append(_build_chat_completions_filesystem_capability(sdk))
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


async def _exec_text(sandbox: Any, command: str) -> CommandResult:  # pragma: no cover
    result = await sandbox.exec(command, shell=True)
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    return CommandResult(
        command=command,
        exit_code=result.exit_code,
        stdout=stdout,
        stderr=stderr,
    )


async def _prepare_sandbox_runtime(
    sandbox: Any,
    config: PhaseOneConfig,
) -> SandboxRuntimeReport:  # pragma: no cover
    sandbox_test_cmd, notes = _build_sandbox_test_command(config)
    report = SandboxRuntimeReport(
        enabled=config.sandbox_runtime_enabled,
        python_command=config.sandbox_python,
        original_test_cmd=config.test_cmd,
        sandbox_test_cmd=sandbox_test_cmd,
        notes=notes,
    )

    if not config.sandbox_runtime_enabled:
        return report
    if not _command_needs_python(config.test_cmd):
        report.notes.append("no Python-specific verification command detected")
        return report

    report.python_check = await _exec_text(
        sandbox,
        _sandbox_python_check_command(config.sandbox_python),
    )
    if report.python_check.exit_code != 0:
        report.notes.append("sandbox Python health check failed")
        return report

    if _command_uses_pytest(config.test_cmd):
        report.pytest_check = await _exec_text(
            sandbox,
            _sandbox_pytest_check_command(config.sandbox_python),
        )
        if report.pytest_check.exit_code != 0:
            report.dependency_install = await _install_sandbox_pytest(
                config.sandbox_python,
                sandbox,
            )
            if report.dependency_install.exit_code == 0:
                report.notes.append(f"installed pytest into {SANDBOX_RUNTIME_SITE}")
            else:
                report.notes.append("pytest dependency provisioning failed")
    return report


def _sandbox_python_check_command(python_command: str) -> str:
    code = (
        "import encodings, json, sys; "
        "print(json.dumps({'executable': sys.executable, 'prefix': sys.prefix, "
        "'base_prefix': sys.base_prefix}))"
    )
    return f"{shlex.quote(python_command)} -c {shlex.quote(code)}"


def _sandbox_pytest_check_command(python_command: str) -> str:
    code = "import pytest; print(getattr(pytest, '__version__', 'unknown'))"
    return f"{shlex.quote(python_command)} -c {shlex.quote(code)}"


async def _install_sandbox_pytest(
    python_command: str,
    sandbox: Any,
) -> CommandResult:  # pragma: no cover
    command = (
        f"mkdir -p {shlex.quote(SANDBOX_RUNTIME_SITE)} && "
        f"{shlex.quote(python_command)} -m pip install "
        f"--target {shlex.quote(SANDBOX_RUNTIME_SITE)} pytest"
    )
    return await _exec_text(sandbox, command)


async def _ensure_git_baseline(sandbox: Any) -> tuple[bool, str]:  # pragma: no cover
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


async def _read_sandbox_text(sandbox: Any, path: Path) -> str | None:  # pragma: no cover
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


async def _snapshot_sandbox_tree(
    sandbox: Any, root: str = "repo"
) -> FileSnapshot:  # pragma: no cover
    find = await _exec_text(
        sandbox,
        f"find {root} -type f "
        "! -path '*/.git/*' "
        "! -path '*/.copilot/*' "
        "! -path '*/.copilot-runtime/*' "
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
        fromfile = "/dev/null" if before_text is None else f"repo/{rel}"
        tofile = "/dev/null" if after_text is None else f"repo/{rel}"
        diff_chunks.extend(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=fromfile,
                tofile=tofile,
            )
        )

    status_lines: list[str] = []
    for path in changed_paths:
        if path not in before.files:
            prefix = "A"
        elif path not in after.files:
            prefix = "D"
        else:
            prefix = "M"
        status_lines.append(f"{prefix} {path}")
    status = "\n".join(status_lines)
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
    if report.host_verification is not None:
        payload["host_verification"] = asdict(report.host_verification)
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
    if report.sandbox_runtime is not None:
        (run_dir / "sandbox_runtime.log").write_text(
            _format_sandbox_runtime_log(report.sandbox_runtime),
            encoding="utf-8",
        )
    if report.verification is not None:
        (run_dir / "verification.log").write_text(
            report.verification.combined_output,
            encoding="utf-8",
        )
    if report.host_verification is not None:
        (run_dir / "host_verification.log").write_text(
            report.host_verification.combined_output,
            encoding="utf-8",
        )

    return run_dir


def _format_sandbox_runtime_log(runtime: SandboxRuntimeReport) -> str:
    sections = [
        f"enabled={runtime.enabled}",
        f"python_command={runtime.python_command}",
        f"original_test_cmd={runtime.original_test_cmd or ''}",
        f"sandbox_test_cmd={runtime.sandbox_test_cmd or ''}",
    ]
    if runtime.notes:
        sections.append("notes:")
        sections.extend(f"- {note}" for note in runtime.notes)
    for label, result in (
        ("python_check", runtime.python_check),
        ("pytest_check", runtime.pytest_check),
        ("dependency_install", runtime.dependency_install),
    ):
        if result is None:
            continue
        sections.extend(
            [
                "",
                f"[{label}]",
                f"$ {result.command}",
                f"exit_code={result.exit_code}",
                result.combined_output,
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


def _copy_repo_for_host_verification(repo: Path, destination: Path) -> None:
    def ignore(_: str, names: list[str]) -> set[str]:
        return {name for name in names if name in SNAPSHOT_SKIP_DIRS}

    shutil.copytree(repo, destination, ignore=ignore)


def _run_host_command(command: str, cwd: Path) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        text=True,
        capture_output=True,
    )
    return CommandResult(
        command=command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _run_host_verification(repo: Path, diff_text: str, test_cmd: str) -> CommandResult:
    if not diff_text.strip():
        return CommandResult(
            command=test_cmd,
            exit_code=0,
            stdout="Host verification skipped because the sandbox diff is empty.\n",
            stderr="",
        )

    with tempfile.TemporaryDirectory(prefix="copilot-host-verify-") as tmp:
        tmp_root = Path(tmp)
        repo_copy = tmp_root / "repo"
        diff_path = tmp_root / "diff.patch"
        _copy_repo_for_host_verification(repo, repo_copy)
        diff_path.write_text(diff_text, encoding="utf-8")

        check = subprocess.run(
            ["git", "-C", str(repo_copy), "apply", "-p1", "--check", str(diff_path)],
            text=True,
            capture_output=True,
        )
        if check.returncode != 0:
            return CommandResult(
                command=f"git apply --check {diff_path}",
                exit_code=check.returncode,
                stdout=check.stdout,
                stderr=check.stderr,
            )

        apply = subprocess.run(
            ["git", "-C", str(repo_copy), "apply", "-p1", str(diff_path)],
            text=True,
            capture_output=True,
        )
        if apply.returncode != 0:
            return CommandResult(
                command=f"git apply {diff_path}",
                exit_code=apply.returncode,
                stdout=apply.stdout,
                stderr=apply.stderr,
            )

        result = _run_host_command(test_cmd, repo_copy)
        result_stdout = (
            "Host verification ran in an isolated temporary copy of the repository.\n"
            f"Temporary repo: {repo_copy}\n"
            f"{result.stdout}"
        )
        return CommandResult(
            command=test_cmd,
            exit_code=result.exit_code,
            stdout=result_stdout,
            stderr=result.stderr,
        )


async def run_phase_one(config: PhaseOneConfig) -> PhaseOneReport:  # pragma: no cover
    validate_config(config)

    sdk = _load_agents_sdk()
    sdk["set_tracing_disabled"](config.model_config.tracing_disabled)
    prompt = build_phase_one_prompt(config)
    backend = get_sandbox_backend_adapter(config.sandbox_backend)
    agent = _build_agent(config, sdk)
    before_snapshot = _snapshot_local_tree(config.repo)
    backend_options = SandboxBackendRunOptions(
        docker_image=config.docker_image,
        docker_exposed_ports=config.docker_exposed_ports,
    )
    sandbox_session = await backend.create_session(
        sdk,
        manifest=agent.default_manifest,
        options=backend_options,
    )
    sandbox = sandbox_session.sandbox
    run_id = datetime.now(UTC).strftime("run_%Y%m%d_%H%M%S_%f")

    try:
        async with sandbox:
            sandbox_runtime = await _prepare_sandbox_runtime(sandbox, config)
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
                verification_command = sandbox_runtime.sandbox_test_cmd or config.test_cmd
                verification = await _exec_text(sandbox, f"cd repo && {verification_command}")

            host_verification = None
            if config.test_cmd and config.host_verify:
                host_verification = _run_host_verification(
                    config.repo,
                    diff_text,
                    config.test_cmd,
                )

            report = PhaseOneReport(
                run_id=run_id,
                repo=str(config.repo),
                task=config.task,
                model=config.model_config.model,
                model_provider=config.model_config.provider,
                model_transport=config.model_config.transport,
                tool_strategy=config.model_config.tool_strategy,
                sandbox_backend=config.sandbox_backend,
                model_base_url=config.model_config.base_url,
                prompt=prompt,
                final_output=str(result.final_output),
                memory_enabled=config.memory_enabled,
                memory_path=(
                    str(resolve_memory_path(config.repo, config.memory_path))
                    if config.memory_enabled
                    else None
                ),
                tool_calls=_extract_tool_calls(list(result.new_items)),
                git_baseline_created=baseline_created,
                git_baseline_log=baseline_log,
                git_status=git_status_text,
                diff=diff_text,
                sandbox_runtime=sandbox_runtime,
                verification=verification,
                host_verification=host_verification,
            )
    finally:
        await backend.delete_session(sandbox_session)

    if config.save:
        save_report(report, config.output_dir)
    if config.memory_enabled:
        append_run_memory(report, resolve_memory_path(config.repo, config.memory_path))

    return report
