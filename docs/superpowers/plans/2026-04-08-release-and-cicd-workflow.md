# Sebastian 发布与 CI/CD 工作流实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Sebastian 从"个人工作仓库"升级为准开源工程形态：引入完整 CI/CD、一键安装、友好首次配置、分支保护与 PR 规范。

**Architecture:** 五个阶段串行推进。Phase 1 打底 CI 门禁与分支规则；Phase 2 改造 auth 让 owner/secret 入 store + 单文件，加 setup mode 与 Web 向导；Phase 3 写 install.sh 与 bootstrap.sh；Phase 4 接入 release.yml 打 Android keystore 发首个版本；Phase 5 同步文档。

**Tech Stack:** GitHub Actions、FastAPI、SQLAlchemy async、Typer、bash、Gradle (Android)、keytool、shasum、ruff/mypy/pytest

**Spec:** `docs/superpowers/specs/2026-04-08-release-and-cicd-workflow-design.md`

---

## 文件结构（全量）

### Phase 1 新增
```
.github/workflows/ci.yml                    # PR / push 质量门禁
.github/ISSUE_TEMPLATE/bug_report.md        # Bug 模板
.github/ISSUE_TEMPLATE/feature_request.md   # Feature 模板
.github/ISSUE_TEMPLATE/config.yml           # 禁用空白 issue
.github/PULL_REQUEST_TEMPLATE.md            # PR 模板
.github/CODEOWNERS                          # 代码所有者
.github/dependabot.yml                      # 依赖更新
```

### Phase 2 新增/修改
```
新增:
  sebastian/gateway/setup/__init__.py       # 包导出
  sebastian/gateway/setup/setup_routes.py   # /setup/* 路由 + 内嵌 HTML
  sebastian/gateway/setup/security.py       # setup token + 127.0.0.1 限制
  sebastian/cli/__init__.py                 # CLI 包
  sebastian/cli/init_wizard.py              # sebastian init --headless
  tests/unit/test_setup_security.py
  tests/unit/test_setup_routes.py
  tests/unit/test_auth_from_store.py
  tests/integration/test_setup_flow.py

修改:
  sebastian/gateway/auth.py                 # owner from store, jwt secret from file
  sebastian/gateway/app.py                  # 启动时检测 owner → setup mode 分支
  sebastian/gateway/routes/turns.py         # /auth/login 改为从 store 查 owner
  sebastian/main.py                         # 替换老 init 命令为向导、接入 CLI 包
  sebastian/config/__init__.py              # 新增 secret_key_path 配置项
  sebastian/store/__init__.py               # 若缺 owner 查询 helper 则补充
  .gitignore                                # 排除 secret.key
```

### Phase 3 新增
```
bootstrap.sh                                # 一键安装脚本（仓库根目录）
scripts/install.sh                          # 解压后的安装入口
```

### Phase 4 新增/修改
```
新增:
  .github/workflows/release.yml             # 发版流水线
  android/app/build.gradle 相关签名配置     # 通过 env 读 keystore

修改:
  pyproject.toml                            # 被 release workflow 改写 version
  ui/mobile/app.json                        # 被 release workflow 改写 version
```

### Phase 5 新增/修改
```
新增:
  CHANGELOG.md                              # Keep a Changelog 格式
  LICENSE                                   # Apache-2.0

修改:
  README.md                                 # 面向用户的安装说明
  CLAUDE.md                                 # §3 启动、§6 env、§11 PR 流程
  sebastian/README.md                       # 启动命令更新
```

---

# Phase 1：基础 CI/CD 骨架与分支保护

**目标**：所有未来 PR 自动跑 lint/type/test 门禁；有 PR/Issue 模板；main 分支被保护。

### Task 1.1：创建 `.github/workflows/ci.yml`

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1：创建 workflow 文件**

```yaml
name: CI

on:
  pull_request:
    branches: [main, dev]
  push:
    branches: [dev]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  backend-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install ruff
        run: pip install "ruff>=0.8"
      - name: Ruff check
        run: ruff check sebastian/ tests/
      - name: Ruff format check
        run: ruff format --check sebastian/ tests/

  backend-type:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install project
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev,memory]"
      - name: Mypy
        run: mypy sebastian/

  backend-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install project
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev,memory]"
      - name: Pytest
        run: pytest tests/unit tests/integration -v

  mobile-lint:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ui/mobile
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: ui/mobile/package-lock.json
      - name: Install deps
        run: npm ci --legacy-peer-deps
      - name: TypeScript check
        run: npx tsc --noEmit
```

- [ ] **Step 2：提交**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: 新增 backend lint/type/test + mobile lint 质量门禁 workflow"
```

---

### Task 1.2：创建 PR 模板

**Files:**
- Create: `.github/PULL_REQUEST_TEMPLATE.md`

- [ ] **Step 1：写模板**

```markdown
## Summary
<!-- 改了什么、为什么改（1-3 条要点） -->

## Test plan
<!-- 验证步骤 checklist -->
- [ ]
- [ ]

## Related
<!-- 关联 Issue / Spec / PR，例如 closes #123 -->
```

- [ ] **Step 2：提交**

```bash
git add .github/PULL_REQUEST_TEMPLATE.md
git commit -m "chore: 新增 PR 模板"
```

---

### Task 1.3：创建 Issue 模板

**Files:**
- Create: `.github/ISSUE_TEMPLATE/bug_report.md`
- Create: `.github/ISSUE_TEMPLATE/feature_request.md`
- Create: `.github/ISSUE_TEMPLATE/config.yml`

- [ ] **Step 1：bug_report.md**

```markdown
---
name: Bug report
about: 报告一个 bug
title: "[BUG] "
labels: bug
---

## 问题描述

## 复现步骤
1.
2.

## 期望行为

## 实际行为

## 环境
- Sebastian 版本:
- OS:
- Python 版本:
- 相关日志:
```

- [ ] **Step 2：feature_request.md**

```markdown
---
name: Feature request
about: 提议一个新功能
title: "[FEAT] "
labels: enhancement
---

## 需求背景

## 建议方案

## 替代方案

## 额外上下文
```

- [ ] **Step 3：config.yml**

```yaml
blank_issues_enabled: false
```

- [ ] **Step 4：提交**

```bash
git add .github/ISSUE_TEMPLATE/
git commit -m "chore: 新增 bug/feature issue 模板并禁用空白 issue"
```

---

### Task 1.4：创建 CODEOWNERS 与 dependabot

**Files:**
- Create: `.github/CODEOWNERS`
- Create: `.github/dependabot.yml`

- [ ] **Step 1：CODEOWNERS**

```
# 默认所有文件归 Jaxton07 审查
*       @Jaxton07
```

- [ ] **Step 2：dependabot.yml**

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
    commit-message:
      prefix: "chore(deps)"
    ignore:
      - dependency-name: "*"
        update-types: ["version-update:semver-major"]

  - package-ecosystem: "npm"
    directory: "/ui/mobile"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
    commit-message:
      prefix: "chore(deps-mobile)"
    ignore:
      - dependency-name: "*"
        update-types: ["version-update:semver-major"]

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "monthly"
    open-pull-requests-limit: 3
    commit-message:
      prefix: "chore(ci)"
```

- [ ] **Step 3：提交**

```bash
git add .github/CODEOWNERS .github/dependabot.yml
git commit -m "chore: 新增 CODEOWNERS 与 Dependabot 每周依赖扫描"
```

---

### Task 1.5：推送 dev 分支，验证 CI 能跑起来

- [ ] **Step 1：推送并开一个 draft PR 触发 CI**

```bash
git push origin dev
gh pr create --base main --head dev --draft \
  --title "ci: 引入质量门禁与仓库模板（Phase 1 骨架）" \
  --body "$(cat <<'EOF'
## Summary
- 新增 ci.yml：backend lint/type/test + mobile TS 检查
- 新增 PR/Issue 模板、CODEOWNERS、Dependabot

## Test plan
- [ ] GitHub Actions 上 4 个 job 全部绿
- [ ] PR 页面自动加载 PR 模板

## Related
spec: docs/superpowers/specs/2026-04-08-release-and-cicd-workflow-design.md
EOF
)"
```

- [ ] **Step 2：等 CI 跑完并验证**

```bash
gh pr checks --watch
```
Expected：`backend-lint` `backend-type` `backend-test` `mobile-lint` 四项全部 ✓。若失败需先修复到全绿再进行下一步。

- [ ] **Step 3：配置 main 分支保护规则**

**手动操作**（通过 GitHub Web UI 完成，没有可提交的代码）：

1. 打开 `https://github.com/Jaxton07/Sebastian/settings/branches`
2. Add branch protection rule → Branch name pattern: `main`
3. 勾选：
   - ✅ Require a pull request before merging
   - ✅ Require approvals: 1
   - ✅ Dismiss stale pull request approvals when new commits are pushed
   - ✅ Require status checks to pass before merging
   - ✅ Require branches to be up to date before merging
   - Required checks（输入名称）：`backend-lint` `backend-type` `backend-test` `mobile-lint`
   - ✅ Do not allow bypassing the above settings（暂不勾，因为后面需要 admin + bot bypass）
   - ❌ Allow force pushes
   - ❌ Allow deletions
4. Allowed merge methods：仅保留 `Squash`（仓库级 Settings → General → Pull Requests）
5. 在 "Restrict pushes that create matching branches" / "Allow specified actors to bypass required pull requests" 里加：`Jaxton07`（admin），`github-actions[bot]` 留到 Phase 4 加（那时 release workflow 才需要）

6. Add branch protection rule → Branch name pattern: `v*.*.*`（tag 保护）
7. 勾选：
   - ✅ Restrict who can create matching tags
   - Allowed：`Jaxton07` + 预留位置给 `github-actions[bot]`
   - ❌ Allow force pushes
   - ❌ Allow deletions

- [ ] **Step 4：记录配置完成**

无代码提交。在 PR 对话里评论 "Branch protection 配置完成" 作为时间戳。

- [ ] **Step 5：Merge PR（使用 squash）**

```bash
gh pr ready
gh pr merge --squash --delete-branch=false
```
**注意**：不删除 `dev` 分支，它是长期分支。`--delete-branch=false` 显式保留。

- [ ] **Step 6：同步本地 main**

```bash
git fetch origin
git checkout main
git pull origin main
git checkout dev
git rebase origin/main
git push -u origin dev
```

---

# Phase 2：首次配置 UX

**目标**：auth 层彻底从 env 解耦；启动时检测 owner 不存在则进入 setup mode；Web 向导完成 owner 创建 + JWT secret 生成；CLI 兜底。

**重要**：本 Phase 改动跨多个文件且互相依赖，请严格按任务顺序执行。每个 task 都跟 TDD：先写测试，再改实现。

### Task 2.1：`.gitignore` 加 `secret.key` 排除

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1：追加一行**

```bash
# 在文件末尾追加
echo "" >> .gitignore
echo "# Sebastian runtime secrets" >> .gitignore
echo "secret.key" >> .gitignore
echo ".sebastian/" >> .gitignore
```

- [ ] **Step 2：提交**

```bash
git add .gitignore
git commit -m "chore: gitignore 排除 secret.key 与 .sebastian/ 运行时目录"
```

---

### Task 2.2：新增 `secret_key_path` 配置项

**Files:**
- Modify: `sebastian/config/__init__.py`

- [ ] **Step 1：读现有 config**

```bash
# 看清楚当前 Settings 字段
```

运行：`cat sebastian/config/__init__.py`

- [ ] **Step 2：添加 secret_key_path 字段**

在 `class Settings` 的合适位置（jwt 相关字段附近）添加：

```python
sebastian_secret_key_path: str = ""  # 留空表示使用 data_dir/secret.key
```

添加计算属性方法：

```python
def resolved_secret_key_path(self) -> Path:
    from pathlib import Path

    if self.sebastian_secret_key_path:
        return Path(self.sebastian_secret_key_path).expanduser()
    return Path(self.sebastian_data_dir).expanduser() / "secret.key"
```

**注意**：若文件顶部没有 `from pathlib import Path`，在顶部添加。`sebastian_data_dir` 如果现在不存在也需要添加：

```python
sebastian_data_dir: str = "~/.sebastian"
```

- [ ] **Step 3：单元测试**

Create: `tests/unit/test_config_secret_path.py`

```python
from __future__ import annotations

from pathlib import Path

from sebastian.config import Settings


def test_secret_key_path_default_uses_data_dir() -> None:
    s = Settings(sebastian_data_dir="/tmp/sebx")
    assert s.resolved_secret_key_path() == Path("/tmp/sebx/secret.key")


def test_secret_key_path_explicit_override() -> None:
    s = Settings(
        sebastian_data_dir="/tmp/sebx",
        sebastian_secret_key_path="/etc/sebastian/secret.key",
    )
    assert s.resolved_secret_key_path() == Path("/etc/sebastian/secret.key")


def test_secret_key_path_expands_tilde() -> None:
    s = Settings(sebastian_secret_key_path="~/custom/secret.key")
    assert s.resolved_secret_key_path() == Path("~/custom/secret.key").expanduser()
```

- [ ] **Step 4：运行测试**

Run: `pytest tests/unit/test_config_secret_path.py -v`
Expected: 3 passed

- [ ] **Step 5：提交**

```bash
git add sebastian/config/__init__.py tests/unit/test_config_secret_path.py
git commit -m "feat(config): 新增 secret_key_path 配置与路径解析"
```

---

### Task 2.3：新增 `SecretKeyManager` —— 生成/读取 jwt secret 文件

**Files:**
- Create: `sebastian/gateway/setup/__init__.py`
- Create: `sebastian/gateway/setup/secret_key.py`
- Create: `tests/unit/test_secret_key_manager.py`

- [ ] **Step 1：写失败测试**

`tests/unit/test_secret_key_manager.py`:

```python
from __future__ import annotations

import os
from pathlib import Path

import pytest

from sebastian.gateway.setup.secret_key import SecretKeyManager


def test_generate_creates_file_with_600_permission(tmp_path: Path) -> None:
    target = tmp_path / "secret.key"
    mgr = SecretKeyManager(target)

    key = mgr.generate()

    assert target.exists()
    assert len(key) >= 32
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600


def test_generate_is_idempotent_refuses_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "secret.key"
    mgr = SecretKeyManager(target)
    mgr.generate()

    with pytest.raises(FileExistsError):
        mgr.generate()


def test_read_returns_persisted_key(tmp_path: Path) -> None:
    target = tmp_path / "secret.key"
    mgr = SecretKeyManager(target)
    generated = mgr.generate()

    assert mgr.read() == generated


def test_read_raises_when_missing(tmp_path: Path) -> None:
    mgr = SecretKeyManager(tmp_path / "nope.key")

    with pytest.raises(FileNotFoundError):
        mgr.read()


def test_exists_reflects_file_presence(tmp_path: Path) -> None:
    target = tmp_path / "secret.key"
    mgr = SecretKeyManager(target)

    assert mgr.exists() is False
    mgr.generate()
    assert mgr.exists() is True


def test_generate_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "secret.key"
    mgr = SecretKeyManager(target)

    mgr.generate()

    assert target.exists()
```

- [ ] **Step 2：运行测试（应该失败）**

Run: `pytest tests/unit/test_secret_key_manager.py -v`
Expected: FAIL with ImportError or ModuleNotFoundError

- [ ] **Step 3：实现 `sebastian/gateway/setup/__init__.py`**

```python
"""Setup mode package: first-run wizard and secret key provisioning."""
```

- [ ] **Step 4：实现 `sebastian/gateway/setup/secret_key.py`**

```python
from __future__ import annotations

import os
import secrets
from pathlib import Path


class SecretKeyManager:
    """Manage the JWT signing secret stored at a single file (chmod 600)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def generate(self) -> str:
        if self._path.exists():
            raise FileExistsError(f"Secret key already exists at {self._path}")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(32)
        # Write with restrictive permissions atomically
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(self._path, flags, 0o600)
        try:
            os.write(fd, key.encode("utf-8"))
        finally:
            os.close(fd)
        return key

    def read(self) -> str:
        if not self._path.exists():
            raise FileNotFoundError(f"Secret key not found at {self._path}")
        return self._path.read_text(encoding="utf-8").strip()
```

- [ ] **Step 5：运行测试（应该通过）**

Run: `pytest tests/unit/test_secret_key_manager.py -v`
Expected: 6 passed

- [ ] **Step 6：提交**

```bash
git add sebastian/gateway/setup/__init__.py sebastian/gateway/setup/secret_key.py tests/unit/test_secret_key_manager.py
git commit -m "feat(setup): SecretKeyManager 负责生成/读取 JWT 签名密钥单文件"
```

---

### Task 2.4：新增 store-side `OwnerStore` helper

**Files:**
- Create: `sebastian/store/owner_store.py`
- Create: `tests/unit/test_owner_store.py`

**背景**：[sebastian/store/models.py:62](sebastian/store/models.py#L62) 已有 `UserRecord`，本任务只新增一个薄 helper。

- [ ] **Step 1：写测试**

`tests/unit/test_owner_store.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.store.database import Database
from sebastian.store.owner_store import OwnerStore


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(url=f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await database.init()
    return database


@pytest.mark.asyncio
async def test_owner_exists_false_on_empty_db(db: Database) -> None:
    store = OwnerStore(db)
    assert await store.owner_exists() is False


@pytest.mark.asyncio
async def test_create_owner_then_exists_true(db: Database) -> None:
    store = OwnerStore(db)

    await store.create_owner(name="Eric", password_hash="$2b$12$fakehash")

    assert await store.owner_exists() is True


@pytest.mark.asyncio
async def test_get_owner_returns_record(db: Database) -> None:
    store = OwnerStore(db)
    await store.create_owner(name="Eric", password_hash="$2b$12$fakehash")

    owner = await store.get_owner()

    assert owner is not None
    assert owner.name == "Eric"
    assert owner.password_hash == "$2b$12$fakehash"
    assert owner.role == "owner"


@pytest.mark.asyncio
async def test_get_owner_none_when_empty(db: Database) -> None:
    store = OwnerStore(db)
    assert await store.get_owner() is None


@pytest.mark.asyncio
async def test_create_owner_refuses_second_owner(db: Database) -> None:
    store = OwnerStore(db)
    await store.create_owner(name="Eric", password_hash="$2b$12$a")

    with pytest.raises(ValueError, match="owner already exists"):
        await store.create_owner(name="Bob", password_hash="$2b$12$b")
```

- [ ] **Step 2：运行测试**

Run: `pytest tests/unit/test_owner_store.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3：实现 `sebastian/store/owner_store.py`**

```python
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from sebastian.store.database import Database
from sebastian.store.models import UserRecord


class OwnerStore:
    """Thin helper around UserRecord scoped to the single-owner account."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def owner_exists(self) -> bool:
        async with self._db.session() as session:
            stmt = select(UserRecord).where(UserRecord.role == "owner").limit(1)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def get_owner(self) -> UserRecord | None:
        async with self._db.session() as session:
            stmt = select(UserRecord).where(UserRecord.role == "owner").limit(1)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def create_owner(self, *, name: str, password_hash: str) -> UserRecord:
        if await self.owner_exists():
            raise ValueError("owner already exists")

        async with self._db.session() as session:
            record = UserRecord(
                id=str(uuid4()),
                name=name,
                password_hash=password_hash,
                role="owner",
                created_at=datetime.now(UTC),
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record
```

**注意**：查看 [sebastian/store/database.py](sebastian/store/database.py) 确认 `Database` 类的 `session()` / `init()` 方法签名是否匹配。如果签名不同，按实际签名调整。

- [ ] **Step 4：运行测试**

Run: `pytest tests/unit/test_owner_store.py -v`
Expected: 5 passed

- [ ] **Step 5：提交**

```bash
git add sebastian/store/owner_store.py tests/unit/test_owner_store.py
git commit -m "feat(store): 新增 OwnerStore 包装 UserRecord 的 owner 单账号操作"
```

---

### Task 2.5：重构 `auth.py` —— secret 从文件读

**Files:**
- Modify: `sebastian/gateway/auth.py`
- Create: `tests/unit/test_auth_secret_source.py`

- [ ] **Step 1：写测试**

`tests/unit/test_auth_secret_source.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.gateway.auth import JwtSigner


def test_signer_reads_secret_from_file(tmp_path: Path) -> None:
    key_file = tmp_path / "secret.key"
    key_file.write_text("file-secret-abc")

    signer = JwtSigner(secret_key_path=key_file, algorithm="HS256", expire_minutes=60)
    token = signer.encode({"sub": "eric"})
    payload = signer.decode(token)

    assert payload["sub"] == "eric"


def test_signer_falls_back_to_env_secret_when_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "absent.key"

    signer = JwtSigner(
        secret_key_path=missing,
        algorithm="HS256",
        expire_minutes=60,
        fallback_secret="env-secret",
    )
    token = signer.encode({"sub": "eric"})
    assert signer.decode(token)["sub"] == "eric"


def test_signer_refuses_when_no_secret_at_all(tmp_path: Path) -> None:
    missing = tmp_path / "absent.key"

    with pytest.raises(RuntimeError, match="No JWT secret available"):
        JwtSigner(
            secret_key_path=missing,
            algorithm="HS256",
            expire_minutes=60,
            fallback_secret="",
        )
```

- [ ] **Step 2：运行测试**

Run: `pytest tests/unit/test_auth_secret_source.py -v`
Expected: FAIL (JwtSigner not defined)

- [ ] **Step 3：重构 `sebastian/gateway/auth.py`**

```python
# mypy: disable-error-code=import-untyped

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from sebastian.config import settings

_pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
_bearer = HTTPBearer()


def hash_password(password: str) -> str:
    return cast(str, _pwd_context.hash(password))


def verify_password(plain: str, hashed: str) -> bool:
    return cast(bool, _pwd_context.verify(plain, hashed))


class JwtSigner:
    """Encapsulates JWT encode/decode with secret loaded from file or env fallback."""

    def __init__(
        self,
        *,
        secret_key_path: Path,
        algorithm: str,
        expire_minutes: int,
        fallback_secret: str = "",
    ) -> None:
        self._algorithm = algorithm
        self._expire_minutes = expire_minutes

        if secret_key_path.exists():
            self._secret = secret_key_path.read_text(encoding="utf-8").strip()
        elif fallback_secret:
            self._secret = fallback_secret
        else:
            raise RuntimeError(
                f"No JWT secret available (file {secret_key_path} missing and "
                "no fallback provided)"
            )

    def encode(self, payload: dict[str, Any]) -> str:
        data = payload.copy()
        data["exp"] = datetime.now(UTC) + timedelta(minutes=self._expire_minutes)
        return cast(str, jwt.encode(data, self._secret, algorithm=self._algorithm))

    def decode(self, token: str) -> dict[str, Any]:
        try:
            return cast(
                dict[str, Any],
                jwt.decode(token, self._secret, algorithms=[self._algorithm]),
            )
        except JWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


_signer: JwtSigner | None = None


def get_signer() -> JwtSigner:
    """Lazy-loaded global JwtSigner, refreshed by reset_signer()."""
    global _signer
    if _signer is None:
        _signer = JwtSigner(
            secret_key_path=settings.resolved_secret_key_path(),
            algorithm=settings.sebastian_jwt_algorithm,
            expire_minutes=settings.sebastian_jwt_expire_minutes,
            fallback_secret=settings.sebastian_jwt_secret,
        )
    return _signer


def reset_signer() -> None:
    """Drop cached signer so next get_signer() rereads the secret file.

    Used right after the setup wizard generates a new secret.key so that
    subsequent token operations pick it up without a process restart.
    """
    global _signer
    _signer = None


def create_access_token(data: dict[str, Any]) -> str:
    return get_signer().encode(data)


def decode_token(token: str) -> dict[str, Any]:
    return get_signer().decode(token)


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> dict[str, Any]:
    """FastAPI dependency: validates Bearer token and returns the payload."""
    return decode_token(credentials.credentials)
```

- [ ] **Step 4：运行新测试**

Run: `pytest tests/unit/test_auth_secret_source.py -v`
Expected: 3 passed

- [ ] **Step 5：跑完整 auth 相关回归**

Run: `pytest tests/ -k auth -v`
Expected: 全绿（既有测试不应被破坏，`settings.sebastian_jwt_secret` 作为 fallback 让开发模式不受影响）

- [ ] **Step 6：提交**

```bash
git add sebastian/gateway/auth.py tests/unit/test_auth_secret_source.py
git commit -m "refactor(auth): 抽出 JwtSigner，支持从 secret.key 文件读取签名密钥"
```

---

### Task 2.6：`/auth/login` 改为从 store 查 owner

**Files:**
- Modify: `sebastian/gateway/routes/turns.py`
- Create: `tests/integration/test_login_from_store.py`

- [ ] **Step 1：写集成测试**

`tests/integration/test_login_from_store.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

import pytest

from sebastian.gateway.app import create_app
from sebastian.gateway.auth import hash_password
from sebastian.store.database import Database
from sebastian.store.owner_store import OwnerStore


@pytest.mark.asyncio
async def test_login_succeeds_with_store_owner(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SEBASTIAN_DATA_DIR", str(tmp_path))
    # Prepare DB with owner account
    db = Database(url=f"sqlite+aiosqlite:///{tmp_path}/sebastian.db")
    await db.init()
    await OwnerStore(db).create_owner(name="Eric", password_hash=hash_password("hunter2"))

    # Write secret key so JwtSigner works
    (tmp_path / "secret.key").write_text("integration-secret")

    app = create_app()
    client = TestClient(app)

    resp = client.post("/api/v1/auth/login", json={"password": "hunter2"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SEBASTIAN_DATA_DIR", str(tmp_path))
    db = Database(url=f"sqlite+aiosqlite:///{tmp_path}/sebastian.db")
    await db.init()
    await OwnerStore(db).create_owner(name="Eric", password_hash=hash_password("hunter2"))
    (tmp_path / "secret.key").write_text("integration-secret")

    app = create_app()
    client = TestClient(app)

    resp = client.post("/api/v1/auth/login", json={"password": "wrong"})
    assert resp.status_code == 401
```

**注意**：`create_app` 可能需要在 Phase 2.8 添加为导出符号。若当前 `sebastian/gateway/app.py` 只有 module-level `app`，这个测试可能暂时失败，Task 2.8 完成后会修复。**此刻先跳过 Step 2-4，把测试标记为 skip 或让它保留在那儿**，先改 `turns.py`。

- [ ] **Step 2：修改 `/auth/login`**

在 `sebastian/gateway/routes/turns.py` 的 `login` 函数里，替换实现：

```python
@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    import sebastian.gateway.state as state
    from sebastian.gateway.auth import verify_password
    from sebastian.store.owner_store import OwnerStore

    owner_store = OwnerStore(state.database)  # 依赖 Phase 2.8 在 state 中暴露 database
    owner = await owner_store.get_owner()
    if owner is None or not verify_password(body.password, owner.password_hash):
        raise HTTPException(status_code=401, detail="Invalid password")
    token = create_access_token({"sub": owner.name, "role": "owner"})
    return TokenResponse(access_token=token)
```

**警告**：`state.database` 需要 Task 2.8 提供；若当前 state 模块没有 `database` 属性，此处先留 TODO 注释，Task 2.8 会完整修复。

为避免断裂，**本 task 采用以下策略**：新增一个临时的 `_get_owner_store()` 函数从 `state` 懒加载，Task 2.8 做正式接线。

替代实现：

```python
@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    from sebastian.gateway.auth import verify_password
    from sebastian.gateway.state import get_owner_store

    owner = await get_owner_store().get_owner()
    if owner is None or not verify_password(body.password, owner.password_hash):
        raise HTTPException(status_code=401, detail="Invalid password")
    token = create_access_token({"sub": owner.name, "role": "owner"})
    return TokenResponse(access_token=token)
```

`get_owner_store()` 由 Task 2.8 实现。

- [ ] **Step 3：暂时跳过集成测试**

在 `tests/integration/test_login_from_store.py` 顶部加：

```python
pytestmark = pytest.mark.skip(reason="unblocked by Task 2.8 state wiring")
```

- [ ] **Step 4：运行测试确认无破坏**

Run: `pytest tests/ -k login -v`
Expected: 其他登录相关测试不应被破坏；新测试 skipped

- [ ] **Step 5：提交**

```bash
git add sebastian/gateway/routes/turns.py tests/integration/test_login_from_store.py
git commit -m "refactor(auth): /auth/login 改走 store 查询 owner（待 Task 2.8 接线）"
```

---

### Task 2.7：`state` 模块暴露 `database` 与 `get_owner_store`

**Files:**
- Modify: `sebastian/gateway/state.py`

- [ ] **Step 1：查看当前 state.py**

Run: `cat sebastian/gateway/state.py`

理解当前 module-level globals（通常是 `sebastian`、`database` 之类的占位）。

- [ ] **Step 2：添加 getter**

在 `sebastian/gateway/state.py` 末尾添加：

```python
def get_owner_store() -> "OwnerStore":
    from sebastian.store.owner_store import OwnerStore

    if database is None:
        raise RuntimeError("Database not initialized; call lifespan startup first")
    return OwnerStore(database)
```

如果 `database` 不是 module-level 变量而是某对象的属性，按实际结构调整。务必保证：
- 模块级可以安全 `from sebastian.gateway.state import get_owner_store`
- `database` 在 lifespan 启动后被赋值

- [ ] **Step 3：提交**

```bash
git add sebastian/gateway/state.py
git commit -m "feat(gateway): state 模块暴露 get_owner_store helper"
```

---

### Task 2.8：Setup mode 检测与路由挂载

**Files:**
- Create: `sebastian/gateway/setup/security.py`
- Create: `sebastian/gateway/setup/setup_routes.py`
- Create: `tests/unit/test_setup_security.py`
- Modify: `sebastian/gateway/app.py`

- [ ] **Step 1：写 security 模块测试**

`tests/unit/test_setup_security.py`:

```python
from __future__ import annotations

import pytest
from fastapi import HTTPException, Request

from sebastian.gateway.setup.security import SetupSecurity


def _make_request(client_host: str, headers: dict[str, str] | None = None) -> Request:
    scope = {
        "type": "http",
        "client": (client_host, 12345),
        "headers": [
            (k.lower().encode(), v.encode())
            for k, v in (headers or {}).items()
        ],
    }
    return Request(scope)


def test_security_allows_localhost_with_token() -> None:
    sec = SetupSecurity(token="abc123")
    req = _make_request("127.0.0.1", {"X-Setup-Token": "abc123"})

    sec.check(req)  # should not raise


def test_security_rejects_non_localhost() -> None:
    sec = SetupSecurity(token="abc123")
    req = _make_request("192.168.1.50", {"X-Setup-Token": "abc123"})

    with pytest.raises(HTTPException) as exc:
        sec.check(req)
    assert exc.value.status_code == 403


def test_security_rejects_missing_token() -> None:
    sec = SetupSecurity(token="abc123")
    req = _make_request("127.0.0.1", {})

    with pytest.raises(HTTPException) as exc:
        sec.check(req)
    assert exc.value.status_code == 401


def test_security_rejects_wrong_token() -> None:
    sec = SetupSecurity(token="abc123")
    req = _make_request("127.0.0.1", {"X-Setup-Token": "wrong"})

    with pytest.raises(HTTPException) as exc:
        sec.check(req)
    assert exc.value.status_code == 401


def test_security_allows_ipv6_localhost() -> None:
    sec = SetupSecurity(token="abc123")
    req = _make_request("::1", {"X-Setup-Token": "abc123"})

    sec.check(req)


def test_generate_token_is_urlsafe_32_bytes() -> None:
    t = SetupSecurity.generate_token()
    assert len(t) >= 32
    assert "/" not in t and "+" not in t
```

- [ ] **Step 2：运行测试**

Run: `pytest tests/unit/test_setup_security.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3：实现 security**

`sebastian/gateway/setup/security.py`:

```python
from __future__ import annotations

import hmac
import secrets

from fastapi import HTTPException, Request

_ALLOWED_HOSTS = {"127.0.0.1", "::1", "localhost"}


class SetupSecurity:
    """Guards /setup/* routes: localhost-only + one-time token."""

    def __init__(self, token: str) -> None:
        self._token = token

    def check(self, request: Request) -> None:
        client = request.client.host if request.client else ""
        if client not in _ALLOWED_HOSTS:
            raise HTTPException(status_code=403, detail="Setup only accessible from localhost")

        provided = request.headers.get("x-setup-token", "")
        if not provided or not hmac.compare_digest(provided, self._token):
            raise HTTPException(status_code=401, detail="Invalid setup token")

    @staticmethod
    def generate_token() -> str:
        return secrets.token_urlsafe(32)
```

- [ ] **Step 4：运行测试**

Run: `pytest tests/unit/test_setup_security.py -v`
Expected: 6 passed

- [ ] **Step 5：实现 setup_routes**

`sebastian/gateway/setup/setup_routes.py`:

```python
from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from sebastian.gateway.auth import hash_password, reset_signer
from sebastian.gateway.setup.secret_key import SecretKeyManager
from sebastian.gateway.setup.security import SetupSecurity
from sebastian.store.owner_store import OwnerStore

_SETUP_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Sebastian 初始化</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 480px; margin: 4rem auto; padding: 0 1rem; }
  h1 { font-size: 1.5rem; }
  label { display: block; margin-top: 1rem; font-weight: 600; }
  input { width: 100%; padding: 0.5rem; margin-top: 0.25rem; border: 1px solid #ccc; border-radius: 4px; }
  button { margin-top: 1.5rem; padding: 0.75rem 1.5rem; background: #111; color: #fff; border: 0; border-radius: 4px; cursor: pointer; font-size: 1rem; }
  button:disabled { background: #888; }
  .error { color: #c00; margin-top: 1rem; }
  .success { color: #060; margin-top: 1rem; }
</style>
</head>
<body>
<h1>欢迎使用 Sebastian</h1>
<p>这是首次启动的初始化向导。设置完成后你才能正式使用系统。</p>
<form id="setup-form">
  <label>主人名字
    <input name="name" required maxlength="100" />
  </label>
  <label>登录密码（至少 8 位）
    <input name="password" type="password" required minlength="8" />
  </label>
  <label>确认密码
    <input name="password_confirm" type="password" required minlength="8" />
  </label>
  <button type="submit">完成初始化</button>
  <div id="msg"></div>
</form>
<script>
const TOKEN = new URLSearchParams(location.search).get("token");
const form = document.getElementById("setup-form");
const msg = document.getElementById("msg");
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  if (data.password !== data.password_confirm) {
    msg.className = "error"; msg.textContent = "两次密码不一致";
    return;
  }
  form.querySelector("button").disabled = true;
  msg.className = ""; msg.textContent = "处理中...";
  const r = await fetch("/setup/complete", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Setup-Token": TOKEN },
    body: JSON.stringify({ name: data.name, password: data.password })
  });
  if (r.ok) {
    msg.className = "success";
    msg.textContent = "初始化完成。服务即将自动关闭，请重启 sebastian serve。";
  } else {
    const err = await r.json().catch(() => ({ detail: "未知错误" }));
    msg.className = "error";
    msg.textContent = "失败：" + (err.detail || r.status);
    form.querySelector("button").disabled = false;
  }
});
</script>
</body>
</html>
"""


class CompleteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)


def create_setup_router(
    *,
    security: SetupSecurity,
    owner_store: OwnerStore,
    secret_key: SecretKeyManager,
) -> APIRouter:
    router = APIRouter(prefix="/setup", tags=["setup"])

    async def _guard(request: Request) -> None:
        security.check(request)

    @router.get("", response_class=HTMLResponse)
    @router.get("/", response_class=HTMLResponse)
    async def setup_page(request: Request) -> HTMLResponse:
        # Page itself is served without token check so the browser can load HTML;
        # the completion POST is guarded.
        client = request.client.host if request.client else ""
        if client not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(status_code=403, detail="Setup only from localhost")
        return HTMLResponse(_SETUP_HTML)

    @router.post("/complete", dependencies=[Depends(_guard)])
    async def setup_complete(body: CompleteRequest) -> JSONResponse:
        if await owner_store.owner_exists():
            raise HTTPException(status_code=409, detail="Setup already completed")

        await owner_store.create_owner(
            name=body.name,
            password_hash=hash_password(body.password),
        )
        if not secret_key.exists():
            secret_key.generate()
        reset_signer()  # force next JWT op to pick up the new key

        async def _shutdown() -> None:
            await asyncio.sleep(2)
            os._exit(0)

        asyncio.create_task(_shutdown())
        return JSONResponse({"status": "ok"})

    return router
```

- [ ] **Step 6：修改 `sebastian/gateway/app.py` 添加启动时分支**

先查看当前结构：

Run: `sed -n '40,180p' sebastian/gateway/app.py`

在 lifespan 里、数据库 init 之后，添加 setup mode 检测。修改 `create_app`（或对应的工厂函数）：

```python
from sebastian.gateway.setup.secret_key import SecretKeyManager
from sebastian.gateway.setup.security import SetupSecurity
from sebastian.gateway.setup.setup_routes import create_setup_router
from sebastian.store.owner_store import OwnerStore

# 在 create_app 内，数据库初始化完成后：
async def _is_setup_needed() -> bool:
    assert state.database is not None
    owner_exists = await OwnerStore(state.database).owner_exists()
    secret_exists = settings.resolved_secret_key_path().exists()
    return not (owner_exists and secret_exists)
```

在 lifespan 启动逻辑里加入：

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # ... existing db/init code ...

    if await _is_setup_needed():
        token = SetupSecurity.generate_token()
        security = SetupSecurity(token=token)
        secret_key = SecretKeyManager(settings.resolved_secret_key_path())
        owner_store = OwnerStore(state.database)
        app.state.setup_mode = True
        app.include_router(
            create_setup_router(
                security=security,
                owner_store=owner_store,
                secret_key=secret_key,
            )
        )
        url = f"http://127.0.0.1:{settings.sebastian_gateway_port}/setup?token={token}"
        print("\n" + "=" * 60)
        print("  Sebastian 首次启动：请完成初始化")
        print(f"  打开浏览器: {url}")
        print("=" * 60 + "\n")
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    else:
        app.state.setup_mode = False

    yield
    # ... existing shutdown ...
```

**关键：需要一个中间件阻止 setup mode 下访问非 /setup 路由**。在 `create_app` 添加：

```python
from fastapi import Request
from fastapi.responses import JSONResponse

@app.middleware("http")
async def setup_mode_gate(request: Request, call_next):
    if getattr(app.state, "setup_mode", False):
        if not request.url.path.startswith("/setup"):
            return JSONResponse(
                {"detail": "Sebastian is in setup mode. Visit /setup to initialize."},
                status_code=503,
            )
    return await call_next(request)
```

- [ ] **Step 7：取消 Task 2.6 集成测试的 skip**

移除 `tests/integration/test_login_from_store.py` 顶部的 `pytestmark = pytest.mark.skip(...)` 那一行。

- [ ] **Step 8：运行集成测试**

Run: `pytest tests/integration/test_login_from_store.py -v`
Expected: 2 passed

**可能失败点**：
- `create_app()` 不存在 → 把 `app.py` 中的顶层 `app = FastAPI(...)` 抽到一个 `create_app()` 工厂函数，顶层 `app = create_app()` 保留向后兼容
- `state.database` 为 None 因为未触发 lifespan → TestClient 应在 `with TestClient(app) as client:` 上下文里用，确保 startup 跑到
- DB 路径和 `SEBASTIAN_DATA_DIR` 不一致 → 确认 `sebastian/store/database.py` 读取 data_dir 的方式

逐个修复后所有测试通过。

- [ ] **Step 9：手动端到端验证**

```bash
# 用临时目录启动
export SEBASTIAN_DATA_DIR=$(mktemp -d)
sebastian serve
```

观察终端打印 `Sebastian 首次启动` 和 URL。浏览器访问 URL、填表、提交，看后端是否正常退出。

```bash
# 第二次启动应直接进入正常模式
sebastian serve
```

不应再出现 setup 提示，`/api/v1/auth/login` 能用新密码登录成功。

- [ ] **Step 10：提交**

```bash
git add sebastian/gateway/setup/ sebastian/gateway/app.py tests/unit/test_setup_security.py tests/integration/test_login_from_store.py
git commit -m "feat(setup): 启动检测 owner → setup mode，新增 /setup Web 向导与安全限制"
```

---

### Task 2.9：CLI `sebastian init --headless` 向导

**Files:**
- Create: `sebastian/cli/__init__.py`
- Create: `sebastian/cli/init_wizard.py`
- Modify: `sebastian/main.py`
- Create: `tests/unit/test_init_wizard.py`

- [ ] **Step 1：包初始化**

`sebastian/cli/__init__.py`:

```python
"""Sebastian CLI subcommands."""
```

- [ ] **Step 2：写向导测试**

`tests/unit/test_init_wizard.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sebastian.cli.init_wizard import run_headless_wizard


@pytest.mark.asyncio
async def test_headless_wizard_creates_owner_and_secret(tmp_path: Path) -> None:
    owner_store = AsyncMock()
    owner_store.owner_exists = AsyncMock(return_value=False)
    owner_store.create_owner = AsyncMock()
    secret_path = tmp_path / "secret.key"

    await run_headless_wizard(
        owner_store=owner_store,
        secret_key_path=secret_path,
        answers={"name": "Eric", "password": "hunter2pass"},
    )

    owner_store.create_owner.assert_awaited_once()
    kwargs = owner_store.create_owner.await_args.kwargs
    assert kwargs["name"] == "Eric"
    assert kwargs["password_hash"].startswith("$pbkdf2")  # passlib format
    assert secret_path.exists()
    assert (secret_path.stat().st_mode & 0o777) == 0o600


@pytest.mark.asyncio
async def test_headless_wizard_refuses_if_owner_exists(tmp_path: Path) -> None:
    owner_store = AsyncMock()
    owner_store.owner_exists = AsyncMock(return_value=True)

    with pytest.raises(RuntimeError, match="already initialized"):
        await run_headless_wizard(
            owner_store=owner_store,
            secret_key_path=tmp_path / "secret.key",
            answers={"name": "Eric", "password": "hunter2pass"},
        )
```

- [ ] **Step 3：运行测试（失败）**

Run: `pytest tests/unit/test_init_wizard.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 4：实现向导**

`sebastian/cli/init_wizard.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from sebastian.gateway.auth import hash_password
from sebastian.gateway.setup.secret_key import SecretKeyManager


async def run_headless_wizard(
    *,
    owner_store: Any,
    secret_key_path: Path,
    answers: dict[str, str],
) -> None:
    """Non-interactive wizard used by `sebastian init --headless` and tests.

    `answers` carries pre-collected inputs so the same core logic can be called
    from interactive CLI or tests.
    """
    if await owner_store.owner_exists():
        raise RuntimeError("Sebastian is already initialized (owner exists)")

    await owner_store.create_owner(
        name=answers["name"],
        password_hash=hash_password(answers["password"]),
    )

    mgr = SecretKeyManager(secret_key_path)
    if not mgr.exists():
        mgr.generate()
```

- [ ] **Step 5：运行测试**

Run: `pytest tests/unit/test_init_wizard.py -v`
Expected: 2 passed

- [ ] **Step 6：实现交互入口并改写 main.py 的 init**

`sebastian/cli/init_wizard.py` 末尾追加交互函数：

```python
async def run_interactive_headless_cli() -> None:
    import typer

    from sebastian.config import settings
    from sebastian.store.database import Database
    from sebastian.store.owner_store import OwnerStore

    typer.echo("Sebastian 首次初始化（headless 模式）")
    name = typer.prompt("主人名字")
    password = typer.prompt("登录密码", hide_input=True, confirmation_prompt=True)
    if len(password) < 8:
        typer.echo("密码至少 8 位", err=True)
        raise typer.Exit(code=1)

    db = Database()  # 按现有构造器签名调整
    await db.init()
    store = OwnerStore(db)

    await run_headless_wizard(
        owner_store=store,
        secret_key_path=settings.resolved_secret_key_path(),
        answers={"name": name, "password": password},
    )
    typer.echo("\n✓ 初始化完成。现在可以运行 `sebastian serve`")
```

修改 `sebastian/main.py` 的 `init` 命令：

```python
@app.command()
def init(
    headless: bool = typer.Option(
        False, help="Non-interactive CLI wizard (for SSH / headless servers)"
    ),
) -> None:
    """Initialize Sebastian (create owner account + generate JWT secret)."""
    import asyncio

    if headless:
        from sebastian.cli.init_wizard import run_interactive_headless_cli

        asyncio.run(run_interactive_headless_cli())
    else:
        typer.echo(
            "默认通过 Web 向导初始化。请运行 `sebastian serve` 并在浏览器打开提示的 URL。\n"
            "如果当前是无头服务器，请加 --headless 进入命令行向导。"
        )
```

- [ ] **Step 7：运行所有测试确认无破坏**

Run: `pytest tests/ -v 2>&1 | tail -40`
Expected: 全绿

- [ ] **Step 8：提交**

```bash
git add sebastian/cli/ sebastian/main.py tests/unit/test_init_wizard.py
git commit -m "feat(cli): sebastian init --headless 无头向导 + 替换 main.py 旧 init"
```

---

### Task 2.10：Phase 2 回归 + push dev

- [ ] **Step 1：全量测试**

Run: `pytest tests/ -v 2>&1 | tail -20`
Expected: 全绿

- [ ] **Step 2：Lint & Type**

```bash
ruff check sebastian/ tests/
ruff format sebastian/ tests/
mypy sebastian/
```
Expected: 无错误

- [ ] **Step 3：Push dev 触发 CI**

```bash
git push origin dev
gh run list --branch dev --limit 1
```
等 CI 全绿。

---

# Phase 3：install.sh 与 bootstrap.sh

**目标**：本地拿到源码或拿到 release tar.gz 的用户都能一条命令启动服务并进入 setup 向导。

### Task 3.1：`scripts/install.sh` 实现

**Files:**
- Create: `scripts/install.sh`

- [ ] **Step 1：写脚本**

```bash
#!/usr/bin/env bash
# Sebastian installer — runs inside an already-extracted source tree.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

color_red()  { printf "\033[31m%s\033[0m\n" "$*"; }
color_grn()  { printf "\033[32m%s\033[0m\n" "$*"; }
color_ylw()  { printf "\033[33m%s\033[0m\n" "$*"; }

# 1. OS check
OS="$(uname -s)"
case "$OS" in
  Darwin|Linux) ;;
  *) color_red "❌ 不支持的操作系统: $OS (仅支持 macOS / Linux)"; exit 1 ;;
esac

# 2. Python 3.12+
if ! command -v python3 >/dev/null 2>&1; then
  color_red "❌ 未找到 python3。请先安装 Python 3.12 或更高版本。"
  exit 1
fi

PY_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_MAJOR="$(echo "$PY_VERSION" | cut -d. -f1)"
PY_MINOR="$(echo "$PY_VERSION" | cut -d. -f2)"
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 12 ]]; }; then
  color_red "❌ Python 版本过低（当前 $PY_VERSION），需要 >= 3.12"
  exit 1
fi
color_grn "✓ Python $PY_VERSION"

# 3. venv
if [[ ! -d .venv ]]; then
  color_ylw "→ 创建虚拟环境 .venv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
color_grn "✓ 已激活 .venv"

# 4. 安装依赖
color_ylw "→ 安装依赖（可能需要几分钟）"
pip install --upgrade pip >/dev/null
pip install -e .
color_grn "✓ 依赖安装完成"

# 5. 启动
color_grn ""
color_grn "============================================"
color_grn "  即将启动 Sebastian（首次启动会进入初始化向导）"
color_grn "============================================"
color_grn ""
exec sebastian serve
```

- [ ] **Step 2：赋执行权限**

```bash
chmod +x scripts/install.sh
```

- [ ] **Step 3：本地真机验证**

```bash
cd /tmp
rm -rf sebastian-test
cp -r /Users/ericw/work/code/ai/sebastian sebastian-test
cd sebastian-test
rm -rf .venv data ~/.sebastian/test-install
SEBASTIAN_DATA_DIR=~/.sebastian/test-install ./scripts/install.sh
```
Expected:
- 打印 `✓ Python 3.12.x`
- 创建 .venv
- 安装完成
- 启动服务，提示首次初始化 URL

Ctrl+C 停止。

- [ ] **Step 4：提交**

```bash
cd /Users/ericw/work/code/ai/sebastian
git add scripts/install.sh
git commit -m "feat(install): 新增 scripts/install.sh 处理 venv + 依赖 + 首启向导"
```

---

### Task 3.2：`bootstrap.sh` 实现

**Files:**
- Create: `bootstrap.sh`

- [ ] **Step 1：写脚本**

```bash
#!/usr/bin/env bash
# Sebastian one-line installer.
# Usage: curl -fsSL https://raw.githubusercontent.com/Jaxton07/Sebastian/main/bootstrap.sh | bash
set -euo pipefail

REPO="Jaxton07/Sebastian"
INSTALL_DIR="${SEBASTIAN_INSTALL_DIR:-$HOME/.sebastian/app}"

color_red() { printf "\033[31m%s\033[0m\n" "$*"; }
color_grn() { printf "\033[32m%s\033[0m\n" "$*"; }
color_ylw() { printf "\033[33m%s\033[0m\n" "$*"; }

cat <<'BANNER'
============================================
  Sebastian 一键安装脚本
  动作清单：
    1. 检查系统依赖
    2. 从 GitHub 获取最新 release 信息
    3. 下载 sebastian-backend-<ver>.tar.gz 与 SHA256SUMS
    4. 校验 SHA256 指纹
    5. 解压到 $INSTALL_DIR
    6. 运行 ./scripts/install.sh（venv + 依赖 + 首启向导）
  按 Ctrl+C 随时中止
============================================
BANNER

# 1. 依赖检查
for cmd in curl tar shasum python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    color_red "❌ 缺少依赖命令: $cmd"
    exit 1
  fi
done
color_grn "✓ 系统依赖齐全"

# 2. 最新 release tag
color_ylw "→ 查询最新 release..."
LATEST_JSON="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest")"
LATEST_TAG="$(printf '%s' "$LATEST_JSON" | grep -o '"tag_name":[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
if [[ -z "$LATEST_TAG" ]]; then
  color_red "❌ 无法解析最新 release tag"
  exit 1
fi
color_grn "✓ 最新版本: $LATEST_TAG"

TAR_NAME="sebastian-backend-${LATEST_TAG}.tar.gz"
TAR_URL="https://github.com/${REPO}/releases/download/${LATEST_TAG}/${TAR_NAME}"
SUMS_URL="https://github.com/${REPO}/releases/download/${LATEST_TAG}/SHA256SUMS"

# 3. 下载到临时目录
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

color_ylw "→ 下载 $TAR_NAME ..."
curl -fsSL "$TAR_URL" -o "${TMPDIR}/${TAR_NAME}"
color_ylw "→ 下载 SHA256SUMS ..."
curl -fsSL "$SUMS_URL" -o "${TMPDIR}/SHA256SUMS"

# 4. 校验
color_ylw "→ 校验 SHA256 指纹..."
(
  cd "$TMPDIR"
  shasum -a 256 -c SHA256SUMS --ignore-missing 2>&1 | grep -E "^${TAR_NAME}: OK$" >/dev/null \
    || { color_red "❌ SHA256 校验失败，已中止以防供应链污染"; exit 1; }
)
color_grn "✓ SHA256 校验通过"

# 5. 解压
color_ylw "→ 解压到 $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
if [[ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
  color_ylw "⚠ 目标目录非空，已有内容将被覆盖（仅同名文件）"
fi
tar xzf "${TMPDIR}/${TAR_NAME}" -C "$INSTALL_DIR" --strip-components=1

# 6. 运行 install.sh
cd "$INSTALL_DIR"
if [[ ! -x scripts/install.sh ]]; then
  color_red "❌ 解压后未找到 scripts/install.sh"
  exit 1
fi
color_grn "✓ 开始执行安装脚本"
exec ./scripts/install.sh
```

- [ ] **Step 2：赋执行权限**

```bash
chmod +x bootstrap.sh
```

- [ ] **Step 3：ShellCheck 静态检查**

```bash
shellcheck bootstrap.sh scripts/install.sh || echo "(shellcheck 未安装或有警告，人工快速 review 即可)"
```

修复严重 warning（有的话）。

- [ ] **Step 4：提交**

```bash
git add bootstrap.sh
git commit -m "feat(install): 新增 bootstrap.sh 一键安装（含 SHA256 校验）"
```

**注意**：bootstrap.sh 的真实运行验证要等 Phase 4 发出第一个 release（有 tar.gz + SHA256SUMS）后才能做，记录在 Task 4.5。

---

### Task 3.3：Push dev

- [ ] **Step 1：push**

```bash
git push origin dev
```

---

# Phase 4：Release 流水线

**目标**：配置 Android release keystore；写 release.yml；手动触发首次发版 v0.2.0；验证 bootstrap.sh 端到端可用。

### Task 4.1：生成 Android release keystore 并上传 Secrets

**这是一次性手动任务，不产生代码提交。**

- [ ] **Step 1：生成 keystore**

```bash
cd ~
keytool -genkeypair -v -storetype PKCS12 \
  -keystore sebastian-release.keystore \
  -alias sebastian -keyalg RSA -keysize 2048 -validity 10000 \
  -dname "CN=Sebastian, OU=Dev, O=Jaxton07, L=Unknown, S=Unknown, C=CN"
```

按提示设置 keystore 密码（记录下来）。alias 密码建议和 keystore 密码相同以简化 CI 配置。

- [ ] **Step 2：备份**

```bash
# 至少两份备份
cp ~/sebastian-release.keystore ~/Documents/sebastian-release.keystore.backup
# 建议再上传一份到密码管理器 / 加密云存储
```

同时把 keystore 密码 / alias / alias 密码记到密码管理器。

**⚠️ 严禁**：
- ❌ 把 keystore 文件加入 git
- ❌ 明文写入任何项目文件
- keystore 丢失 = 该 App 永远无法被同一 package 覆盖更新

- [ ] **Step 3：上传到 GitHub Secrets**

```bash
cd ~
base64 -i sebastian-release.keystore -o keystore.b64

cd /Users/ericw/work/code/ai/sebastian
gh secret set ANDROID_KEYSTORE_BASE64 < ~/keystore.b64
gh secret set ANDROID_KEYSTORE_PASSWORD --body "<你设置的 keystore 密码>"
gh secret set ANDROID_KEY_ALIAS --body "sebastian"
gh secret set ANDROID_KEY_PASSWORD --body "<你设置的 alias 密码>"

# 清理本地 base64 中间文件
shred -u ~/keystore.b64 2>/dev/null || rm -P ~/keystore.b64
```

- [ ] **Step 4：验证**

```bash
gh secret list
```
Expected: 看到 4 个 secret 项。

---

### Task 4.2：配置 Android 项目读取签名 env

**Files:**
- Modify: `ui/mobile/android/app/build.gradle`

- [ ] **Step 1：查看现状**

Run: `cat ui/mobile/android/app/build.gradle | grep -A 20 "signingConfigs\|release {" | head -40`

- [ ] **Step 2：在 signingConfigs 里添加 release 配置**

在 `android { signingConfigs { ... } }` 内添加（若已有 `debug` 配置，保留）：

```groovy
signingConfigs {
    debug { /* 原有内容 */ }
    release {
        if (System.getenv("ANDROID_KEYSTORE_FILE")) {
            storeFile file(System.getenv("ANDROID_KEYSTORE_FILE"))
            storePassword System.getenv("ANDROID_KEYSTORE_PASSWORD")
            keyAlias System.getenv("ANDROID_KEY_ALIAS")
            keyPassword System.getenv("ANDROID_KEY_PASSWORD")
        }
    }
}
```

并在 `buildTypes { release { ... } }` 中使用：

```groovy
buildTypes {
    release {
        // ... existing minify/shrink config ...
        signingConfig signingConfigs.release
    }
}
```

- [ ] **Step 3：本地不加载签名时仍能 debug build（回归）**

```bash
cd ui/mobile
# 不设 env 变量时应不报错（release config 只在 env 存在时填充 storeFile）
npx expo start # 或 expo run:android，选其中一个快速 smoke
```

Ctrl+C 结束。只要没报 gradle 错即可，不必真的跑完 emulator。

- [ ] **Step 4：提交**

```bash
cd /Users/ericw/work/code/ai/sebastian
git add ui/mobile/android/app/build.gradle
git commit -m "build(android): release 签名配置从 env 读取，兼容无 env 场景"
```

---

### Task 4.3：`release.yml` 发版 workflow

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1：写 workflow**

```yaml
name: Release

on:
  workflow_dispatch:
    inputs:
      version:
        description: "Semantic version without v prefix (e.g. 0.2.0)"
        required: true
        type: string

permissions:
  contents: write

concurrency:
  group: release-${{ github.event.inputs.version }}
  cancel-in-progress: false

jobs:
  sync-version:
    runs-on: ubuntu-latest
    outputs:
      tag: ${{ steps.tagout.outputs.tag }}
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
          fetch-depth: 0
          token: ${{ secrets.GITHUB_TOKEN }}
      - name: Validate version format
        run: |
          if ! [[ "${{ inputs.version }}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo "❌ Invalid version: ${{ inputs.version }}"
            exit 1
          fi
      - name: Configure git
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
      - name: Update pyproject.toml version
        run: |
          python -c "
          import re, sys
          p = 'pyproject.toml'
          s = open(p).read()
          s = re.sub(r'^version = \"[^\"]*\"', 'version = \"${{ inputs.version }}\"', s, count=1, flags=re.M)
          open(p, 'w').write(s)
          "
      - name: Update ui/mobile/app.json version
        run: |
          python -c "
          import json
          with open('ui/mobile/app.json') as f: d = json.load(f)
          d['expo']['version'] = '${{ inputs.version }}'
          with open('ui/mobile/app.json', 'w') as f: json.dump(d, f, indent=2); f.write('\n')
          "
      - name: Update CHANGELOG.md
        run: |
          python - <<'PY'
          import datetime, re
          p = 'CHANGELOG.md'
          content = open(p).read()
          today = datetime.date.today().isoformat()
          version = "${{ inputs.version }}"
          new_unreleased = "## [Unreleased]\n\n"
          released = f"## [{version}] - {today}"
          if "## [Unreleased]" not in content:
              raise SystemExit("CHANGELOG.md missing [Unreleased] section")
          content = content.replace("## [Unreleased]", new_unreleased + released, 1)
          open(p, 'w').write(content)
          PY
      - name: Commit and tag
        id: tagout
        run: |
          git add pyproject.toml ui/mobile/app.json CHANGELOG.md
          git commit -m "chore(release): v${{ inputs.version }}"
          git tag "v${{ inputs.version }}"
          git push origin main
          git push origin "v${{ inputs.version }}"
          echo "tag=v${{ inputs.version }}" >> "$GITHUB_OUTPUT"

  build-backend:
    runs-on: ubuntu-latest
    needs: sync-version
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ needs.sync-version.outputs.tag }}
      - name: Build tarball
        run: |
          NAME="sebastian-backend-v${{ inputs.version }}"
          mkdir -p "/tmp/${NAME}"
          cp -r sebastian pyproject.toml README.md LICENSE CHANGELOG.md scripts "/tmp/${NAME}/"
          tar czf "${NAME}.tar.gz" -C /tmp "${NAME}"
      - uses: actions/upload-artifact@v4
        with:
          name: backend-tarball
          path: sebastian-backend-v${{ inputs.version }}.tar.gz

  build-android:
    runs-on: ubuntu-latest
    needs: sync-version
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ needs.sync-version.outputs.tag }}
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: ui/mobile/package-lock.json
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: "17"
      - uses: android-actions/setup-android@v3
      - name: Install JS deps
        working-directory: ui/mobile
        run: npm ci --legacy-peer-deps
      - name: Prebuild Android project
        working-directory: ui/mobile
        run: npx expo prebuild --platform android --no-install
      - name: Restore keystore
        run: |
          echo "${{ secrets.ANDROID_KEYSTORE_BASE64 }}" | base64 -d > /tmp/sebastian-release.keystore
      - name: Gradle assembleRelease
        working-directory: ui/mobile/android
        env:
          ANDROID_KEYSTORE_FILE: /tmp/sebastian-release.keystore
          ANDROID_KEYSTORE_PASSWORD: ${{ secrets.ANDROID_KEYSTORE_PASSWORD }}
          ANDROID_KEY_ALIAS: ${{ secrets.ANDROID_KEY_ALIAS }}
          ANDROID_KEY_PASSWORD: ${{ secrets.ANDROID_KEY_PASSWORD }}
        run: ./gradlew assembleRelease
      - name: Rename APK
        run: |
          APK="$(find ui/mobile/android/app/build/outputs/apk/release -name '*.apk' | head -1)"
          cp "$APK" "sebastian-app-v${{ inputs.version }}.apk"
      - name: Cleanup keystore
        if: always()
        run: rm -f /tmp/sebastian-release.keystore
      - uses: actions/upload-artifact@v4
        with:
          name: android-apk
          path: sebastian-app-v${{ inputs.version }}.apk

  publish:
    runs-on: ubuntu-latest
    needs: [build-backend, build-android, sync-version]
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ needs.sync-version.outputs.tag }}
      - uses: actions/download-artifact@v4
        with:
          path: dist
          merge-multiple: true
      - name: Generate SHA256SUMS
        working-directory: dist
        run: |
          shasum -a 256 sebastian-backend-v${{ inputs.version }}.tar.gz \
                        sebastian-app-v${{ inputs.version }}.apk > SHA256SUMS
          cat SHA256SUMS
      - name: Extract changelog body
        id: changelog
        run: |
          python - <<'PY' >> "$GITHUB_OUTPUT"
          import re
          content = open('CHANGELOG.md').read()
          m = re.search(r'## \[${{ inputs.version }}\][^\n]*\n(.*?)(?=\n## \[|\Z)', content, re.S)
          body = m.group(1).strip() if m else '(No changelog entry)'
          body = body.replace('\n', '%0A').replace('\r', '')
          print(f"body={body}")
          PY
      - name: Create GitHub Release
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          cd dist
          gh release create "v${{ inputs.version }}" \
            sebastian-backend-v${{ inputs.version }}.tar.gz \
            sebastian-app-v${{ inputs.version }}.apk \
            SHA256SUMS \
            --title "v${{ inputs.version }}" \
            --notes "${{ steps.changelog.outputs.body }}"
```

- [ ] **Step 2：提交**

```bash
git add .github/workflows/release.yml
git commit -m "ci: 新增 release.yml 支持手动触发统一版本发版流水线"
```

---

### Task 4.4：初始化 `CHANGELOG.md` 与 `LICENSE`

**Files:**
- Create: `CHANGELOG.md`
- Create: `LICENSE`

- [ ] **Step 1：CHANGELOG**

```markdown
# Changelog

本文件记录 Sebastian 的所有重要变更，遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- 完整 CI/CD 工作流（质量门禁 + 手动触发发版）
- 一键安装脚本 `bootstrap.sh` 与 `scripts/install.sh`
- 首次启动 Web 初始化向导（`/setup`）与 CLI 兜底 `sebastian init --headless`
- Android release APK 自动构建与签名
- SHA256SUMS 校验文件随 Release 一起发布

### Changed
- Owner 账号从环境变量迁移到数据库 `users` 表
- JWT 签名密钥从环境变量迁移到 `~/.sebastian/secret.key` 单文件
- `main` 分支启用保护规则，只接受 PR squash merge

### Removed
- 手工生成密码 hash 再填 `.env` 的原始初始化流程
```

- [ ] **Step 2：LICENSE (Apache-2.0)**

```bash
curl -fsSL https://www.apache.org/licenses/LICENSE-2.0.txt -o LICENSE
```

检查下载成功后在文件末尾不需要额外修改（Apache 2.0 文本是标准的）。

- [ ] **Step 3：提交**

```bash
git add CHANGELOG.md LICENSE
git commit -m "docs: 新增 CHANGELOG.md (Keep a Changelog) 与 LICENSE (Apache-2.0)"
```

---

### Task 4.5：合 dev → main，首次触发 release v0.2.0

- [ ] **Step 1：准备 PR**

```bash
git push origin dev
gh pr create --base main --head dev \
  --title "chore: 引入完整 CI/CD、一键安装、首次配置向导（Phase 1-4）" \
  --body "$(cat <<'EOF'
## Summary
- Phase 1: CI 质量门禁、PR/Issue 模板、CODEOWNERS、Dependabot、分支保护
- Phase 2: Setup mode + Web 向导 + CLI 兜底；auth 从 store 读
- Phase 3: bootstrap.sh + scripts/install.sh
- Phase 4: release.yml + Android keystore 接入 + CHANGELOG + LICENSE

## Test plan
- [ ] ci.yml 四项 job 全绿
- [ ] 本地 `./scripts/install.sh` 在临时 data dir 下能启动到 setup 向导
- [ ] 手动触发 release workflow 成功产出 tar.gz + apk + SHA256SUMS

## Related
spec: docs/superpowers/specs/2026-04-08-release-and-cicd-workflow-design.md
plan: docs/superpowers/plans/2026-04-08-release-and-cicd-workflow.md
EOF
)"
```

- [ ] **Step 2：等 CI 绿后 squash merge**

```bash
gh pr checks --watch
gh pr merge --squash --delete-branch=false
```

- [ ] **Step 3：把 `github-actions[bot]` 加入 main bypass 列表**

手动在 GitHub Web UI → Settings → Branches → main rule → Allow specified actors to bypass required pull requests → 加 `github-actions[bot]`。

同时在 Tag rule `v*.*.*` 的 allowed actors 里加 `github-actions[bot]`。

- [ ] **Step 4：触发首次 release**

```bash
gh workflow run release.yml -f version=0.2.0
gh run watch
```
等待所有 job 完成。

**可能失败的环节 + 修复**：
- `build-android` 因 prebuild 生成的目录结构不符 → 查 Expo prebuild 日志，可能需要在 workflow 里先 `expo install` 一下
- gradle 签名步骤报 `keystore not found` → 检查 keystore base64 解码路径 / env 传递
- `sync-version` push 被拒 → branch protection 没加 `github-actions[bot]` bypass，补上 Step 3
- CHANGELOG 解析失败 → `[Unreleased]` section 不存在或格式不对

每次失败后：修复问题 → 创建新 PR（因为 release commit 可能已经被部分写入 main） → 再次触发 workflow（如果 v0.2.0 tag 已存在要先删掉：`gh release delete v0.2.0 --yes && git push origin :v0.2.0`）。

- [ ] **Step 5：验证 Release 页面**

```bash
gh release view v0.2.0
```

Expected：
- 三个 asset：`sebastian-backend-v0.2.0.tar.gz` / `sebastian-app-v0.2.0.apk` / `SHA256SUMS`
- Release notes 展示 CHANGELOG 内容

- [ ] **Step 6：端到端验证 bootstrap.sh**

在一个干净的目录（或另一台机器）执行：

```bash
export SEBASTIAN_INSTALL_DIR=/tmp/sebastian-e2e
rm -rf "$SEBASTIAN_INSTALL_DIR"
curl -fsSL https://raw.githubusercontent.com/Jaxton07/Sebastian/main/bootstrap.sh | bash
```

Expected：
- 依赖检查 ✓
- 下载 tar.gz ✓
- SHA256 校验 ✓
- 解压 ✓
- install.sh 开始运行 → venv → 依赖装完 → 启动服务 → 打印 setup URL
- 浏览器走完向导 → 可正常登录

如果某一步失败，按日志修复相应脚本或 workflow，再跑一次。

- [ ] **Step 7：（失败时的）修复循环**

如果 bootstrap 有问题，在 dev 分支上修 → 新 PR → 合 main → 再发 v0.2.1（重复 Step 4-6）。

---

# Phase 5：文档同步

**目标**：所有用户入口的文档都反映新的安装/启动流程。

### Task 5.1：重写 README.md 的 "安装与启动" 章节

**Files:**
- Modify: `README.md`

- [ ] **Step 1：查看现状**

Run: `cat README.md | head -80`

- [ ] **Step 2：替换安装/启动章节**

在合适位置（"快速开始" / "安装" / 项目介绍之后）加入：

````markdown
## 快速开始

### 一键安装（推荐，macOS / Linux）

```bash
curl -fsSL https://raw.githubusercontent.com/Jaxton07/Sebastian/main/bootstrap.sh | bash
```

脚本会：
1. 检查 Python 3.12+ 等依赖
2. 从最新 GitHub Release 下载源码包与 `SHA256SUMS`
3. 校验文件指纹
4. 解压到 `~/.sebastian/app/`
5. 创建 venv、安装依赖、启动首次初始化向导

初始化完成后浏览器访问后端服务，填入主人名字和登录密码即可。

### 手动安装（偏执模式）

```bash
# 1. 下载
curl -LO https://github.com/Jaxton07/Sebastian/releases/latest/download/sebastian-backend-v0.2.0.tar.gz
curl -LO https://github.com/Jaxton07/Sebastian/releases/latest/download/SHA256SUMS

# 2. 手动校验 SHA256（必做）
shasum -a 256 -c SHA256SUMS --ignore-missing

# 3. 解压并运行
tar xzf sebastian-backend-v0.2.0.tar.gz
cd sebastian-backend-v0.2.0
./scripts/install.sh
```

### 从源码开发

```bash
git clone git@github.com:Jaxton07/Sebastian.git
cd Sebastian
./scripts/install.sh          # 首次
# 或
pip install -e ".[dev,memory]"
sebastian serve                # 日常
```

### Android App

从 [Releases 页面](https://github.com/Jaxton07/Sebastian/releases) 下载 `sebastian-app-v*.apk`，通过 `adb install` 或直接传手机安装。

首次打开 App → Settings → 填写 Server URL：
- 模拟器（宿主机）：`http://10.0.2.2:8000`
- 同局域网真机：`http://<电脑局域网 IP>:8000`

### iOS

本版本不分发 iOS 构建。开发者可以通过 Xcode 自行 build：

```bash
cd ui/mobile
npm install --legacy-peer-deps
npx expo run:ios        # 需要 macOS + Xcode
```
````

- [ ] **Step 3：提交**

```bash
git add README.md
git commit -m "docs(readme): 重写快速开始，新增一键/手动安装、iOS 自构建说明"
```

---

### Task 5.2：更新 CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1：§3 构建与启动章节更新**

把原来的"生成测试用密码 Hash"段落替换为：

```markdown
### 本地开发首次启动

```bash
# 从源码开发首次启动（会进入 Web 初始化向导）
./scripts/install.sh

# 或已装好依赖后直接启动
sebastian serve

# 浏览器会被自动唤起到 http://127.0.0.1:8000/setup?token=...
# 填入主人名字和密码（至少 8 位）→ 完成 → 服务自动退出
# 再次 `sebastian serve` 进入正常模式
```

Headless 服务器（无图形界面）可以用：

```bash
sebastian init --headless
sebastian serve
```
```

- [ ] **Step 2：§6 运行时环境变量章节更新**

从环境变量列表中**删除** `SEBASTIAN_OWNER_PASSWORD_HASH` 和 `SEBASTIAN_JWT_SECRET`。
在下方加一段说明：

```markdown
> **注意**：owner 账号和 JWT 签名密钥从 v0.2.0 起不再由环境变量提供：
> - Owner 账号存在 `~/.sebastian/sebastian.db` 的 `users` 表
> - JWT 密钥存在 `~/.sebastian/secret.key`（chmod 600）
> - 两者都由首启 Web 向导或 `sebastian init --headless` 生成
> - 开发模式若未初始化，可临时设置 `SEBASTIAN_JWT_SECRET` 作为 fallback
```

- [ ] **Step 3：§11 PR 工作流章节更新**

在"分支模型"或"提交规范"处追加：

```markdown
### 分支保护
- `main` 只接受 PR squash merge，需 CI 四项全绿 + 1 个 approval
- tag `v*.*.*` 只有 admin 和 `github-actions[bot]` 可创建
- 日常开发直接 push 到 `dev`

### 发版流程
1. 在 `main` 上 Actions 页面手动触发 `Release` workflow
2. 输入语义版本号（如 `0.3.0`）
3. Workflow 自动同步 `pyproject.toml` + `app.json` 版本 + 改 CHANGELOG + 打 tag + 构建 + 发布
```

- [ ] **Step 4：提交**

```bash
git add CLAUDE.md
git commit -m "docs(claude): 同步首次启动/环境变量/分支保护/发版流程到 CLAUDE.md"
```

---

### Task 5.3：`sebastian/README.md` 小幅更新

**Files:**
- Modify: `sebastian/README.md`

- [ ] **Step 1：查看**

Run: `head -60 sebastian/README.md`

- [ ] **Step 2：更新启动命令**

把任何涉及"生成密码 hash 填 env"的内容替换为"`sebastian serve` 首启进入 Web 向导"。具体段落按实际文件内容调整。

- [ ] **Step 3：提交**

```bash
git add sebastian/README.md
git commit -m "docs(sebastian/readme): 启动命令对齐 v0.2.0 首启向导"
```

---

### Task 5.4：最终发版 v0.2.1（包含文档同步）

- [ ] **Step 1：PR 合并**

```bash
git push origin dev
gh pr create --base main --head dev \
  --title "docs: 同步 README / CLAUDE.md 到 v0.2.0 新流程" \
  --body "## Summary

文档同步：快速开始、环境变量、发版流程、PR 规范。

## Test plan
- [ ] CI 全绿
- [ ] README 渲染看起来 OK"
gh pr checks --watch
gh pr merge --squash --delete-branch=false
```

- [ ] **Step 2：触发 v0.2.1**

```bash
gh workflow run release.yml -f version=0.2.1
gh run watch
```

- [ ] **Step 3：验证**

```bash
gh release view v0.2.1
```

Release 页面更新，三个 asset 齐全。

---

## 完成验收 Checklist

整个计划全部执行完后，逐条确认：

- [ ] `.github/workflows/ci.yml` 存在且 PR 触发四项 job 全绿
- [ ] `.github/workflows/release.yml` 存在且 workflow_dispatch 可触发
- [ ] `main` 分支保护规则配置完毕（1 approval + 4 required checks + squash only + bot bypass）
- [ ] tag `v*.*.*` 保护规则配置完毕
- [ ] `bootstrap.sh` 在空白环境一条命令可安装并进入 setup 向导
- [ ] `sebastian/gateway/setup/` 向导页面可填表并创建 owner
- [ ] `sebastian init --headless` 可在无浏览器环境完成初始化
- [ ] `~/.sebastian/secret.key` 以 chmod 600 存在
- [ ] store `users` 表有 owner 记录
- [ ] `/api/v1/auth/login` 用新密码可以取到 token
- [ ] GitHub Release v0.2.0 / v0.2.1 页面包含 tar.gz + apk + SHA256SUMS
- [ ] Android APK 可安装且正常连后端登录
- [ ] `CHANGELOG.md` 记录了 v0.2.0 与 v0.2.1
- [ ] `LICENSE` 为 Apache-2.0
- [ ] `README.md` 一键安装章节指向正确 URL
- [ ] `CLAUDE.md` 不再提及手工生成 hash 的老流程
