# 产品需求设计

## 产品定位

目标产品是一个面向研发团队和知识工作流的工程化 Copilot 平台。它不是单一聊天机器人，而是一个能够理解项目、进入受控 workspace、调用工具、执行多步任务、保留项目记忆、支持多模型切换，并能被审计和治理的 agent runtime 产品。

一句话定位：

> 一个带 workspace 沙箱、长期 memory、多模型路由和企业权限治理的 agentic copilot 平台。

## 目标用户

| 用户 | 诉求 | 成功标准 |
| --- | --- | --- |
| 个人开发者 | 在本地或远程 repo 上完成分析、修复、测试、重构 | 少切上下文，能看到真实文件变更和验证结果 |
| 团队开发者 | 让 Copilot 按团队规范参与 issue、PR、review、测试 | 结果可复现、可审批、可追踪 |
| 技术负责人 | 把团队经验沉淀为 memory 和 workflow | 新任务能复用历史决策和代码约定 |
| 平台管理员 | 管理模型、成本、权限、数据边界 | 租户隔离、安全审计、成本可控 |
| 安全/合规人员 | 控制工具、文件、网络、密钥访问 | 所有高风险操作可审计、可阻断 |

## 核心场景

1. Repo onboarding
   用户连接一个代码仓库，Copilot 读取结构、依赖、测试命令、代码规范，生成项目地图和初始 memory。

2. Issue-to-patch
   用户输入 bug 或 issue，Copilot 在沙箱中检索代码、定位原因、修改文件、运行测试，并输出 patch 摘要。

3. PR review
   Copilot 对 diff、测试覆盖、潜在回归、性能和安全风险做审查，必要时运行只读或写入受限的验证命令。

4. 多步研发任务
   Copilot 将需求拆解成计划、实现、验证、总结，并在每个阶段写入 run log、trace 和 memory。

5. 团队记忆复用
   Copilot 记住项目结构、用户偏好、常见失败、测试命令、架构约束，但不能记住密钥、隐私数据和未授权内容。

6. 多模型协作
   简单分类任务走低成本模型，复杂推理和代码修改走高能力模型，非敏感辅助任务可走第三方或本地模型。

7. 人工审批
   对写文件、执行命令、访问网络、安装依赖、提交 PR、删除文件等动作，按风险策略要求用户审批。

## 产品目标

- 支持 workspace 级隔离，agent 必须在受控文件系统中工作。
- 支持短期会话记忆、项目长期记忆、用户偏好记忆和代码检索记忆。
- 支持 OpenAI 模型、OpenAI-compatible provider、LiteLLM/Any-LLM、本地模型或企业内网模型。
- 支持可观测性，包括 trace、tool call、handoff、approval、sandbox 命令、文件 diff、成本和 token。
- 支持权限治理，包括 RBAC、tool policy、sandbox policy、密钥隔离和审计日志。
- 支持可恢复任务，包括 run state、sandbox session state、workspace snapshot 和 pending approval。

## 非目标

- 第一阶段不做完整 IDE 替代。
- 第一阶段不承诺任意模型能力一致。
- 第一阶段不让模型直接访问宿主机任意路径。
- 第一阶段不自动执行高风险生产变更。
- 第一阶段不把 memory 当事实来源，当前 workspace 永远优先。

## 功能需求

### Workspace 管理

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| W1 | 创建 project 和 workspace，绑定 repo、branch、commit、task spec | P0 |
| W2 | 支持 GitHub repo、local directory、uploaded archive、remote object store 输入 | P0 |
| W3 | 每个 run 拥有独立 sandbox session 或显式复用 session | P0 |
| W4 | 支持 workspace snapshot、恢复、diff、artifact 导出 | P0 |
| W5 | 支持只读输入目录和可写 output/scratch 目录 | P0 |
| W6 | 支持命令超时、CPU、内存、磁盘、网络 egress 限制 | P1 |
| W7 | 支持多 agent 各自 workspace 或共享 workspace | P1 |

### Agent 编排

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| A1 | 支持 triage、planner、workspace explorer、coder、reviewer、test runner 等 specialist | P0 |
| A2 | 支持 agents as tools 和 handoffs 两种协作模式 | P0 |
| A3 | 支持 streaming 输出和中断恢复 | P0 |
| A4 | 支持 run state 序列化，用于 approval 后恢复 | P0 |
| A5 | 支持 guardrails 和 output schema | P1 |
| A6 | 支持任务模板和团队 workflow 配置 | P1 |

### Tool 与审批

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| T1 | 支持文件读取、搜索、patch、命令执行、测试运行 | P0 |
| T2 | 支持 MCP 工具注册和 tool allowlist | P0 |
| T3 | 支持按动作风险触发人工审批 | P0 |
| T4 | 支持 approval state 持久化和恢复 | P0 |
| T5 | 支持 tool 参数脱敏和审计 | P1 |
| T6 | 支持 tool 调用预算和速率限制 | P1 |

### Memory

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| M1 | 会话历史自动持久化 | P0 |
| M2 | workspace 级 memory 文件和 summary | P0 |
| M3 | 项目长期 memory，按 tenant/project/repo 隔离 | P0 |
| M4 | 用户偏好 memory，默认需要透明可编辑 | P1 |
| M5 | 代码索引和语义检索 | P1 |
| M6 | memory 写入前过滤密钥、PII、敏感文件 | P0 |
| M7 | memory 失效、冲突、回滚、删除 | P1 |

### 多模型

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| L1 | 配置多个 provider 和 model profile | P0 |
| L2 | 按 agent、任务类型、成本、质量、延迟选择模型 | P0 |
| L3 | 记录每个 provider 的能力矩阵 | P0 |
| L4 | 支持 fallback 和熔断 | P1 |
| L5 | 支持模型评测和灰度 | P1 |

## 非功能需求

| 维度 | 要求 |
| --- | --- |
| 安全 | 默认拒绝，高风险操作审批，密钥不进 prompt，不让模型决定 host path grant |
| 隔离 | 生产优先 Docker 或 hosted sandbox，本地 Unix sandbox 只作为开发模式 |
| 可恢复 | 长任务、审批中断、进程重启后可恢复 |
| 可观测 | 每个 run 可回放关键步骤，trace 关联模型、工具、文件 diff、approval |
| 成本 | 每个 run 记录 token、模型、tool 时间、sandbox 资源 |
| 性能 | 普通问答秒级返回，代码任务允许分钟级但要 streaming 进度 |
| 合规 | 支持数据保留策略、memory 删除、审计导出 |

## MVP 验收标准

- 可以创建一个 project，导入 GitHub repo 或 local directory。
- 可以在 Docker 或 Unix-local sandbox 中运行一个 coding agent。
- agent 能读 repo、修改文件、运行指定测试、输出 diff 和验证结果。
- 所有 shell 和 patch 操作进入审计日志。
- 高风险命令需要人工 approval。
- 支持 SQLite 或 Postgres session history。
- 支持项目 memory summary 和 run summary。
- 支持至少 OpenAI provider 和一个 OpenAI-compatible provider。
- UI 或 API 能查看 run 状态、trace、tool calls、diff、artifacts。

## 关键风险

- Sandbox Agents 在上游 SDK 中仍属于 beta，需要平台层抽象，避免被 API 变化锁死。
- 多模型 provider 能力不一致，必须做 capability gating。
- 长期 memory 容易污染或泄露敏感信息，必须默认保守。
- 让模型执行命令存在供应链和数据泄露风险，必须有 egress、approval、secret policy。
- “自动修复”需要强验证，否则会产生看似合理但不可运行的 patch。

