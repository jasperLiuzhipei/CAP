from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    """Indicative per-token pricing used for local run cost estimates."""

    input_usd_per_million_tokens: float
    output_usd_per_million_tokens: float
    source: str = "default_estimate"
    source_url: str | None = None
    updated_at: str = "2026-05-28"


@dataclass(frozen=True)
class ModelCapabilityProfile:
    """Product-level capability matrix for model routing and UI display."""

    provider: str
    model: str
    display_name: str
    transport: str
    tool_strategy: str
    native_tools: str
    function_tools: str
    filesystem: str
    compaction: str
    hosted_tools: str
    structured_outputs: str
    context_window_tokens: int | None
    cost_tier: str
    stability: str
    pricing: ModelPricing | None = None
    notes: tuple[str, ...] = ()


OPENAI_PRICING_URL = "https://openai.com/api/pricing/"
DEEPSEEK_PRICING_URL = "https://api-docs.deepseek.com/quick_start/pricing"


MODEL_CAPABILITY_PROFILES: dict[tuple[str, str], ModelCapabilityProfile] = {
    ("openai", "gpt-5.5"): ModelCapabilityProfile(
        provider="openai",
        model="gpt-5.5",
        display_name="OpenAI GPT-5.5",
        transport="native",
        tool_strategy="native",
        native_tools="supported",
        function_tools="supported",
        filesystem="native_agents_sdk",
        compaction="native_agents_sdk",
        hosted_tools="supported",
        structured_outputs="supported",
        context_window_tokens=None,
        cost_tier="premium",
        stability="high",
        pricing=None,
        notes=(
            "Best native fit for the OpenAI Agents SDK execution model.",
            "Set explicit pricing when using this model in production cost reports.",
        ),
    ),
    ("openai", "gpt-4.1-mini"): ModelCapabilityProfile(
        provider="openai",
        model="gpt-4.1-mini",
        display_name="OpenAI GPT-4.1 mini",
        transport="native",
        tool_strategy="native",
        native_tools="supported",
        function_tools="supported",
        filesystem="native_agents_sdk",
        compaction="native_agents_sdk",
        hosted_tools="supported",
        structured_outputs="supported",
        context_window_tokens=1_047_576,
        cost_tier="low",
        stability="high",
        pricing=ModelPricing(
            input_usd_per_million_tokens=0.40,
            output_usd_per_million_tokens=1.60,
            source_url=OPENAI_PRICING_URL,
        ),
    ),
    ("openai", "gpt-4o-mini"): ModelCapabilityProfile(
        provider="openai",
        model="gpt-4o-mini",
        display_name="OpenAI GPT-4o mini",
        transport="native",
        tool_strategy="native",
        native_tools="supported",
        function_tools="supported",
        filesystem="native_agents_sdk",
        compaction="native_agents_sdk",
        hosted_tools="supported",
        structured_outputs="supported",
        context_window_tokens=128_000,
        cost_tier="low",
        stability="high",
        pricing=ModelPricing(
            input_usd_per_million_tokens=0.15,
            output_usd_per_million_tokens=0.60,
            source_url=OPENAI_PRICING_URL,
        ),
    ),
    ("deepseek", "deepseek-v4-flash"): ModelCapabilityProfile(
        provider="deepseek",
        model="deepseek-v4-flash",
        display_name="DeepSeek V4 Flash",
        transport="chat_completions",
        tool_strategy="compat_functions",
        native_tools="unsupported",
        function_tools="openai_compatible",
        filesystem="platform_emulated",
        compaction="platform_memory",
        hosted_tools="unsupported",
        structured_outputs="model_dependent",
        context_window_tokens=None,
        cost_tier="very_low",
        stability="medium",
        pricing=ModelPricing(
            input_usd_per_million_tokens=0.14,
            output_usd_per_million_tokens=0.28,
            source_url=DEEPSEEK_PRICING_URL,
        ),
        notes=(
            "Works through Chat Completions compatibility and platform-owned tools.",
            "Does not support OpenAI Responses native filesystem, compaction, or hosted tools.",
        ),
    ),
    ("deepseek", "deepseek-chat"): ModelCapabilityProfile(
        provider="deepseek",
        model="deepseek-chat",
        display_name="DeepSeek Chat",
        transport="chat_completions",
        tool_strategy="compat_functions",
        native_tools="unsupported",
        function_tools="openai_compatible",
        filesystem="platform_emulated",
        compaction="platform_memory",
        hosted_tools="unsupported",
        structured_outputs="model_dependent",
        context_window_tokens=None,
        cost_tier="very_low",
        stability="medium",
        pricing=ModelPricing(
            input_usd_per_million_tokens=0.27,
            output_usd_per_million_tokens=1.10,
            source_url=DEEPSEEK_PRICING_URL,
        ),
    ),
    ("dashscope", "qwen-plus"): ModelCapabilityProfile(
        provider="dashscope",
        model="qwen-plus",
        display_name="Alibaba DashScope Qwen Plus",
        transport="chat_completions",
        tool_strategy="compat_functions",
        native_tools="unsupported",
        function_tools="openai_compatible",
        filesystem="platform_emulated",
        compaction="platform_memory",
        hosted_tools="unsupported",
        structured_outputs="model_dependent",
        context_window_tokens=None,
        cost_tier="unknown",
        stability="medium",
        pricing=None,
        notes=("Configure project-specific pricing before relying on cost reports.",),
    ),
}


def list_model_profiles(provider: str | None = None) -> list[ModelCapabilityProfile]:
    normalized_provider = _normalize(provider) if provider else None
    profiles = sorted(
        MODEL_CAPABILITY_PROFILES.values(),
        key=lambda profile: (profile.provider, profile.model),
    )
    if normalized_provider is None:
        return profiles
    return [profile for profile in profiles if profile.provider == normalized_provider]


def get_model_profile(provider: str, model: str) -> ModelCapabilityProfile | None:
    return MODEL_CAPABILITY_PROFILES.get((_normalize(provider), _normalize(model)))


def get_model_pricing(provider: str, model: str) -> ModelPricing | None:
    profile = get_model_profile(provider, model)
    return profile.pricing if profile else None


def default_pricing_table() -> dict[tuple[str, str], ModelPricing]:
    return {
        key: profile.pricing
        for key, profile in MODEL_CAPABILITY_PROFILES.items()
        if profile.pricing is not None
    }


def _normalize(value: str) -> str:
    return value.strip().lower()
