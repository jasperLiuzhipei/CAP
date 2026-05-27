# Phase 2 Sandbox Runtime Provisioning

## 为什么要做这一块

之前本地 macOS `UnixLocalSandboxClient` 里出现过一个关键问题：

```text
Fatal Python error: Failed to import encodings module
ModuleNotFoundError: No module named 'encodings'
```

根因不是 Python 本身坏了，而是 macOS sandbox 默认只允许读取 workspace、少量系统路径和命令本身。Python 可执行文件可以启动，但它需要读取的标准库目录、venv 目录、base prefix 没有被授权，所以启动后无法加载 `encodings`。

这说明 Copilot 平台不能直接把用户传入的宿主机验证命令塞进 sandbox 执行。平台必须有一层 runtime provisioning。

## 当前实现

新增能力集中在 `phase_one.py`：

- `PhaseOneConfig.sandbox_runtime_enabled`：默认开启 sandbox runtime provisioning。
- `PhaseOneConfig.sandbox_python`：默认使用 `python3` 作为 sandbox 内 Python 命令。
- `SandboxRuntimeReport`：记录 runtime health check、pytest check、依赖安装结果、原始命令和 sandbox-safe 命令。
- `Manifest.extra_path_grants`：为 Python runtime roots 增加只读授权。
- `sandbox_runtime.log`：每次 run 保存 runtime 检查日志。
- `RunEvent`：新增 `sandbox.runtime_checked` 和 `verification.completed`。

## 命令归一化

如果用户传入：

```bash
/Users/jasperliuzp/my_python_project/copilot_agent/.venv/bin/python -m pytest tests
```

sandbox 内会归一化为：

```bash
PYTEST_ADDOPTS="-p no:debugging ${PYTEST_ADDOPTS:-}" \
PYTHONPATH="../.copilot-runtime/site:${PYTHONPATH:-}" \
sh -c 'python3 -m pytest tests'
```

这么做有两个目的：

- 避免 sandbox 直接执行宿主机绝对路径 venv Python。
- 避免 pytest debugging plugin 在 macOS sandbox 中加载 `pdb/readline` 时触发崩溃。

host verification 仍然使用用户原始命令，因为它运行在隔离临时仓库副本里，不受 SDK sandbox 的 macOS 文件读取策略限制。

## 依赖 provisioning

当前实现是轻量版：

- 先检查 sandbox Python 是否能 `import encodings`。
- 如果验证命令使用 pytest，再检查是否能 `import pytest`。
- 如果 pytest 缺失，尝试安装到 workspace 内的 `.copilot-runtime/site`。
- 验证命令自动把 `../.copilot-runtime/site` 加入 `PYTHONPATH`。

这解决了本地 sample repo 的稳定验证问题，也为后续项目级依赖安装打下接口。

## 和 OpenAI Agents SDK 的关系

这仍然符合 `openai-agents-python` 的设计理念。

SDK 负责：

- `SandboxAgent`
- `Manifest`
- `LocalDir`
- `SandboxRunConfig`
- sandbox session lifecycle
- tool execution

我们补的是产品工程层：

- 生成更完整的 sandbox manifest。
- 给 runtime 依赖加只读授权。
- 把宿主机命令归一化成 sandbox-safe 命令。
- 把 runtime 和 verification 结果持久化成 artifact 和 RunEvent。

也就是说，我们没有绕开 SDK sandbox，而是更正确地使用它的 manifest 和 path grant 能力。

## 验证结果

已验证之前失败的命令形态：

```bash
/Users/jasperliuzp/my_python_project/copilot_agent/.venv/bin/python -m pytest tests
```

在 sandbox 内会被改写后执行，并通过 sample repo 测试：

```text
python_check=0
verification_exit=0
1 passed
```

## 后续增强

API 级 AI run 入口已在 [Phase 2 API AI Run](19-phase-two-api-ai-run.md) 中补齐。

下一步可以继续做更完整的 dependency provisioning：

1. 读取 `requirements.txt`、`pyproject.toml`、`uv.lock`、`poetry.lock`。
2. 生成 dependency install plan，而不是立刻安装。
3. 支持 `uv sync`、`pip install -r requirements.txt`、`npm install` 等多语言运行时。
4. 把 Docker sandbox backend 接进同一个 runtime provisioning 接口。
5. 给每个 runtime step 增加超时、缓存和安全策略。
