from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    run_dir: Path
    repo: str
    task: str
    model: str
    model_provider: str
    tool_strategy: str
    changed: bool


@dataclass(frozen=True)
class ApplyResult:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    applied: bool

    @property
    def combined_output(self) -> str:
        if self.stderr:
            return f"{self.stdout}{self.stderr}"
        return self.stdout


def resolve_run_dir(run: str, output_dir: Path) -> Path:
    candidate = Path(run)
    if candidate.exists():
        return candidate.resolve()
    return (output_dir / run).resolve()


def load_report(run_dir: Path) -> dict[str, Any]:
    report_path = run_dir / "report.json"
    if not report_path.exists():
        raise FileNotFoundError(f"Run report not found: {report_path}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def list_runs(output_dir: Path, *, limit: int | None = None) -> list[RunRecord]:
    if not output_dir.exists():
        return []

    records: list[RunRecord] = []
    for report_path in sorted(output_dir.glob("run_*/report.json"), reverse=True):
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        run_dir = report_path.parent
        records.append(
            RunRecord(
                run_id=str(payload.get("run_id") or run_dir.name),
                run_dir=run_dir,
                repo=str(payload.get("repo") or ""),
                task=str(payload.get("task") or ""),
                model=str(payload.get("model") or ""),
                model_provider=str(payload.get("model_provider") or ""),
                tool_strategy=str(payload.get("tool_strategy") or ""),
                changed=bool(str(payload.get("diff") or "").strip()),
            )
        )
        if limit is not None and len(records) >= limit:
            break
    return records


def read_run_text(run_dir: Path, name: str) -> str:
    path = run_dir / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def apply_run_patch(
    run_dir: Path,
    *,
    repo: Path | None = None,
    check_only: bool = False,
) -> ApplyResult:
    report = load_report(run_dir)
    repo_path = (repo or Path(str(report.get("repo") or ""))).resolve()
    if not repo_path.exists():
        raise FileNotFoundError(f"Target repo does not exist: {repo_path}")

    diff_path = run_dir / "diff.patch"
    if not diff_path.exists():
        raise FileNotFoundError(f"Run diff not found: {diff_path}")
    if not diff_path.read_text(encoding="utf-8").strip():
        raise ValueError("Run diff is empty; there is nothing to apply.")

    check_command = ["git", "-C", str(repo_path), "apply", "-p1", "--check", str(diff_path)]
    check = subprocess.run(check_command, text=True, capture_output=True)
    if check.returncode != 0 or check_only:
        return ApplyResult(
            command=check_command,
            exit_code=check.returncode,
            stdout=check.stdout,
            stderr=check.stderr,
            applied=False,
        )

    apply_command = ["git", "-C", str(repo_path), "apply", "-p1", str(diff_path)]
    applied = subprocess.run(apply_command, text=True, capture_output=True)
    return ApplyResult(
        command=apply_command,
        exit_code=applied.returncode,
        stdout=applied.stdout,
        stderr=applied.stderr,
        applied=applied.returncode == 0,
    )
