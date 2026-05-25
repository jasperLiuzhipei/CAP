# Copilot Agent Platform

这是一个工程化 Copilot 平台的产品与技术规划工作区。当前目标是基于 OpenAI Agents SDK 设计并逐步实现一个具备 workspace 沙箱、memory 管理、多模型路由、工具审批和企业治理能力的 agentic copilot。

## 目录

```text
.
├── docs/                    # 产品与技术设计文档
├── examples/                # 本地测试样例仓库
└── src/                     # Phase 1 Copilot CLI 原型
```

## 快速入口

- [文档索引](docs/README.md)
- [产品需求设计](docs/01-product-requirements.md)
- [系统架构设计](docs/02-system-architecture.md)
- [Workspace 沙箱设计](docs/03-workspace-sandbox.md)
- [Memory 管理设计](docs/04-memory-management.md)
- [实现蓝图](docs/10-implementation-blueprint.md)
- [Phase 1 Local Sandbox CLI](docs/11-phase-one-local-cli.md)
- [Model Provider Env 设计](docs/12-model-provider-env-design.md)
- [上游源码阅读笔记](docs/09-openai-agents-reading-notes.md)

## 当前状态

- 已建立第一版产品需求、架构、安全、memory、多模型和路线图文档。
- 已创建阶段一最小 CLI skeleton：`copilot-agent run --repo ... --task ...`。
- 已验证 DeepSeek 兼容 API 可通过 shell-only sandbox 路径完成 sample repo 修复任务。

> Note: `openai-agents-python/` 是本地阅读上游源码时使用的可选目录，不提交到本仓库。需要阅读源码时可单独 clone `https://github.com/openai/openai-agents-python`。

## Phase 1 Dry Run

```bash
PYTHONPATH=src python3 -m copilot_agent run \
  --repo examples/sample_repo \
  --task "Fix the discount calculation bug and run tests." \
  --test-cmd "python -m pytest" \
  --dry-run
```

## Local API Key

真实运行前可以把 key 放进本地 `.env`：

```bash
cp .env.example .env
```

然后编辑 `.env`，例如低成本 DeepSeek 开发配置：

```env
COPILOT_MODEL_PROVIDER=deepseek
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=<your-deepseek-api-key>
```

`.env` 已经被 `.gitignore` 忽略。
