from __future__ import annotations

from copilot_agent.backend.models import TokenUsage
from copilot_agent.backend.observability import estimate_cost
from copilot_agent.model_registry import (
    get_model_pricing,
    get_model_profile,
    list_model_profiles,
)


def test_model_registry_lists_provider_profiles() -> None:
    profiles = list_model_profiles("deepseek")

    assert {profile.model for profile in profiles} >= {
        "deepseek-chat",
        "deepseek-v4-flash",
    }
    assert all(profile.provider == "deepseek" for profile in profiles)


def test_model_registry_exposes_capability_details() -> None:
    profile = get_model_profile("DeepSeek", "DEEPSEEK-V4-FLASH")

    assert profile is not None
    assert profile.transport == "chat_completions"
    assert profile.tool_strategy == "compat_functions"
    assert profile.native_tools == "unsupported"
    assert profile.filesystem == "platform_emulated"
    assert profile.pricing is not None
    assert profile.pricing.source == "default_estimate"


def test_deepseek_flash_pricing_feeds_cost_estimates() -> None:
    pricing = get_model_pricing("deepseek", "deepseek-v4-flash")
    cost = estimate_cost(
        provider="deepseek",
        model="deepseek-v4-flash",
        usage=TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000),
    )

    assert pricing is not None
    assert cost.pricing_source == "default_estimate"
    assert cost.input_cost_usd == pricing.input_usd_per_million_tokens
    assert cost.output_cost_usd == pricing.output_usd_per_million_tokens
