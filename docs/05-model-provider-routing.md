# 多模型与 Provider 路由设计

## 设计目标

平台需要让用户和管理员配置多种大模型，同时让 agent runtime 只面对稳定的 model profile。模型路由层负责 provider 差异、能力检查、成本控制、fallback 和审计。

## 支持范围

| Provider 类型 | 示例 | 优先级 |
| --- | --- | --- |
| OpenAI Responses | GPT 系列、reasoning、hosted tools | P0 |
| OpenAI Chat Completions | 兼容旧模型和部分第三方 | P0 |
| OpenAI-compatible endpoint | OpenRouter、自建 proxy、vLLM gateway | P0 |
| LiteLLM adapter | 多 provider 聚合 | P1 |
| Any-LLM adapter | 多 provider 聚合 | P1 |
| Local model | Ollama、vLLM、本地 GPU | P1 |

## Model Registry

建议以 model profile 管理，而不是直接把 provider model id 暴露给每个 agent。

```json
{
  "id": "profile_code_strong",
  "display_name": "Code Strong",
  "provider": "openai",
  "model": "gpt-5.5",
  "api_shape": "responses",
  "capabilities": {
    "tool_calling": true,
    "structured_outputs": true,
    "multimodal_input": true,
    "hosted_web_search": true,
    "hosted_file_search": true,
    "computer_tool": true,
    "streaming": true,
    "usage_metrics": true
  },
  "defaults": {
    "reasoning_effort": "medium",
    "verbosity": "low",
    "parallel_tool_calls": true
  },
  "limits": {
    "max_input_tokens": 200000,
    "max_output_tokens": 16000
  },
  "cost_class": "premium",
  "status": "active"
}
```

## 能力矩阵

不同 provider 支持的功能不同。平台必须在 run 前检查。

| 能力 | 用途 | 不支持时处理 |
| --- | --- | --- |
| tool calling | function tools、MCP、shell approvals | 降级或拒绝该模型 |
| structured outputs | schema 输出、planner JSON | 改用支持 JSON schema 的模型 |
| hosted tools | web/file search、computer tool | 移除 hosted tool 或换模型 |
| multimodal input | 图片、PDF、截图 | 转文本或换模型 |
| streaming | 实时 UI | 切非 streaming 响应 |
| usage metrics | 成本统计 | 标记估算成本 |
| Responses API | 新工具面和状态管理 | 用 Chat Completions path |

## 路由策略

### Agent 级路由

| Agent | 推荐模型类型 |
| --- | --- |
| Triage | fast, cheap, tool-capable |
| Planner | strong reasoning, structured output |
| Workspace Explorer | fast, long context |
| Coder | strong code, tool calling |
| Reviewer | strong reasoning, low hallucination |
| Test Runner | cheap, diagnostic |
| Memory Curator | cheap, structured output, redaction safe |

### Run 级覆盖

用户或管理员可以对整个 run 设置：

- `quality=fast | balanced | best`
- `budget=max_cost`
- `latency=max_seconds`
- `provider_policy=openai_only | allow_third_party | local_only`
- `data_policy=zero_retention | standard`

### Fallback

Fallback 必须能力等价或更强。

示例：

```text
profile_code_strong:
  primary: openai/gpt-5.5
  fallback:
    - openai/gpt-5.4
    - openai-compatible/company-code-large
  required_capabilities:
    - tool_calling
    - structured_outputs
    - streaming
```

不允许 fallback 到缺少 required capability 的模型。

## OpenAI Agents SDK 集成

SDK 支持以下接入点：

- 在 `Agent(model=...)` 上设置单个 agent 的模型。
- 在 `RunConfig(model=...)` 上设置 run 默认模型。
- 在 `RunConfig(model_provider=...)` 上注入 provider。
- 使用 OpenAI-compatible client。
- 使用 `MultiProvider` 做 prefix-based routing。
- 使用 Any-LLM 或 LiteLLM adapter。

平台封装建议：

```python
def build_run_config(model_profile, sandbox_config, workflow_name):
    provider = model_router.resolve_provider(model_profile)
    return RunConfig(
        model=model_profile.model,
        model_provider=provider,
        sandbox=sandbox_config,
        workflow_name=workflow_name,
    )
```

## 成本和质量控制

每次 model call 记录：

- provider。
- model。
- agent name。
- run id。
- prompt tokens、completion tokens、reasoning tokens。
- latency。
- retry count。
- error code。
- cache hit。
- estimated cost。
- output quality signals。

质量闭环：

- 离线 golden task eval。
- patch 是否通过测试。
- reviewer risk score。
- 用户接受率。
- rollback rate。
- memory pollution rate。

## MVP 方案

- 先支持 OpenAI 默认 provider 和一个 OpenAI-compatible provider。
- model profile 存在数据库或 YAML。
- 每个 agent 绑定默认 profile。
- run 可以覆盖 quality tier。
- 先实现 capability check，不实现复杂自动 fallback。
- 对第三方 provider 默认禁用 hosted tools 和 strict structured output，直到验证通过。

