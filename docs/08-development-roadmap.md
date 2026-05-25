# 开发路线图

## Phase 0: 技术验证

目标：证明 OpenAI Agents SDK + sandbox + memory 能支撑核心任务。

任务：

- 阅读并运行 `openai-agents-python` 基础 examples。
- 跑通 `SandboxAgent` 对本地 repo 的读取、patch、测试。
- 跑通 `SQLiteSession` 多轮对话。
- 跑通一个简单 Memory Curator。
- 验证 OpenAI provider 和一个 OpenAI-compatible provider。
- 验证 shell approval 和 patch approval。

产出：

- PoC CLI。
- 一个可运行的 coding task demo。
- 技术风险清单。

## Phase 1: MVP 后端

目标：做出可用的单租户 Copilot backend。

任务：

- FastAPI 或类似框架搭建 API。
- Project、Run、Conversation、Approval、Memory 数据表。
- Docker sandbox backend。
- Run event streaming。
- Model profile registry。
- Tool policy engine。
- RunState 持久化和 approval resume。
- Artifact 和 diff 存储。

验收：

- 用户能提交一个 repo task。
- Copilot 能在 sandbox 中修改代码并运行测试。
- 高风险命令会暂停并等待审批。
- Run 完成后可查看 diff、logs、summary。

## Phase 2: 产品化前端

目标：让用户能从 Web UI 完成任务闭环。

任务：

- Project setup 页面。
- Conversation + run timeline。
- Tool calls 和 approvals 面板。
- Diff viewer。
- Artifact viewer。
- Memory viewer/editor。
- Model/profile 配置页面。

验收：

- 用户无需看后台日志即可理解 agent 做了什么。
- 用户可以审批、拒绝、恢复 run。
- 用户可以删除或编辑错误 memory。

## Phase 3: 多租户与安全

目标：支持团队级使用。

任务：

- Tenant 和 RBAC。
- Secret manager 集成。
- Egress policy。
- Audit log。
- Quota 和 budget。
- Memory scope 隔离。
- Provider policy。
- 安全验收测试。

验收：

- 不同 project 数据隔离。
- 第三方模型策略可控。
- 敏感操作可审计。
- Memory 不跨租户泄露。

## Phase 4: 质量闭环

目标：让平台持续变聪明，而不是只会“跑 agent”。

任务：

- Golden task eval。
- Run replay。
- Agent prompt/version 管理。
- Model A/B test。
- Patch acceptance metrics。
- Memory quality metrics。
- Cost dashboard。

验收：

- 每次 prompt 或 model 升级可评估。
- 可以找到高成本低质量任务。
- 可以回放失败 run。

## Phase 5: Enterprise

目标：企业可部署、可治理、可扩展。

任务：

- 私有部署。
- SSO/SAML/OIDC。
- 客户自有 model provider。
- 客户自有 sandbox backend。
- 数据保留和删除策略。
- 审计导出。
- Policy as code。
- 插件市场或内部工具 registry。

## 8 周 MVP 计划

| 周 | 重点 | 产出 |
| --- | --- | --- |
| Week 1 | SDK 阅读和 PoC | 本地 sandbox coding demo |
| Week 2 | API 和数据模型 | Project/Run/Approval 基础 API |
| Week 3 | Docker sandbox | create/resume/snapshot/diff |
| Week 4 | Agent workflow | triage/planner/coder/reviewer |
| Week 5 | Memory MVP | session + project memory summary |
| Week 6 | 多模型 | model profile + provider routing |
| Week 7 | 前端闭环 | run timeline、approval、diff viewer |
| Week 8 | 安全和验收 | audit、policy、eval、demo |

## 当前建议的第一步

1. 在当前工作区写一个最小 backend skeleton。
2. 引入 `openai-agents` 作为依赖，不直接改上游 clone。
3. 实现一个 CLI 或 API：输入 repo path 和 task，启动 sandbox agent。
4. 先用 Unix local 验证，再切 Docker。
5. 把每次 run 的 events、diff、summary 落库。

