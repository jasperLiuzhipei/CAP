# 实现蓝图

## 技术栈建议

| 层 | 建议 |
| --- | --- |
| Backend API | Python + FastAPI |
| Agent runtime | `openai-agents` package |
| Worker | asyncio workers + queue, 后续可切 Celery/Temporal |
| DB | Postgres, 本地可用 SQLite |
| Cache/Event | Redis Streams 或 Postgres notification, 本地可先内存队列 |
| Object storage | S3-compatible, 本地可用 filesystem |
| Sandbox | PoC 用 Unix local, MVP 用 Docker |
| Frontend | React/Next.js 或现有前端框架 |
| Observability | OpenTelemetry + structured audit logs |

## 推荐代码结构

```text
copilot_agent/
├── app/
│   ├── api/
│   │   ├── routes_projects.py
│   │   ├── routes_runs.py
│   │   ├── routes_approvals.py
│   │   ├── routes_memories.py
│   │   └── routes_models.py
│   ├── core/
│   │   ├── config.py
│   │   ├── auth.py
│   │   ├── policy.py
│   │   └── audit.py
│   ├── agents/
│   │   ├── factory.py
│   │   ├── workflows.py
│   │   ├── prompts.py
│   │   └── tools.py
│   ├── sandbox/
│   │   ├── manifest_builder.py
│   │   ├── client_factory.py
│   │   ├── snapshots.py
│   │   └── diff.py
│   ├── memory/
│   │   ├── sessions.py
│   │   ├── retrieval.py
│   │   ├── curator.py
│   │   └── redaction.py
│   ├── models/
│   │   ├── registry.py
│   │   ├── router.py
│   │   └── capabilities.py
│   ├── workers/
│   │   ├── run_worker.py
│   │   └── memory_worker.py
│   └── db/
│       ├── models.py
│       └── migrations/
├── tests/
└── docs/
```

## 第一条 vertical slice

目标：输入 repo path 和任务，平台创建 sandbox run，agent 修改文件，运行测试，返回 diff。

最小流程：

1. `POST /runs` 创建 run。
2. Orchestrator 根据 project 生成 manifest。
3. Sandbox client 创建 session。
4. Agent factory 创建 `SandboxAgent`。
5. `Runner.run` 执行任务。
6. Tool policy 拦截 shell 和 patch。
7. Run event stream 输出进度。
8. 完成后保存 diff、summary、artifact。
9. Memory Curator 生成 run summary。

## MVP agent 定义

```python
from agents import ModelSettings
from agents.sandbox import Manifest, SandboxAgent
from agents.sandbox.capabilities import Capabilities
from agents.sandbox.entries import LocalDir


def build_coding_agent(repo_path: str, model: str) -> SandboxAgent:
    return SandboxAgent(
        name="Workspace Coding Agent",
        model=model,
        instructions=(
            "Inspect the repository before editing. Make the smallest correct change. "
            "Run the most relevant verification command. Summarize changed files, "
            "verification results, and remaining risks."
        ),
        default_manifest=Manifest(
            entries={
                "repo": LocalDir(src=repo_path),
            }
        ),
        capabilities=Capabilities.default(),
        model_settings=ModelSettings(tool_choice="required"),
    )
```

## Policy MVP

先实现规则引擎，不急着做复杂 DSL。

```python
class ToolDecision:
    action: str  # allow, require_approval, deny
    reason: str
    risk_level: str


def decide_shell_command(cmd: str) -> ToolDecision:
    if "rm -rf" in cmd or "git push" in cmd:
        return ToolDecision(action="deny", reason="destructive command", risk_level="R4")
    if cmd.startswith(("ls", "pwd", "rg", "sed", "cat", "git diff")):
        return ToolDecision(action="allow", reason="read-only command", risk_level="R0")
    if cmd.startswith(("pytest", "uv run pytest", "npm test", "bun test")):
        return ToolDecision(action="allow", reason="test command", risk_level="R1")
    return ToolDecision(action="require_approval", reason="unclassified command", risk_level="R2")
```

## Memory MVP

第一版不做复杂向量检索，先做结构化 project memory。

文件形态：

```text
project_memory/
├── PROJECT_MEMORY.md
├── RUN_SUMMARIES/
│   └── run_123.md
└── USER_PREFERENCES.md
```

写入规则：

- 每个 run 结束生成 run summary。
- 只有明确高价值信息才进入 `PROJECT_MEMORY.md`。
- 写入前做 secret scan。
- 用户可以查看和删除。

## 迭代顺序

1. 后端 skeleton 和 config。
2. Model registry，先 hardcode 两个 profile。
3. Sandbox manifest builder。
4. Coding agent factory。
5. Run worker。
6. Event stream。
7. Approval interruption storage。
8. Diff and artifact storage。
9. Session memory。
10. Project memory curator。

## 不变式

- Agent 永远不直接获得宿主机任意路径。
- Model Router 永远先做 capability check。
- Tool call 永远先过 policy。
- Memory 写入永远先过 redaction。
- Run 完成永远产出可审计摘要。
- 所有外部 side effect 默认需要审批。
