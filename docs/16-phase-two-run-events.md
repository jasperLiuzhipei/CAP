# Phase 2 Run Events and Timeline

## 目标

这一块补齐 run timeline。之前后端已经能创建 run、执行 run、保存 artifact，但用户还缺少一个清晰的问题答案：

```text
这次 Copilot run 到底发生了什么？
```

所以我们新增 `RunEvent`，把 run 生命周期中的关键节点持久化下来，供 API、前端、审计和后续 SSE 实时流使用。

## 新增能力

| 能力 | 说明 |
| --- | --- |
| `RunEvent` 领域模型 | 记录 run 的事件类型、payload 和时间 |
| `run_events` SQLite 表 | 持久化 timeline |
| `CopilotBackendService.record_event` | service 层统一写事件 |
| `GET /api/v1/runs/{run_id}/events` | 返回已保存事件列表 |
| `GET /api/v1/runs/{run_id}/events/stream` | 以 SSE 格式输出已保存事件 |

## 当前事件类型

```text
run.queued
run.started
run.needs_approval
run.completed
run.failed
run.cancelled
tool.reviewed
approval.required
approval.decided
sandbox.runtime_checked
verification.completed
artifact.created
```

## 写入时机

| 代码路径 | 事件 |
| --- | --- |
| `queue_run` | `run.queued` |
| `start_run` | `run.started` |
| `finish_run(..., succeeded)` | `run.completed` |
| `finish_run(..., failed)` | `run.failed` |
| `record_tool_decision` | `tool.reviewed` |
| `record_tool_decision` 发现需要审批 | `approval.required` + `run.needs_approval` |
| `decide_approval` | `approval.decided` |
| `_record_report_runtime_events` | `sandbox.runtime_checked` + `verification.completed` |
| `_record_report_artifacts` | `artifact.created` |
| `ingest_phase_one_report` finalization | `run.completed` 或 `run.failed` |

`ingest_phase_one_report` 会把最终状态事件放在最后。这样 `events/stream?follow=true`
在看到 terminal run status 前，已经可以先收到 runtime、verification 和 artifact 事件，
避免前端 timeline 提前结束。

## API 示例

查询事件列表：

```bash
curl http://127.0.0.1:8000/api/v1/runs/<run_id>/events
```

SSE 格式输出事件：

```bash
curl http://127.0.0.1:8000/api/v1/runs/<run_id>/events/stream
```

当前 `/events/stream` 会把已经持久化的事件按 SSE 格式输出，方便前端先接入 timeline。后续真正实时化时，可以继续复用同一个 `RunEvent` 模型和 `run_events` 表，只需要让 worker 边执行边推送。

## 和 OpenAI Agents SDK 的关系

OpenAI Agents SDK 的 tracing 更适合开发者调试 agent loop、model call 和 tool call。我们的 `RunEvent` 更偏产品控制平面：

| OpenAI trace | Copilot RunEvent |
| --- | --- |
| 调试模型和工具执行细节 | 给用户展示 run timeline |
| 依赖 OpenAI tracing 能力 | 存在我们自己的数据库 |
| 面向开发者可观测性 | 面向产品 UI、审批、审计 |
| 描述 SDK runtime 内部过程 | 描述平台状态变化和用户可理解事件 |

两者不是替代关系。真正生产化时，timeline 可以链接到 OpenAI trace id，让用户看摘要，开发者看深度 trace。

## 本阶段验收

测试覆盖：

- SQLite 可以保存和按写入顺序读取 `RunEvent`。
- service 在 queue/start/finish/tool review/approval/artifact 节点写事件。
- worker 执行 queued run 后生成 started/runtime/verification/artifact/completed timeline。
- `run.completed` 或 `run.failed` 是 report ingest 的最后一个事件。
- API 可以返回 JSON events。
- API 可以返回 SSE 格式事件流。
- 缺失 run 返回 404。

验证命令：

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest tests --cov=copilot_agent --cov-report=term-missing
```

## 下一步

第五块已实现后台异步 worker 和 `follow=true` 事件流。sandbox runtime/provisioning 第一版也已补齐，详见 [Phase 2 Sandbox Runtime Provisioning](18-phase-two-sandbox-runtime.md)。
