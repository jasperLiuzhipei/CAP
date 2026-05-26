from __future__ import annotations

import os
from pathlib import Path

from copilot_agent.env import load_dotenv


def test_load_dotenv_reads_simple_values(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "# ignored",
                "A=value",
                "B='quoted'",
                "C=\"double\"",
                "NO_EQUALS",
                "=missing_key",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("A", raising=False)
    monkeypatch.delenv("B", raising=False)
    monkeypatch.delenv("C", raising=False)
    monkeypatch.setenv("EXISTING", "keep")
    env_path.write_text(env_path.read_text(encoding="utf-8") + "\nEXISTING=replace\n")

    load_dotenv(env_path)

    assert os.environ["A"] == "value"
    assert os.environ["B"] == "quoted"
    assert os.environ["C"] == "double"
    assert os.environ["EXISTING"] == "keep"


def test_load_dotenv_missing_file_is_noop(tmp_path: Path) -> None:
    load_dotenv(tmp_path / "missing.env")
