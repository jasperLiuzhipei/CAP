# Phase 2 API Layer

## 目标

这一块把 `CopilotBackendService` 包成 FastAPI API，让后续 Web UI、worker、CLI 或第三方系统都能通过同一套后端接口管理 Copilot run。

这一步仍然不重写 OpenAI Agents SDK 的执行逻辑。API 层只负责产品控制平面：

- 创建和查询 project。
- 创建、启动、完成和查询 run。
- 记录 tool call 的策略判断。
- 查询和处理 approval。
- 查询 artifact 和 diff。

真正的 agent loop、模型调用、sandbox execution 仍然保留在 `phase_one.py` 和 OpenAI Agents SDK 侧。

## 新增代码

| 文件 | 作用 |
| --- | --- |
| `src/copilot_agent/api/app.py` | FastAPI app factory 和 `/api/v1` routes |
| `src/copilot_agent/api/schemas.py` | API request / response schema |
| `src/copilot_agent/api/main.py` | 默认 ASGI 入口 |
| `tests/test_api_app.py` | API 层集成测试 |

## 当前 API

### Health

```http
GET /api/v1/health
```

### Projects

```http
POST /api/v1/projects
GET /api/v1/projects
GET /api/v1/projects/{project_id}
```

### Runs

```http
POST /api/v1/runs
GET /api/v1/runs
GET /api/v1/runs?project_id={project_id}
GET /api/v1/runs/{run_id}
POST /api/v1/runs/{run_id}/start
POST /api/v1/runs/{run_id}/finish
GET /api/v1/runs/{run_id}/diff
```

### Tool Calls and Approvals

```http
POST /api/v1/runs/{run_id}/tool-calls/review
GET /api/v1/runs/{run_id}/tool-calls
GET /api/v1/runs/{run_id}/approvals
POST /api/v1/approvals/{approval_id}/decide
```

### Artifacts

```http
GET /api/v1/runs/{run_id}/artifacts
```

## 如何启动

安装依赖后，可以直接启动本地 API：

```bash
.venv/bin/uvicorn copilot_agent.api.main:app --reload
```

默认 SQLite 数据库路径是当前目录下的 `.copilot/control.sqlite`。

测试里也可以用 app factory 注入临时数据库：

```python
from copilot_agent.api import create_app
from copilot_agent.backend.service import CopilotBackendService
from copilot_agent.backend.store import SQLiteBackendStore

service = CopilotBackendService(SQLiteBackendStore("control.sqlite"))
app = create_app(service=service)
```

## 和 OpenAI Agents SDK 的对应关系

| OpenAI Agents SDK 概念 | API 层对应 |
| --- | --- |
| `Runner.run` 产生一次执行 | `RunRecord` 暴露为 `/runs` |
| Tool call 需要 guardrail / approval | `/tool-calls/review` 和 `/approvals/{id}/decide` |
| Run result / artifacts | `/runs/{id}/artifacts` 和 `/runs/{id}/diff` |
| SDK state 后续可恢复 | 当前 `RunRecord` 为后续 serialized state 字段预留位置 |
| Sandbox execution | API 只记录 sandbox backend，不直接绕开 SDK 执行 |

## 本阶段验收

当前 API 测试覆盖：

- Project 创建、列表、详情。
- Run 创建、列表、详情、启动、完成。
- Tool call review 生成 allow 或 approval。
- Approval 决策。
- Artifact 和 diff 查询。
- 常见 400 / 404 错误映射。

验证命令：

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest tests --cov=copilot_agent --cov-report=term-missing
```

## 下一步

建议第三块做 run worker：

1. `POST /api/v1/runs` 只负责排队。
2. Worker 读取 queued run，调用 Phase 1 agent runtime。
3. 执行过程中写入 `ToolCall`、`Approval`、`Artifact`。
4. 后续再把 event stream 接到前端 timeline。
