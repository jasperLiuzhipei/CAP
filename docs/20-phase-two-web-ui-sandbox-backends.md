# Phase 2 Web UI and Sandbox Backends

## 目标

这一块补齐两个产品化能力：

1. 一个轻量 Web UI 控制台，让用户不用 `curl` 也能操作 Copilot run。
2. 一个 sandbox backend registry，让平台开始从“固定 Unix local sandbox”走向“可切换 sandbox backend”。

## Web UI 控制台

入口：

```bash
PYTHONPATH=src .venv/bin/uvicorn copilot_agent.api.main:app --reload
```

打开：

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/app
```

当前 UI 支持：

- 查看 API runtime config。
- 查看 worker 状态。
- 启动和停止 background worker。
- 创建 project。
- 创建 run。
- 选择 sandbox backend。
- 查看 run summary。
- 查看 RunEvent timeline。
- 查看 artifacts。
- 查看 diff。

这个 UI 不是单独的前端工程，而是 FastAPI 直接返回一个轻量 HTML 页面。这样做的原因是：

- 阶段二重点仍然是后端 Copilot 控制面。
- 不引入 Node/Vite/React 依赖，降低当前验证成本。
- 方便后续把同样 API 接给正式前端。

## Sandbox Backend Registry

新增 `sandbox_backend.py`，用 registry 表达当前和未来的 sandbox backend。

后续第三阶段已经在这个 registry 上继续推进：`SandboxBackend` protocol、
`UnixLocalSandboxBackend` adapter 和 `DockerSandboxBackend` adapter 已经实现，
当前文档仍保留第二阶段产品入口说明。

当前后端：

| Backend | 状态 | 用途 |
| --- | --- | --- |
| `unix_local` | available | 本地开发，使用 OpenAI Agents SDK `UnixLocalSandboxClient` |
| `docker` | available | 容器隔离方向，使用 OpenAI Agents SDK `DockerSandboxClient` |

API：

```bash
curl http://127.0.0.1:8000/api/v1/sandbox/backends
```

`POST /runs` 会校验 `sandbox_backend`。当前 `unix_local` 和 `docker` 都可作为平台 backend 选择；`docker` 真正执行时要求安装 Python `docker` 包、启动 Docker daemon，并选择包含任务所需工具的镜像。

## 和 OpenAI Agents SDK 的关系

这一层仍然不替代 SDK sandbox。

第二阶段刚完成时的执行路径是：

```text
RunWorker
  -> PhaseOneConfig(sandbox_backend="unix_local")
  -> run_phase_one()
  -> OpenAI Agents SDK UnixLocalSandboxClient
  -> SandboxAgent + Runner
```

新增 registry 的价值是把“产品层支持哪些 sandbox 后端”从 `phase_one.py` 里拆出来。第三阶段已经把这条路径推进成：

```text
RunWorker
  -> PhaseOneConfig(sandbox_backend="unix_local")
  -> run_phase_one()
  -> SandboxBackend adapter
  -> OpenAI Agents SDK UnixLocalSandboxClient
  -> SandboxAgent + Runner
```

后续 Docker backend 可以接入同一个 registry、API schema、RunRecord、UI 选择器和 adapter protocol。

第三阶段已经接入：

```text
RunWorker
  -> PhaseOneConfig(sandbox_backend="docker", docker_image="python:3.13-slim")
  -> run_phase_one()
  -> DockerSandboxBackend
  -> OpenAI Agents SDK DockerSandboxClient
  -> SandboxAgent + Runner
```

## 当前边界

- UI 是 MVP 控制台，不是最终前端架构。
- UI 使用轮询和 SSE，不做复杂状态管理。
- `docker` backend 依赖本机 Docker daemon 和镜像环境。
- Docker image 必须包含任务需要的 runtime 工具，例如 Python、pip、pytest、git、node 等。
- Docker backend 当前复用现有 artifact、verification、RunEvent contract，还没有做企业级资源配额策略。

## 下一步

建议继续做 Docker sandbox backend 的生产化增强：

1. 定义 Docker image baseline。
2. 增加 CPU、内存、网络、超时限制。
3. 增加 dependency provisioning/cache 策略。
4. 增加真实 Docker smoke test。
