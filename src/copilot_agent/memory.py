from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

COPILOT_DIR = ".copilot"
MEMORY_FILENAME = "memory.md"
STRUCTURED_MEMORY_FILENAME = "memory.json"
MEMORY_SCHEMA_VERSION = 2
DEFAULT_MEMORY_MAX_CHARS = 12_000
DEFAULT_MEMORY_RETRIEVAL_LIMIT = 8
MAX_RUN_HISTORY_ENTRIES = 20
MAX_RUN_RESULT_CHARS = 700

MemoryCategory = Literal["project_fact", "code_preference"]
MemoryStatus = Literal["active", "superseded", "stale"]


@dataclass
class MemoryRecord:
    id: str
    category: MemoryCategory
    title: str
    content: str
    source_run_id: str | None = None
    confidence: float = 0.8
    status: MemoryStatus = "active"
    tags: list[str] = field(default_factory=list)
    why: str = ""
    how_to_apply: str = ""
    created_at: str = field(default_factory=lambda: _utc_now())
    updated_at: str = field(default_factory=lambda: _utc_now())


@dataclass
class RunMemoryRecord:
    run_id: str
    task: str
    model: str
    changed_files: list[str]
    verification: str
    result: str
    created_at: str = field(default_factory=lambda: _utc_now())


@dataclass
class MemoryConflict:
    id: str
    category: MemoryCategory
    title: str
    old_record_id: str
    new_record_id: str
    reason: str
    resolved_by: str = "newer_memory_wins"
    created_at: str = field(default_factory=lambda: _utc_now())


@dataclass
class StructuredMemory:
    schema_version: int = MEMORY_SCHEMA_VERSION
    project_facts: list[MemoryRecord] = field(default_factory=list)
    code_preferences: list[MemoryRecord] = field(default_factory=list)
    run_history: list[RunMemoryRecord] = field(default_factory=list)
    conflicts: list[MemoryConflict] = field(default_factory=list)
    compacted_run_summary: str = ""
    updated_at: str = field(default_factory=lambda: _utc_now())


def default_memory_path(repo: Path) -> Path:
    return repo / COPILOT_DIR / MEMORY_FILENAME


def resolve_memory_path(repo: Path, memory_path: Path | None = None) -> Path:
    if memory_path is None:
        return default_memory_path(repo)
    if memory_path.is_absolute():
        return memory_path
    return repo / memory_path


def structured_memory_path(memory_path: Path) -> Path:
    if memory_path.name == STRUCTURED_MEMORY_FILENAME or memory_path.suffix == ".json":
        return memory_path
    return memory_path.with_name(STRUCTURED_MEMORY_FILENAME)


def ensure_memory_file(repo: Path, memory_path: Path | None = None) -> Path:
    path = resolve_memory_path(repo, memory_path)
    store = load_structured_memory(repo, memory_path)
    save_structured_memory(store, structured_memory_path(path))
    write_memory_index(path, store)
    return path


def load_memory_text(
    repo: Path,
    memory_path: Path | None = None,
    *,
    max_chars: int = DEFAULT_MEMORY_MAX_CHARS,
    query: str | None = None,
) -> str:
    path = resolve_memory_path(repo, memory_path)
    store_path = structured_memory_path(path)

    if store_path.exists():
        text = render_memory_prompt(load_structured_memory(repo, memory_path), query=query)
    elif path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        return ""

    if max_chars < 1 or len(text) <= max_chars:
        return text
    return text[-max_chars:]


def memory_is_enabled(repo: Path, memory_path: Path | None, forced: bool, disabled: bool) -> bool:
    if disabled:
        return False
    if forced:
        return True
    path = resolve_memory_path(repo, memory_path)
    return path.exists() or structured_memory_path(path).exists()


def load_structured_memory(repo: Path, memory_path: Path | None = None) -> StructuredMemory:
    path = resolve_memory_path(repo, memory_path)
    store_path = structured_memory_path(path)
    if store_path.exists():
        try:
            data = json.loads(store_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return StructuredMemory()
            return _structured_memory_from_dict(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return StructuredMemory()
    if path.exists():
        return migrate_legacy_memory(path.read_text(encoding="utf-8"))
    return StructuredMemory()


def save_structured_memory(store: StructuredMemory, memory_json_path: Path) -> None:
    store.updated_at = _utc_now()
    memory_json_path.parent.mkdir(parents=True, exist_ok=True)
    memory_json_path.write_text(
        json.dumps(asdict(store), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def upsert_memory_record(
    repo: Path,
    *,
    category: MemoryCategory,
    title: str,
    content: str,
    memory_path: Path | None = None,
    source_run_id: str | None = None,
    confidence: float = 0.8,
    tags: list[str] | None = None,
    why: str = "",
    how_to_apply: str = "",
) -> MemoryRecord:
    entrypoint = resolve_memory_path(repo, memory_path)
    store = load_structured_memory(repo, memory_path)
    record = add_memory_record(
        store,
        category=category,
        title=title,
        content=content,
        source_run_id=source_run_id,
        confidence=confidence,
        tags=tags,
        why=why,
        how_to_apply=how_to_apply,
    )
    save_structured_memory(store, structured_memory_path(entrypoint))
    write_memory_index(entrypoint, store)
    return record


def add_memory_record(
    store: StructuredMemory,
    *,
    category: MemoryCategory,
    title: str,
    content: str,
    source_run_id: str | None = None,
    confidence: float = 0.8,
    tags: list[str] | None = None,
    why: str = "",
    how_to_apply: str = "",
) -> MemoryRecord:
    title = title.strip()
    content = content.strip()
    if not title:
        raise ValueError("Memory title must not be empty.")
    if not content:
        raise ValueError("Memory content must not be empty.")
    if not 0 <= confidence <= 1:
        raise ValueError("Memory confidence must be between 0 and 1.")

    records = _records_for_category(store, category)
    existing = next(
        (
            record
            for record in records
            if record.status == "active" and _norm(record.title) == _norm(title)
        ),
        None,
    )
    if existing and _norm(existing.content) == _norm(content):
        existing.source_run_id = source_run_id or existing.source_run_id
        existing.confidence = max(existing.confidence, confidence)
        existing.tags = sorted(set(existing.tags + (tags or [])))
        existing.why = why or existing.why
        existing.how_to_apply = how_to_apply or existing.how_to_apply
        existing.updated_at = _utc_now()
        return existing

    record = MemoryRecord(
        id=f"mem_{uuid.uuid4().hex}",
        category=category,
        title=title,
        content=content,
        source_run_id=source_run_id,
        confidence=confidence,
        tags=sorted(set(tags or [])),
        why=why.strip(),
        how_to_apply=how_to_apply.strip(),
    )
    records.append(record)

    if existing:
        existing.status = "superseded"
        existing.updated_at = _utc_now()
        store.conflicts.append(
            MemoryConflict(
                id=f"conflict_{uuid.uuid4().hex}",
                category=category,
                title=title,
                old_record_id=existing.id,
                new_record_id=record.id,
                reason="A newer memory with the same normalized title has different content.",
            )
        )
    return record


def retrieve_memory(
    store: StructuredMemory,
    *,
    query: str | None = None,
    limit: int = DEFAULT_MEMORY_RETRIEVAL_LIMIT,
) -> list[MemoryRecord]:
    records = [
        record
        for record in [*store.project_facts, *store.code_preferences]
        if record.status == "active"
    ]
    query_tokens = _tokens(query or "")
    if not query_tokens:
        return sorted(records, key=lambda record: record.updated_at, reverse=True)[:limit]

    scored = [
        (_memory_score(record, query_tokens), record)
        for record in records
        if _memory_score(record, query_tokens) > 0
    ]
    scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
    return [record for _, record in scored[:limit]]


def render_memory_prompt(
    store: StructuredMemory,
    *,
    query: str | None = None,
    limit: int = DEFAULT_MEMORY_RETRIEVAL_LIMIT,
) -> str:
    selected = retrieve_memory(store, query=query, limit=limit)
    recent_runs = sorted(store.run_history, key=lambda run: run.created_at, reverse=True)[:5]
    lines = [
        "# Copilot Structured Memory v2",
        "",
        (
            "Use this as background context only. Current repository files and the "
            "current user task are authoritative when they disagree with memory."
        ),
        (
            "A memory that names a file, function, command, or model may be stale; "
            "verify it before acting on it."
        ),
        "",
    ]

    if selected:
        lines.extend(["## Retrieved Memories", ""])
        for record in selected:
            lines.extend(_record_prompt_lines(record))
            lines.append("")
    else:
        lines.extend(
            [
                "## Retrieved Memories",
                "",
                "- No active project facts or code preferences matched this task.",
                "",
            ]
        )

    if recent_runs:
        lines.extend(["## Recent Runs", ""])
        for run in recent_runs:
            lines.append(
                f"- {run.run_id}: {run.task or 'No task recorded.'} "
                f"(verification: {run.verification}; "
                f"changed: {', '.join(run.changed_files) or 'none'})"
            )
        lines.append("")

    active_conflicts = store.conflicts[-5:]
    if active_conflicts:
        lines.extend(
            [
                "## Conflict Notes",
                "",
                (
                    "- Newer memories supersede older records with the same title. "
                    "Treat superseded/stale records as historical context only."
                ),
            ]
        )
        for conflict in active_conflicts:
            lines.append(
                f"- {conflict.title}: {conflict.old_record_id} -> {conflict.new_record_id}"
            )
        lines.append("")

    if store.compacted_run_summary:
        lines.extend(["## Compacted Run Summary", "", store.compacted_run_summary, ""])

    return "\n".join(lines).strip()


def write_memory_index(memory_path: Path, store: StructuredMemory) -> None:
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(render_memory_index(store), encoding="utf-8")


def render_memory_index(store: StructuredMemory) -> str:
    lines = [
        "# Copilot Memory",
        "",
        (
            "This is a human-readable index for Memory v2. The structured source "
            "of truth is `memory.json` in the same directory."
        ),
        "Keep durable memory factual, sourced, and useful for future coding tasks.",
        "",
        "## Project Facts",
        "",
    ]
    lines.extend(_index_record_lines(store.project_facts))
    lines.extend(["", "## Code Preferences", ""])
    lines.extend(_index_record_lines(store.code_preferences))
    lines.extend(["", "## Run History", ""])
    if store.run_history:
        for run in sorted(store.run_history, key=lambda item: item.created_at, reverse=True):
            lines.extend(
                [
                    f"### {run.created_at} - {run.run_id}",
                    "",
                    f"- Task: {run.task or 'No task recorded.'}",
                    f"- Model: {run.model}",
                    f"- Changed files: {', '.join(run.changed_files) or 'none'}",
                    f"- Verification: {run.verification}",
                    f"- Result: {run.result or 'No final output recorded.'}",
                    "",
                ]
            )
    else:
        lines.extend(["- No runs recorded yet.", ""])

    lines.extend(["## Conflicts", ""])
    if store.conflicts:
        for conflict in store.conflicts[-10:]:
            lines.append(
                f"- {conflict.created_at}: {conflict.title} "
                f"({conflict.old_record_id} -> {conflict.new_record_id})"
            )
    else:
        lines.append("- No conflicts recorded.")

    if store.compacted_run_summary:
        lines.extend(["", "## Compacted Run Summary", "", store.compacted_run_summary])

    return "\n".join(lines).rstrip() + "\n"


def migrate_legacy_memory(text: str) -> StructuredMemory:
    store = StructuredMemory()
    for note in _legacy_project_notes(text):
        add_memory_record(
            store,
            category="project_fact",
            title=note[:80],
            content=note,
            confidence=0.55,
            tags=["legacy"],
        )
    store.run_history.extend(_legacy_runs(text))
    compact_memory(store)
    return store


def append_run_memory(report: Any, memory_path: Path) -> None:
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    store = load_structured_memory(Path(report.repo), memory_path)
    store.run_history.append(_run_record_from_report(report))
    compact_memory(store)
    save_structured_memory(store, structured_memory_path(memory_path))
    write_memory_index(memory_path, store)


def compact_memory(store: StructuredMemory, *, max_runs: int = MAX_RUN_HISTORY_ENTRIES) -> None:
    store.run_history.sort(key=lambda run: run.created_at, reverse=True)
    if len(store.run_history) <= max_runs:
        return

    compacted = store.run_history[max_runs:]
    store.run_history = store.run_history[:max_runs]
    examples = "; ".join(
        f"{run.run_id}: {run.task[:80] or 'No task'}" for run in compacted[:5]
    )
    prefix = store.compacted_run_summary.strip()
    new_summary = (
        f"Compacted {len(compacted)} older run history entries at {_utc_now()}. "
        f"Representative older runs: {examples or 'none'}."
    )
    store.compacted_run_summary = f"{prefix}\n{new_summary}".strip() if prefix else new_summary


def _run_record_from_report(report: Any) -> RunMemoryRecord:
    changed_files = _changed_files_from_status(getattr(report, "git_status", ""))
    verification = getattr(report, "verification", None)
    host_verification = getattr(report, "host_verification", None)
    if host_verification is not None:
        verification_text = f"host_exit_code={host_verification.exit_code}"
    elif verification is None:
        verification_text = "not run"
    else:
        verification_text = f"exit_code={verification.exit_code}"

    final_output = str(getattr(report, "final_output", "")).strip()
    if len(final_output) > MAX_RUN_RESULT_CHARS:
        final_output = f"{final_output[:MAX_RUN_RESULT_CHARS].rstrip()}..."

    return RunMemoryRecord(
        run_id=str(getattr(report, "run_id", "")),
        task=str(getattr(report, "task", "")),
        model=f"{getattr(report, 'model_provider', '')}/{getattr(report, 'model', '')}",
        changed_files=changed_files,
        verification=verification_text,
        result=final_output or "No final output recorded.",
    )


def _changed_files_from_status(status: str) -> list[str]:
    changed: list[str] = []
    for line in status.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(maxsplit=1)
        changed.append(parts[-1] if parts else stripped)
    return changed


def _structured_memory_from_dict(data: dict[str, Any]) -> StructuredMemory:
    return StructuredMemory(
        schema_version=int(data.get("schema_version", MEMORY_SCHEMA_VERSION)),
        project_facts=[
            _memory_record_from_dict(item, "project_fact")
            for item in data.get("project_facts", [])
            if isinstance(item, dict)
        ],
        code_preferences=[
            _memory_record_from_dict(item, "code_preference")
            for item in data.get("code_preferences", [])
            if isinstance(item, dict)
        ],
        run_history=[
            _run_memory_record_from_dict(item)
            for item in data.get("run_history", [])
            if isinstance(item, dict)
        ],
        conflicts=[
            _memory_conflict_from_dict(item)
            for item in data.get("conflicts", [])
            if isinstance(item, dict)
        ],
        compacted_run_summary=str(data.get("compacted_run_summary", "")),
        updated_at=str(data.get("updated_at") or _utc_now()),
    )


def _memory_record_from_dict(data: dict[str, Any], fallback: MemoryCategory) -> MemoryRecord:
    category = data.get("category", fallback)
    if category not in {"project_fact", "code_preference"}:
        category = fallback
    status = data.get("status", "active")
    if status not in {"active", "superseded", "stale"}:
        status = "active"
    return MemoryRecord(
        id=str(data.get("id") or f"mem_{uuid.uuid4().hex}"),
        category=category,
        title=str(data.get("title") or "Untitled memory"),
        content=str(data.get("content") or ""),
        source_run_id=(
            str(data["source_run_id"]) if data.get("source_run_id") is not None else None
        ),
        confidence=float(data.get("confidence", 0.8)),
        status=status,
        tags=[str(tag) for tag in data.get("tags", []) if str(tag).strip()],
        why=str(data.get("why") or ""),
        how_to_apply=str(data.get("how_to_apply") or ""),
        created_at=str(data.get("created_at") or _utc_now()),
        updated_at=str(data.get("updated_at") or _utc_now()),
    )


def _run_memory_record_from_dict(data: dict[str, Any]) -> RunMemoryRecord:
    return RunMemoryRecord(
        run_id=str(data.get("run_id") or ""),
        task=str(data.get("task") or ""),
        model=str(data.get("model") or ""),
        changed_files=[str(item) for item in data.get("changed_files", [])],
        verification=str(data.get("verification") or ""),
        result=str(data.get("result") or ""),
        created_at=str(data.get("created_at") or _utc_now()),
    )


def _memory_conflict_from_dict(data: dict[str, Any]) -> MemoryConflict:
    category = data.get("category", "project_fact")
    if category not in {"project_fact", "code_preference"}:
        category = "project_fact"
    return MemoryConflict(
        id=str(data.get("id") or f"conflict_{uuid.uuid4().hex}"),
        category=category,
        title=str(data.get("title") or "Untitled conflict"),
        old_record_id=str(data.get("old_record_id") or ""),
        new_record_id=str(data.get("new_record_id") or ""),
        reason=str(data.get("reason") or ""),
        resolved_by=str(data.get("resolved_by") or "newer_memory_wins"),
        created_at=str(data.get("created_at") or _utc_now()),
    )


def _records_for_category(store: StructuredMemory, category: MemoryCategory) -> list[MemoryRecord]:
    if category == "project_fact":
        return store.project_facts
    if category == "code_preference":
        return store.code_preferences
    raise ValueError(f"Unsupported memory category: {category}")


def _memory_score(record: MemoryRecord, query_tokens: set[str]) -> float:
    haystack = _tokens(
        " ".join(
            [
                record.title,
                record.content,
                record.why,
                record.how_to_apply,
                " ".join(record.tags),
            ]
        )
    )
    overlap = len(query_tokens & haystack)
    if overlap == 0:
        return 0
    return overlap + record.confidence


def _record_prompt_lines(record: MemoryRecord) -> list[str]:
    lines = [
        (
            f"- [{record.category}] {record.title} "
            f"(confidence={record.confidence:.2f}, "
            f"source={record.source_run_id or 'manual'})"
        ),
        f"  Content: {record.content}",
    ]
    if record.why:
        lines.append(f"  Why: {record.why}")
    if record.how_to_apply:
        lines.append(f"  How to apply: {record.how_to_apply}")
    if record.tags:
        lines.append(f"  Tags: {', '.join(record.tags)}")
    return lines


def _index_record_lines(records: list[MemoryRecord]) -> list[str]:
    active = [record for record in records if record.status == "active"]
    if not active:
        return ["- No active entries yet."]
    return [
        f"- [{record.status}] {record.title} — {record.content} "
        f"(confidence={record.confidence:.2f}, source={record.source_run_id or 'manual'})"
        for record in sorted(active, key=lambda item: item.updated_at, reverse=True)
    ]


def _legacy_project_notes(text: str) -> list[str]:
    match = re.search(r"## Project Notes(?P<body>.*?)(?:\n## |\Z)", text, flags=re.S)
    if not match:
        return []
    notes: list[str] = []
    for line in match.group("body").splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        note = stripped[2:].strip()
        if note and note.lower() != "no durable notes yet.":
            notes.append(note)
    return notes


def _legacy_runs(text: str) -> list[RunMemoryRecord]:
    runs: list[RunMemoryRecord] = []
    for block in re.split(r"\n### ", text):
        if " - run_" not in block:
            continue
        lines = block.strip().splitlines()
        header = lines[0]
        created_at, _, run_id = header.partition(" - ")
        fields: dict[str, str] = {}
        for line in lines[1:]:
            stripped = line.strip()
            if not stripped.startswith("- ") or ":" not in stripped:
                continue
            key, value = stripped[2:].split(":", 1)
            fields[key.strip().lower()] = value.strip()
        runs.append(
            RunMemoryRecord(
                run_id=run_id.strip(),
                task=fields.get("task", ""),
                model=fields.get("model", ""),
                changed_files=[
                    item.strip()
                    for item in fields.get("changed files", "").split(",")
                    if item.strip() and item.strip() != "none"
                ],
                verification=fields.get("verification", ""),
                result=fields.get("result", ""),
                created_at=created_at.strip(),
            )
        )
    return runs


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9_./:-]+", value.lower())
        if len(token) > 1
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
