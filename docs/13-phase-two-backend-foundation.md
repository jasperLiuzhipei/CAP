# Phase 2 Backend Control Plane Foundation

> 命名说明：路线图里的 “Phase 1: MVP 后端” 对应我们聊天里的第二阶段。因为第一阶段已经先做完本地 CLI vertical slice，所以这里把当前实现称为 Phase 2。

## 目标

这一阶段先不急着做 Web UI，而是先把 Copilot 产品后端的控制平面打出来。控制平面负责记录和管理这些东西：

- Project：一个被 Copilot 管理的代码仓库。
- Run：一次用户任务执行。
- ToolCall：agent 想调用的工具和参数。
- Approval：需要人工审批的风险操作。
- Artifact：一次 run 产出的 diff、summary、log、report。

这层不是新的 agent 框架。真正的 agent loop、工具调用、sandbox execution 仍然由 OpenAI Agents SDK 承担。

## 和 OpenAI Agents SDK 的边界

OpenAI 官方文档建议在服务端拥有 orchestration、tool execution、state、approvals、sandbox execution 时使用 Agents SDK。我们的分层正是按这个思路做的：

| 层 | 我们的代码 | 职责 |
| --- | --- | --- |
| Agent runtime | `phase_one.py` + `openai-agents` | 创建 `SandboxAgent`，调用 `Runner.run`，处理 OpenAI 原生或 Chat Completions 兼容模型 |
| Product control plane | `backend/service.py` | 创建 project/run，记录工具风险，生成 approval，保存 artifact |
| Persistence | `backend/store.py` | 用 SQLite 保存 Project、Run、ToolCall、Approval、Artifact |
| Policy | `backend/policy.py` | 在工具执行前判断 allow、approval_required、deny |

所以我们没有把 `openai-agents-python` 改成另一个框架，而是在它外面补了产品工程层。这个方向适合后续接 FastAPI、Web UI、Docker sandbox、event stream 和长期 memory。

## 本阶段新增代码

### `backend/models.py`

定义产品后端的核心领域对象：

- `Project`
- `RunRecord`
- `ToolCall`
- `Approval`
- `Artifact`

这些对象和 `docs/07-api-and-data-model.md` 里的数据模型一一对应，是未来 API 和数据库表的最小版本。

### `backend/store.py`

实现 `SQLiteBackendStore`，先用本地 SQLite 作为 MVP 数据库。后续迁移 Postgres 时，service 层不用大改，只需要换 store 实现。

当前支持：

- 创建和查询 project。
- 创建、查询、更新 run 状态。
- 创建和审批 approval。
- 创建、查询、更新 tool call。
- 创建和查询 artifact。

### `backend/policy.py`

实现最小工具策略引擎：

- 只读命令：`rg`、`sed`、`cat`、`git diff`、`git status` 等，直接 allow。
- 验证命令：`pytest`、`python`、`ruff`、`npm`、`uv` 等，直接 allow，但风险标记为 `R1`。
- 网络和依赖安装：`curl`、`wget`、`pip install`、`npm install`、`uv sync` 等，需要 approval。
- 破坏性命令：`rm -rf`、`git reset --hard`、`git push`、`shutdown` 等，直接 deny。
- `apply_patch`：标记为 `approval_required`，因为最终应用到真实仓库前需要人审。

### `backend/service.py`

实现 `CopilotBackendService`，它是未来 FastAPI route 和 worker 会调用的应用服务层。

当前支持：

- `create_project`
- `queue_run`
- `start_run`
- `finish_run`
- `record_tool_decision`
- `decide_approval`
- `ingest_phase_one_report`

其中 `ingest_phase_one_report` 可以把第一阶段 CLI 保存的 `PhaseOneReport` 吸收到后端数据库里，让本地 CLI 结果进入平台化数据模型。

## 为什么这符合 OpenAI Agents SDK 理念

官方 Agents SDK 强调的是：

- Agent loop 负责模型推理、工具调用和循环控制。
- Tools 和 function tools 需要清晰定义。
- Guardrails 和 human review 用来控制风险。
- Result/state/tracing 用于可观测和恢复。
- Sandbox agents 适合需要文件、命令、包、快照和挂载的任务。

我们当前实现对应关系如下：

| SDK 理念 | 当前实现 |
| --- | --- |
| Agent loop | 继续由 `Runner.run` 执行，不在 backend 中重写 |
| Sandbox execution | 继续由 `SandboxAgent` 和 sandbox client 承担 |
| Human review | `Approval` 表和 `record_tool_decision` 打出审批闭环 |
| Tool guardrails | `ToolPolicyEngine` 在工具调用前分类风险 |
| Results and state | `RunRecord`、`Artifact` 保存结果和产物 |
| Observability | `ToolCall`、`Approval`、`Artifact` 为 run timeline 做准备 |

这也说明 DeepSeek、千问、火山这类 OpenAI-compatible provider 可以继续接入：它们影响的是 `phase_one.py` 的模型 transport 和工具兼容策略，不影响后端控制平面模型。

## 本阶段如何测试

只跑后端新增测试：

```bash
.venv/bin/python -m pytest \
  tests/test_backend_policy.py \
  tests/test_backend_store.py \
  tests/test_backend_service.py
```

跑全量测试和覆盖率：

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest tests --cov=copilot_agent --cov-report=term-missing
```

## 下一步

建议继续按这个顺序迭代：

1. 给 `CopilotBackendService` 套 FastAPI routes：`/projects`、`/runs`、`/approvals`、`/runs/{id}/artifacts`。
2. 引入 run worker，把 `queue_run` 和 `run_phase_one` 连起来。
3. 把 native OpenAI approval interruption 的 serialized state 存进 run state。
4. 把 Unix local sandbox 抽象成 sandbox backend，准备切 Docker。
5. 增加 run event stream，让前端可以显示 timeline。
