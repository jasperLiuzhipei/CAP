from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Literal

PolicyAction = Literal["allow", "approval_required", "deny"]


@dataclass(frozen=True)
class ToolDecision:
    tool_name: str
    action: PolicyAction
    risk: str
    reason: str

    @property
    def requires_approval(self) -> bool:
        return self.action == "approval_required"

    @property
    def allowed(self) -> bool:
        return self.action in {"allow", "approval_required"}


@dataclass(frozen=True)
class ToolPolicyConfig:
    read_only_commands: set[str] = field(
        default_factory=lambda: {"cat", "find", "grep", "head", "ls", "pwd", "rg", "sed", "tail"}
    )
    verification_commands: set[str] = field(
        default_factory=lambda: {
            "bun",
            "mypy",
            "npm",
            "pytest",
            "python",
            "python3",
            "ruff",
            "uv",
        }
    )
    read_only_git_subcommands: set[str] = field(
        default_factory=lambda: {"diff", "log", "rev-parse", "show", "status"}
    )
    denied_patterns: tuple[str, ...] = (
        r"\brm\s+-rf\b",
        r"\bgit\s+reset\s+--hard\b",
        r"\bgit\s+push\b",
        r"\bshutdown\b",
        r"\breboot\b",
    )
    approval_patterns: tuple[str, ...] = (
        r"\bcurl\b",
        r"\bwget\b",
        r"\bpip\s+install\b",
        r"\bnpm\s+install\b",
        r"\buv\s+sync\b",
        r"\bgit\s+clone\b",
    )


class ToolPolicyEngine:
    """Classify tool calls before execution or audit replay."""

    def __init__(self, config: ToolPolicyConfig | None = None) -> None:
        self.config = config or ToolPolicyConfig()

    def decide(self, tool_name: str, arguments: dict[str, object] | None = None) -> ToolDecision:
        arguments = arguments or {}
        if tool_name in {"shell.exec", "exec_command"}:
            command = str(arguments.get("cmd") or arguments.get("command") or "")
            return self.decide_shell(command)
        if tool_name == "apply_patch":
            return ToolDecision(
                tool_name=tool_name,
                action="approval_required",
                risk="R1",
                reason="file modification requires review before applying to the real repo",
            )
        return ToolDecision(
            tool_name=tool_name,
            action="approval_required",
            risk="R2",
            reason="unknown tool requires explicit approval",
        )

    def decide_shell(self, command: str) -> ToolDecision:
        normalized = command.strip()
        if not normalized:
            return ToolDecision(
                tool_name="shell.exec",
                action="deny",
                risk="R4",
                reason="empty shell command is invalid",
            )

        for pattern in self.config.denied_patterns:
            if re.search(pattern, normalized):
                return ToolDecision(
                    tool_name="shell.exec",
                    action="deny",
                    risk="R4",
                    reason=f"command matches denied pattern: {pattern}",
                )

        for pattern in self.config.approval_patterns:
            if re.search(pattern, normalized):
                return ToolDecision(
                    tool_name="shell.exec",
                    action="approval_required",
                    risk="R2",
                    reason=f"command matches approval pattern: {pattern}",
                )

        command_parts = self._first_command_parts(normalized)
        executable = command_parts[0] if command_parts else ""
        if executable == "git":
            subcommand = self._git_subcommand(command_parts)
            if subcommand in self.config.read_only_git_subcommands:
                return ToolDecision(
                    tool_name="shell.exec",
                    action="allow",
                    risk="R0",
                    reason=f"read-only git command `{subcommand}` is allowlisted",
                )
        if executable in self.config.read_only_commands:
            return ToolDecision(
                tool_name="shell.exec",
                action="allow",
                risk="R0",
                reason=f"read-only command `{executable}` is allowlisted",
            )
        if executable in self.config.verification_commands:
            return ToolDecision(
                tool_name="shell.exec",
                action="allow",
                risk="R1",
                reason=f"verification command `{executable}` is allowlisted",
            )

        return ToolDecision(
            tool_name="shell.exec",
            action="approval_required",
            risk="R2",
            reason=f"command `{executable or 'unknown'}` is not allowlisted",
        )

    @staticmethod
    def _first_command_parts(command: str) -> list[str]:
        for segment in _split_shell_segments(command):
            try:
                parts = shlex.split(segment)
            except ValueError:
                return []
            parts = _strip_env_assignments(parts)
            if not parts:
                continue
            if parts[0] == "cd":
                continue
            return parts
        return []

    @staticmethod
    def _first_executable(command: str) -> str:
        parts = ToolPolicyEngine._first_command_parts(command)
        return parts[0] if parts else ""

    @staticmethod
    def _git_subcommand(parts: list[str]) -> str:
        index = 1
        while index < len(parts):
            part = parts[index]
            if part == "-C":
                index += 2
                continue
            if part.startswith("-"):
                index += 1
                continue
            return part
        return ""


def _split_shell_segments(command: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"\s*(?:&&|\|\||;)\s*", command)]


def _strip_env_assignments(parts: list[str]) -> list[str]:
    index = 0
    if parts and parts[0] == "env":
        index = 1
    while index < len(parts) and _is_env_assignment(parts[index]):
        index += 1
    return parts[index:]


def _is_env_assignment(part: str) -> bool:
    name, separator, _ = part.partition("=")
    return bool(separator and name and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))
