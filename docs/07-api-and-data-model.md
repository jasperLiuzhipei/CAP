# API 与数据模型设计

## API 风格

平台建议提供 REST API 管理资源，WebSocket 或 SSE 推送 run events。

基础路径：

```text
/api/v1/tenants
/api/v1/projects
/api/v1/workspaces
/api/v1/conversations
/api/v1/runs
/api/v1/approvals
/api/v1/memories
/api/v1/models
/api/v1/tools
```

## 核心 API

### 创建项目

```http
POST /api/v1/projects
```

```json
{
  "name": "copilot-agent",
  "repo": {
    "type": "github",
    "url": "https://github.com/org/repo",
    "default_branch": "main"
  },
  "settings": {
    "default_model_profile": "profile_balanced",
    "sandbox_backend": "docker"
  }
}
```

### 创建 run

```http
POST /api/v1/runs
```

```json
{
  "project_id": "proj_123",
  "conversation_id": "conv_123",
  "task": {
    "type": "coding",
    "prompt": "修复登录失败的 bug，并运行相关测试"
  },
  "workspace": {
    "source": "project_repo",
    "branch": "main",
    "commit": "abc123"
  },
  "model_policy": {
    "quality": "balanced",
    "provider_policy": "openai_only"
  },
  "sandbox_policy": {
    "network": "deny",
    "approval_level": "standard"
  }
}
```

### 订阅 run events

```http
GET /api/v1/runs/{run_id}/events
```

Event types：

| Event | 说明 |
| --- | --- |
| `run.started` | run 创建 |
| `agent.started` | agent 开始 |
| `model.started` | 模型调用开始 |
| `model.completed` | 模型调用结束 |
| `tool.requested` | 工具调用请求 |
| `approval.required` | 需要人工审批 |
| `tool.completed` | 工具执行完成 |
| `file.changed` | 文件发生变更 |
| `artifact.created` | artifact 生成 |
| `memory.read` | memory 被读取 |
| `memory.written` | memory 被写入 |
| `run.completed` | run 完成 |
| `run.failed` | run 失败 |

### 审批 tool call

```http
POST /api/v1/approvals/{approval_id}/decide
```

```json
{
  "decision": "approve",
  "reason": "允许安装测试依赖",
  "scope": "this_call"
}
```

### 获取 diff

```http
GET /api/v1/runs/{run_id}/diff
```

### 获取 memory

```http
GET /api/v1/projects/{project_id}/memories
```

### 更新 memory

```http
PATCH /api/v1/memories/{memory_id}
```

## 数据模型

### Project

```json
{
  "id": "proj_123",
  "tenant_id": "tenant_123",
  "name": "copilot-agent",
  "repo_url": "https://github.com/org/repo",
  "default_branch": "main",
  "default_model_profile": "profile_balanced",
  "sandbox_backend": "docker",
  "created_at": "2026-05-21T00:00:00Z"
}
```

### Run

```json
{
  "id": "run_123",
  "tenant_id": "tenant_123",
  "project_id": "proj_123",
  "conversation_id": "conv_123",
  "status": "running",
  "workflow": "coding_task",
  "active_agent": "Coder Agent",
  "sandbox_session_id": "sbx_123",
  "model_policy": {},
  "cost_estimate": {},
  "created_by": "user_123",
  "created_at": "2026-05-21T00:00:00Z",
  "completed_at": null
}
```

### SandboxSession

```json
{
  "id": "sbx_123",
  "run_id": "run_123",
  "backend": "docker",
  "status": "active",
  "manifest_ref": "obj://manifests/123.json",
  "session_state_ref": "obj://states/123.json",
  "snapshot_ref": "obj://snapshots/123.tar.zst",
  "resource_limits": {
    "cpu": "2",
    "memory_mb": 4096,
    "disk_mb": 10240
  }
}
```

### ToolCall

```json
{
  "id": "tool_123",
  "run_id": "run_123",
  "agent_name": "Coder Agent",
  "tool_name": "shell.exec",
  "arguments_redacted": {"cmd": "pytest tests/login"},
  "risk_level": "R1",
  "approval_id": null,
  "status": "completed",
  "started_at": "2026-05-21T00:00:00Z",
  "completed_at": "2026-05-21T00:00:10Z"
}
```

### Memory

```json
{
  "id": "mem_123",
  "tenant_id": "tenant_123",
  "project_id": "proj_123",
  "scope": "project",
  "type": "workflow_hint",
  "content": "Run tests with `uv run pytest`.",
  "source_run_id": "run_123",
  "confidence": 0.85,
  "status": "active"
}
```

### ModelProfile

```json
{
  "id": "profile_balanced",
  "provider_id": "provider_openai",
  "model": "gpt-5.5",
  "api_shape": "responses",
  "capabilities": {
    "tool_calling": true,
    "structured_outputs": true,
    "streaming": true
  },
  "cost_class": "premium",
  "status": "active"
}
```

## 数据库建议

MVP：

- Postgres 存储 tenant、project、run、approval、memory metadata。
- Redis 存储 run event stream 和短期状态。
- S3-compatible object store 存储 snapshots、artifacts、large logs。
- SQLite 可用于本地开发。

Beta：

- 增加 vector DB 或 Postgres pgvector。
- 增加 OpenTelemetry traces。
- 增加 cold storage retention。

