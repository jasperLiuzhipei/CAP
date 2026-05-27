# Phase 2 Run Worker

## 目标

这一块把 API 创建的 queued run 和第一阶段的真实 agent runtime 接起来。

之前我们已经有：

- `run_phase_one()`：能调用 OpenAI Agents SDK 执行一次本地 coding task。
- `CopilotBackendService`：能保存 Project、Run、ToolCall、Approval、Artifact。
- FastAPI routes：能创建 run、查询 run、查询 diff 和 artifact。

现在新增 `RunWorker`，让流程变成：

```text
POST /api/v1/runs
        |
        v
RunRecord(status="queued")
        |
        v
RunWorker.execute_run(...)
        |
        v
PhaseOneConfig -> run_phase_one() -> PhaseOneReport
        |
        v
RunRecord(status="succeeded" / "failed") + Artifact + diff/log/summary
```

## 新增代码

| 文件 | 作用 |
| --- | --- |
| `src/copilot_agent/worker/run_worker.py` | 本地 run worker，读取 queued run 并调用 Phase 1 runtime |
| `src/copilot_agent/worker/__init__.py` | worker package export |
| `tests/test_run_worker.py` | worker 单元/集成测试 |
| `tests/test_api_app.py` | 新增 API execute endpoint 测试 |

## API 新增入口

```http
POST /api/v1/runs/{run_id}/execute
```

请求示例：

```json
{
  "test_cmd": "python -m pytest tests",
  "max_turns": 32,
  "output_dir": "runs",
  "memory_enabled": true,
  "host_verify": true,
  "require_api_key": true
}
```

本地测试时，如果你不想真的校验 API key，可以把 `require_api_key` 设为 `false`。真实执行时应保持 `true`。

## 和 OpenAI Agents SDK 的关系

`RunWorker` 不是新的 agent loop，它只是把平台 run 转成 SDK runtime 需要的配置：

| 平台对象 | SDK runtime 对应 |
| --- | --- |
| `Project.repo_path` | `PhaseOneConfig.repo`，最终进入 `SandboxAgent` manifest |
| `RunRecord.task` | `PhaseOneConfig.task`，最终进入 agent prompt |
| `RunRecord.model_provider/model/tool_strategy` | `resolve_model_config()`，决定 OpenAI native 或 Chat Completions compatible |
| `RunExecutionOptions.test_cmd` | `PhaseOneConfig.test_cmd`，让 agent 或 host verify 执行验证 |
| `PhaseOneReport` | 回写为 `RunRecord.summary/status` 和 `Artifact` |

所以执行引擎仍然是：

```text
OpenAI Agents SDK Runner + SandboxAgent
```

我们新增的是：

```text
queued run orchestration + result persistence
```

这符合 `openai-agents-python` 的工程化使用方式：SDK 负责 agent runtime，产品平台负责状态、审批、产物和 API。

## 当前限制

- `/execute` 是同步等待执行完成的本地 MVP 端点，适合开发验证。
- 生产化以后应改成后台 worker：API 只入队，worker 独立消费 queued run。
- 当前还没有 event stream，前端暂时只能轮询 run 状态。
- OpenAI 原生 approval interruption 的 serialized state 还没有持久化，后续会加到 RunState。

## 本阶段验收

测试覆盖：

- worker 能执行 queued run，并把 report 写回原 run。
- worker 不会把 SDK 生成的 report run id 误建成另一条产品 run。
- worker 能处理空队列。
- runner 异常会把 run 标记为 failed。
- API `/runs/{id}/execute` 能触发 worker 并返回完成后的 run。

验证命令：

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest tests --cov=copilot_agent --cov-report=term-missing
```

## 下一步

建议第四块做 event stream / run timeline：

1. 定义 `RunEvent` 数据模型。
2. Worker 在状态变化时写入 event。
3. API 提供 `GET /api/v1/runs/{run_id}/events`。
4. 后续前端就能展示 agent timeline、tool calls、approval 和 artifacts。
