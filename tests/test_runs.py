from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from copilot_agent.runs import (
    ApplyResult,
    apply_run_patch,
    list_runs,
    load_report,
    read_run_text,
    resolve_run_dir,
)


def test_apply_run_patch_round_trip(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)

    run_dir = tmp_path / "runs" / "run_test"
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(
        json.dumps(
            {
                "run_id": "run_test",
                "repo": str(repo),
                "task": "Change value",
                "model": "deepseek-v4-flash",
                "model_provider": "deepseek",
                "tool_strategy": "compat_functions",
                "diff": "present",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "diff.patch").write_text(
        "\n".join(
            [
                "--- repo/sample.py",
                "+++ repo/sample.py",
                "@@ -1 +1 @@",
                "-value = 1",
                "+value = 2",
                "",
            ]
        ),
        encoding="utf-8",
    )

    check = apply_run_patch(run_dir, check_only=True)
    applied = apply_run_patch(run_dir)

    assert check.exit_code == 0
    assert not check.applied
    assert applied.applied
    assert (repo / "sample.py").read_text(encoding="utf-8") == "value = 2\n"


def test_list_runs_reads_saved_reports(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_test"
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(
        json.dumps(
            {
                "run_id": "run_test",
                "repo": "/tmp/repo",
                "task": "Do work",
                "model": "m",
                "model_provider": "p",
                "tool_strategy": "compat_functions",
                "diff": "non-empty",
            }
        ),
        encoding="utf-8",
    )

    records = list_runs(tmp_path / "runs")

    assert len(records) == 1
    assert records[0].run_id == "run_test"
    assert records[0].changed
    assert len(list_runs(tmp_path / "runs", limit=1)) == 1


def test_run_helpers_cover_edge_cases(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs"
    output_dir.mkdir()
    existing = output_dir / "run_existing"
    existing.mkdir()
    missing_run = output_dir / "run_missing"

    assert resolve_run_dir(str(existing), output_dir) == existing.resolve()
    assert resolve_run_dir("run_missing", output_dir) == missing_run.resolve()
    assert list_runs(tmp_path / "missing") == []
    assert read_run_text(existing, "missing.txt") == ""

    with pytest.raises(FileNotFoundError, match="Run report not found"):
        load_report(existing)

    (existing / "bad_report.json").write_text("{", encoding="utf-8")
    assert list_runs(output_dir) == []

    bad_run = output_dir / "run_bad"
    bad_run.mkdir()
    (bad_run / "report.json").write_text("{", encoding="utf-8")
    assert list_runs(output_dir) == []

    (existing / "note.txt").write_text("hello", encoding="utf-8")
    assert read_run_text(existing, "note.txt") == "hello"


def test_apply_result_combined_output() -> None:
    assert ApplyResult(["cmd"], 0, "out", "", True).combined_output == "out"
    assert ApplyResult(["cmd"], 1, "out", "err", False).combined_output == "outerr"


def test_apply_run_patch_errors(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "report.json").write_text(
        json.dumps({"repo": str(tmp_path / "missing")}),
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError, match="Target repo"):
        apply_run_patch(run_dir)

    repo = tmp_path / "repo"
    repo.mkdir()
    (run_dir / "report.json").write_text(json.dumps({"repo": str(repo)}), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="Run diff"):
        apply_run_patch(run_dir)

    (run_dir / "diff.patch").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="diff is empty"):
        apply_run_patch(run_dir)


def test_apply_run_patch_check_failure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)

    run_dir = tmp_path / "runs" / "run_fail"
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(json.dumps({"repo": str(repo)}), encoding="utf-8")
    (run_dir / "diff.patch").write_text(
        "\n".join(
            [
                "--- repo/missing.py",
                "+++ repo/missing.py",
                "@@ -1 +1 @@",
                "-a",
                "+b",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = apply_run_patch(run_dir)

    assert result.exit_code != 0
    assert not result.applied
