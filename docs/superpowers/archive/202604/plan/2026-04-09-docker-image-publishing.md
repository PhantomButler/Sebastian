# Docker 镜像发布 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release workflow 自动构建并发布 Docker 镜像到 GHCR，用户可通过 `docker pull` + `docker run` 一行部署 Sebastian，跳过 Python 环境和 pip 安装。

**Architecture:** 在现有 `release.yml` 的 `publish` job 之前新增 `build-docker` job，基于已有 `Dockerfile` 构建多平台镜像（linux/amd64 + linux/arm64），推送到 `ghcr.io/jaxton07/sebastian`。同时优化 Dockerfile（多阶段构建减小体积、用 uv 替代 pip 加速 CI 和本地构建）、完善 `docker-compose.yml` 安全默认值、补充用户文档。

**Tech Stack:** Docker Buildx, GHCR (GitHub Container Registry), GitHub Actions, uv

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `Dockerfile` | 修改 | 多阶段构建 + uv 替代 pip + 非 root 用户 |
| `docker-compose.yml` | 修改 | 绑定 127.0.0.1 + 从 GHCR 拉镜像 |
| `.github/workflows/release.yml` | 修改 | 新增 build-docker job |
| `.dockerignore` | 创建 | 排除无关文件减小 build context |
| `docs/DEPLOYMENT.md` | 修改 | 新增 Docker 部署路径说明 |
| `CHANGELOG.md` | 修改 | 记录 Docker 镜像发布 |
| `bootstrap.sh` | 修改 | 安装依赖阶段用 uv 替代 pip（有 uv 时） |
| `scripts/install.sh` | 修改 | 安装依赖阶段用 uv 替代 pip（有 uv 时） |

---

## Task 1: 创建 .dockerignore

**Files:**
- Create: `.dockerignore`

目的：减小 build context，避免把 .venv / node_modules / .git 等发送给 Docker daemon。

- [ ] **Step 1: 创建 .dockerignore**

```text
.git
.github
.venv
__pycache__
*.pyc
.env
data/
ui/
docs/
tests/
*.md
!README.md
!CHANGELOG.md
!LICENSE
```

- [ ] **Step 2: Commit**

```bash
git add .dockerignore
git commit -m "chore: 新增 .dockerignore 减小 Docker build context"
```

---

## Task 2: 优化 Dockerfile（多阶段 + uv + 非 root）

**Files:**
- Modify: `Dockerfile`

当前 Dockerfile 是单阶段、用 pip、以 root 运行。改为：
1. Builder 阶段：用 `uv` 安装依赖到独立目录
2. Runtime 阶段：只拷贝安装好的包 + 源码，非 root 用户运行
3. 镜像体积预计从 ~1.2GB 降到 ~400MB

- [ ] **Step 1: 重写 Dockerfile**

```dockerfile
# ---- builder ----
FROM python:3.12-slim AS builder

WORKDIR /build

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml .
COPY sebastian/ ./sebastian/

# Install into a standalone virtual env that we'll copy to runtime
RUN uv venv /opt/venv && \
    UV_PYTHON=/opt/venv/bin/python uv pip install --python /opt/venv/bin/python ".[memory]"

# ---- runtime ----
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -r sebastian && useradd -r -g sebastian -d /app sebastian

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY sebastian/ ./sebastian/
COPY pyproject.toml README.md LICENSE CHANGELOG.md ./
COPY .env.example ./.env.example

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN mkdir -p /app/data/sessions/sebastian /app/data/extensions/skills \
             /app/data/extensions/agents /app/data/workspace && \
    chown -R sebastian:sebastian /app/data

USER sebastian

EXPOSE 8823

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD curl -f http://localhost:8823/api/v1/health || exit 1

CMD ["uvicorn", "sebastian.gateway.app:app", "--host", "0.0.0.0", "--port", "8823"]
```

- [ ] **Step 2: 本地验证构建**

```bash
docker build -t sebastian:test .
docker run --rm -p 8823:8823 -v ~/.sebastian:/app/data sebastian:test
# 验证 http://127.0.0.1:8823/api/v1/health 返回 200
```

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "feat(docker): 多阶段构建 + uv 加速 + 非 root 运行"
```

---

## Task 3: 完善 docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

改动点：
1. 端口绑定 `127.0.0.1:8823:8823`（不暴露到所有网卡）
2. `image:` 指向 GHCR（带 `build:` 作为本地 fallback）
3. 数据目录映射改用命名 volume 或 `~/.sebastian`

- [ ] **Step 1: 重写 docker-compose.yml**

```yaml
services:
  gateway:
    image: ghcr.io/jaxton07/sebastian:latest
    build: .  # fallback: 本地无镜像时从源码构建
    env_file: .env
    environment:
      SEBASTIAN_DATA_DIR: /app/data
      SEBASTIAN_GATEWAY_HOST: "0.0.0.0"
    ports:
      - "127.0.0.1:8823:8823"
    volumes:
      - sebastian-data:/app/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8823/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

volumes:
  sebastian-data:
    driver: local
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(docker): docker-compose 绑 127.0.0.1 + 命名 volume + GHCR 镜像"
```

---

## Task 4: release.yml 新增 build-docker job

**Files:**
- Modify: `.github/workflows/release.yml`

在 `build-backend` 和 `build-android` 平行的位置新增 `build-docker` job，构建多平台镜像推送到 GHCR。

- [ ] **Step 1: 在 release.yml 顶部 permissions 里加 `packages: write`**

当前只有 `contents: write`，GHCR push 需要 `packages: write`。

```yaml
permissions:
  contents: write
  packages: write
```

- [ ] **Step 2: 在 `build-android` job 后面添加 `build-docker` job**

```yaml
  build-docker:
    runs-on: ubuntu-latest
    needs: sync-version
    steps:
      - uses: actions/checkout@v6
        with:
          ref: ${{ needs.sync-version.outputs.tag }}
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: |
            ghcr.io/jaxton07/sebastian:v${{ inputs.version }}
            ghcr.io/jaxton07/sebastian:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

- [ ] **Step 3: publish job 的 needs 加上 build-docker**

```yaml
  publish:
    runs-on: ubuntu-latest
    needs: [build-backend, build-android, build-docker, sync-version]
```

这样 publish 等所有构建（tarball + APK + Docker）都完成后才发 Release。

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "feat(ci): release 自动构建并推送 Docker 镜像到 GHCR"
```

---

## Task 5: bootstrap.sh 和 install.sh 用 uv 加速安装

**Files:**
- Modify: `bootstrap.sh`
- Modify: `scripts/install.sh`

策略：检测 `uv` 是否可用，有则用 `uv pip install`，无则 fallback 到 `pip install`。不强制要求用户安装 uv。

- [ ] **Step 1: 修改 scripts/install.sh 第 44-48 行**

把：
```bash
# 4. 安装依赖
color_ylw "→ 安装依赖（可能需要几分钟）"
pip install --upgrade pip >/dev/null
pip install -e .
color_grn "✓ 依赖安装完成"
```

改为：
```bash
# 4. 安装依赖
color_ylw "→ 安装依赖（可能需要几分钟）"
if command -v uv >/dev/null 2>&1; then
  color_grn "  检测到 uv，使用加速安装"
  uv pip install -e .
else
  pip install --upgrade pip >/dev/null
  pip install -e .
fi
color_grn "✓ 依赖安装完成"
```

- [ ] **Step 2: 测试安装脚本**

```bash
cd /tmp && git clone --depth 1 https://github.com/Jaxton07/Sebastian.git test-install
cd test-install && ./scripts/install.sh
# 验证安装成功
```

- [ ] **Step 3: Commit**

```bash
git add scripts/install.sh
git commit -m "feat(install): 检测 uv 可用时自动加速依赖安装"
```

---

## Task 6: DEPLOYMENT.md 补充 Docker 部署路径

**Files:**
- Modify: `docs/DEPLOYMENT.md`

在「路径 C」之后追加「路径 D：Docker 一行部署」小节，说明：
- `docker pull ghcr.io/jaxton07/sebastian:latest`
- `docker run` 命令（含 volume、env、port）
- 与 Tailscale / Caddy 的配合（和非 Docker 完全一致，只是 backend 跑在容器里）
- `docker-compose up` 的用法

- [ ] **Step 1: 在路径 C 的 `---` 分隔线后、对比速查表前插入**

```markdown
## 路径 D：Docker 一行部署（**适合已有 Docker 环境**）

**适合**：熟悉 Docker、不想管 Python 环境和依赖。

**优点**：
- 零 Python 环境依赖，`docker pull` 即可
- 多平台镜像（amd64 / arm64），NAS、树莓派、云 VPS 通吃
- 升级 = `docker pull` 新版 + 重启容器

**缺点**：
- 需要预装 Docker
- 首次 pull 镜像 ~400MB（之后增量更新）

### 快速启动

\```bash
# 拉取最新镜像
docker pull ghcr.io/jaxton07/sebastian:latest

# 运行（数据持久化到 ~/.sebastian）
docker run -d \
  --name sebastian \
  -p 127.0.0.1:8823:8823 \
  -v ~/.sebastian:/app/data \
  --env-file .env \
  --restart unless-stopped \
  ghcr.io/jaxton07/sebastian:latest

# 或使用 docker compose
docker compose up -d
\```

> Sebastian 容器只监听 `127.0.0.1:8823`，不直接对外暴露。
> 按前面路径 A/B/C 任一方案配置 HTTPS 反代即可，流量链路不变。
```

- [ ] **Step 2: 对比速查表加一列 Docker**

- [ ] **Step 3: Commit**

```bash
git add docs/DEPLOYMENT.md
git commit -m "docs: DEPLOYMENT.md 补充 Docker 一行部署路径"
```

---

## Task 7: CHANGELOG 记录

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 在 `[Unreleased]` 的 `### Added` 下追加**

```markdown
- Docker 镜像自动构建并推送至 GHCR（`ghcr.io/jaxton07/sebastian`），支持
  `docker pull` + `docker run` 一行部署，免 Python 环境。Dockerfile 改为
  多阶段构建 + uv 加速 + 非 root 运行，镜像体积降至 ~400MB。
- `scripts/install.sh` 检测 `uv` 可用时自动使用加速安装。
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: CHANGELOG 记录 Docker 镜像发布与 uv 加速"
```
