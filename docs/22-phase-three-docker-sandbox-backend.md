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
- CLI 参数 `--docker-image`
- CLI 参数 `--docker-exposed-port`
- API worker runtime config 中的 Docker image 和 exposed ports

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
COPILOT_DOCKER_IMAGE=python:3.13-slim
COPILOT_DOCKER_EXPOSED_PORTS=8000,5173
```

CLI 示例：

```bash
PYTHONPATH=src .venv/bin/python -m copilot_agent run \
  --repo examples/sample_repo \
  --task "Inspect the sample repo and run tests. Do not modify code unless tests fail." \
  --test-cmd "python -m pytest tests" \
  --provider deepseek \
  --sandbox-backend docker \
  --docker-image python:3.13-slim
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

后台 worker 会使用 `.env` 中的 Docker defaults。

## 当前边界

- 需要本机 Docker Desktop 或 Docker daemon 已运行。
- 默认镜像 `python:3.13-slim` 适合 Python 小项目，但不一定包含 git、node、系统包或项目依赖。
- Docker backend 当前还没有 CPU、内存、网络、超时等生产级策略。
- 真实 Docker smoke test 需要本机 Docker 环境，因此当前单元测试用 fake SDK client 验证 adapter contract。

## 下一步

建议继续做：

1. 提供项目专用 Copilot Dockerfile。
2. 增加 Docker smoke test，环境不可用时自动 skip。
3. 增加资源限制和网络策略。
4. 增加依赖缓存或预构建镜像。
5. 在 UI 中展示 Docker image 与运行环境提示。
