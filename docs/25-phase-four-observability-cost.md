# Phase 4B Observability and Cost

本阶段把 Copilot 平台从“能安全执行”推进到“能被运营、调试和评估”。核心目标是：每次 run 都能回答它用了什么模型、花了多久、调用了哪些工具、哪里失败、token 和成本大概是多少。

## 设计原则

OpenAI Agents SDK 继续负责 agent runtime、模型调用和 sandbox tool loop。平台层在 SDK 外建立产品级可观测性：

- `RunEvent` 记录生命周期、verification、usage、artifact 和 policy 事件。
- `ToolCall` 记录工具名、策略动作、风险等级、审批状态、结果摘要和耗时字段。
- `RunMetrics` 从 run、events、tool calls、approvals 中派生。
- `RunTrace` 聚合工具轨迹和 timeline，给前端、调试和审计使用。
- 成本估算使用 provider/model 定价表；没有 usage 或定价时明确返回 unavailable。

这不是替代 OpenAI tracing。OpenAI tracing 更适合开发者调试 SDK 内部模型调用；Copilot metrics/trace 更适合产品控制平面、用户界面和审计报表。

## Metrics

新增 API：

```bash
curl http://127.0.0.1:8000/api/v1/runs/<run_id>/metrics
```

返回内容包括：

- `started_at`、`finished_at`、`duration_ms`
- `model_provider`、`model`、`tool_strategy`
- `sandbox_backend`
- `total_events`、`total_tool_calls`
- `approvals_required`、`approvals_pending`、`approvals_approved`、`approvals_rejected`
- `failed_reason`
- `token_usage`
- `cost_estimate`

`started_at` 来自 `run.started` 事件；`finished_at` 来自 `run.completed`、`run.failed` 或 `run.cancelled`。如果 run 已终止但没有终止事件，会退回 `RunRecord.updated_at`。

## Trace

新增 API：

```bash
curl http://127.0.0.1:8000/api/v1/runs/<run_id>/trace
```

返回内容包括：

- 工具调用轨迹：工具名、action、status、risk、reason、approval decision、脱敏参数、结果摘要。
- run event timeline：已有的 `RunEvent` 序列。

当前 tool trace 的耗时字段已在数据模型里保留。Phase 4B 主要记录 policy/approval 结果；后续如果接入执行前拦截器，可以把真实工具执行耗时写入同一字段。

## Token Usage

`PhaseOneReport` 新增 `model_usage` 字段。OpenAI Agents SDK run result 中如果存在 `result.context_wrapper.usage`，平台会抽取：

- `requests`
- `input_tokens`
- `output_tokens`
- `total_tokens`

这些数据会作为 `model.usage` 事件写入 timeline。对于 DeepSeek、千问、火山等 OpenAI-compatible provider，如果 SDK 或兼容接口没有稳定返回 usage，字段可以为空，metrics 会明确显示 usage unavailable。

## Cost Estimate

成本估算在 `backend/observability.py` 中完成：

- 有 usage 且 provider/model 在定价表中：返回 `input_cost_usd`、`output_cost_usd`、`total_cost_usd`。
- 有 usage 但没有定价：返回 `pricing_source="pricing_unavailable"`。
- 没有 usage：返回 `pricing_source="usage_unavailable"`。

当前内置定价表用于本地开发和演示，后续应该升级为项目级配置或 provider capability matrix，不应该把它当作长期精确定价来源。

## API Contract

```text
GET /api/v1/runs/{run_id}/metrics
GET /api/v1/runs/{run_id}/trace
GET /api/v1/runs/{run_id}/events
GET /api/v1/runs/{run_id}/tool-calls
```

这四个 API 共同构成 run replay 的基础：metrics 看总览，trace 看工具轨迹，events 看 timeline，tool-calls 看审批与工具详情。

## 下一步

- 把 metrics 和 trace 接入正式 Web 控制台。
- 把模型定价迁移到 provider capability matrix 或项目级配置。
- 记录 sandbox 命令真实耗时和资源使用。
- 支持 run retry/cancel/resume 的可观测字段。
- 为 GitHub workflow 集成记录 branch、commit、push、PR、CI 状态和耗时。
