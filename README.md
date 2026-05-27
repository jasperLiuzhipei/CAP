# Copilot Agent Platform

这是一个工程化 Copilot 平台的产品与技术规划工作区。当前目标是基于 OpenAI Agents SDK 设计并逐步实现一个具备 workspace 沙箱、memory 管理、多模型路由、工具审批和企业治理能力的 agentic copilot。

## 目录

```text
.
├── docs/                    # 产品与技术设计文档
├── examples/                # 本地测试样例仓库
└── src/                     # Phase 1 Copilot CLI 原型
```

## 快速入口

- [文档索引](docs/README.md)
- [产品需求设计](docs/01-product-requirements.md)
- [系统架构设计](docs/02-system-architecture.md)
- [Workspace 沙箱设计](docs/03-workspace-sandbox.md)
- [Memory 管理设计](docs/04-memory-management.md)
- [实现蓝图](docs/10-implementation-blueprint.md)
- [Phase 1 Local Sandbox CLI](docs/11-phase-one-local-cli.md)
- [Model Provider Env 设计](docs/12-model-provider-env-design.md)
- [Phase 2 Backend Control Plane Foundation](docs/13-phase-two-backend-foundation.md)
- [Phase 2 API Layer](docs/14-phase-two-api-layer.md)
- [Phase 2 Run Worker](docs/15-phase-two-run-worker.md)
- [Phase 2 Run Events and Timeline](docs/16-phase-two-run-events.md)
- [Phase 2 Async Worker and Live Events](docs/17-phase-two-async-worker.md)
- [Phase 2 Sandbox Runtime Provisioning](docs/18-phase-two-sandbox-runtime.md)
- [Phase 2 API AI Run](docs/19-phase-two-api-ai-run.md)
- [Phase 2 Web UI and Sandbox Backends](docs/20-phase-two-web-ui-sandbox-backends.md)
- [Phase 3 Sandbox Backend Protocol](docs/21-phase-three-sandbox-backend-protocol.md)
- [上游源码阅读笔记](docs/09-openai-agents-reading-notes.md)

## 当前状态

- 已建立第一版产品需求、架构、安全、memory、多模型和路线图文档。
- 已创建阶段一最小 CLI skeleton：`copilot-agent run --repo ... --task ...`。
- 已验证 DeepSeek 兼容 API 可运行 sample repo 修复任务，并新增函数工具版 `apply_patch` 兼容层，让 Chat Completions provider 更接近 OpenAI 原生 patch 流程。
- 已补齐本地 Copilot MVP 闭环：项目初始化、project memory、历史 run 查看、sandbox diff 审计、手动应用 run patch。
- 已开始第二阶段后端控制平面：Project、Run、ToolCall、Approval、Artifact、SQLite store、工具策略和 Phase 1 report 入库。
- 已补齐第二阶段 API 层：FastAPI app、Project/Run/Approval/Artifact routes、diff 查询和 API 集成测试。
- 已接通第二阶段本地 run worker：API 创建 queued run 后，可触发 `run_phase_one()` 执行并把结果写回原 run。
- 已补齐第二阶段 run timeline：RunEvent 持久化、events API、SSE 格式事件流和关键生命周期事件。
- 已补齐第二阶段后台 worker：可启动/停止后台队列，自动消费 queued run，并支持 `follow=true` 实时事件流。
- 已补齐第二阶段 sandbox runtime provisioning：为 Python runtime 增加 path grants、health check、pytest sandbox-safe 命令归一化，解决 macOS sandbox 中 `encodings` 缺失导致 pytest 不稳定的问题。
- 已补齐 API 级 AI run 入口：`copilot_agent.api.main:app` 读取 `.env`，可自动启动后台 worker，并让 `POST /runs` 复用 project 或 env 的默认模型路由。
- 已补齐轻量 Web UI 控制台和 sandbox backend registry：浏览器可创建 project/run、查看 timeline/artifacts/diff，并暴露 `unix_local` 与 planned `docker` backend。
- 已开始第三阶段 sandbox backend 抽象：定义 `SandboxBackend` protocol，并把现有 OpenAI Agents SDK `UnixLocalSandboxClient` 收口到 `UnixLocalSandboxBackend` adapter。

> Note: `openai-agents-python/` 是本地阅读上游源码时使用的可选目录，不提交到本仓库。需要阅读源码时可单独 clone `https://github.com/openai/openai-agents-python`。

## Phase 1 Dry Run

```bash
PYTHONPATH=src python3 -m copilot_agent run \
  --repo examples/sample_repo \
  --task "Fix the discount calculation bug and run tests." \
  --test-cmd "python -m pytest" \
  --dry-run
```

## Local API Key

真实运行前可以把 key 放进本地 `.env`：

```bash
cp .env.example .env
```

然后编辑 `.env`，例如低成本 DeepSeek 开发配置：

```env
COPILOT_MODEL_PROVIDER=deepseek
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=<your-deepseek-api-key>
```

`.env` 已经被 `.gitignore` 忽略。

## Local Copilot MVP

初始化目标仓库的 Copilot 元数据：

```bash
copilot-agent init --repo examples/sample_repo
```

运行任务时，如果目标仓库存在 `.copilot/memory.md`，CLI 会自动把它作为项目记忆读入 prompt，并在运行后追加简短记忆。也可以显式开启：

```bash
copilot-agent run \
  --repo examples/sample_repo \
  --task "Fix the discount calculation bug and run tests." \
  --test-cmd "python -m pytest" \
  --memory \
  --host-verify
```

查看和应用沙箱结果：

```bash
copilot-agent runs
copilot-agent show-run --run run_YYYYMMDD_HHMMSS_xxxxxx --diff --final
copilot-agent apply-run --run run_YYYYMMDD_HHMMSS_xxxxxx --check
copilot-agent apply-run --run run_YYYYMMDD_HHMMSS_xxxxxx
```

`apply-run` 会先执行 `git apply --check`，通过后才把保存的 sandbox diff 应用回真实仓库。

CLI 默认会开启 sandbox runtime provisioning：如果验证命令里出现宿主机绝对路径 Python，例如 `.venv/bin/python -m pytest tests`，sandbox 会自动改写为 sandbox-safe Python 命令，并给 Python 标准库和 venv roots 增加只读授权。

如果仍然希望双保险，可以继续使用 `--host-verify`。它会把 sandbox diff 应用到一个临时仓库副本，再在沙箱外运行原始验证命令，不会直接修改真实仓库。

## Local API

启动第二阶段本地 API：

```bash
PYTHONPATH=src .venv/bin/uvicorn copilot_agent.api.main:app --reload
```

默认数据库路径是当前目录下的 `.copilot/control.sqlite`。API 文档入口是 `http://127.0.0.1:8000/docs`。
Web UI 控制台入口是 `http://127.0.0.1:8000/` 或 `http://127.0.0.1:8000/app`。

如果希望 API 创建 run 后自动执行，可以在 `.env` 中配置：

```env
COPILOT_API_AUTO_START_WORKER=true
COPILOT_WORKER_TEST_CMD=python -m pytest tests
COPILOT_WORKER_HOST_VERIFY=true
COPILOT_WORKER_MEMORY_ENABLED=true
```

查看当前 API runtime：

```bash
curl http://127.0.0.1:8000/api/v1/runtime/config
```

本地触发一次 queued run 执行：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/runs/<run_id>/execute \
  -H "Content-Type: application/json" \
  -d '{"test_cmd":"python -m pytest tests","host_verify":true}'
```

查看 run timeline：

```bash
curl http://127.0.0.1:8000/api/v1/runs/<run_id>/events
curl http://127.0.0.1:8000/api/v1/runs/<run_id>/events/stream
```

启动后台 worker，让新建 queued run 自动执行：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/worker/start
curl "http://127.0.0.1:8000/api/v1/runs/<run_id>/events/stream?follow=true"
curl -X POST http://127.0.0.1:8000/api/v1/worker/stop
```

完整 API 级 AI run 流程见 [Phase 2 API AI Run](docs/19-phase-two-api-ai-run.md)。
