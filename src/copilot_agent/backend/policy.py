from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Literal

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
    write_git_subcommands: set[str] = field(
        default_factory=lambda: {
            "add",
            "apply",
            "checkout",
            "commit",
            "merge",
            "rebase",
            "restore",
            "switch",
        }
    )
    remote_git_subcommands: set[str] = field(
        default_factory=lambda: {"clone", "fetch", "pull", "push"}
    )
    network_commands: set[str] = field(
        default_factory=lambda: {
            "curl",
            "ftp",
            "http",
            "https",
            "nc",
            "ncat",
            "scp",
            "ssh",
            "telnet",
            "wget",
        }
    )
    denied_patterns: tuple[str, ...] = (
        r"\brm\s+-rf\b",
        r"\bgit\s+reset\s+--hard\b",
        r"\bgit\s+clean\s+-[^\s]*f[^\s]*\b",
        r"\bchmod\s+-R\s+777\b",
        r"\bdd\s+if=",
        r"\bmkfs\b",
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
        if tool_name in {"git.exec", "git"}:
            command = str(arguments.get("cmd") or arguments.get("command") or "")
            return self.decide_git(command)
        if tool_name in {"network.request", "http.request", "web.fetch"}:
            return ToolDecision(
                tool_name=tool_name,
                action="approval_required",
                risk="R3",
                reason="network access requires explicit approval and egress review",
            )
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

        command_parts = self._first_command_parts(normalized)
        executable = command_parts[0] if command_parts else ""
        if executable == "git":
            return self._decide_git_parts(command_parts, tool_name="shell.exec")
        if executable in self.config.network_commands:
            return ToolDecision(
                tool_name="shell.exec",
                action="approval_required",
                risk="R3",
                reason=f"network command `{executable}` requires egress approval",
            )
        for pattern in self.config.approval_patterns:
            if re.search(pattern, normalized):
                return ToolDecision(
                    tool_name="shell.exec",
                    action="approval_required",
                    risk="R2",
                    reason=f"command matches approval pattern: {pattern}",
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

    def decide_git(self, command: str) -> ToolDecision:
        normalized = command.strip()
        if not normalized:
            return ToolDecision(
                tool_name="git.exec",
                action="deny",
                risk="R4",
                reason="empty git command is invalid",
            )

        try:
            parts = shlex.split(normalized)
        except ValueError:
            return ToolDecision(
                tool_name="git.exec",
                action="approval_required",
                risk="R2",
                reason="malformed git command requires manual review",
            )

        if parts and parts[0] != "git":
            parts = ["git", *parts]
        return self._decide_git_parts(parts, tool_name="git.exec")

    def describe_rules(self) -> list[dict[str, Any]]:
        return [
            {
                "scope": "shell.read_only",
                "action": "allow",
                "risk": "R0",
                "description": "Read-only inspection commands can run without approval.",
                "examples": sorted(self.config.read_only_commands),
            },
            {
                "scope": "shell.verification",
                "action": "allow",
                "risk": "R1",
                "description": (
                    "Local verification commands are allowed because they are expected "
                    "in coding runs."
                ),
                "examples": sorted(self.config.verification_commands),
            },
            {
                "scope": "git.read_only",
                "action": "allow",
                "risk": "R0",
                "description": "Read-only git commands are safe for inspection and diff review.",
                "examples": sorted(self.config.read_only_git_subcommands),
            },
            {
                "scope": "git.write",
                "action": "approval_required",
                "risk": "R2",
                "description": (
                    "Local git write operations can change repository state and "
                    "require review."
                ),
                "examples": sorted(self.config.write_git_subcommands),
            },
            {
                "scope": "git.remote",
                "action": "approval_required",
                "risk": "R3",
                "description": (
                    "Remote git operations can exfiltrate code or mutate remote "
                    "history."
                ),
                "examples": sorted(self.config.remote_git_subcommands),
            },
            {
                "scope": "network",
                "action": "approval_required",
                "risk": "R3",
                "description": "Network access requires explicit approval and egress review.",
                "examples": sorted(self.config.network_commands),
            },
            {
                "scope": "apply_patch",
                "action": "approval_required",
                "risk": "R1",
                "description": (
                    "File modifications require review before the sandbox result "
                    "is trusted."
                ),
                "examples": ["apply_patch"],
            },
            {
                "scope": "destructive",
                "action": "deny",
                "risk": "R4",
                "description": "Destructive host or repository operations are denied by default.",
                "examples": list(self.config.denied_patterns),
            },
        ]

    def _decide_git_parts(self, parts: list[str], *, tool_name: str) -> ToolDecision:
        subcommand = self._git_subcommand(parts)
        if subcommand in self.config.read_only_git_subcommands:
            return ToolDecision(
                tool_name=tool_name,
                action="allow",
                risk="R0",
                reason=f"read-only git command `{subcommand}` is allowlisted",
            )
        if subcommand == "apply" and "--check" in parts:
            return ToolDecision(
                tool_name=tool_name,
                action="allow",
                risk="R1",
                reason="git apply --check validates a patch without mutating the repo",
            )
        if subcommand in self.config.remote_git_subcommands:
            return ToolDecision(
                tool_name=tool_name,
                action="approval_required",
                risk="R3",
                reason=f"remote git command `{subcommand}` requires approval",
            )
        if subcommand in self.config.write_git_subcommands or subcommand == "reset":
            return ToolDecision(
                tool_name=tool_name,
                action="approval_required",
                risk="R2",
                reason=f"git command `{subcommand}` can modify repository state",
            )
        return ToolDecision(
            tool_name=tool_name,
            action="approval_required",
            risk="R2",
            reason=f"git command `{subcommand or 'unknown'}` is not allowlisted",
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
