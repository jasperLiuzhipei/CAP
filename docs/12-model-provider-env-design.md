# Model Provider Env 设计

本文档定义 Copilot 平台的模型密钥与路由配置。目标是兼容 OpenAI、DeepSeek、阿里百炼 DashScope、火山方舟 Ark，以及任意 OpenAI-compatible provider，同时尽量保持 `openai-agents-python` 的原生使用方式。

## 设计原则

- OpenAI 默认保持原生：`provider=openai` 时优先传模型字符串给 Agents SDK，让 SDK 自己选择原生 OpenAI provider 和 Responses 能力。
- 非 OpenAI 走兼容模型对象：DeepSeek、DashScope、Ark、custom provider 使用 SDK 官方推荐的 `AsyncOpenAI(base_url=..., api_key=...)` + `OpenAIChatCompletionsModel(...)`。
- 工具能力分层适配：OpenAI 使用原生 sandbox tools；Chat Completions provider 默认使用函数工具兼容层，必要时可降级为 shell-only。
- `.env` 只表达部署配置，不写业务策略：provider、model、base URL、key env 是配置；agent prompt、sandbox policy、memory policy 不放在 `.env`。
- 支持两级密钥：正常使用 provider-specific key，例如 `DEEPSEEK_API_KEY`；自动化或临时实验可以用通用 `COPILOT_API_KEY` 覆盖。
- 不把真实 key 写进代码、文档、报告：运行报告只保存 provider、model、transport、base_url 和 key env 名，不保存 key 内容。

## 配置分层

优先级从高到低：

1. CLI 参数：`--provider`、`--model`、`--base-url`、`--api-key-env`、`--model-transport`、`--tool-strategy`。
2. 平台级 `.env`：`COPILOT_MODEL_PROVIDER`、`COPILOT_MODEL`、`COPILOT_BASE_URL`、`COPILOT_API_KEY_ENV`、`COPILOT_MODEL_TRANSPORT`、`COPILOT_TOOL_STRATEGY`。
3. 供应商级 `.env`：`OPENAI_MODEL`、`DEEPSEEK_MODEL`、`DEEPSEEK_TOOL_STRATEGY`、`DASHSCOPE_MODEL`、`ARK_MODEL` 等。
4. 内置 provider 默认值：例如 DeepSeek 默认 `deepseek-v4-flash`，DashScope 默认 `qwen-plus`。

密钥解析优先级：

1. `COPILOT_API_KEY`：临时覆盖所有 provider。
2. `COPILOT_API_KEY_ENV` 指向的 env var。
3. provider 默认 key env：`OPENAI_API_KEY`、`DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY`、`ARK_API_KEY`。

## Provider 矩阵

| provider | 默认 transport | 默认 tool strategy | 默认 key env | 默认 model | 默认 base URL |
| --- | --- | --- | --- | --- | --- |
| `openai` | `native` | `native` | `OPENAI_API_KEY` | `gpt-5.5` | SDK 默认 |
| `deepseek` | `chat_completions` | `compat_functions` | `DEEPSEEK_API_KEY` | `deepseek-v4-flash` | `https://api.deepseek.com` |
| `dashscope` | `chat_completions` | `compat_functions` | `DASHSCOPE_API_KEY` | `qwen-plus` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `ark` | `chat_completions` | `compat_functions` | `ARK_API_KEY` | 必填 | `https://ark.cn-beijing.volces.com/api/v3` |
| `custom` | `chat_completions` | `compat_functions` | `COPILOT_API_KEY` | 必填 | 必填 |

Ark 的模型值经常是控制台里的 endpoint id 或已部署模型 id，所以我们不在代码里硬编码一个默认模型，避免“看起来能跑、实际打错 endpoint”的隐患。

## 推荐 `.env`

低成本开发默认：

```env
COPILOT_MODEL_PROVIDER=deepseek
COPILOT_TRACING_DISABLED=true
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=<your-deepseek-api-key>
```

OpenAI 原生验证：

```env
COPILOT_MODEL_PROVIDER=openai
COPILOT_TRACING_DISABLED=false
OPENAI_MODEL=gpt-5.5
OPENAI_API_KEY=<your-openai-api-key>
```

DashScope 千问：

```env
COPILOT_MODEL_PROVIDER=dashscope
DASHSCOPE_MODEL=qwen-plus
DASHSCOPE_API_KEY=<your-dashscope-api-key>
```

火山方舟：

```env
COPILOT_MODEL_PROVIDER=ark
ARK_MODEL=your-ark-endpoint-or-model-id
ARK_API_KEY=your-ark-api-key
```

## 在代码中的落点

`src/copilot_agent/model_config.py` 是唯一负责 provider 注册、`.env` 解析和 key 校验的模块。业务代码不直接读取 `OPENAI_API_KEY`、`DEEPSEEK_API_KEY` 等供应商变量。

`phase_one.py` 只接收 `ResolvedModelConfig`：

- `transport=native`：把 `model` 字符串传给 `SandboxAgent`，保持 Agents SDK 原生路径。
- `transport=chat_completions`：构建 `OpenAIChatCompletionsModel`，把兼容 provider 作为具体 model object 交给 `Agent.model`。

`COPILOT_TOOL_STRATEGY` 控制沙箱工具如何暴露给模型：

- `native`：只给 OpenAI 原生 Responses 路径使用，保留 SDK 默认 `Filesystem`、`Shell`、`Compaction`。
- `compat_functions`：给 DeepSeek、千问、方舟等 Chat Completions provider 使用普通函数工具版 `apply_patch`，再配合 `Shell`，尽量接近原生可审计 patch 流程。
- `shell_only`：最低兼容模式，只暴露 shell。适合某个 provider 的 function calling 不稳定时临时降级。

如果只想调整某个 provider，优先使用供应商级变量，例如 `DEEPSEEK_TOOL_STRATEGY=shell_only`；`COPILOT_TOOL_STRATEGY` 更适合临时全局覆盖。

这个边界后续可以继续扩展：

- 增加 `model_router`，按任务类型选择便宜模型或强模型。
- 增加 `provider_capabilities`，记录 tool calling、structured output、vision、context window 等能力差异。
- 增加企业密钥托管，把 `.env` 替换为 Vault/KMS，但不改变 agent 层代码。
