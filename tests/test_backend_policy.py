from __future__ import annotations

from copilot_agent.backend.policy import ToolDecision, ToolPolicyEngine


def test_tool_decision_helpers() -> None:
    approval = ToolDecision("apply_patch", "approval_required", "R1", "review")
    denied = ToolDecision("shell.exec", "deny", "R4", "danger")

    assert approval.requires_approval
    assert approval.allowed
    assert not denied.requires_approval
    assert not denied.allowed


def test_shell_policy_allows_read_only_and_verification_commands() -> None:
    policy = ToolPolicyEngine()

    assert policy.decide_shell("rg apply_discount").risk == "R0"
    assert policy.decide_shell("git -C repo diff --").risk == "R0"

    verification = policy.decide_shell(
        "cd repo && PYTHONPATH=src python3 -m pytest tests"
    )
    assert verification.action == "allow"
    assert verification.risk == "R1"


def test_shell_policy_requires_approval_for_network_or_unknown_commands() -> None:
    policy = ToolPolicyEngine()

    install = policy.decide_shell("python3 -m pip install pytest")
    unknown = policy.decide_shell("make deploy")

    assert install.action == "approval_required"
    assert install.risk == "R2"
    assert unknown.action == "approval_required"


def test_shell_policy_denies_destructive_or_invalid_commands() -> None:
    policy = ToolPolicyEngine()

    assert policy.decide_shell("").action == "deny"
    assert policy.decide_shell("git reset --hard HEAD").action == "deny"
    assert policy.decide_shell("rm -rf /tmp/example").risk == "R4"


def test_tool_policy_classifies_patch_and_unknown_tools() -> None:
    policy = ToolPolicyEngine()

    patch = policy.decide("apply_patch", {"patch": "*** Begin Patch"})
    unknown = policy.decide("mcp.delete_everything", {})

    assert patch.requires_approval
    assert patch.risk == "R1"
    assert unknown.requires_approval
    assert unknown.risk == "R2"


def test_command_parser_handles_env_cd_and_malformed_shell() -> None:
    policy = ToolPolicyEngine()

    assert policy._first_executable("env PYTHONPATH=src pytest tests") == "pytest"
    assert policy._first_executable("cd repo && ruff check .") == "ruff"
    assert policy._first_executable("python -c 'unterminated") == ""
