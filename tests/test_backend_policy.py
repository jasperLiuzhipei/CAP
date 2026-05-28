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
    network = policy.decide_shell("curl https://example.com")
    unknown = policy.decide_shell("make deploy")

    assert install.action == "approval_required"
    assert install.risk == "R2"
    assert network.action == "approval_required"
    assert network.risk == "R3"
    assert unknown.action == "approval_required"


def test_shell_policy_denies_destructive_or_invalid_commands() -> None:
    policy = ToolPolicyEngine()

    assert policy.decide_shell("").action == "deny"
    assert policy.decide_shell("git reset --hard HEAD").action == "deny"
    assert policy.decide_shell("git clean -fd").action == "deny"
    assert policy.decide_shell("rm -rf /tmp/example").risk == "R4"


def test_git_policy_separates_read_write_and_remote_operations() -> None:
    policy = ToolPolicyEngine()

    readonly = policy.decide_shell("git -C repo status --short")
    readonly_with_option = policy.decide_shell("git --no-pager status")
    patch_check = policy.decide_shell("git -C repo apply --check diff.patch")
    write = policy.decide_shell("git commit -m 'feat: demo'")
    remote = policy.decide_shell("git push origin feature")
    unknown = policy.decide_shell("git -C repo")

    assert readonly.action == "allow"
    assert readonly.risk == "R0"
    assert readonly_with_option.action == "allow"
    assert patch_check.action == "allow"
    assert patch_check.risk == "R1"
    assert write.action == "approval_required"
    assert write.risk == "R2"
    assert remote.action == "approval_required"
    assert remote.risk == "R3"
    assert unknown.action == "approval_required"


def test_direct_git_tool_policy_handles_empty_malformed_and_remote_commands() -> None:
    policy = ToolPolicyEngine()

    empty = policy.decide("git.exec", {"command": ""})
    malformed = policy.decide_git("commit -m 'unterminated")
    remote = policy.decide_git("push origin feature")
    unknown = policy.decide_git("bisect start")

    assert empty.action == "deny"
    assert malformed.action == "approval_required"
    assert remote.risk == "R3"
    assert unknown.action == "approval_required"


def test_tool_policy_classifies_patch_and_unknown_tools() -> None:
    policy = ToolPolicyEngine()

    patch = policy.decide("apply_patch", {"patch": "*** Begin Patch"})
    network = policy.decide("network.request", {"url": "https://example.com"})
    unknown = policy.decide("mcp.delete_everything", {})

    assert patch.requires_approval
    assert patch.risk == "R1"
    assert network.requires_approval
    assert network.risk == "R3"
    assert unknown.requires_approval
    assert unknown.risk == "R2"


def test_policy_rules_are_describable_for_the_api() -> None:
    rules = ToolPolicyEngine().describe_rules()

    scopes = {rule["scope"] for rule in rules}
    assert {"apply_patch", "git.remote", "network", "destructive"}.issubset(scopes)


def test_command_parser_handles_env_cd_and_malformed_shell() -> None:
    policy = ToolPolicyEngine()

    assert policy._first_executable("env PYTHONPATH=src pytest tests") == "pytest"
    assert policy._first_executable("cd repo && ruff check .") == "ruff"
    assert policy._first_executable("python -c 'unterminated") == ""
    assert policy._first_executable("FOO=bar") == ""
