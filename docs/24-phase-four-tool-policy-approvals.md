# Phase 4A Tool Policy and Approvals

本阶段把 Copilot 从“能运行任务”推进到“能被治理地运行任务”。核心目标是：所有工具调用都能被统一分类、审计，并在高风险场景进入人工审批。

## 设计原则

OpenAI Agents SDK 继续负责 agent runtime、模型调用、tool loop 和 sandbox session。Copilot 平台负责产品级治理：

- Policy：判断工具调用是否允许、需要审批或直接拒绝。
- Approval：把高风险操作变成可持久化、可展示、可决策的人工审批对象。
- Audit：保存 tool call、审批结果、风险等级、原因和 run event。
- Status gate：如果 run 产生待审批工具调用，run 不再直接视为安全完成，而是进入 `needs_approval`。

这保持了 SDK 的原生优势，也把 SaaS / Copilot 产品必须具备的安全边界放在平台层。

## Policy 分层

`ToolPolicyEngine` 现在覆盖以下工具范围：

| 范围 | 动作 | 风险 | 说明 |
| --- | --- | --- | --- |
| `shell.read_only` | `allow` | `R0` | `rg`、`sed`、`cat`、`ls` 等只读检查 |
| `shell.verification` | `allow` | `R1` | `pytest`、`ruff`、`python`、`npm` 等本地验证 |
| `git.read_only` | `allow` | `R0` | `git diff`、`git status`、`git log` 等 |
| `git.write` | `approval_required` | `R2` | `git add`、`commit`、`apply`、`merge` 等 |
| `git.remote` | `approval_required` | `R3` | `git clone`、`fetch`、`pull`、`push` |
| `network` | `approval_required` | `R3` | `curl`、`wget`、`ssh`、`scp` 等 |
| `apply_patch` | `approval_required` | `R1` | sandbox 内修改文件后，需要人审结果 |
| `destructive` | `deny` | `R4` | `rm -rf`、`git reset --hard`、`git clean -fd` 等 |

## API

查看当前策略规则：

```bash
curl http://127.0.0.1:8000/api/v1/policy/rules
```

手动 review 一个工具调用：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/runs/<run_id>/tool-calls/review \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"shell.exec","arguments":{"cmd":"git push origin feature"}}'
```

审批：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/approvals/<approval_id>/decide \
  -H "Content-Type: application/json" \
  -d '{"approved":true,"decided_by":"jasper"}'
```

## Run Ingestion

Phase-one run 结束后，`PhaseOneReport.tool_calls` 会被后端自动过一遍 policy：

- `allow`：记录 `ToolCall(status="allowed")`。
- `approval_required`：创建 `Approval(decision="pending")`，run 进入 `needs_approval`。
- `deny`：记录 `policy.violation` 事件，run 标记为 `failed`。

这不是替代 sandbox 隔离，而是在 sandbox 之上增加产品级安全门禁。后续正式前端可以基于这些数据展示审批弹窗、风险说明和工具轨迹。

## 下一步

- 在 Web UI 里加入审批列表和审批弹窗。
- 对 native OpenAI hosted tools 探索更靠近执行前的 interruption / resume。
- 把 GitHub 工作流工具纳入同一套 policy，不绕过审批系统。
- 增加项目级 policy preset，例如 `strict`、`standard`、`trusted_local`。
