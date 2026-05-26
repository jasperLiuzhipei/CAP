# Phase 1: Local Sandbox CLI

本阶段目标是先跑通一个最小 Copilot vertical slice，而不是马上做完整平台。

## 目标链路

```text
repo path + task
-> Manifest(LocalDir -> repo/)
-> SandboxAgent
-> UnixLocalSandboxClient
-> Runner.run
-> git diff + final summary + optional verification
```

这个实现刻意贴着 `openai-agents-python` 的 sandbox 示例：

- 用 `Manifest(entries={"repo": LocalDir(src=...)})` 声明 workspace。
- 用 `SandboxAgent` 定义 coding agent。
- OpenAI 原生路径用 `Capabilities.default()` 暴露 shell、filesystem、compaction 等默认 sandbox 能力。
- Chat Completions 兼容路径默认用函数工具版 `apply_patch` 加 `Shell`，不能使用原生 Responses-only 工具时仍保留可审计 patch 流程。
- 用 developer-owned sandbox lifecycle，这样 run 后可以在同一个 sandbox 里收集 diff 和验证结果。
- 用 `ResolvedModelConfig` 管理 provider/model/key/base URL，OpenAI 走原生 model string，第三方 provider 走 `OpenAIChatCompletionsModel`。
- 默认用 `RunConfig(tracing_disabled=True)` 让本地 PoC 不依赖 tracing 配置。
- 默认 `max_turns=32`，给 Chat Completions 兼容模型留出足够工具调用回合；prompt 会要求模型保持 inspect -> patch -> verify -> final 的短循环。
- 用 project memory 把长期上下文放在 `.copilot/memory.md`，并在 prompt 中作为背景上下文输入。
- 用 `runs/` 保存 report、diff、verification，再由 `apply-run` 经过 `git apply --check` 后应用回真实仓库。

## 安装

当前机器还没有安装 `agents` 依赖。运行真实 agent 前先执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

如果你在本地单独 clone 了 `openai/openai-agents-python` 并希望基于源码调试 SDK，可以改用：

```bash
python -m pip install -e openai-agents-python
python -m pip install -e .
```

然后编辑 `.env`，低成本开发可以先用 DeepSeek：

```env
COPILOT_MODEL_PROVIDER=deepseek
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=<your-deepseek-api-key>
```

`.env` 已经被 `.gitignore` 忽略，不会进入版本库。

如果只是看 CLI 生成的 prompt，不需要安装 SDK：

```bash
PYTHONPATH=src python3 -m copilot_agent run \
  --repo examples/sample_repo \
  --task "Fix the discount calculation bug and run tests." \
  --test-cmd "python -m pytest" \
  --dry-run
```

## 运行真实任务

```bash
copilot-agent run \
  --repo /path/to/repo \
  --task "Fix the failing login test with the smallest safe change." \
  --test-cmd "python -m pytest tests/login" \
  --provider deepseek \
  --tool-strategy compat_functions \
  --model deepseek-v4-flash
```

运行完成后 CLI 会打印：

- final output。
- sandbox 内的 `git status --short`。
- sandbox 内的 `git diff`。
- 可选 verification 命令输出。
- 保存目录，例如 `runs/run_20260521_123456/`。

## Copilot 工作流命令

初始化目标仓库：

```bash
copilot-agent init --repo /path/to/repo
```

启用 memory 运行：

```bash
copilot-agent run \
  --repo /path/to/repo \
  --task "Refactor the parser and keep tests passing." \
  --test-cmd "python -m pytest" \
  --memory \
  --host-verify
```

查看历史 run：

```bash
copilot-agent runs
copilot-agent show-run --run run_20260521_123456_000000 --diff --final
```

把 sandbox diff 应用回真实仓库：

```bash
copilot-agent apply-run --run run_20260521_123456_000000 --check
copilot-agent apply-run --run run_20260521_123456_000000
```

`--host-verify` 会把 sandbox diff 应用到临时 repo 副本，再在沙箱外运行验证命令。它用于解决本地 macOS sandbox 中系统 Python 或 Anaconda Python 被文件系统限制阻断的问题，同时仍然避免直接污染真实仓库。

## 当前边界

- 这是本地 PoC，默认使用 `UnixLocalSandboxClient`。
- 还没有实现 approval policy，高风险命令控制会在阶段 3 做。
- 还没有实现 Web UI、数据库、长期 memory。
- 已有本地 project memory，但还不是向量库或跨项目检索。
- 本地 macOS `UnixLocalSandboxClient` 可能无法运行系统 Python；此时优先使用 `--host-verify`，生产环境建议迁移到 Docker sandbox 或 hosted sandbox。
- 如果输入目录不是 git repo，CLI 会在 sandbox 副本里初始化临时 git baseline，方便收集 diff；默认不会修改宿主机目录，只有执行 `apply-run` 才会应用修改。
