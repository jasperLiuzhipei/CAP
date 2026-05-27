# Phase 3 Docker Sandbox Backend

## 目标

这一块把 Docker 从 planned backend 推进到可执行 backend。

核心目标不是自研容器执行器，而是把 OpenAI Agents SDK 的
`DockerSandboxClient` 接入我们已经定义好的 `SandboxBackend` protocol。

## 当前能力

新增能力：

- `DockerSandboxBackend`
- `SandboxBackendRunOptions`
- `COPILOT_DOCKER_IMAGE`
- `COPILOT_DOCKER_EXPOSED_PORTS`
- `COPILOT_DOCKER_NETWORK`
- `COPILOT_DOCKER_MEMORY_LIMIT`
- `COPILOT_DOCKER_CPUS`
- `COPILOT_SANDBOX_COMMAND_TIMEOUT_SECONDS`
- CLI 参数 `--docker-image`
- CLI 参数 `--docker-exposed-port`
- CLI 参数 `--docker-network`
- CLI 参数 `--docker-memory-limit`
- CLI 参数 `--docker-cpus`
- API worker runtime config 中的 Docker image、network、resource limits 和 exposed ports

当前执行路径：

```text
CLI / API worker
  -> PhaseOneConfig(sandbox_backend="docker")
  -> DockerSandboxBackend.build_manifest()
  -> DockerSandboxBackend.create_session()
  -> OpenAI Agents SDK DockerSandboxClient
  -> SandboxAgent + Runner
```

## 和 Unix Local Backend 的区别

`unix_local` 使用宿主机 macOS sandbox 和本地临时 workspace。它可以通过
`SandboxPathGrant` 把宿主机 Python runtime 只读授权进 sandbox，用来解决
`encodings` 缺失和 pytest 不稳定问题。

`docker` 使用容器环境。它不应该依赖宿主机 Python path grants，而应该依赖镜像内
已经存在的运行时工具。

因此 Docker backend 的 manifest 会挂载目标 repo，但不会把宿主机 Python roots 加入
`extra_path_grants`。

## 配置

安装可选 Docker 依赖：

```bash
.venv/bin/python -m pip install -e '.[docker]'
```

`.env` 示例：

```env
COPILOT_DOCKER_IMAGE=copilot-agent-python:latest
COPILOT_DOCKER_EXPOSED_PORTS=8000,5173
COPILOT_DOCKER_NETWORK=none
COPILOT_DOCKER_MEMORY_LIMIT=1g
COPILOT_DOCKER_CPUS=2
COPILOT_SANDBOX_COMMAND_TIMEOUT_SECONDS=120
```

构建项目专用镜像：

```bash
docker build -t copilot-agent-python:latest -f docker/copilot-python.Dockerfile .
```

这个 Dockerfile 使用 BuildKit pip cache mount。第一次构建会下载依赖，后续构建会复用缓存和
Docker layer，适合作为项目依赖缓存的第一版。

CLI 示例：

```bash
PYTHONPATH=src .venv/bin/python -m copilot_agent run \
  --repo examples/sample_repo \
  --task "Inspect the sample repo and run tests. Do not modify code unless tests fail." \
  --test-cmd "python -m pytest tests" \
  --provider deepseek \
  --sandbox-backend docker \
  --docker-image copilot-agent-python:latest \
  --docker-network none \
  --docker-memory-limit 1g \
  --docker-cpus 2
```

API 创建 run 时选择 Docker：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "proj_xxx",
    "task": "Inspect the repo and run tests.",
    "sandbox_backend": "docker"
  }'
```

后台 worker 会使用 `.env` 中的 Docker defaults。Web UI 里选择 `docker` backend 后，
run record 会记录 `sandbox_backend=docker`，worker 再读取上述 runtime defaults 来执行。

## Smoke Test

真实 Docker smoke test 默认不跑，避免没有 Docker 的环境失败。需要时显式开启：

```bash
COPILOT_RUN_DOCKER_SMOKE=1 \
COPILOT_DOCKER_IMAGE=copilot-agent-python:latest \
COPILOT_DOCKER_NETWORK=none \
COPILOT_DOCKER_MEMORY_LIMIT=1g \
COPILOT_DOCKER_CPUS=2 \
COPILOT_DOCKER_SMOKE_COMMAND="python -m pytest tests" \
.venv/bin/python -m pytest tests/test_docker_smoke.py
```

也可以直接运行脚本：

```bash
PYTHONPATH=src .venv/bin/python scripts/smoke_docker_backend.py \
  --repo examples/sample_repo \
  --image copilot-agent-python:latest \
  --network none \
  --memory-limit 1g \
  --cpus 2 \
  --command "python -m pytest tests"
```

## 当前边界

- 需要本机 Docker Desktop 或 Docker daemon 已运行。
- 默认镜像 `python:3.13-slim` 适合 Python 小项目，但不一定包含 git、node、系统包或项目依赖。
- CPU、内存和网络策略现在是平台层注入到 Docker SDK `containers.create()` 的参数。
- `COPILOT_DOCKER_NETWORK=none` 会禁用容器网络，适合使用预构建镜像的更安全运行。
- 平台自有的 runtime check、verification、git diff 等命令现在受 sandbox command timeout 控制。
- Agent 自己通过 SDK shell tool 发起的命令仍由 OpenAI Agents SDK 的 tool/runtime 行为控制。
- 项目专用 Dockerfile 已预装 pytest，并通过 BuildKit pip cache 降低重复构建成本。

## 下一步

建议继续做：

1. 在 UI 中展示 Docker image、network 和 resource defaults。
2. 增加依赖缓存或多语言预构建镜像。
3. 增加 run-level resource policy。
4. 增加 CI 中可选 Docker smoke job。
