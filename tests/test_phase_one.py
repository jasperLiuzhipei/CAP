from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from copilot_agent import phase_one as phase_one_module
from copilot_agent.model_config import resolve_model_config
from copilot_agent.phase_one import (
    CommandResult,
    FileSnapshot,
    PhaseOneConfig,
    PhaseOneReport,
    SandboxRuntimeReport,
    _build_sandbox_manifest,
    _build_sandbox_test_command,
    _command_needs_python,
    _command_uses_pytest,
    _dependency_help,
    _diff_snapshots,
    _extract_tool_calls,
    _format_sandbox_runtime_log,
    _python_executables_from_test_cmd,
    _python_prefixes_from_host,
    _python_runtime_roots,
    _pyvenv_home_roots,
    _report_to_json,
    _resolve_executable,
    _run_host_verification,
    _safe_unique_paths,
    _sandbox_pytest_check_command,
    _sandbox_python_check_command,
    _sandbox_runtime_grant_paths,
    _should_snapshot_file,
    _snapshot_local_tree,
    build_phase_one_prompt,
    save_report,
    validate_config,
)


@dataclass
class DictRawItem:
    raw_item: dict[str, object]


@dataclass
class ObjectRaw:
    type: str
    name: str | None = None
    arguments: str | None = None


@dataclass
class ObjectRawItem:
    raw_item: ObjectRaw


class FakeSandboxPathGrant:
    def __init__(self, *, path: Path, read_only: bool) -> None:
        self.path = path
        self.read_only = read_only


class FakeLocalDir:
    def __init__(self, *, src: Path) -> None:
        self.src = src


class FakeManifest:
    def __init__(
        self,
        *,
        entries: dict[str, object],
        extra_path_grants: tuple[object, ...],
    ) -> None:
        self.entries = entries
        self.extra_path_grants = extra_path_grants


FAKE_MANIFEST_SDK = {
    "LocalDir": FakeLocalDir,
    "Manifest": FakeManifest,
    "SandboxPathGrant": FakeSandboxPathGrant,
}


def test_host_verification_runs_on_temp_copy(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)

    diff = "\n".join(
        [
            "--- repo/sample.py",
            "+++ repo/sample.py",
            "@@ -1 +1 @@",
            "-value = 1",
            "+value = 2",
            "",
        ]
    )

    result = _run_host_verification(
        repo,
        diff,
        (
            "python3 -c \"from pathlib import Path; "
            "assert Path('sample.py').read_text() == 'value = 2\\n'\""
        ),
    )

    assert result.exit_code == 0
    assert (repo / "sample.py").read_text(encoding="utf-8") == "value = 1\n"


def test_host_verification_handles_empty_and_bad_diffs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    empty = _run_host_verification(repo, "", "echo ok")
    bad = _run_host_verification(
        repo,
        "--- repo/missing\n+++ repo/missing\n@@\n-bad\n+good\n",
        "echo ok",
    )

    assert empty.exit_code == 0
    assert "skipped" in empty.stdout
    assert bad.exit_code != 0


def test_command_result_combined_output() -> None:
    assert CommandResult("cmd", 0, "out", "").combined_output == "out"
    assert CommandResult("cmd", 1, "out", "err").combined_output == "outerr"


def test_validate_config_errors(tmp_path: Path) -> None:
    model_config = resolve_model_config(provider="deepseek", require_api_key=False)
    repo = tmp_path / "repo"
    repo.mkdir()

    validate_config(PhaseOneConfig(repo=repo, task="ok", model_config=model_config))

    with pytest.raises(ValueError, match="does not exist"):
        validate_config(
            PhaseOneConfig(repo=tmp_path / "missing", task="ok", model_config=model_config)
        )
    file_path = tmp_path / "file"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not a directory"):
        validate_config(PhaseOneConfig(repo=file_path, task="ok", model_config=model_config))
    with pytest.raises(ValueError, match="must not be empty"):
        validate_config(PhaseOneConfig(repo=repo, task=" ", model_config=model_config))
    with pytest.raises(ValueError, match="max_turns"):
        validate_config(
            PhaseOneConfig(repo=repo, task="ok", model_config=model_config, max_turns=0)
        )
    with pytest.raises(ValueError, match="Unsupported sandbox backend"):
        validate_config(
            PhaseOneConfig(
                repo=repo,
                task="ok",
                model_config=model_config,
                sandbox_backend="space_station",
            )
        )


def test_build_prompt_for_strategies_and_memory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    memory = repo / ".copilot" / "memory.md"
    memory.parent.mkdir()
    memory.write_text("remember this", encoding="utf-8")

    native = PhaseOneConfig(
        repo=repo,
        task="task",
        model_config=resolve_model_config(provider="openai", require_api_key=False),
    )
    compat = PhaseOneConfig(
        repo=repo,
        task="task",
        test_cmd="pytest",
        memory_enabled=True,
        model_config=resolve_model_config(provider="deepseek", require_api_key=False),
    )
    shell = PhaseOneConfig(
        repo=repo,
        task="task",
        model_config=resolve_model_config(
            provider="deepseek",
            tool_strategy="shell_only",
            require_api_key=False,
        ),
    )

    assert "SDK-native sandbox tools" in build_phase_one_prompt(native)
    assert "Project memory" in build_phase_one_prompt(compat)
    assert "Do not call apply_patch" in build_phase_one_prompt(shell)
    assert "sandbox-safe verification command" in build_phase_one_prompt(compat)


def test_sandbox_test_command_rewrites_host_python_and_pytest(tmp_path: Path) -> None:
    config = PhaseOneConfig(
        repo=tmp_path,
        task="task",
        test_cmd="/Users/me/project/.venv/bin/python -m pytest tests",
        sandbox_python="python3",
    )

    command, notes = _build_sandbox_test_command(config)

    assert command is not None
    assert "/Users/me/project/.venv/bin/python" not in command
    assert "python3 -m pytest tests" in command
    assert "PYTEST_ADDOPTS" in command
    assert "../.copilot-runtime/site" in command
    assert any("absolute host Python" in note for note in notes)
    assert any("pytest debugging plugin" in note for note in notes)


def test_sandbox_runtime_command_helper_edges(tmp_path: Path) -> None:
    no_test = PhaseOneConfig(repo=tmp_path, task="task")
    disabled = PhaseOneConfig(
        repo=tmp_path,
        task="task",
        test_cmd="python -m pytest",
        sandbox_runtime_enabled=False,
    )

    assert _build_sandbox_test_command(no_test) == (None, [])
    assert _build_sandbox_test_command(disabled) == (
        "python -m pytest",
        ["sandbox runtime provisioning disabled"],
    )
    assert not _command_uses_pytest(None)
    assert _command_uses_pytest("python -m pytest tests")
    assert not _command_uses_pytest("broken '")
    assert not _command_needs_python(None)
    assert _command_needs_python("python -c 'print(1)'")
    assert not _command_needs_python("echo ok")
    assert _python_executables_from_test_cmd(None) == []
    assert _python_executables_from_test_cmd("broken ' /tmp/venv/bin/python -m pytest") == [
        "/tmp/venv/bin/python"
    ]
    assert "import encodings" in _sandbox_python_check_command("python3")
    assert "import pytest" in _sandbox_pytest_check_command("python3")


def test_sandbox_runtime_grants_include_python_roots(tmp_path: Path) -> None:
    config = PhaseOneConfig(
        repo=tmp_path,
        task="task",
        test_cmd="python3 -m pytest tests",
    )

    grants = _sandbox_runtime_grant_paths(config)

    assert grants
    assert any(path.name in {"python", "python3"} or path.exists() for path in grants)


def test_build_sandbox_manifest_uses_backend_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    config = PhaseOneConfig(repo=tmp_path, task="task")

    monkeypatch.setattr(
        phase_one_module,
        "_sandbox_runtime_grant_paths",
        lambda _: [runtime_root],
    )

    manifest = _build_sandbox_manifest(config, FAKE_MANIFEST_SDK)

    assert isinstance(manifest, FakeManifest)
    assert isinstance(manifest.entries["repo"], FakeLocalDir)
    assert manifest.entries["repo"].src == tmp_path
    assert len(manifest.extra_path_grants) == 1
    assert manifest.extra_path_grants[0].path == runtime_root
    assert manifest.extra_path_grants[0].read_only


def test_python_runtime_path_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.write_text("", encoding="utf-8")
    (tmp_path / "venv" / "pyvenv.cfg").write_text(
        f"home = {tmp_path / 'base' / 'bin'}\n",
        encoding="utf-8",
    )

    assert _resolve_executable("") is None
    assert _resolve_executable(str(python)) == python
    assert _pyvenv_home_roots(python) == [tmp_path / "base"]

    monkeypatch.setattr(phase_one_module, "_resolve_executable", lambda _: None)
    assert _python_runtime_roots("missing-python") == []

    monkeypatch.setattr(phase_one_module, "_resolve_executable", lambda _: python)
    monkeypatch.setattr(phase_one_module, "_python_prefixes_from_host", lambda _: [tmp_path])
    monkeypatch.setattr(phase_one_module, "_pyvenv_home_roots", lambda _: [tmp_path / "base"])
    assert _python_runtime_roots("python") == [tmp_path / "venv", tmp_path, tmp_path / "base"]

    safe = _safe_unique_paths([tmp_path, tmp_path, Path("/"), tmp_path / "missing"])
    assert safe == [tmp_path.resolve()]


def test_python_prefix_probe_handles_host_process_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python = tmp_path / "python"

    def ok_run(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout='["/runtime", "/base"]')

    monkeypatch.setattr(phase_one_module.subprocess, "run", ok_run)
    assert _python_prefixes_from_host(python) == [Path("/runtime"), Path("/base")]

    def failed_run(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(phase_one_module.subprocess, "run", failed_run)
    assert _python_prefixes_from_host(python) == []

    def bad_json_run(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="not-json")

    monkeypatch.setattr(phase_one_module.subprocess, "run", bad_json_run)
    assert _python_prefixes_from_host(python) == []

    def raising_run(*args: object, **kwargs: object) -> SimpleNamespace:
        raise OSError("missing")

    monkeypatch.setattr(phase_one_module.subprocess, "run", raising_run)
    assert _python_prefixes_from_host(python) == []


def test_snapshot_and_diff_helpers(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    (repo / ".copilot").mkdir()
    (repo / ".copilot" / "memory.md").write_text("ignored", encoding="utf-8")
    (repo / "big.txt").write_text("x" * 1_000_001, encoding="utf-8")

    assert _should_snapshot_file(repo / "a.txt", repo)
    assert not _should_snapshot_file(repo / ".copilot" / "memory.md", repo)
    assert not _should_snapshot_file(repo / "big.txt", repo)

    snapshot = _snapshot_local_tree(repo)
    assert snapshot.files == {"a.txt": "a\n"}

    before = FileSnapshot(files={"a.txt": "a\n", "delete.txt": "bye\n"})
    after = FileSnapshot(files={"a.txt": "b\n", "new.txt": "new\n"})
    status, diff = _diff_snapshots(before, after)
    clean_status, clean_diff = _diff_snapshots(before, before)

    assert "M a.txt" in status
    assert "D delete.txt" in status
    assert "A new.txt" in status
    assert "--- repo/a.txt" in diff
    assert "+++ /dev/null" in diff
    assert "--- /dev/null" in diff
    assert clean_status == ""
    assert clean_diff == ""


def test_extract_tool_calls() -> None:
    calls = _extract_tool_calls(
        [
            DictRawItem(
                {"type": "function_call", "name": "tool_call", "arguments": "{\"x\": 1}"}
            ),
            DictRawItem({"type": "apply_patch_call", "arguments": "not-json"}),
            ObjectRawItem(ObjectRaw(type="function_call", name="exec_call", arguments=None)),
            ObjectRawItem(ObjectRaw(type="function_call", name=None, arguments=None)),
            ObjectRawItem(ObjectRaw(type="message", name="message", arguments=None)),
            object(),
        ]
    )

    assert calls[0] == {"name": "tool_call", "arguments": {"x": 1}}
    assert calls[1] == {"name": "apply_patch", "arguments": "not-json"}
    assert calls[2] == {"name": "exec_call", "arguments": None}
    assert calls[3] == {"name": "function_call", "arguments": None}


def test_report_serialization_and_save(tmp_path: Path) -> None:
    runtime = SandboxRuntimeReport(
        enabled=True,
        python_command="python3",
        original_test_cmd="python -m pytest",
        sandbox_test_cmd="PYTEST_ADDOPTS='-p no:debugging' python -m pytest",
        python_check=CommandResult("python3 -c check", 0, "ok", ""),
        notes=["runtime ok"],
    )
    report = PhaseOneReport(
        run_id="run_test",
        repo=str(tmp_path),
        task="task",
        model="m",
        model_provider="p",
        model_transport="chat_completions",
        tool_strategy="compat_functions",
        model_base_url=None,
        prompt="prompt",
        final_output="final",
        git_status="M file.py",
        diff="diff",
        sandbox_runtime=runtime,
        verification=CommandResult("pytest", 0, "ok", ""),
        host_verification=CommandResult("pytest", 0, "host ok", ""),
    )

    payload = _report_to_json(report)
    run_dir = save_report(report, tmp_path / "runs")

    assert payload["verification"]["exit_code"] == 0
    assert payload["sandbox_runtime"]["python_check"]["exit_code"] == 0
    assert payload["host_verification"]["stdout"] == "host ok"
    assert report.saved_dir == str(run_dir)
    assert (run_dir / "report.json").exists()
    assert (run_dir / "sandbox_runtime.log").exists()
    assert "runtime ok" in (run_dir / "sandbox_runtime.log").read_text(encoding="utf-8")
    assert "[python_check]" in _format_sandbox_runtime_log(runtime)
    assert (run_dir / "verification.log").read_text(encoding="utf-8") == "ok"
    assert (run_dir / "host_verification.log").read_text(encoding="utf-8") == "host ok"

    report_without_logs = PhaseOneReport(
        run_id="run_no_logs",
        repo=str(tmp_path),
        task="task",
        model="m",
        model_provider="p",
        model_transport="native",
        tool_strategy="native",
        model_base_url=None,
        prompt="prompt",
        final_output="final",
    )
    run_dir_without_logs = save_report(report_without_logs, tmp_path / "runs")
    assert not (run_dir_without_logs / "verification.log").exists()


def test_dependency_help_mentions_missing_package() -> None:
    assert "missing_pkg" in _dependency_help("missing_pkg")
