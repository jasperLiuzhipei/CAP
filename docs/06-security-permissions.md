# 安全与权限设计

## 安全目标

本产品允许 agent 读取代码、运行命令、修改文件、调用外部工具，因此安全设计必须作为核心产品能力，而不是后补功能。

安全目标：

- 租户隔离。
- workspace 隔离。
- 最小权限。
- 高风险操作审批。
- 密钥不进 prompt。
- 完整审计。
- 可回滚和可追责。

## 威胁模型

| 威胁 | 示例 | 防护 |
| --- | --- | --- |
| Prompt injection | repo 中恶意 README 要求泄露密钥 | tool policy、secret isolation、instruction hierarchy |
| Data exfiltration | agent 用 curl 上传源码 | egress allowlist、approval、network deny |
| Host escape | shell 访问宿主机敏感路径 | container isolation、path grant 审批 |
| Supply chain | 安装恶意依赖 | package install approval、lockfile、network proxy |
| Memory poisoning | 错误或恶意内容写入长期 memory | curator policy、review、source lineage |
| Tool abuse | 模型调用危险 MCP tool | tool allowlist、approval、scope |
| Cross-tenant leak | memory 或 artifact 串租户 | tenant scoped storage、DB RLS、access checks |
| Cost abuse | 无限 run 或昂贵模型 | quotas、budget、rate limit |

## 权限模型

资源层级：

```text
Tenant
└── Project
    ├── Repo
    ├── Workspace
    ├── Conversation
    ├── Run
    ├── Memory
    ├── SandboxSession
    └── Artifact
```

角色建议：

| 角色 | 能力 |
| --- | --- |
| Owner | 管理 tenant、billing、security policy |
| Admin | 管理 project、model、tool、memory policy |
| Developer | 创建 run、审批自己的 workspace 操作 |
| Reviewer | 查看 run、审批高风险操作、review patch |
| Viewer | 只读查看结果和 artifact |
| Service Account | 自动化触发 run，权限最小化 |

## Tool policy

每个 tool 必须声明：

- tool name。
- capability type。
- read/write/network/side effect。
- required scopes。
- approval rule。
- audit schema。
- timeout。
- max output size。
- secret access needs。

示例：

```json
{
  "tool_name": "shell.exec",
  "risk": "high",
  "requires_approval": "conditional",
  "allowed_commands": ["pytest", "rg", "sed", "ls", "git diff"],
  "denied_patterns": ["rm -rf", "curl .*http", "git push"],
  "timeout_seconds": 120,
  "network": "deny",
  "audit": true
}
```

## Human in the loop

审批触发条件：

- 写文件。
- 执行非 allowlist 命令。
- 网络访问。
- 安装依赖。
- 读取敏感路径。
- 写远程系统。
- 生成 PR、commit、issue comment。
- 写入长期 memory 中的用户或团队偏好。

审批记录：

```json
{
  "approval_id": "appr_123",
  "run_id": "run_123",
  "tool_name": "shell.exec",
  "arguments_redacted": {"cmd": "pip install package"},
  "risk": "R2",
  "requested_by": "agent:coder",
  "decided_by": "user_1",
  "decision": "approved",
  "created_at": "2026-05-21T00:00:00Z",
  "decided_at": "2026-05-21T00:01:00Z"
}
```

## 密钥管理

规则：

- 密钥存储在 secret manager。
- 密钥不写入 memory。
- 密钥不注入普通 prompt。
- 工具需要密钥时，由 tool runtime 在执行层读取。
- trace 和 audit 必须脱敏。
- sandbox 环境变量按最小权限注入。
- 第三方 provider 不接收不必要的私有上下文。

## 网络策略

默认：

- Sandbox egress deny。
- 允许 package registry 需要项目策略或审批。
- 允许 GitHub clone 需要 repo allowlist。
- 禁止直接访问 cloud metadata endpoint。
- 禁止向未知域名上传 workspace 内容。

生产建议：

- 使用 egress proxy。
- 记录域名、IP、字节数。
- 对 POST/PUT/PATCH 等出站请求要求更高审批。
- 对 provider API 和 object store 使用固定网络策略。

## Memory 安全

- Memory 写入先做 secret scanning。
- Memory 内容带 tenant/project/repo scope。
- User memory 默认用户可见可删。
- Team memory 需要 admin 管理。
- Memory retrieval 经过 RBAC 和 project scope。
- Sensitive run 可以禁用 memory generation。
- Memory provenance 必须记录 source run 和 source artifact。

## 审计日志

必须记录：

- 登录和权限变更。
- project/repo/workspace 创建。
- model provider 配置变更。
- run 创建、恢复、取消。
- tool call 和参数脱敏摘要。
- shell command、exit code、stdout/stderr 摘要。
- file diff、artifact。
- approval 决策。
- memory 读写。
- secret 访问。

## 安全验收测试

MVP 前必须通过：

- repo 中 prompt injection 无法读取 secret。
- 默认 sandbox 无法访问 workspace 外路径。
- 未审批不能执行网络上传。
- 未审批不能删除大量文件。
- 第三方模型不能接收被标记为 OpenAI-only 或 local-only 的数据。
- memory scanner 能阻断常见 API key。
- 审批暂停后恢复 run 不丢 session。
- audit log 足以还原一次文件修改和命令执行。

