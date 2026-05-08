# Skill Package Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Sebastian-native consumer-side Skill package manager that installs ClawHub-compatible Skills into the user extension directory, plus a builtin `skill_installer` Skill and robust CLI PATH setup.

**Architecture:** Keep runtime capability expansion file-based: installed Skills land in `settings.skills_extensions_dir` and become visible through existing new-session hot reload. The registry installer is a Python CLI/package-manager layer, not a model-visible native install tool. Package-manager writes are protected by an exclusive per-install-root lock covering conflict validation, recoverable directory swap, origin/lockfile writes, and backup cleanup.

**Tech Stack:** Python 3.12, Typer, httpx, pathlib/shutil/zipfile, fcntl/msvcrt-compatible file locking where practical, pytest, existing Sebastian `Settings`, `CapabilityRegistry`, and Skill loader.

---

## File Structure

Create:

- `sebastian/cli/path_setup.py` — stable shim creation and shell rc PATH block management.
- `sebastian/cli/skills.py` — Typer subcommands under `sebastian skills`.
- `sebastian/capabilities/skills/metadata.py` — shared `SKILL.md` frontmatter parsing and Skill name validation.
- `sebastian/capabilities/skills/skill_installer/SKILL.md` — builtin Skill instructions for agent-assisted install/update/remove.
- `sebastian/skills_registry/__init__.py` — package exports.
- `sebastian/skills_registry/models.py` — typed data models/errors for registry entries, lockfile entries, and installer results.
- `sebastian/skills_registry/client.py` — ClawHub-compatible registry HTTP client and registry URL/download URL policy.
- `sebastian/skills_registry/safety.py` — archive safety scan, staged extraction, metadata fingerprinting.
- `sebastian/skills_registry/lockfile.py` — exclusive package-manager lock, lockfile load/save, atomic JSON writes.
- `sebastian/skills_registry/installer.py` — install/update/remove/list orchestration.
- `tests/unit/runtime/test_path_setup.py` — PATH setup unit tests.
- `tests/unit/capabilities/test_skill_metadata.py` — shared metadata validation tests.
- `tests/unit/skills_registry/test_client.py` — registry client parsing and URL policy tests.
- `tests/unit/skills_registry/test_safety.py` — archive safety and fingerprint tests.
- `tests/unit/skills_registry/test_lockfile.py` — lockfile atomicity and lock behavior tests.
- `tests/unit/skills_registry/test_installer.py` — installer transaction/conflict/update/remove tests.
- `tests/unit/runtime/test_skills_cli.py` — Typer CLI tests.

Modify:

- `scripts/install.sh` — call path setup through Python after venv install.
- `sebastian/cli/updater.py` — refresh shim after successful update, before service restart.
- `sebastian/main.py` — mount `skills` Typer app.
- `sebastian/capabilities/skills/_loader.py` — use shared metadata parser/validator, skip invalid manual Skills with warning.
- `sebastian/capabilities/README.md` — document install workflow.
- `sebastian/capabilities/skills/README.md` — document package-managed Skills and `skill_installer`.
- `sebastian/cli/README.md` — document `sebastian skills` and PATH setup.
- `sebastian/README.md` — update CLI/capabilities overview.
- `README.md` — mention `sebastian skills` and the PATH shim.
- `docs/architecture/spec/capabilities/INDEX.md` — link implemented architecture doc.
- `docs/architecture/spec/capabilities/skill-package-manager.md` — integrated architecture spec after implementation.
- `CHANGELOG.md` — add user-facing entries under `[Unreleased]`.

Reference:

- Spec: `docs/superpowers/specs/2026-05-08-skill-package-manager-design.md`
- Existing loader: `sebastian/capabilities/skills/_loader.py`
- Existing hot reload: `sebastian/capabilities/skills/hot_reload.py`
- Existing CLI: `sebastian/main.py`
- Existing install script tests: `tests/unit/runtime/test_install_script.py`
- Existing updater tests: `tests/unit/runtime/test_updater.py`
- Existing CLI tests: `tests/unit/runtime/test_cli_main.py`

---

### Task 1: PATH Setup Helper and Installer Integration

**Files:**
- Create: `sebastian/cli/path_setup.py`
- Modify: `scripts/install.sh`
- Modify: `sebastian/cli/updater.py`
- Test: `tests/unit/runtime/test_path_setup.py`
- Test: `tests/unit/runtime/test_install_script.py`
- Test: `tests/unit/runtime/test_updater.py`

- [ ] **Step 1: Write failing tests for shim generation**

Create `tests/unit/runtime/test_path_setup.py`:

```python
from __future__ import annotations

from pathlib import Path

from sebastian.cli.path_setup import ensure_cli_path


def test_ensure_cli_path_creates_shim_for_default_install(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    install_dir = home / ".sebastian" / "app"
    target = install_dir / ".venv" / "bin" / "sebastian"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\n")
    target.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("SEBASTIAN_SKIP_PATH_SETUP", raising=False)

    result = ensure_cli_path(install_dir=install_dir, update_shell_rc=False)

    shim = home / ".sebastian" / "bin" / "sebastian"
    assert shim.is_file()
    assert str(target) in shim.read_text()
    assert shim.stat().st_mode & 0o111
    assert result.shim_path == shim
```

- [ ] **Step 2: Write failing tests for shell rc block idempotency and skip**

Append to `tests/unit/runtime/test_path_setup.py`:

```python
def test_ensure_cli_path_updates_zshrc_once(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    install_dir = home / ".sebastian" / "app"
    (install_dir / ".venv" / "bin").mkdir(parents=True)
    (install_dir / ".venv" / "bin" / "sebastian").write_text("#!/bin/sh\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELL", "/bin/zsh")

    ensure_cli_path(install_dir=install_dir, update_shell_rc=True)
    ensure_cli_path(install_dir=install_dir, update_shell_rc=True)

    content = (home / ".zshrc").read_text()
    assert content.count("# >>> sebastian PATH >>>") == 1
    assert 'export PATH="$HOME/.sebastian/bin:$PATH"' in content


def test_skip_path_setup_skips_rc_but_not_shim(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    install_dir = home / ".sebastian" / "app"
    (install_dir / ".venv" / "bin").mkdir(parents=True)
    (install_dir / ".venv" / "bin" / "sebastian").write_text("#!/bin/sh\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("SEBASTIAN_SKIP_PATH_SETUP", "1")

    ensure_cli_path(install_dir=install_dir, update_shell_rc=True)

    assert (home / ".sebastian" / "bin" / "sebastian").is_file()
    assert not (home / ".zshrc").exists()
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
pytest tests/unit/runtime/test_path_setup.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'sebastian.cli.path_setup'`.

- [ ] **Step 4: Implement `path_setup.py`**

Create `sebastian/cli/path_setup.py` with:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

START = "# >>> sebastian PATH >>>"
END = "# <<< sebastian PATH <<<"
EXPORT_LINE = 'export PATH="$HOME/.sebastian/bin:$PATH"'


@dataclass(frozen=True)
class PathSetupResult:
    shim_path: Path
    target_path: Path
    rc_files_updated: tuple[Path, ...]
    rc_skipped: bool


def ensure_cli_path(
    *,
    install_dir: Path,
    update_shell_rc: bool = True,
    home: Path | None = None,
) -> PathSetupResult:
    resolved_home = (home or Path.home()).expanduser()
    target = install_dir.expanduser().resolve() / ".venv" / "bin" / "sebastian"
    shim_dir = resolved_home / ".sebastian" / "bin"
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "sebastian"
    shim.write_text(f'#!/usr/bin/env sh\nexec "{target}" "$@"\n', encoding="utf-8")
    shim.chmod(0o755)

    rc_skipped = os.environ.get("SEBASTIAN_SKIP_PATH_SETUP") == "1"
    updated: list[Path] = []
    if update_shell_rc and not rc_skipped:
        for rc_file in _target_rc_files(resolved_home):
            _upsert_path_block(rc_file)
            updated.append(rc_file)

    return PathSetupResult(
        shim_path=shim,
        target_path=target,
        rc_files_updated=tuple(updated),
        rc_skipped=rc_skipped,
    )


def _target_rc_files(home: Path) -> list[Path]:
    shell = os.environ.get("SHELL", "")
    if shell.endswith("zsh"):
        return [home / ".zshrc"]
    if shell.endswith("bash"):
        if os.uname().sysname == "Darwin":
            existing = [p for p in (home / ".bash_profile", home / ".bashrc") if p.exists()]
            return existing or [home / ".bash_profile"]
        return [home / ".bashrc"]
    return []


def _upsert_path_block(path: Path) -> None:
    block = f"{START}\n{EXPORT_LINE}\n{END}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    start = existing.find(START)
    end = existing.find(END)
    if start != -1 and end != -1 and end > start:
        end += len(END)
        new_content = existing[:start] + block.rstrip("\n") + existing[end:]
        if not new_content.endswith("\n"):
            new_content += "\n"
        path.write_text(new_content, encoding="utf-8")
        return
    prefix = existing
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    path.write_text(prefix + block, encoding="utf-8")
```

- [ ] **Step 5: Run path setup tests**

Run:

```bash
pytest tests/unit/runtime/test_path_setup.py -q
```

Expected: pass.

- [ ] **Step 6: Add failing install script assertion**

Modify `tests/unit/runtime/test_install_script.py` first test to assert shim creation. Add after existing env assertions:

```python
    shim = tmp_path / "home" / ".sebastian" / "bin" / "sebastian"
    assert shim.is_file()
    assert str(project / ".venv" / "bin" / "sebastian") in shim.read_text()
```

- [ ] **Step 7: Update `scripts/install.sh` to call path setup**

After `pip install -e .` succeeds, insert:

```bash
color_ylw "→ 配置 sebastian 命令入口"
python3 -m sebastian.cli.path_setup >/dev/null || {
  color_red "❌ 配置 sebastian 命令入口失败"
  exit 1
}
export PATH="$HOME/.sebastian/bin:$PATH"
color_grn "✓ sebastian 命令入口已配置"
```

Add a `if __name__ == "__main__"` entrypoint to `path_setup.py`:

```python
def main() -> None:
    from sebastian.cli.updater import resolve_install_dir

    ensure_cli_path(install_dir=resolve_install_dir())


if __name__ == "__main__":
    main()
```

Keep the script using `python3 -m ...` instead of bare `python -m ...` because
the existing shell-script tests fake `python3`; they do not provide a
`.venv/bin/python` executable in the activated fake venv. If implementation
switches to bare `python`, update the fake activation harness to create
`.venv/bin/python` and handle the module invocation deterministically.

- [ ] **Step 8: Add updater test for shim refresh**

In `tests/unit/runtime/test_updater.py`, add:

```python
def test_run_update_refreshes_cli_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    _patch_backup_parent: Path,
) -> None:
    inst = _make_install_dir(tmp_path)
    tar = _build_release_tarball(tmp_path, version="9.9.9")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(
        f"{hashlib.sha256(tar.read_bytes()).hexdigest()}  {tar.name}\n"
    )
    monkeypatch.setenv("SEBASTIAN_INSTALL_DIR", str(inst))
    monkeypatch.setattr(updater, "fetch_latest_tag", lambda: "v9.9.9")
    monkeypatch.setattr(updater, "_download", lambda url, dest: dest.write_bytes(
        tar.read_bytes() if dest.name.endswith(".tar.gz") else sums.read_bytes()
    ))
    monkeypatch.setattr(updater, "reinstall_editable", lambda install_dir: None)
    monkeypatch.setattr(updater, "_try_restart_daemon", lambda printer: None)
    path_setup = MagicMock()
    monkeypatch.setattr("sebastian.cli.path_setup.ensure_cli_path", path_setup)

    assert updater.run_update(assume_yes=True) == 0

    path_setup.assert_called_once_with(install_dir=inst)
```

- [ ] **Step 9: Update updater implementation**

In `sebastian/cli/updater.py`, after `printer(f"✓ 升级完成：{cur} → {latest}")` and before `_try_restart_daemon(printer)`, add:

```python
    try:
        from sebastian.cli.path_setup import ensure_cli_path

        ensure_cli_path(install_dir=install_dir)
        printer("✓ sebastian 命令入口已刷新")
    except Exception as e:  # noqa: BLE001
        printer(f"⚠ sebastian 命令入口刷新失败：{e}")
```

- [ ] **Step 10: Run focused runtime tests**

Run:

```bash
pytest tests/unit/runtime/test_path_setup.py tests/unit/runtime/test_install_script.py tests/unit/runtime/test_updater.py -q
```

Expected: pass.

- [ ] **Step 11: Commit Task 1**

```bash
git add sebastian/cli/path_setup.py scripts/install.sh sebastian/cli/updater.py tests/unit/runtime/test_path_setup.py tests/unit/runtime/test_install_script.py tests/unit/runtime/test_updater.py
git commit -m "feat(cli): 配置稳定 sebastian 命令入口"
```

---

### Task 2: Shared Skill Metadata Validation

**Files:**
- Create: `sebastian/capabilities/skills/metadata.py`
- Modify: `sebastian/capabilities/skills/_loader.py`
- Test: `tests/unit/capabilities/test_skill_metadata.py`
- Test: `tests/unit/capabilities/test_skills_loader.py`

- [ ] **Step 1: Write failing metadata tests**

Create `tests/unit/capabilities/test_skill_metadata.py`:

```python
from __future__ import annotations

import pytest

from sebastian.capabilities.skills.metadata import (
    SkillMetadataError,
    parse_skill_metadata,
    validate_skill_name,
)


def test_parse_skill_metadata_reads_frontmatter() -> None:
    meta = parse_skill_metadata(
        "---\nname: flight_search\ndescription: Search flights\n---\nBody",
        fallback_name="fallback",
    )
    assert meta.name == "flight_search"
    assert meta.registered_name == "skill__flight_search"
    assert meta.description == "Search flights"
    assert meta.body == "Body"


@pytest.mark.parametrize("name", ["bad name", "../x", "skill__double", "x.y"])
def test_validate_skill_name_rejects_invalid_names(name: str) -> None:
    with pytest.raises(SkillMetadataError):
        validate_skill_name(name)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest tests/unit/capabilities/test_skill_metadata.py -q
```

Expected: fail with missing module.

- [ ] **Step 3: Implement shared metadata helper**

Create `sebastian/capabilities/skills/metadata.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_FRONTMATTER_RE = re.compile(r"^(\w+)\s*:\s*(.+)$")


class SkillMetadataError(ValueError):
    pass


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    registered_name: str
    description: str
    body: str


def validate_skill_name(name: str) -> None:
    if not name or not _NAME_RE.match(name):
        raise SkillMetadataError(f"Invalid skill name: {name!r}")
    if name.startswith("skill__"):
        raise SkillMetadataError("Skill name must not include skill__ prefix")


def parse_skill_metadata(content: str, *, fallback_name: str) -> SkillMetadata:
    meta: dict[str, str] = {}
    body = content
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            block = content[3:end].strip()
            body = content[end + 4 :].strip()
            for line in block.splitlines():
                m = _FRONTMATTER_RE.match(line.strip())
                if m:
                    meta[m.group(1)] = m.group(2).strip()
    name = meta.get("name", fallback_name)
    validate_skill_name(name)
    return SkillMetadata(
        name=name,
        registered_name=f"skill__{name}",
        description=meta.get("description", ""),
        body=body,
    )
```

- [ ] **Step 4: Update loader to use shared helper**

Modify `sebastian/capabilities/skills/_loader.py`:

- Remove local `_parse_frontmatter`.
- Import `logging` and `parse_skill_metadata`, `SkillMetadataError`.
- In `load_skills()`, replace parsing block with:

```python
            try:
                metadata = parse_skill_metadata(content, fallback_name=entry.name)
            except SkillMetadataError as exc:
                logger.warning("Skipping invalid Skill %s: %s", skill_md, exc)
                continue

            full_instructions = (
                f"{metadata.description}\n\n{metadata.body}".strip()
                if metadata.body
                else metadata.description
            )
            skills[metadata.name] = {
                "name": metadata.registered_name,
                ...
            }
```

- [ ] **Step 5: Add loader test for invalid manual Skill skip**

Append to `tests/unit/capabilities/test_skills_loader.py`:

```python
def test_skill_loader_skips_invalid_skill_name(tmp_path: Path) -> None:
    skill_dir = tmp_path / "bad"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: bad name\ndescription: Bad\n---\n")

    from sebastian.capabilities.skills._loader import load_skills

    assert load_skills(builtin_dir=tmp_path) == []
```

- [ ] **Step 6: Run focused metadata/loader tests**

```bash
pytest tests/unit/capabilities/test_skill_metadata.py tests/unit/capabilities/test_skills_loader.py -q
```

Expected: pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add sebastian/capabilities/skills/metadata.py sebastian/capabilities/skills/_loader.py tests/unit/capabilities/test_skill_metadata.py tests/unit/capabilities/test_skills_loader.py
git commit -m "feat(skills): 统一 Skill 元数据校验"
```

---

### Task 3: Registry Models, Client, and URL Policy

**Files:**
- Create: `sebastian/skills_registry/__init__.py`
- Create: `sebastian/skills_registry/models.py`
- Create: `sebastian/skills_registry/client.py`
- Test: `tests/unit/skills_registry/test_client.py`

- [ ] **Step 1: Write failing client tests**

Create `tests/unit/skills_registry/test_client.py`:

```python
from __future__ import annotations

import pytest

from sebastian.skills_registry.client import (
    RegistryClient,
    RegistryUrlError,
    resolve_registry_url,
)


def test_resolve_registry_url_prefers_argument(monkeypatch) -> None:
    monkeypatch.setenv("SEBASTIAN_SKILLS_REGISTRY_URL", "https://mirror.example")
    assert resolve_registry_url("https://custom.example") == "https://custom.example"


def test_resolve_registry_url_uses_env(monkeypatch) -> None:
    monkeypatch.setenv("SEBASTIAN_SKILLS_REGISTRY_URL", "https://mirror.example")
    assert resolve_registry_url(None) == "https://mirror.example"


def test_resolve_registry_url_defaults(monkeypatch) -> None:
    monkeypatch.delenv("SEBASTIAN_SKILLS_REGISTRY_URL", raising=False)
    assert resolve_registry_url(None) == "https://clawhub.ai"


def test_resolve_registry_url_rejects_http() -> None:
    with pytest.raises(RegistryUrlError):
        resolve_registry_url("http://example.com")


def test_direct_download_url_rejects_third_party_origin() -> None:
    client = RegistryClient("https://clawhub.ai")
    with pytest.raises(RegistryUrlError):
        client.resolve_download_url({"download_url": "https://evil.example/x.zip"})
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest tests/unit/skills_registry/test_client.py -q
```

Expected: fail with missing package.

- [ ] **Step 3: Implement models**

Create `sebastian/skills_registry/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


class SkillRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SkillSearchResult:
    slug: str
    name: str
    description: str
    latest_version: str | None = None
    security_status: str | None = None


@dataclass(frozen=True)
class SkillDetail:
    slug: str
    name: str
    description: str
    version: str | None
    download_url: str | None
    sha256: str | None
    security_status: str | None
    raw: dict[str, object]
```

- [ ] **Step 4: Implement client**

Create `sebastian/skills_registry/client.py` using `httpx.Client(trust_env=True)`:

```python
from __future__ import annotations

from urllib.parse import urljoin, urlparse

import httpx

from sebastian.skills_registry.models import SkillDetail, SkillRegistryError, SkillSearchResult

DEFAULT_REGISTRY_URL = "https://clawhub.ai"


class RegistryUrlError(SkillRegistryError):
    pass


def resolve_registry_url(registry: str | None) -> str:
    import os

    value = (registry or os.environ.get("SEBASTIAN_SKILLS_REGISTRY_URL") or DEFAULT_REGISTRY_URL)
    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise RegistryUrlError("Skill registry URL must use https")
    return value.rstrip("/")


class RegistryClient:
    def __init__(self, registry_url: str | None = None) -> None:
        self.registry_url = resolve_registry_url(registry_url)

    def search(self, query: str, *, limit: int = 20) -> list[SkillSearchResult]:
        with httpx.Client(trust_env=True, timeout=30) as client:
            response = client.get(
                f"{self.registry_url}/api/v1/search",
                params={"q": query, "limit": limit},
            )
            response.raise_for_status()
        data = response.json()
        items = data if isinstance(data, list) else data.get("items", [])
        return [self._parse_search_item(item) for item in items if isinstance(item, dict)]

    def inspect(self, slug: str, *, version: str | None = None) -> SkillDetail:
        params = {"version": version} if version else None
        with httpx.Client(trust_env=True, timeout=30) as client:
            response = client.get(f"{self.registry_url}/api/v1/skills/{slug}", params=params)
            response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise SkillRegistryError("Registry returned invalid skill detail")
        return self._parse_detail(data)

    def resolve_download_url(self, data: dict[str, object]) -> str:
        raw = data.get("download_url") or data.get("downloadUrl") or data.get("url")
        if raw:
            value = str(raw)
            parsed = urlparse(value)
            registry = urlparse(self.registry_url)
            if parsed.scheme != "https":
                raise RegistryUrlError("Download URL must use https")
            if parsed.netloc != registry.netloc:
                raise RegistryUrlError("Download URL must be same-origin with registry")
            return value
        return urljoin(self.registry_url + "/", "api/v1/download")

    def _parse_search_item(self, item: dict[str, object]) -> SkillSearchResult:
        return SkillSearchResult(
            slug=str(item.get("slug") or item.get("id") or ""),
            name=str(item.get("name") or item.get("slug") or ""),
            description=str(item.get("description") or item.get("summary") or ""),
            latest_version=_maybe_str(item.get("latest_version") or item.get("version")),
            security_status=_maybe_str(item.get("security_status") or item.get("status")),
        )

    def _parse_detail(self, data: dict[str, object]) -> SkillDetail:
        return SkillDetail(
            slug=str(data.get("slug") or data.get("id") or ""),
            name=str(data.get("name") or data.get("slug") or ""),
            description=str(data.get("description") or data.get("summary") or ""),
            version=_maybe_str(data.get("version") or data.get("latest_version")),
            download_url=_maybe_str(data.get("download_url") or data.get("downloadUrl")),
            sha256=_maybe_str(data.get("sha256") or data.get("digest")),
            security_status=_maybe_str(data.get("security_status") or data.get("status")),
            raw=data,
        )


def _maybe_str(value: object) -> str | None:
    return None if value is None else str(value)
```

- [ ] **Step 5: Add unsafe status tests**

Append:

```python
from sebastian.skills_registry.client import is_installable_status


@pytest.mark.parametrize("status", ["malicious", "quarantined", "blocked", "hidden", "suspicious"])
def test_unsafe_status_is_not_installable(status: str) -> None:
    assert is_installable_status(status) is False


def test_missing_status_is_installable() -> None:
    assert is_installable_status(None) is True
```

Implement in `client.py`:

```python
UNSAFE_STATUSES = {"malicious", "quarantined", "blocked", "hidden", "suspicious"}


def is_installable_status(status: str | None) -> bool:
    return status is None or status.lower() not in UNSAFE_STATUSES
```

- [ ] **Step 6: Run client tests**

```bash
pytest tests/unit/skills_registry/test_client.py -q
```

Expected: pass.

- [ ] **Step 7: Commit Task 3**

```bash
git add sebastian/skills_registry/__init__.py sebastian/skills_registry/models.py sebastian/skills_registry/client.py tests/unit/skills_registry/test_client.py
git commit -m "feat(skills): 新增 Skill registry client"
```

---

### Task 4: Archive Safety, Fingerprint, Lockfile, and Recoverable Swap

**Files:**
- Create: `sebastian/skills_registry/safety.py`
- Create: `sebastian/skills_registry/lockfile.py`
- Test: `tests/unit/skills_registry/test_safety.py`
- Test: `tests/unit/skills_registry/test_lockfile.py`

- [ ] **Step 1: Write failing archive safety tests**

Create `tests/unit/skills_registry/test_safety.py`:

```python
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from sebastian.skills_registry.safety import (
    ArchiveSafetyError,
    compute_package_fingerprint,
    safe_extract_zip,
)


def _zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


def test_safe_extract_rejects_traversal(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "bad.zip", {"../evil": b"x"})
    with pytest.raises(ArchiveSafetyError):
        safe_extract_zip(archive, tmp_path / "out")


def test_safe_extract_requires_skill_md(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "bad.zip", {"skill/README.md": b"x"})
    with pytest.raises(ArchiveSafetyError, match="SKILL.md"):
        safe_extract_zip(archive, tmp_path / "out")


def test_fingerprint_excludes_manager_metadata(tmp_path: Path) -> None:
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text("hello")
    fp1 = compute_package_fingerprint(root)
    (root / ".sebastian-origin.json").write_text("{}")
    (root / ".sebastian").mkdir()
    (root / ".sebastian" / "state.json").write_text("{}")
    fp2 = compute_package_fingerprint(root)
    assert fp1 == fp2


def test_safe_extract_rejects_zip_symlink_entry(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("skill/link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        zf.writestr(info, "target")
        zf.writestr("skill/SKILL.md", "---\nname: ok\ndescription: Ok\n---\n")
    with pytest.raises(ArchiveSafetyError, match="symlink"):
        safe_extract_zip(archive, tmp_path / "out")


def test_safe_extract_rejects_zip_special_file_entry(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("skill/socket")
        info.create_system = 3
        info.external_attr = 0o140777 << 16
        zf.writestr(info, "")
        zf.writestr("skill/SKILL.md", "---\nname: ok\ndescription: Ok\n---\n")
    with pytest.raises(ArchiveSafetyError, match="special"):
        safe_extract_zip(archive, tmp_path / "out")


def test_safe_extract_rejects_binary_skill_md(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "bad.zip", {"skill/SKILL.md": b"\xff\xfe\x00"})
    with pytest.raises(ArchiveSafetyError, match="SKILL.md"):
        safe_extract_zip(archive, tmp_path / "out")


def test_safe_extract_rejects_invalid_skill_name(tmp_path: Path) -> None:
    archive = _zip(
        tmp_path / "bad.zip",
        {"skill/SKILL.md": b"---\nname: bad name\ndescription: Bad\n---\n"},
    )
    with pytest.raises(ArchiveSafetyError, match="Invalid skill name"):
        safe_extract_zip(archive, tmp_path / "out")
```

- [ ] **Step 2: Implement safety helpers**

Create `sebastian/skills_registry/safety.py`:

```python
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from sebastian.capabilities.skills.metadata import SkillMetadataError, parse_skill_metadata

MAX_FILES = 200
MAX_FILE_SIZE = 1_048_576
MAX_TOTAL_SIZE = 5 * 1_048_576
MANAGER_METADATA = {".sebastian-origin.json"}


class ArchiveSafetyError(RuntimeError):
    pass


def safe_extract_zip(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    total = 0
    count = 0
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            count += 1
            if count > MAX_FILES:
                raise ArchiveSafetyError("Archive contains too many files")
            if info.file_size > MAX_FILE_SIZE:
                raise ArchiveSafetyError(f"Archive member too large: {info.filename}")
            if _zipinfo_is_symlink(info):
                raise ArchiveSafetyError(f"Archive member is a symlink: {info.filename}")
            if _zipinfo_is_special_file(info):
                raise ArchiveSafetyError(f"Archive member is a special file: {info.filename}")
            total += info.file_size
            if total > MAX_TOTAL_SIZE:
                raise ArchiveSafetyError("Archive total size too large")
            target = (destination / info.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ArchiveSafetyError(f"Unsafe archive path: {info.filename}")
        zf.extractall(destination)
    root = _find_skill_root(destination)
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        raise ArchiveSafetyError("Archive does not contain root-level SKILL.md")
    try:
        content = skill_md.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ArchiveSafetyError("SKILL.md must be UTF-8 text") from exc
    try:
        parse_skill_metadata(content, fallback_name=root.name)
    except SkillMetadataError as exc:
        raise ArchiveSafetyError(str(exc)) from exc
    return root


def _find_skill_root(destination: Path) -> Path:
    if (destination / "SKILL.md").is_file():
        return destination
    dirs = [p for p in destination.iterdir() if p.is_dir()]
    if len(dirs) == 1 and (dirs[0] / "SKILL.md").is_file():
        return dirs[0]
    raise ArchiveSafetyError("Archive must contain exactly one Skill root")


def compute_package_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if _is_manager_metadata(rel):
            continue
        digest.update(str(rel).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _is_manager_metadata(relative: Path) -> bool:
    parts = relative.parts
    return relative.name in MANAGER_METADATA or (parts and parts[0] == ".sebastian")


def _zipinfo_is_symlink(info: zipfile.ZipInfo) -> bool:
    return info.create_system == 3 and ((info.external_attr >> 16) & 0o170000) == 0o120000


def _zipinfo_is_special_file(info: zipfile.ZipInfo) -> bool:
    if info.create_system != 3:
        return False
    file_type = (info.external_attr >> 16) & 0o170000
    return file_type not in {0, 0o040000, 0o100000, 0o120000}
```

ZIP does not have a distinct POSIX hardlink entry type like tar. v1 only
supports ZIP extraction and never creates filesystem links from archive
metadata. If a future registry format adds tar support, reject hardlink entries
before extraction the same way symlinks and special files are rejected here.

- [ ] **Step 3: Write failing lockfile tests**

Create `tests/unit/skills_registry/test_lockfile.py`:

```python
from __future__ import annotations

from pathlib import Path

from sebastian.skills_registry.lockfile import (
    LockfileEntry,
    SkillPackageLock,
    with_package_lock,
)


def test_lockfile_round_trip(tmp_path: Path) -> None:
    lock = SkillPackageLock(tmp_path)
    entry = LockfileEntry(
        slug="flight",
        registered_name="skill__flight",
        registry="https://clawhub.ai",
        version="1.0.0",
        tag="latest",
        sha256="abc",
        fingerprint="def",
        installed_at="2026-05-08T00:00:00Z",
    )
    lock.update_entry(entry)

    loaded = SkillPackageLock(tmp_path).load()
    assert loaded["flight"].registered_name == "skill__flight"


def test_package_lock_covers_entire_transaction(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    with with_package_lock(tmp_path):
        marker.write_text("inside")
    assert marker.read_text() == "inside"
```

- [ ] **Step 4: Implement lockfile helper**

Create `sebastian/skills_registry/lockfile.py` with a simple Unix `fcntl` exclusive lock. If Windows support is not in scope for v1, raise a clear error on non-POSIX; do not silently skip locking.

```python
from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

LOCKFILE_NAME = ".sebastian-skills.lock.json"
MUTEX_NAME = ".sebastian-skills.lock"


@dataclass(frozen=True)
class LockfileEntry:
    slug: str
    registered_name: str
    registry: str
    version: str
    tag: str
    sha256: str
    fingerprint: str
    installed_at: str


@contextlib.contextmanager
def with_package_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / MUTEX_NAME
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class SkillPackageLock:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / LOCKFILE_NAME

    def load(self) -> dict[str, LockfileEntry]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        skills = data.get("skills", {})
        return {slug: LockfileEntry(**entry) for slug, entry in skills.items()}

    def save(self, entries: dict[str, LockfileEntry]) -> None:
        payload = {
            "version": 1,
            "skills": {
                slug: dataclasses.asdict(entry)
                for slug, entry in sorted(entries.items())
            },
        }
        _atomic_write_json(self.path, payload)

    def update_entry(self, entry: LockfileEntry) -> None:
        with with_package_lock(self.root):
            entries = self.load()
            entries[entry.slug] = entry
            self.save(entries)


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(tmp, path)
```

- [ ] **Step 5: Run safety/lockfile tests**

```bash
pytest tests/unit/skills_registry/test_safety.py tests/unit/skills_registry/test_lockfile.py -q
```

Expected: pass.

- [ ] **Step 6: Commit Task 4**

```bash
git add sebastian/skills_registry/safety.py sebastian/skills_registry/lockfile.py tests/unit/skills_registry/test_safety.py tests/unit/skills_registry/test_lockfile.py
git commit -m "feat(skills): 增加 Skill 包安全校验与锁文件"
```

---

### Task 5: Installer Orchestration

**Files:**
- Create: `sebastian/skills_registry/installer.py`
- Modify: `sebastian/skills_registry/models.py`
- Test: `tests/unit/skills_registry/test_installer.py`

- [ ] **Step 1: Write installer tests for registered name collision**

Create `tests/unit/skills_registry/test_installer.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.skills_registry.installer import (
    SkillInstallError,
    _scan_registered_name_owners,
    _validate_registered_name_available,
)
from sebastian.skills_registry.lockfile import LockfileEntry, SkillPackageLock


def test_registered_name_collision_rejects_different_slug(tmp_path: Path) -> None:
    existing = {
        "travel-pack": LockfileEntry(
            slug="travel-pack",
            registered_name="skill__travel",
            registry="https://clawhub.ai",
            version="1.0.0",
            tag="latest",
            sha256="sha",
            fingerprint="fp",
            installed_at="2026-05-08T00:00:00Z",
        )
    }
    with pytest.raises(SkillInstallError, match="registered name"):
        _validate_registered_name_available(
            slug="foo-pack",
            registered_name="skill__travel",
            entries=existing,
            skills_root=tmp_path,
            owners={},
            destination=tmp_path / "foo-pack",
            force=False,
        )
```

- [ ] **Step 2: Write installer tests for unmanaged registered name collision**

Append:

```python
def test_registered_name_collision_rejects_unmanaged_skill_directory(tmp_path: Path) -> None:
    manual = tmp_path / "manual-travel"
    manual.mkdir()
    (manual / "SKILL.md").write_text(
        "---\nname: travel\ndescription: Manual travel skill\n---\n",
        encoding="utf-8",
    )

    owners = _scan_registered_name_owners(tmp_path)

    with pytest.raises(SkillInstallError, match="manual-travel"):
        _validate_registered_name_available(
            slug="foo-pack",
            registered_name="skill__travel",
            entries={},
            skills_root=tmp_path,
            owners=owners,
            destination=tmp_path / "foo-pack",
            force=False,
        )
```

This must scan `skills_root/*/SKILL.md` with the shared metadata parser, not
only the managed lockfile. Runtime registration is based on frontmatter name, so
manual Skills can collide even when the lockfile is empty.

- [ ] **Step 3: Write installer tests for rename on update**

Append:

```python
from sebastian.skills_registry.installer import _validate_update_registered_name


def test_update_registered_name_change_requires_confirmation() -> None:
    entry = LockfileEntry(
        slug="flight",
        registered_name="skill__flight",
        registry="https://clawhub.ai",
        version="1.0.0",
        tag="latest",
        sha256="sha",
        fingerprint="fp",
        installed_at="2026-05-08T00:00:00Z",
    )
    with pytest.raises(SkillInstallError, match="runtime tool name"):
        _validate_update_registered_name(entry, "skill__airfare", allow_rename=False)
```

- [ ] **Step 4: Write installer tests for unsafe status and digest verification**

Append:

```python
from sebastian.skills_registry.installer import (
    _validate_archive_digest,
    _validate_security_status,
)


def test_unsafe_registry_status_is_rejected() -> None:
    with pytest.raises(SkillInstallError, match="unsafe"):
        _validate_security_status("malicious")


def test_archive_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "skill.zip"
    archive.write_bytes(b"not-the-registry-archive")

    with pytest.raises(SkillInstallError, match="sha256"):
        _validate_archive_digest(archive, expected_sha256="0" * 64)
```

Treat `malicious`, `quarantined`, `hidden`, and `suspicious` as fail-closed
statuses. Do not let agent-assisted install bypass this with `force`.

- [ ] **Step 5: Write installer tests for origin write and rollback**

Append:

```python
from sebastian.skills_registry.installer import (
    _atomic_write_origin,
    _run_install_transaction,
)


def test_origin_json_is_written_atomically(tmp_path: Path) -> None:
    destination = tmp_path / "flight"
    destination.mkdir()

    _atomic_write_origin(destination, {"slug": "flight", "registry": "https://clawhub.ai"})

    assert (destination / ".sebastian-origin.json").is_file()
    assert not (destination / ".sebastian-origin.json.tmp").exists()


def test_install_transaction_rolls_back_when_origin_write_fails(tmp_path: Path, monkeypatch) -> None:
    destination = tmp_path / "flight"
    destination.mkdir()
    (destination / "SKILL.md").write_text(
        "---\nname: old_flight\ndescription: Old\n---\n",
        encoding="utf-8",
    )
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "SKILL.md").write_text(
        "---\nname: flight\ndescription: New\n---\n",
        encoding="utf-8",
    )

    def fail_origin(*args, **kwargs) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("sebastian.skills_registry.installer._atomic_write_origin", fail_origin)

    with pytest.raises(OSError, match="disk full"):
        _run_install_transaction(
            skills_root=tmp_path,
            slug="flight",
            registered_name="skill__flight",
            staging_root=staging,
            origin_payload={"slug": "flight"},
            lockfile_entry_factory=lambda fingerprint: None,
            force=True,
        )

    assert "old_flight" in (destination / "SKILL.md").read_text(encoding="utf-8")
```

The transaction helper may use a different return shape during implementation,
but the test must prove rollback on origin/lockfile failure, not just successful
swap.

- [ ] **Step 6: Write installer tests for update mismatch, remove, and unmanaged list**

Append:

```python
from sebastian.skills_registry.installer import (
    _validate_local_fingerprint,
    list_installed,
    remove_installed_skill,
)


def test_update_rejects_local_fingerprint_mismatch() -> None:
    entry = LockfileEntry(
        slug="flight",
        registered_name="skill__flight",
        registry="https://clawhub.ai",
        version="1.0.0",
        tag="latest",
        sha256="sha",
        fingerprint="expected",
        installed_at="2026-05-08T00:00:00Z",
    )

    with pytest.raises(SkillInstallError, match="local changes"):
        _validate_local_fingerprint(entry, current_fingerprint="actual", force=False)


def test_remove_transaction_removes_directory_and_lockfile_entry(tmp_path: Path) -> None:
    destination = tmp_path / "flight"
    destination.mkdir()
    (destination / "SKILL.md").write_text(
        "---\nname: flight\ndescription: Flight search\n---\n",
        encoding="utf-8",
    )
    entry = LockfileEntry(
        slug="flight",
        registered_name="skill__flight",
        registry="https://clawhub.ai",
        version="1.0.0",
        tag="latest",
        sha256="sha",
        fingerprint="fp",
        installed_at="2026-05-08T00:00:00Z",
    )
    SkillPackageLock(tmp_path).save({"flight": entry})

    result = remove_installed_skill("flight", skills_root=tmp_path, yes=True)

    assert result.slug == "flight"
    assert not destination.exists()
    assert "flight" not in SkillPackageLock(tmp_path).load()


def test_list_installed_includes_unmanaged_skills(tmp_path: Path) -> None:
    manual = tmp_path / "manual"
    manual.mkdir()
    (manual / "SKILL.md").write_text(
        "---\nname: manual\ndescription: Manual\n---\n",
        encoding="utf-8",
    )

    installed = list_installed(tmp_path)

    assert any(item.slug == "manual" and item.managed is False for item in installed)
```

Keep these as executable tests, not prose-only reminders.

- [ ] **Step 7: Write installer test that lock covers whole transaction**

Use a fake hook inside installer later:

```python
def test_install_transaction_holds_package_lock_during_swap(tmp_path: Path, monkeypatch) -> None:
    from sebastian.skills_registry import installer

    observed: list[bool] = []

    def fake_swap(*args, **kwargs):
        observed.append((tmp_path / ".sebastian-skills.lock").exists())

    monkeypatch.setattr(installer, "_recoverable_directory_swap", fake_swap)
    # Construct this as a narrow unit around the transaction helper if full install setup is too heavy.
    # Expected final assertion:
    # assert observed == [True]
```

If this full test becomes awkward during implementation, replace it with a direct test of a `_run_install_transaction(root, callback)` helper. The invariant is non-negotiable: the package-manager lock wraps conflict validation, directory swap, origin write, lockfile write, and backup cleanup.

- [ ] **Step 8: Implement installer helper functions**

Create `sebastian/skills_registry/installer.py` with:

```python
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from sebastian.capabilities.skills.metadata import parse_skill_metadata
from sebastian.skills_registry.lockfile import LockfileEntry


class SkillInstallError(RuntimeError):
    pass


def _validate_registered_name_available(
    *,
    slug: str,
    registered_name: str,
    entries: dict[str, LockfileEntry],
    skills_root: Path,
    owners: dict[str, Path],
    destination: Path,
    force: bool,
) -> None:
    for existing_slug, entry in entries.items():
        if entry.registered_name != registered_name:
            continue
        if existing_slug == slug and force:
            return
        if existing_slug == slug:
            return
        raise SkillInstallError(
            f"Skill registered name {registered_name!r} is already managed by {existing_slug!r}"
        )
    owner = owners.get(registered_name)
    if owner is not None and owner.resolve() != destination.resolve():
        raise SkillInstallError(
            f"Skill registered name {registered_name!r} is already provided by {owner.name!r}"
        )


def _scan_registered_name_owners(skills_root: Path) -> dict[str, Path]:
    owners: dict[str, Path] = {}
    for child in skills_root.iterdir() if skills_root.exists() else []:
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        metadata = parse_skill_metadata(
            skill_md.read_text(encoding="utf-8"),
            fallback_name=child.name,
        )
        owners[metadata.registered_name] = child
    return owners


def _validate_archive_digest(archive: Path, *, expected_sha256: str) -> None:
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise SkillInstallError("Downloaded archive sha256 does not match registry metadata")


def _validate_security_status(status: str | None) -> None:
    if status in {"malicious", "quarantined", "hidden", "suspicious"}:
        raise SkillInstallError(f"Registry marks this Skill as unsafe: {status}")


def _atomic_write_origin(destination: Path, payload: dict[str, object]) -> None:
    path = destination / ".sebastian-origin.json"
    tmp = destination / ".sebastian-origin.json.tmp"
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(tmp, path)


def _validate_update_registered_name(
    entry: LockfileEntry,
    new_registered_name: str,
    *,
    allow_rename: bool,
) -> None:
    if entry.registered_name == new_registered_name:
        return
    if allow_rename:
        return
    raise SkillInstallError(
        "Update changes runtime tool name "
        f"from {entry.registered_name!r} to {new_registered_name!r}"
    )
```

- [ ] **Step 9: Implement recoverable directory swap**

In `installer.py`, add:

```python
import shutil
import uuid


def _recoverable_directory_swap(staging: Path, destination: Path) -> Path | None:
    backup: Path | None = None
    if destination.exists():
        backup = destination.with_name(f".{destination.name}.backup.{uuid.uuid4().hex}")
        shutil.move(str(destination), str(backup))
    try:
        shutil.move(str(staging), str(destination))
    except Exception:
        if backup is not None and backup.exists():
            shutil.move(str(backup), str(destination))
        raise
    return backup


def _rollback_swap(destination: Path, backup: Path | None) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    if backup is not None and backup.exists():
        shutil.move(str(backup), str(destination))


def _cleanup_backup(backup: Path | None) -> None:
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)
```

- [ ] **Step 10: Implement high-level install/update/remove/list**

Add result models to `sebastian/skills_registry/models.py`:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InstalledSkill:
    slug: str
    registered_name: str
    version: str | None
    registry: str | None
    managed: bool
    path: Path


@dataclass(frozen=True)
class InstallResult:
    slug: str
    registered_name: str
    version: str
    path: Path


@dataclass(frozen=True)
class RemoveResult:
    slug: str
    registered_name: str
    path: Path
```

Implement public functions in `installer.py` with explicit signatures:

- `list_installed(root: Path) -> list[InstalledSkill]`
- `install_skill(slug: str, *, version: str | None, registry: str | None, force: bool) -> InstallResult`
- `update_skill(slug: str, *, version: str | None, registry: str | None, force: bool, allow_rename: bool) -> InstallResult`
- `remove_installed_skill(slug: str, *, yes: bool) -> RemoveResult`

Install and update must follow this order before entering the transaction:

1. Inspect registry metadata and reject unsafe moderation/security status.
2. Resolve download URL with the same-origin HTTPS policy from Task 3.
3. Download the archive to a temp path.
4. Verify `sha256` before extraction.
5. Extract through `safe_extract_zip()`.
6. Parse staged `SKILL.md` with `parse_skill_metadata()` and derive `registered_name`.

The critical install transaction must then be shaped like:

```python
with with_package_lock(skills_root):
    entries = lock.load()
    owners = _scan_registered_name_owners(skills_root)
    _validate_registered_name_available(
        slug=slug,
        registered_name=registered_name,
        entries=entries,
        skills_root=skills_root,
        owners=owners,
        destination=destination,
        force=force,
    )
    validate update rename and local fingerprint when replacing an existing managed entry
    backup = _recoverable_directory_swap(staging_root, destination)
    try:
        _atomic_write_origin(destination, origin_payload)
        fingerprint = compute_package_fingerprint(destination)
        entries[slug] = build LockfileEntry with fingerprint and registered_name
        lock.save(entries)
    except Exception:
        _rollback_swap(destination, backup)
        raise
    else:
        _cleanup_backup(backup)
```

Remove must also run under `with_package_lock(skills_root)` and cover:

1. Load lockfile entry.
2. Move destination to a recoverable backup.
3. Remove the lockfile entry atomically.
4. Delete backup only after lockfile write succeeds.
5. Roll back the directory if lockfile write fails.

`list_installed()` must merge managed lockfile entries with unmanaged
`skills_root/*/SKILL.md` scan results and mark unmanaged rows with
`managed=False`.

This is the implementation note from review: do not limit the mutex to lockfile
read/write. The same package-manager mutex covers conflict validation, swap,
origin write, fingerprint/lockfile update, and backup cleanup.

- [ ] **Step 11: Run installer tests**

```bash
pytest tests/unit/skills_registry/test_installer.py -q
```

Expected: pass.

- [ ] **Step 12: Commit Task 5**

```bash
git add sebastian/skills_registry/installer.py sebastian/skills_registry/models.py tests/unit/skills_registry/test_installer.py
git commit -m "feat(skills): 实现 Skill 安装事务"
```

---

### Task 6: `sebastian skills` CLI

**Files:**
- Create: `sebastian/cli/skills.py`
- Modify: `sebastian/main.py`
- Test: `tests/unit/runtime/test_skills_cli.py`
- Test: `tests/unit/runtime/test_cli_main.py`

- [ ] **Step 1: Write failing CLI mount test**

Create `tests/unit/runtime/test_skills_cli.py`:

```python
from __future__ import annotations

from typer.testing import CliRunner

from sebastian.main import app

runner = CliRunner()


def test_skills_command_is_mounted() -> None:
    result = runner.invoke(app, ["skills", "--help"])
    assert result.exit_code == 0
    assert "search" in result.output
    assert "install" in result.output
```

- [ ] **Step 2: Write CLI tests with mocked installer/client**

Append:

```python
def test_skills_search_prints_results(monkeypatch) -> None:
    monkeypatch.setattr(
        "sebastian.cli.skills.search_registry",
        lambda query, registry=None: [("flight-search", "Search flights")],
    )
    result = runner.invoke(app, ["skills", "search", "flight"])
    assert result.exit_code == 0
    assert "flight-search" in result.output
```

- [ ] **Step 3: Run tests to verify failure**

```bash
pytest tests/unit/runtime/test_skills_cli.py -q
```

Expected: fail because `skills` command is not mounted.

- [ ] **Step 4: Implement Typer app**

Create `sebastian/cli/skills.py`:

```python
from __future__ import annotations

import typer

app = typer.Typer(name="skills", help="Search, install, update, and remove Sebastian Skills")


def search_registry(query: str, registry: str | None = None) -> list[tuple[str, str]]:
    from sebastian.skills_registry.client import RegistryClient

    return [(item.slug, item.description) for item in RegistryClient(registry).search(query)]


@app.command()
def search(
    query: str,
    registry: str | None = typer.Option(None, "--registry"),
) -> None:
    for slug, description in search_registry(query, registry=registry):
        typer.echo(f"{slug}\t{description}")
```

Mount in `sebastian/main.py`:

```python
from sebastian.cli.skills import app as skills_app

app.add_typer(skills_app, name="skills")
```

- [ ] **Step 5: Add inspect/install/list/update/remove commands**

In `skills.py`, add commands:

- `inspect(slug, version=None, registry=None)`
- `install(slug, version=None, registry=None, force=False)`
- `list()`
- `update(slug=None, all=False, force=False, allow_rename=False)`
- `remove(slug, yes=False)`

Use `typer.echo()` and catch `SkillRegistryError` / `SkillInstallError` to print `❌ ...` and exit 1.

For mutating commands:

- If `--registry` is not the default registry, call `typer.confirm(..., abort=True)`
  before any network/install action.
- If `install --force` would overwrite an existing Skill, call
  `typer.confirm(..., abort=True)` before passing `force=True`.
- If `update --allow-rename` would accept a runtime tool-name change, call
  `typer.confirm(..., abort=True)` before passing `allow_rename=True`.
- `remove` must confirm unless `--yes` is explicitly present.
- Do not imply `--yes`.
- Do not imply `--force`.
- Print "Available to new Sebastian sessions" on success.

- [ ] **Step 6: Add CLI tests for mutating commands**

Patch `tests/unit/runtime/test_skills_cli.py` with monkeypatched installer functions:

```python
def test_skills_install_prints_new_session_message(monkeypatch) -> None:
    monkeypatch.setattr(
        "sebastian.cli.skills.install_skill",
        lambda **kwargs: type("Result", (), {"registered_name": "skill__flight"})(),
    )
    result = runner.invoke(app, ["skills", "install", "flight"])
    assert result.exit_code == 0
    assert "skill__flight" in result.output
    assert "new Sebastian sessions" in result.output
```

Append confirmation behavior tests:

```python
def test_install_non_default_registry_requires_confirmation(monkeypatch) -> None:
    called = False

    def fake_install_skill(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("sebastian.cli.skills.install_skill", fake_install_skill)

    result = runner.invoke(
        app,
        ["skills", "install", "flight", "--registry", "https://mirror.example"],
        input="n\n",
    )

    assert result.exit_code != 0
    assert called is False


def test_install_force_requires_overwrite_confirmation(monkeypatch) -> None:
    called = False

    def fake_install_skill(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("sebastian.cli.skills.install_skill", fake_install_skill)

    result = runner.invoke(app, ["skills", "install", "flight", "--force"], input="n\n")

    assert result.exit_code != 0
    assert called is False


def test_update_allow_rename_requires_confirmation(monkeypatch) -> None:
    called = False

    def fake_update_skill(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("sebastian.cli.skills.update_skill", fake_update_skill)

    result = runner.invoke(app, ["skills", "update", "flight", "--allow-rename"], input="n\n")

    assert result.exit_code != 0
    assert called is False


def test_remove_requires_confirmation_without_yes(monkeypatch) -> None:
    called = False

    def fake_remove_installed_skill(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("sebastian.cli.skills.remove_installed_skill", fake_remove_installed_skill)

    result = runner.invoke(app, ["skills", "remove", "flight"], input="n\n")

    assert result.exit_code != 0
    assert called is False


def test_remove_yes_skips_confirmation(monkeypatch) -> None:
    called = False

    def fake_remove_installed_skill(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("sebastian.cli.skills.remove_installed_skill", fake_remove_installed_skill)

    result = runner.invoke(app, ["skills", "remove", "flight", "--yes"])

    assert result.exit_code == 0
    assert called is True
```

These tests define cancellation semantics: declined confirmation exits non-zero
and must not call installer functions.

- [ ] **Step 7: Run CLI tests**

```bash
pytest tests/unit/runtime/test_skills_cli.py tests/unit/runtime/test_cli_main.py -q
```

Expected: pass.

- [ ] **Step 8: Commit Task 6**

```bash
git add sebastian/cli/skills.py sebastian/main.py tests/unit/runtime/test_skills_cli.py tests/unit/runtime/test_cli_main.py
git commit -m "feat(cli): 新增 skills 子命令"
```

---

### Task 7: Builtin `skill_installer` Skill and Hot Reload Integration Test

**Files:**
- Create: `sebastian/capabilities/skills/skill_installer/SKILL.md`
- Test: `tests/unit/capabilities/test_skill_hot_reload.py`
- Test: `tests/unit/capabilities/test_skills_loader.py`

- [ ] **Step 1: Add failing test for builtin Skill presence**

In `tests/unit/capabilities/test_skills_loader.py`, add:

```python
def test_builtin_skill_installer_is_loaded() -> None:
    from sebastian.capabilities import skills as skills_pkg
    from sebastian.capabilities.skills._loader import load_skills

    import pathlib

    specs = load_skills(builtin_dir=pathlib.Path(skills_pkg.__file__).parent)
    names = {spec["name"] for spec in specs}
    assert "skill__skill_installer" in names
```

- [ ] **Step 2: Create builtin Skill**

Create `sebastian/capabilities/skills/skill_installer/SKILL.md`:

```markdown
---
name: skill_installer
description: Search, inspect, install, update, list, and remove Sebastian Skills through the Sebastian CLI.
---

# Skill Installer

Use this Skill when the user asks to find, install, update, list, or remove Sebastian Skills.

Use the installed Sebastian CLI shim explicitly:

```bash
~/.sebastian/bin/sebastian skills search "<query>"
~/.sebastian/bin/sebastian skills inspect <slug>
~/.sebastian/bin/sebastian skills install <slug>
~/.sebastian/bin/sebastian skills list
~/.sebastian/bin/sebastian skills update <slug>
~/.sebastian/bin/sebastian skills remove <slug>
```

Rules:

- Always inspect before install or update.
- Before install or update, summarize registry-visible metadata: registry, slug/name, version, security/moderation status, download URL/SHA if shown, and warnings.
- Do not require a bundle file summary; CLI inspect does not list files unless future registry metadata provides them.
- After install or update, report the registered runtime Skill name from the CLI output.
- Ask the user for explicit confirmation before `install`, `update`, or `remove`.
- Do not pass `--yes` or `--force` unless the user explicitly requested that flag in the current conversation.
- Do not pass `--allow-rename` unless the user explicitly approves the registered-name change in the current conversation.
- Never use `--force` to bypass unsafe registry security/moderation status.
- Do not auto-accept an update that changes the registered Skill name.
- Do not use `--registry` unless the user names that registry.
- Never run scripts from downloaded Skill bundles during install.
- Never use `curl | bash` or similar third-party install commands.

After install/update/remove, tell the user that the change applies to new Sebastian sessions.
```

- [ ] **Step 3: Run loader test**

```bash
pytest tests/unit/capabilities/test_skills_loader.py -q
```

Expected: pass.

- [ ] **Step 4: Add hot reload integration test**

In `tests/unit/capabilities/test_skill_hot_reload.py`, add or adjust a test to install a fixture Skill into an extra dir using `installer.install_skill()` with a fake downloaded archive, then call `SkillHotReloader.maybe_reload()` and assert `registry.get_skill_specs()` contains the new registered name.

If full `install_skill()` setup is too much here, keep this as an installer unit test and rely on existing hot reload tests that observe new `SKILL.md` files. Do not duplicate a brittle end-to-end test.

- [ ] **Step 5: Run focused capability tests**

```bash
pytest tests/unit/capabilities/test_skills_loader.py tests/unit/capabilities/test_skill_hot_reload.py -q
```

Expected: pass.

- [ ] **Step 6: Commit Task 7**

```bash
git add sebastian/capabilities/skills/skill_installer/SKILL.md tests/unit/capabilities/test_skills_loader.py tests/unit/capabilities/test_skill_hot_reload.py
git commit -m "feat(skills): 新增 skill_installer 内置 Skill"
```

---

### Task 8: Documentation and Architecture Spec Integration

**Files:**
- Modify: `README.md`
- Modify: `sebastian/README.md`
- Modify: `sebastian/cli/README.md`
- Modify: `sebastian/capabilities/README.md`
- Modify: `sebastian/capabilities/skills/README.md`
- Modify: `docs/architecture/spec/capabilities/INDEX.md`
- Create: `docs/architecture/spec/capabilities/skill-package-manager.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update README docs**

Add concise user-facing docs:

- `sebastian skills search/install/list/update/remove`
- default registry and `--registry`
- install target `~/.sebastian/data/extensions/skills`
- new-session availability
- `~/.sebastian/bin/sebastian` shim and PATH block

- [ ] **Step 2: Update module READMEs**

Update:

- `sebastian/README.md`: CLI/capabilities overview.
- `sebastian/cli/README.md`: `skills.py`, `path_setup.py`, command table.
- `sebastian/capabilities/README.md`: installed Skill workflow.
- `sebastian/capabilities/skills/README.md`: package-managed Skills, `skill_installer`, metadata validation.

- [ ] **Step 3: Integrate architecture spec**

Create `docs/architecture/spec/capabilities/skill-package-manager.md` by adapting the implemented design from `docs/superpowers/specs/2026-05-08-skill-package-manager-design.md`.

Use frontmatter:

```yaml
---
version: "1.0"
last_updated: 2026-05-08
status: implemented
---
```

Update `docs/architecture/spec/capabilities/INDEX.md` with a row:

```markdown
| [skill-package-manager.md](skill-package-manager.md) | Sebastian Skill 包管理器：ClawHub-compatible registry consumer、CLI install/update/remove、lockfile、安全解压、PATH shim、builtin `skill_installer` |
```

- [ ] **Step 4: Update CHANGELOG**

Under `[Unreleased]`:

```markdown
### Added
- 新增 `sebastian skills` 命令，可从 ClawHub-compatible registry 搜索、检查、安装、更新和移除 Skill。
- 新增内置 `skill_installer` Skill，Sebastian 可按安全流程协助用户安装第三方 Skill。

### Changed
- 安装与升级流程会创建 `~/.sebastian/bin/sebastian` 命令入口，并默认写入 zsh/bash PATH 配置。
```

- [ ] **Step 5: Run docs-adjacent checks**

```bash
pytest tests/unit/runtime/test_skills_cli.py tests/unit/capabilities/test_skills_loader.py -q
```

Expected: pass.

- [ ] **Step 6: Commit Task 8**

```bash
git add README.md sebastian/README.md sebastian/cli/README.md sebastian/capabilities/README.md sebastian/capabilities/skills/README.md docs/architecture/spec/capabilities/INDEX.md docs/architecture/spec/capabilities/skill-package-manager.md CHANGELOG.md
git commit -m "docs(skills): 补充 Skill 包管理器文档"
```

---

### Task 9: Final Verification and Graphify

**Files:**
- No code changes expected unless verification finds issues.

- [ ] **Step 1: Run focused Python tests**

```bash
pytest \
  tests/unit/runtime/test_path_setup.py \
  tests/unit/runtime/test_install_script.py \
  tests/unit/runtime/test_updater.py \
  tests/unit/runtime/test_skills_cli.py \
  tests/unit/capabilities/test_skill_metadata.py \
  tests/unit/capabilities/test_skills_loader.py \
  tests/unit/capabilities/test_skill_hot_reload.py \
  tests/unit/skills_registry/test_client.py \
  tests/unit/skills_registry/test_safety.py \
  tests/unit/skills_registry/test_lockfile.py \
  tests/unit/skills_registry/test_installer.py \
  -q
```

Expected: pass.

- [ ] **Step 2: Run full backend quality checks**

```bash
ruff check sebastian/ tests/
ruff format --check sebastian/ tests/
mypy sebastian/
pytest tests/unit tests/integration -v
```

Expected: pass.

- [ ] **Step 3: Run graphify rebuild**

```bash
python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"
```

Expected: pass. If `graphify` is not installed in the active environment, record the exact error in the final implementation report.

- [ ] **Step 4: Inspect git diff**

```bash
git status --short
git log --oneline --decorate -10
```

Expected: only intended commits; worktree clean.

- [ ] **Step 5: Final commit if verification caused fixes**

If any fixes were needed:

```bash
git add <specific files>
git commit -m "fix(skills): 收口 Skill 包管理器验证问题"
```

---

## Implementation Notes

- Before implementing Python code, remember the repo instruction: PyCharm MCP should be preferred for symbol/reference queries if available. If the implementing agent does not have that MCP exposed, state that limitation and use local file reads/search.
- When delegating subagents, tell them they may use JetBrains PyCharm MCP and Android Studio MCP when available.
- Do not add a model-visible native `install_skill` tool.
- Keep `skill_installer` as a Skill that instructs use of Bash + CLI.
- Do not make current sessions refresh installed Skills. New-session hot reload is the v1 lifecycle.
- The package-manager mutex must cover the whole critical section: conflict validation, recoverable directory swap, origin write, lockfile write, and backup cleanup.
- Do not silently skip unsafe registry status. Fail closed.
- Do not let `.sebastian-origin.json` or `.sebastian/` affect package-manager fingerprints.
- Keep implementation files below 500 lines where practical. If `installer.py` approaches 800 lines, split transaction/swap helpers into a smaller module before continuing.
