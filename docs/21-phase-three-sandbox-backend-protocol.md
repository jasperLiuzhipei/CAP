# Phase 3 Sandbox Backend Protocol

## 目标

这一块先完成两个基础动作：

1. 定义正式的 `SandboxBackend` protocol。
2. 把当前可运行的 OpenAI Agents SDK `UnixLocalSandboxClient` 收口到
   `UnixLocalSandboxBackend` adapter。

这一步不是重写 sandbox，而是把平台自己的“后端选择和生命周期管理”从
`phase_one.py` 中抽出来。

## 当前代码结构

核心文件：

- `src/copilot_agent/sandbox_backend.py`
- `src/copilot_agent/phase_one.py`

`sandbox_backend.py` 现在包含三层内容：

- `SandboxBackendSpec`：给 API 和 UI 展示的 backend 元数据。
- `SandboxBackend`：平台内部使用的 backend protocol。
- `UnixLocalSandboxBackend`：当前实际可执行的 adapter。

## 执行链路

当前运行路径是：

```text
API / CLI
  -> PhaseOneConfig(sandbox_backend="unix_local")
  -> run_phase_one()
  -> get_sandbox_backend_adapter("unix_local")
  -> UnixLocalSandboxBackend.build_manifest()
  -> UnixLocalSandboxBackend.create_session()
  -> OpenAI Agents SDK SandboxAgent + Runner
  -> UnixLocalSandboxBackend.delete_session()
```

## 为什么仍然符合 OpenAI Agents SDK 理念

我们没有替换 SDK 的核心模型。

保留的 SDK 原生能力：

- `Manifest` 仍然声明 workspace。
- `LocalDir` 仍然负责把目标 repo 挂进 sandbox。
- `SandboxPathGrant` 仍然负责 Python runtime 只读授权。
- `SandboxAgent` 仍然承载 agent 指令、模型和 capabilities。
- `Runner.run()` 仍然执行 agent loop。
- `SandboxRunConfig(session=...)` 仍然把 sandbox session 交给 SDK runtime。

我们新增的是平台层抽象：

- 哪些 backend 可选。
- backend 是否可执行。
- backend 如何创建 manifest。
- backend 如何创建和销毁 session。

换句话说，OpenAI Agents SDK 仍是 agent execution engine；我们的平台层负责产品化编排。

## 已完成

- `SandboxBackend` protocol。
- `SandboxSessionHandle`。
- `UnixLocalSandboxBackend`。
- planned `docker` backend adapter 占位。
- `run_phase_one()` 改为通过 adapter 创建和销毁 session。
- 单元测试覆盖 manifest 构造、session lifecycle 和 planned backend 不可执行行为。

## 下一步

下一块建议做 `DockerSandboxBackend` 第一版设计和实现：

- Docker 临时 workspace mount。
- 只读/读写目录边界。
- Python 依赖 provisioning 策略。
- 网络默认关闭或可配置。
- CPU、内存、超时限制。
- verification 和 artifact 继续复用现有 RunEvent/report contract。
