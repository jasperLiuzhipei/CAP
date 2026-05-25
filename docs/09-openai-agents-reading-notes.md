# OpenAI Agents Python 阅读笔记

本地阅读时可单独克隆上游仓库：

```text
git clone --depth=1 https://github.com/openai/openai-agents-python.git
openai-agents-python/
```

该目录只作为源码阅读参考，不提交到本仓库。

## 最值得先读的文件

| 主题 | 文件 |
| --- | --- |
| 总览 | <https://github.com/openai/openai-agents-python> |
| Agent 定义 | <https://openai.github.io/openai-agents-python/agents/> |
| 多 agent 编排 | <https://openai.github.io/openai-agents-python/multi_agent/> |
| Tools | <https://openai.github.io/openai-agents-python/tools/> |
| Handoffs | <https://openai.github.io/openai-agents-python/handoffs/> |
| Human in the loop | <https://openai.github.io/openai-agents-python/human_in_the_loop/> |
| Sessions | <https://openai.github.io/openai-agents-python/sessions/> |
| Models | <https://openai.github.io/openai-agents-python/models/> |
| Sandbox agents | <https://openai.github.io/openai-agents-python/sandbox_agents/> |

## 对本产品最关键的上游能力

### Agent

`Agent` 是基础抽象，包含：

- instructions。
- model。
- tools。
- handoffs。
- guardrails。
- hooks。
- structured output。

适合非文件系统任务，例如规划、总结、memory extraction、模型路由。

### SandboxAgent

`SandboxAgent` 是本产品的关键抽象。它仍然是 agent，但增加 workspace 相关能力：

- `default_manifest`。
- `base_instructions`。
- `capabilities`。
- `run_as`。
- sandbox session 绑定。

适合代码修改、文件分析、测试运行、artifact 生成。

### Manifest

Manifest 定义 fresh sandbox session 的初始 workspace：

- Git repo。
- local files/directories。
- synthetic task files。
- output directory。
- remote storage mounts。
- environment。
- users/groups。
- extra path grants。

产品层必须自己生成可信 manifest，不能让模型决定 host path grant。

### SandboxRunConfig

`SandboxRunConfig` 决定 run 如何拿到 sandbox：

- 创建 fresh session。
- 注入 live session。
- 从 session_state 恢复。
- 从 snapshot 恢复 workspace。

### Sessions

SDK sessions 管理对话历史。注意它和 sandbox session 不同：

- SDK session: conversation history。
- Sandbox session: live filesystem and process environment。

我们的产品两个都需要。

### Memory capability

Sandbox memory 会把 prior runs 的经验提炼到 workspace 文件中，例如：

```text
workspace/
├── sessions/
└── memories/
    ├── memory_summary.md
    ├── MEMORY.md
    └── rollout_summaries/
```

产品层还需要更高层的 Project/User/Team memory。

### MultiProvider 和 adapters

Models 文档里说明可使用：

- OpenAI Responses。
- OpenAI Chat Completions。
- OpenAI-compatible endpoint。
- `ModelProvider`。
- `Agent.model`。
- `MultiProvider`。
- Any-LLM。
- LiteLLM。

产品层要建立 capability matrix，不能假设所有 provider 支持同样工具和 structured outputs。

## 推荐阅读路线

1. 先读 `README.md` 和 `docs/agents.md`。
2. 跑 `examples/basic` 里的 hello world。
3. 读 `docs/models/index.md`，理解 provider 和模型路由。
4. 读 `docs/sessions/index.md`，理解会话状态。
5. 读 `docs/human_in_the_loop.md`，理解 approval resume。
6. 读 `docs/sandbox/guide.md` 和 `docs/sandbox/clients.md`。
7. 跑 `examples/sandbox/unix_local_runner.py`。
8. 跑 sandbox memory example。
9. 再设计我们自己的 platform abstraction。

## 不建议直接做的事

- 不建议直接修改上游 clone 作为产品代码。
- 不建议把 SDK beta sandbox API 暴露给产品外部 API。
- 不建议绕过 approval 让 agent 自动执行网络和删除操作。
- 不建议把所有 memory 都塞进 prompt。
- 不建议假设 LiteLLM 或 Any-LLM provider 都支持 structured output 和 hosted tools。
