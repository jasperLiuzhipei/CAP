# Phase 4C: CI and Model Capability Matrix

本阶段把两个工程化缺口补齐：

1. GitHub Actions CI，保证 PR 自动运行 lint、test 和 coverage gate。
2. 模型能力与价格 registry，避免 provider 能力散落在 prompt、文档和成本估算逻辑里。

## 为什么要做

Copilot 平台不是只跑一个模型。OpenAI 原生 Responses/Agents 能力、DeepSeek 的 Chat Completions 兼容能力、Qwen/火山等 provider 的工具稳定性和价格都不同。

如果没有统一的能力矩阵，系统会出现两个问题：

- UI 和 backend 无法解释“为什么这个模型不能用 native filesystem/hosted tools”。
- 成本估算只能靠硬编码，新增模型后容易返回 `pricing_unavailable`。

## 当前实现

新增 `copilot_agent.model_registry` 作为模型能力和价格的 source of truth。

每个模型 profile 包含：

- provider 和 model id。
- transport：`native` 或 `chat_completions`。
- tool strategy：`native`、`compat_functions` 或 `shell_only`。
- native tools、function tools、filesystem、compaction、hosted tools、structured outputs 能力。
- context window、cost tier、stability。
- 可选 token pricing。
- 产品说明 notes。

API 新增：

```text
GET /api/v1/models/capabilities
GET /api/v1/models/capabilities?provider=deepseek
```

返回结果可以直接供 Web UI、run 创建页面、模型选择器和成本面板使用。

## OpenAI Agents SDK 对齐

OpenAI 原生模型仍然走 SDK native route：

- transport: `native`
- tool strategy: `native`
- filesystem: `native_agents_sdk`
- compaction: `native_agents_sdk`
- hosted tools: `supported`

DeepSeek、Qwen、火山等 OpenAI-compatible provider 走平台兼容 route：

- transport: `chat_completions`
- tool strategy: `compat_functions`
- filesystem: `platform_emulated`
- compaction: `platform_memory`
- hosted tools: `unsupported`

也就是说，我们没有把非 OpenAI 模型伪装成完全原生 OpenAI 模型，而是在产品控制平面显式描述能力差异。

## 成本估算

`backend.observability.estimate_cost()` 现在从 model registry 读取 pricing。

如果 registry 中没有价格：

```text
pricing_source="pricing_unavailable"
```

如果 run 没有 usage：

```text
pricing_source="usage_unavailable"
```

价格只用于本地开发和展示估算，不应该作为财务结算来源。生产环境后续应支持项目级 override，例如：

```text
.copilot/pricing.json
organization pricing policy
provider billing export
```

## CI

新增 `.github/workflows/ci.yml`：

- pull request 自动触发。
- push 到 `main` 自动触发。
- Python 3.13。
- 安装 `.[dev]`。
- 运行 `ruff check src tests scripts`。
- 运行 `pytest tests --cov=src/copilot_agent --cov-report=term-missing`。

覆盖率门槛仍由 `pyproject.toml` 中的 coverage config 控制，目前是 95%。

## 后续

- Web UI 模型选择器读取 `/models/capabilities`。
- 支持项目级 pricing override。
- 给每次 run 记录 pricing table version。
- 增加 provider fallback policy，例如“优先低成本模型，但需要 native tools 时强制 OpenAI native”。
- 把 CI 扩展为 matrix：Python 3.10、3.11、3.12、3.13。
