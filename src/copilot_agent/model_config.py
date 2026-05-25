from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


ModelTransport = Literal["native", "chat_completions"]

DEFAULT_PROVIDER = "openai"
DEFAULT_OPENAI_MODEL = "gpt-5.5"


@dataclass(frozen=True)
class ProviderSpec:
    """Static defaults for a model provider supported by the platform."""

    provider: str
    display_name: str
    transport: ModelTransport
    api_key_env: str
    default_model: str | None = None
    base_url: str | None = None
    env_prefix: str | None = None

    @property
    def prefix(self) -> str:
        return self.env_prefix or self.provider.upper()


@dataclass(frozen=True)
class ResolvedModelConfig:
    """Runtime-safe model route after merging CLI flags, .env, and provider defaults."""

    provider: str
    display_name: str
    model: str
    transport: ModelTransport
    api_key_env: str
    api_key: str | None
    base_url: str | None = None
    tracing_disabled: bool = True

    @property
    def model_label(self) -> str:
        return f"{self.provider}:{self.model}"

    def safe_summary(self) -> str:
        base_url = self.base_url or "(provider default)"
        key_state = "set" if self.api_key else "missing"
        return (
            f"{self.display_name} model={self.model} transport={self.transport} "
            f"base_url={base_url} api_key_env={self.api_key_env} api_key={key_state}"
        )

    def public_dict(self) -> dict[str, str | bool | None]:
        return {
            "provider": self.provider,
            "display_name": self.display_name,
            "model": self.model,
            "transport": self.transport,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "tracing_disabled": self.tracing_disabled,
        }


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        provider="openai",
        display_name="OpenAI",
        transport="native",
        api_key_env="OPENAI_API_KEY",
        default_model=DEFAULT_OPENAI_MODEL,
    ),
    "deepseek": ProviderSpec(
        provider="deepseek",
        display_name="DeepSeek",
        transport="chat_completions",
        api_key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
    ),
    "dashscope": ProviderSpec(
        provider="dashscope",
        display_name="Alibaba DashScope",
        transport="chat_completions",
        api_key_env="DASHSCOPE_API_KEY",
        default_model="qwen-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    "ark": ProviderSpec(
        provider="ark",
        display_name="Volcengine Ark",
        transport="chat_completions",
        api_key_env="ARK_API_KEY",
        default_model=None,
        base_url="https://ark.cn-beijing.volces.com/api/v3",
    ),
    "custom": ProviderSpec(
        provider="custom",
        display_name="Custom OpenAI-compatible",
        transport="chat_completions",
        api_key_env="COPILOT_API_KEY",
        default_model=None,
        base_url=None,
    ),
}


def provider_choices() -> tuple[str, ...]:
    return tuple(PROVIDER_SPECS)


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    value = raw_value.strip().lower()
    if value in {"1", "true", "yes", "y", "on", "enabled", "enable"}:
        return True
    if value in {"0", "false", "no", "n", "off", "disabled", "disable"}:
        return False
    raise ValueError(
        f"{name} must be a boolean value such as true/false, yes/no, or 1/0."
    )


def _normalize_provider(provider: str | None) -> str:
    normalized = (provider or DEFAULT_PROVIDER).strip().lower().replace("-", "_")
    aliases = {
        "aliyun": "dashscope",
        "qwen": "dashscope",
        "volcengine": "ark",
        "volcano": "ark",
        "bytedance": "ark",
        "openai_compatible": "custom",
    }
    return aliases.get(normalized, normalized)


def _normalize_transport(transport: str | None, default: ModelTransport) -> ModelTransport:
    if not transport:
        return default

    normalized = transport.strip().lower().replace("-", "_")
    if normalized in {"native", "responses", "openai_native"}:
        return "native"
    if normalized in {"chat", "chat_completions", "chat_completions_api"}:
        return "chat_completions"
    raise ValueError(
        "COPILOT_MODEL_TRANSPORT must be `native` or `chat_completions`."
    )


def resolve_model_config(
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
    transport: str | None = None,
    require_api_key: bool = True,
) -> ResolvedModelConfig:
    """Resolve the active model route from CLI values, .env, and provider defaults."""

    provider_id = _normalize_provider(provider or os.getenv("COPILOT_MODEL_PROVIDER"))
    if provider_id not in PROVIDER_SPECS:
        supported = ", ".join(provider_choices())
        raise ValueError(
            f"Unsupported model provider `{provider_id}`. Choose one of: {supported}."
        )

    spec = PROVIDER_SPECS[provider_id]
    prefix = spec.prefix
    resolved_model = (
        model
        or os.getenv("COPILOT_MODEL")
        or os.getenv(f"{prefix}_MODEL")
        or spec.default_model
    )
    if not resolved_model:
        raise ValueError(
            f"Model is required for provider `{provider_id}`. Set COPILOT_MODEL "
            f"or {prefix}_MODEL in `.env`, or pass --model."
        )

    resolved_base_url = (
        base_url
        or os.getenv("COPILOT_BASE_URL")
        or os.getenv(f"{prefix}_BASE_URL")
        or spec.base_url
    )
    resolved_transport = _normalize_transport(
        transport or os.getenv("COPILOT_MODEL_TRANSPORT"),
        spec.transport,
    )
    resolved_api_key_env = (
        api_key_env
        or os.getenv("COPILOT_API_KEY_ENV")
        or spec.api_key_env
    )

    generic_key = os.getenv("COPILOT_API_KEY")
    provider_key = os.getenv(resolved_api_key_env)
    resolved_api_key = generic_key or provider_key
    resolved_api_key_env_label = "COPILOT_API_KEY" if generic_key else resolved_api_key_env

    if resolved_transport == "chat_completions" and provider_id != "openai" and not resolved_base_url:
        raise ValueError(
            f"Provider `{provider_id}` uses Chat Completions compatibility and requires a base URL."
        )

    if require_api_key and not resolved_api_key:
        raise RuntimeError(
            f"API key is missing for provider `{provider_id}`. Put it in `.env` as "
            f"{resolved_api_key_env}=... or use the generic COPILOT_API_KEY=... override."
        )

    return ResolvedModelConfig(
        provider=provider_id,
        display_name=spec.display_name,
        model=resolved_model,
        transport=resolved_transport,
        api_key_env=resolved_api_key_env_label,
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        tracing_disabled=_env_bool("COPILOT_TRACING_DISABLED", default=True),
    )
