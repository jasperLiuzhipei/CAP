# Phase 2 API AI Run

## 目标

这一块把已经跑通的 CLI Copilot 闭环搬到 API + background worker 链路。

目标链路：

```text
FastAPI
  -> POST /projects
  -> POST /runs
  -> BackgroundRunWorker
  -> RunWorker
  -> run_phase_one()
  -> OpenAI Agents SDK SandboxAgent
  -> model provider + sandbox tools
  -> verification + artifacts + memory
  -> RunEvent timeline
```

这意味着平台不再只是命令行 demo，而是可以作为一个后端服务接收任务，并让 worker 异步和 AI 通信。

## 新增能力

### 1. API runtime config

`copilot_agent.api.main:app` 现在会读取 `.env`：

```bash
.venv/bin/uvicorn copilot_agent.api.main:app --reload
```

支持这些 API / worker 配置：

```env
COPILOT_API_DB_PATH=.copilot/control.sqlite
COPILOT_API_AUTO_START_WORKER=true

COPILOT_WORKER_TEST_CMD=python -m pytest tests
COPILOT_WORKER_MAX_TURNS=16
COPILOT_WORKER_OUTPUT_DIR=runs
COPILOT_WORKER_MEMORY_ENABLED=true
COPILOT_WORKER_HOST_VERIFY=true
COPILOT_WORKER_REQUIRE_API_KEY=true

COPILOT_SANDBOX_RUNTIME_ENABLED=true
COPILOT_SANDBOX_PYTHON=python3
```

查看当前 API runtime：

```bash
curl http://127.0.0.1:8000/api/v1/runtime/config
```

### 2. Run 创建时自动解析模型路由

`POST /runs` 现在不再强制要求手写 `model_provider`、`model`、`tool_strategy`。

优先级：

1. 请求体显式传入。
2. Project 的 `default_model_provider`。
3. `.env` 的 `COPILOT_MODEL_PROVIDER`。
4. provider 默认模型和工具策略。

这让 API 和 CLI 使用同一套模型配置逻辑。

## 真实 API AI run 流程

### 1. 启动 API

```bash
PYTHONPATH=src .venv/bin/uvicorn copilot_agent.api.main:app --reload
```

### 2. 确认 worker 已启动

如果 `.env` 设置了 `COPILOT_API_AUTO_START_WORKER=true`，这里应该返回 `running: true`：

```bash
curl http://127.0.0.1:8000/api/v1/worker/status
```

如果没有自动启动，可以手动启动：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/worker/start
```

### 3. 创建 project

```bash
curl -X POST http://127.0.0.1:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sample Repo",
    "repo_path": "/Users/jasperliuzp/my_python_project/copilot_agent/examples/sample_repo",
    "memory_path": "/Users/jasperliuzp/my_python_project/copilot_agent/examples/sample_repo/.copilot/memory.md",
    "default_model_provider": "deepseek"
  }'
```

返回里的 `id` 是后续的 `project_id`。

### 4. 创建 run

如果 worker 正在运行，创建 run 后会自动入队执行：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "<project_id>",
    "task": "Inspect the sample repo and run tests. Do not modify code unless tests fail."
  }'
```

返回里的 `id` 是 `run_id`。

### 5. 观察事件流

```bash
curl "http://127.0.0.1:8000/api/v1/runs/<run_id>/events/stream?follow=true"
```

典型事件包括：

- `run.queued`
- `run.started`
- `sandbox.runtime_checked`
- `verification.completed`
- `artifact.created`
- `run.completed`

`run.completed` 是最终事件。这样前端或 CLI 使用 `follow=true` 时，不会在 runtime、
verification、artifact 事件写完前提前停止。

### 6. 查看结果

```bash
curl http://127.0.0.1:8000/api/v1/runs/<run_id>
curl http://127.0.0.1:8000/api/v1/runs/<run_id>/events
curl http://127.0.0.1:8000/api/v1/runs/<run_id>/artifacts
```

如果 run 修改了代码，可以查看 diff：

```bash
curl http://127.0.0.1:8000/api/v1/runs/<run_id>/diff
```

## 为什么仍然符合 OpenAI Agents SDK 理念

API 和 background worker 不直接实现 agent loop。

它们只做产品控制面：

- 接收任务。
- 创建 queued run。
- 调度后台执行。
- 记录状态和事件。
- 保存 artifacts。

真正的智能体执行仍然在：

```text
RunWorker -> PhaseOneConfig -> run_phase_one() -> SandboxAgent -> Runner.run()
```

所以这仍然是 OpenAI Agents SDK 的 agent runtime，只是外面包了一层工程化 Copilot 平台。

## 当前边界

- 当前 worker 是进程内队列，服务重启后需要重新扫描 queued run。
- 当前事件流是基于 SQLite 轮询，不是 Redis pub/sub。
- 当前 API 还没有 Web UI。
- 当前审批策略还没有接进真实 sandbox tool execution，只是先有 control-plane 数据模型。

下一步建议做 Web UI 或更正式的 sandbox backend abstraction。
