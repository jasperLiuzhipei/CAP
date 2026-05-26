from __future__ import annotations

import pytest

from copilot_agent.model_config import (
    PROVIDER_SPECS,
    ResolvedModelConfig,
    _env_bool,
    provider_choices,
    resolve_model_config,
)


def test_deepseek_defaults_to_compat_function_tools() -> None:
    config = resolve_model_config(provider="deepseek", require_api_key=False)

    assert config.transport == "chat_completions"
    assert config.tool_strategy == "compat_functions"
    assert config.model_label == "deepseek:deepseek-v4-flash"
    assert config.public_dict()["tool_strategy"] == "compat_functions"
    assert "api_key=missing" in config.safe_summary()


def test_provider_tool_strategy_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_TOOL_STRATEGY", "shell_only")

    config = resolve_model_config(provider="deepseek", require_api_key=False)

    assert config.tool_strategy == "shell_only"


def test_chat_completions_rejects_native_tools() -> None:
    with pytest.raises(ValueError, match="cannot use native"):
        resolve_model_config(
            provider="deepseek",
            tool_strategy="native",
            require_api_key=False,
        )


def test_provider_aliases_and_choices() -> None:
    assert "deepseek" in provider_choices()
    assert PROVIDER_SPECS["openai"].prefix == "OPENAI"
    assert resolve_model_config(provider="qwen", require_api_key=False).provider == "dashscope"
    assert (
        resolve_model_config(provider="volcano", model="m", require_api_key=False).provider
        == "ark"
    )
    assert (
        resolve_model_config(
            provider="openai-compatible",
            model="m",
            base_url="https://example.test/v1",
            require_api_key=False,
        ).provider
        == "custom"
    )


def test_env_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOOL_VALUE", raising=False)
    assert _env_bool("BOOL_VALUE", default=True)

    monkeypatch.setenv("BOOL_VALUE", "no")
    assert not _env_bool("BOOL_VALUE", default=True)

    monkeypatch.setenv("BOOL_VALUE", "enabled")
    assert _env_bool("BOOL_VALUE", default=False)

    monkeypatch.setenv("BOOL_VALUE", "maybe")
    with pytest.raises(ValueError, match="must be a boolean"):
        _env_bool("BOOL_VALUE", default=False)


def test_resolution_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="Unsupported model provider"):
        resolve_model_config(provider="missing", require_api_key=False)

    with pytest.raises(ValueError, match="Model is required"):
        resolve_model_config(provider="ark", require_api_key=False)

    with pytest.raises(ValueError, match="COPILOT_MODEL_TRANSPORT"):
        resolve_model_config(provider="deepseek", transport="bad", require_api_key=False)

    with pytest.raises(ValueError, match="COPILOT_TOOL_STRATEGY"):
        resolve_model_config(provider="deepseek", tool_strategy="bad", require_api_key=False)

    with pytest.raises(ValueError, match="requires COPILOT_TOOL_STRATEGY"):
        resolve_model_config(provider="openai", tool_strategy="shell_only", require_api_key=False)

    monkeypatch.delenv("CUSTOM_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="requires a base URL"):
        resolve_model_config(provider="custom", model="m", base_url="", require_api_key=False)


def test_api_key_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPILOT_API_KEY", "generic")
    config = resolve_model_config(provider="deepseek")
    assert config.api_key == "generic"
    assert config.api_key_env == "COPILOT_API_KEY"

    monkeypatch.delenv("COPILOT_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="API key is missing"):
        resolve_model_config(provider="deepseek")


def test_resolved_model_config_summary() -> None:
    config = ResolvedModelConfig(
        provider="p",
        display_name="Provider",
        model="m",
        transport="chat_completions",
        tool_strategy="shell_only",
        api_key_env="KEY",
        api_key="secret",
    )

    assert "api_key=set" in config.safe_summary()
