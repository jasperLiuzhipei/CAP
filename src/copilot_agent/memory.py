from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

COPILOT_DIR = ".copilot"
MEMORY_FILENAME = "memory.md"
DEFAULT_MEMORY_MAX_CHARS = 12_000


def default_memory_path(repo: Path) -> Path:
    return repo / COPILOT_DIR / MEMORY_FILENAME


def resolve_memory_path(repo: Path, memory_path: Path | None = None) -> Path:
    if memory_path is None:
        return default_memory_path(repo)
    if memory_path.is_absolute():
        return memory_path
    return repo / memory_path


def ensure_memory_file(repo: Path, memory_path: Path | None = None) -> Path:
    path = resolve_memory_path(repo, memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "\n".join(
                [
                    "# Copilot Memory",
                    "",
                    "This file stores durable project context for local Copilot runs.",
                    "Keep entries short, factual, and useful for future coding tasks.",
                    "",
                    "## Project Notes",
                    "",
                    "- No durable notes yet.",
                    "",
                    "## Run History",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return path


def load_memory_text(
    repo: Path,
    memory_path: Path | None = None,
    *,
    max_chars: int = DEFAULT_MEMORY_MAX_CHARS,
) -> str:
    path = resolve_memory_path(repo, memory_path)
    if not path.exists():
        return ""

    text = path.read_text(encoding="utf-8")
    if max_chars < 1 or len(text) <= max_chars:
        return text
    return text[-max_chars:]


def memory_is_enabled(repo: Path, memory_path: Path | None, forced: bool, disabled: bool) -> bool:
    if disabled:
        return False
    if forced:
        return True
    return resolve_memory_path(repo, memory_path).exists()


def _changed_files_from_status(status: str) -> list[str]:
    changed: list[str] = []
    for line in status.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(maxsplit=1)
        changed.append(parts[-1] if parts else stripped)
    return changed


def append_run_memory(report: Any, memory_path: Path) -> None:
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    if not memory_path.exists():
        ensure_memory_file(Path(report.repo), memory_path)

    changed_files = _changed_files_from_status(getattr(report, "git_status", ""))
    changed_text = ", ".join(changed_files) if changed_files else "none"
    verification = getattr(report, "verification", None)
    host_verification = getattr(report, "host_verification", None)
    if host_verification is not None:
        verification_text = f"host_exit_code={host_verification.exit_code}"
    elif verification is None:
        verification_text = "not run"
    else:
        verification_text = f"exit_code={verification.exit_code}"

    final_output = str(getattr(report, "final_output", "")).strip()
    if len(final_output) > 800:
        final_output = f"{final_output[:800].rstrip()}..."

    entry = "\n".join(
        [
            f"### {datetime.now(UTC).isoformat()} - {report.run_id}",
            "",
            f"- Task: {report.task}",
            f"- Model: {report.model_provider}/{report.model}",
            f"- Tool strategy: {report.tool_strategy}",
            f"- Changed files: {changed_text}",
            f"- Verification: {verification_text}",
            f"- Result: {final_output or 'No final output recorded.'}",
            "",
        ]
    )
    with memory_path.open("a", encoding="utf-8") as handle:
        handle.write(entry)
