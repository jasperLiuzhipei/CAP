# Copilot Platform 文档索引

本文档集用于规划一个工程化 Copilot 平台：具备可配置多模型、完整 workspace 沙箱、长期 memory 管理、工具权限、人工审批、可观测性和企业级治理能力。

## 当前目录结构

```text
copilot_agent/
├── docs/
│   ├── README.md
│   ├── 01-product-requirements.md
│   ├── 02-system-architecture.md
│   ├── 03-workspace-sandbox.md
│   ├── 04-memory-management.md
│   ├── 05-model-provider-routing.md
│   ├── 06-security-permissions.md
│   ├── 07-api-and-data-model.md
│   ├── 08-development-roadmap.md
│   ├── 09-openai-agents-reading-notes.md
│   ├── 10-implementation-blueprint.md
│   ├── 11-phase-one-local-cli.md
│   ├── 12-model-provider-env-design.md
│   ├── 13-phase-two-backend-foundation.md
│   ├── 14-phase-two-api-layer.md
│   ├── 15-phase-two-run-worker.md
│   ├── 16-phase-two-run-events.md
│   ├── 17-phase-two-async-worker.md
│   ├── 18-phase-two-sandbox-runtime.md
│   └── 19-phase-two-api-ai-run.md
├── examples/
│   └── sample_repo/
└── src/
    └── copilot_agent/
```

## 推荐阅读顺序

1. [产品需求设计](01-product-requirements.md)
2. [系统架构设计](02-system-architecture.md)
3. [Workspace 沙箱设计](03-workspace-sandbox.md)
4. [Memory 管理设计](04-memory-management.md)
5. [多模型路由设计](05-model-provider-routing.md)
6. [安全与权限设计](06-security-permissions.md)
7. [API 与数据模型](07-api-and-data-model.md)
8. [开发路线图](08-development-roadmap.md)
9. [OpenAI Agents Python 阅读笔记](09-openai-agents-reading-notes.md)
10. [实现蓝图](10-implementation-blueprint.md)
11. [Phase 1 Local Sandbox CLI](11-phase-one-local-cli.md)
12. [Model Provider Env 设计](12-model-provider-env-design.md)
13. [Phase 2 Backend Control Plane Foundation](13-phase-two-backend-foundation.md)
14. [Phase 2 API Layer](14-phase-two-api-layer.md)
15. [Phase 2 Run Worker](15-phase-two-run-worker.md)
16. [Phase 2 Run Events and Timeline](16-phase-two-run-events.md)
17. [Phase 2 Async Worker and Live Events](17-phase-two-async-worker.md)
18. [Phase 2 Sandbox Runtime Provisioning](18-phase-two-sandbox-runtime.md)
19. [Phase 2 API AI Run](19-phase-two-api-ai-run.md)

## 核心技术判断

OpenAI Agents SDK 适合作为 agent 编排层，尤其适合服务端拥有 orchestration、tool execution、state、approval、sandbox execution 的产品。平台层需要在 SDK 外补齐以下工程能力：

- 多租户项目与 workspace 管理。
- 模型能力矩阵与 provider 路由。
- 强沙箱隔离、资源配额、快照、审计。
- 长期 memory 的分层存储、检索、压缩、治理。
- 权限策略、人工审批、密钥隔离。
- 评测、回放、trace、成本与质量监控。

## 上游参考

- Upstream repository: <https://github.com/openai/openai-agents-python>
- Sandbox agents: <https://openai.github.io/openai-agents-python/sandbox_agents/>
- Models and providers: <https://openai.github.io/openai-agents-python/models/>
- Sessions: <https://openai.github.io/openai-agents-python/sessions/>
- Human in the loop: <https://openai.github.io/openai-agents-python/human_in_the_loop/>

本地如果需要阅读上游源码，可单独 clone 到 `openai-agents-python/`。该目录只作为参考资料，不提交到本仓库。
