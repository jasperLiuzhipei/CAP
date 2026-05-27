from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from copilot_agent.memory import (
    MAX_RUN_HISTORY_ENTRIES,
    StructuredMemory,
    add_memory_record,
    append_run_memory,
    compact_memory,
    ensure_memory_file,
    load_memory_text,
    load_structured_memory,
    memory_is_enabled,
    resolve_memory_path,
    retrieve_memory,
    structured_memory_path,
    upsert_memory_record,
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
    store = load_structured_memory(repo)

    assert "run_test" in memory_text
    assert "Fix a bug" in memory_text
    assert "src/app.py" in memory_text
    assert structured_memory_path(memory_path).exists()
    assert store.schema_version == 2
    assert store.run_history[0].run_id == "run_test"


def test_memory_path_and_enablement(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    absolute = tmp_path / "memory.md"

    assert resolve_memory_path(repo) == repo / ".copilot" / "memory.md"
    assert resolve_memory_path(repo, Path("custom.md")) == repo / "custom.md"
    assert resolve_memory_path(repo, absolute) == absolute
    assert structured_memory_path(absolute.with_suffix(".json")) == absolute.with_suffix(".json")
    assert memory_is_enabled(repo, None, forced=True, disabled=False)
    assert not memory_is_enabled(repo, None, forced=True, disabled=True)
    assert not memory_is_enabled(repo, None, forced=False, disabled=False)

    ensure_memory_file(repo)
    assert memory_is_enabled(repo, None, forced=False, disabled=False)
    assert (repo / ".copilot" / "memory.json").exists()


def test_load_memory_text_truncates_legacy_markdown(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    memory_path = repo / ".copilot" / "memory.md"
    memory_path.parent.mkdir()
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


def test_structured_memory_retrieval_and_prompt_filtering(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    ensure_memory_file(repo)

    upsert_memory_record(
        repo,
        category="project_fact",
        title="Docker backend verification",
        content="Docker sandbox smoke tests run pytest inside copilot-agent-python.",
        tags=["docker", "pytest"],
        source_run_id="run_docker",
    )
    upsert_memory_record(
        repo,
        category="code_preference",
        title="Use concise Chinese explanations",
        content="Explain architecture in Chinese with short, direct sections.",
        tags=["communication"],
    )

    store = load_structured_memory(repo)
    selected = retrieve_memory(store, query="run docker pytest smoke")
    prompt = load_memory_text(repo, query="run docker pytest smoke")

    assert [record.title for record in selected] == ["Docker backend verification"]
    assert "Docker backend verification" in prompt
    assert "Use concise Chinese explanations" not in prompt
    assert "Current repository files" in prompt


def test_structured_memory_duplicate_update_and_validation() -> None:
    store = StructuredMemory()

    record = add_memory_record(
        store,
        category="code_preference",
        title="Testing style",
        content="Prefer real pytest verification over unchecked reasoning.",
        tags=["tests"],
        why="Prevents false confidence.",
        how_to_apply="Run pytest when changing Python code.",
    )
    updated = add_memory_record(
        store,
        category="code_preference",
        title="Testing style",
        content="Prefer real pytest verification over unchecked reasoning.",
        tags=["verification"],
        confidence=0.9,
        source_run_id="run_update",
    )

    assert updated.id == record.id
    assert updated.confidence == 0.9
    assert updated.source_run_id == "run_update"
    assert updated.tags == ["tests", "verification"]

    for kwargs, message in [
        ({"title": "", "content": "x"}, "title"),
        ({"title": "x", "content": ""}, "content"),
        ({"title": "x", "content": "x", "confidence": 2.0}, "confidence"),
    ]:
        with pytest.raises(ValueError, match=message):
            add_memory_record(store, category="project_fact", **kwargs)


def test_structured_memory_conflict_supersedes_older_record(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    first = upsert_memory_record(
        repo,
        category="project_fact",
        title="Test command",
        content="Run tests with pytest tests.",
        source_run_id="run_old",
    )
    second = upsert_memory_record(
        repo,
        category="project_fact",
        title="Test command",
        content="Run tests with python -m pytest tests.",
        source_run_id="run_new",
    )
    store = load_structured_memory(repo)

    assert first.id != second.id
    assert store.project_facts[0].status == "superseded"
    assert store.project_facts[1].status == "active"
    assert store.conflicts[0].old_record_id == first.id
    assert store.conflicts[0].new_record_id == second.id
    assert "Test command" in (repo / ".copilot" / "memory.md").read_text(encoding="utf-8")
    assert "Conflict Notes" in load_memory_text(repo, query="test command")


def test_structured_memory_compacts_run_history(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    memory_path = ensure_memory_file(repo)

    for index in range(MAX_RUN_HISTORY_ENTRIES + 3):
        append_run_memory(
            FakeReport(
                run_id=f"run_{index}",
                repo=str(repo),
                task=f"Task {index}",
                model_provider="deepseek",
                model="deepseek-v4-flash",
                tool_strategy="compat_functions",
                git_status="",
                final_output="ok",
                verification=FakeVerification(exit_code=0),
            ),
            memory_path,
        )

    store = load_structured_memory(repo)

    assert len(store.run_history) == MAX_RUN_HISTORY_ENTRIES
    assert "Compacted 1 older run history entries" in store.compacted_run_summary
    assert "run_0" not in {run.run_id for run in store.run_history}


def test_compact_memory_is_noop_under_limit() -> None:
    store = load_structured_memory(Path("/missing"))

    compact_memory(store, max_runs=1)

    assert store.run_history == []


def test_legacy_memory_migrates_notes_and_runs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    memory_path = repo / ".copilot" / "memory.md"
    memory_path.parent.mkdir()
    memory_path.write_text(
        "\n".join(
            [
                "# Copilot Memory",
                "",
                "## Project Notes",
                "",
                "- Prefer Docker backend for stronger isolation.",
                "- No durable notes yet.",
                "",
                "## Run History",
                "",
                "### 2026-05-27T00:00:00+00:00 - run_legacy",
                "",
                "- Task: Inspect repo",
                "- Model: deepseek/deepseek-v4-flash",
                "- Changed files: src/app.py, tests/test_app.py",
                "- Verification: exit_code=0",
                "- Result: Legacy result",
                "",
            ]
        ),
        encoding="utf-8",
    )

    store = load_structured_memory(repo)

    assert store.project_facts[0].content == "Prefer Docker backend for stronger isolation."
    assert store.project_facts[0].tags == ["legacy"]
    assert store.run_history[0].run_id == "run_legacy"
    assert store.run_history[0].changed_files == ["src/app.py", "tests/test_app.py"]


def test_load_structured_memory_tolerates_invalid_json_and_fields(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    memory_path = repo / ".copilot" / "memory.md"
    memory_json = structured_memory_path(memory_path)
    memory_json.parent.mkdir()

    memory_json.write_text("[]", encoding="utf-8")
    assert load_structured_memory(repo).project_facts == []

    memory_json.write_text("{", encoding="utf-8")
    assert load_structured_memory(repo).project_facts == []

    memory_json.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "project_facts": [
                    {
                        "id": "",
                        "category": "unknown",
                        "title": "",
                        "content": "",
                        "source_run_id": 123,
                        "confidence": 0.1,
                        "status": "unknown",
                        "tags": ["x", ""],
                    }
                ],
                "run_history": [{"run_id": "run_loaded", "changed_files": [1, "x"]}],
                "conflicts": [{"category": "unknown", "old_record_id": 1}],
                "compacted_run_summary": "old summary",
            }
        ),
        encoding="utf-8",
    )

    store = load_structured_memory(repo)

    assert store.project_facts[0].category == "project_fact"
    assert store.project_facts[0].status == "active"
    assert store.project_facts[0].source_run_id == "123"
    assert store.project_facts[0].tags == ["x"]
    assert store.run_history[0].changed_files == ["1", "x"]
    assert store.conflicts[0].category == "project_fact"
    assert store.compacted_run_summary == "old summary"
