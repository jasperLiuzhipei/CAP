from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from copilot_agent.memory import (
    append_run_memory,
    ensure_memory_file,
    load_memory_text,
    memory_is_enabled,
    resolve_memory_path,
)


@dataclass(frozen=True)
class FakeVerification:
    exit_code: int


@dataclass(frozen=True)
class FakeReport:
    run_id: str
    repo: str
    task: str
    model_provider: str
    model: str
    tool_strategy: str
    git_status: str
    final_output: str
    verification: FakeVerification
    host_verification: FakeVerification | None = None


def test_memory_file_round_trip(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    memory_path = ensure_memory_file(repo)
    report = FakeReport(
        run_id="run_test",
        repo=str(repo),
        task="Fix a bug",
        model_provider="deepseek",
        model="deepseek-v4-flash",
        tool_strategy="compat_functions",
        git_status="M src/app.py",
        final_output="Fixed the bug.",
        verification=FakeVerification(exit_code=0),
    )

    append_run_memory(report, memory_path)
    memory_text = load_memory_text(repo)

    assert "run_test" in memory_text
    assert "Fix a bug" in memory_text
    assert "src/app.py" in memory_text


def test_memory_path_and_enablement(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    absolute = tmp_path / "memory.md"

    assert resolve_memory_path(repo) == repo / ".copilot" / "memory.md"
    assert resolve_memory_path(repo, Path("custom.md")) == repo / "custom.md"
    assert resolve_memory_path(repo, absolute) == absolute
    assert memory_is_enabled(repo, None, forced=True, disabled=False)
    assert not memory_is_enabled(repo, None, forced=True, disabled=True)
    assert not memory_is_enabled(repo, None, forced=False, disabled=False)

    ensure_memory_file(repo)
    assert memory_is_enabled(repo, None, forced=False, disabled=False)


def test_load_memory_text_truncates(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    memory_path = ensure_memory_file(repo)
    memory_path.write_text("0123456789", encoding="utf-8")

    assert load_memory_text(repo, max_chars=4) == "6789"
    assert load_memory_text(repo, max_chars=0) == "0123456789"
    assert load_memory_text(repo / "missing") == ""


def test_append_run_memory_defaults_and_host_verification(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    memory_path = repo / ".copilot" / "memory.md"
    report = FakeReport(
        run_id="run_host",
        repo=str(repo),
        task="",
        model_provider="p",
        model="m",
        tool_strategy="compat_functions",
        git_status="",
        final_output="x" * 900,
        verification=FakeVerification(exit_code=1),
        host_verification=FakeVerification(exit_code=0),
    )

    append_run_memory(report, memory_path)
    text = memory_path.read_text(encoding="utf-8")

    assert "host_exit_code=0" in text
    assert "Changed files: none" in text
    assert "xxx..." in text


def test_append_run_memory_without_verification_and_blank_status(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    report = FakeReport(
        run_id="run_none",
        repo=str(repo),
        task="Task",
        model_provider="p",
        model="m",
        tool_strategy="shell_only",
        git_status="\n  \n",
        final_output="",
        verification=None,  # type: ignore[arg-type]
    )

    memory_path = ensure_memory_file(repo)
    append_run_memory(report, memory_path)
    text = memory_path.read_text(encoding="utf-8")

    assert "Verification: not run" in text
    assert "No final output recorded." in text
