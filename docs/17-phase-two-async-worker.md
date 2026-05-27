# Phase 2 Async Worker and Live Events

## 目标

这一块把本地 worker 从“手动同步执行”推进到“后台异步消费 queued run”。

之前的能力：

- `POST /api/v1/runs/{run_id}/execute` 会同步等待 run 执行完成。
- `/events/stream` 只能一次性输出已经保存的事件。

现在新增：

- `BackgroundRunWorker`：进程内后台队列。
- `/api/v1/worker/start`：启动后台 worker，并自动扫描已有 queued run。
- `/api/v1/worker/stop`：停止后台 worker。
- `/api/v1/worker/status`：查看后台 worker 状态。
- `/api/v1/runs/{run_id}/dispatch`：把指定 run 放进后台队列。
- `POST /api/v1/runs`：如果后台 worker 正在运行，新建 run 会自动入队。
- `/events/stream?follow=true`：持续轮询新增事件，直到 run 完成、失败、取消或空闲超时。

## 执行流程

```text
POST /api/v1/worker/start
        |
        v
BackgroundRunWorker running
        |
        v
POST /api/v1/runs
        |
        v
RunRecord(status="queued") -> enqueue
        |
        v
RunWorker.execute_run(...)
        |
        v
run_phase_one() / OpenAI Agents SDK runtime
        |
        v
RunRecord(status="succeeded" / "failed")
        |
        v
RunEvent timeline + Artifact + diff
```

## API 示例

启动后台 worker：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/worker/start
```

查看 worker 状态：

```bash
curl http://127.0.0.1:8000/api/v1/worker/status
```

手动 dispatch 一个 queued run：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/runs/<run_id>/dispatch \
  -H "Content-Type: application/json" \
  -d '{"test_cmd":"python -m pytest tests","host_verify":true}'
```

订阅 run timeline：

```bash
curl "http://127.0.0.1:8000/api/v1/runs/<run_id>/events/stream?follow=true"
```

停止后台 worker：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/worker/stop
```

## 和 OpenAI Agents SDK 的关系

`BackgroundRunWorker` 仍然不负责 agent loop。它只负责把平台层 queued run 送给 `RunWorker`，再由 `RunWorker` 构造 `PhaseOneConfig` 并调用 `run_phase_one()`。

真正执行链路仍然是：

```text
run_phase_one()
  -> SandboxAgent
  -> Runner.run
  -> OpenAI native model or OpenAI-compatible Chat Completions model
  -> sandbox tools / compat function tools
```

也就是说，后台 worker 做的是产品级 orchestration，不是替代 `openai-agents-python`。

## 当前限制

- 这是单进程内存队列，适合本地 MVP。
- 进程重启后，队列本身不保留，但 queued run 已经在 SQLite 中，worker 启动时会扫描并重新入队。
- 还没有分布式锁，不适合多进程同时消费同一个 SQLite 队列。
- 生产化可替换为 Redis Streams、Celery、Temporal 或 Postgres advisory lock。

## 本阶段验收

测试覆盖：

- 后台 worker 可以启动、入队、执行、停止。
- 启动时会扫描并消费已有 queued run。
- stopped worker 不允许 dispatch。
- API 可以 dispatch run 并后台执行完成。
- worker running 时，`POST /runs` 会自动入队。
- `events/stream?follow=true` 能输出执行期间产生的 timeline。

验证命令：

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest tests --cov=copilot_agent --cov-report=term-missing
```

## 下一步

建议下一块做 sandbox runtime/provisioning：

1. 抽象 sandbox backend 接口。
2. 为 Unix local backend 增加 Python runtime 检测。
3. 生成 dependency provisioning plan。
4. 为 Docker backend 预留 manifest/build 接口。
5. 解决之前 macOS sandbox 中 `encodings` 缺失的问题。
