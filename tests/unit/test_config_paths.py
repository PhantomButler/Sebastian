from __future__ import annotations

from pathlib import Path

from sebastian.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(sebastian_data_dir=str(tmp_path))


def test_data_dir_remains_root(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.data_dir == tmp_path.resolve()


def test_user_data_dir_is_data_subdir(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.user_data_dir == (tmp_path / "data").resolve()


def test_logs_dir(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.logs_dir == (tmp_path / "logs").resolve()


def test_run_dir(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.run_dir == (tmp_path / "run").resolve()


def test_database_url_uses_user_data_dir(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.database_url == f"sqlite+aiosqlite:///{tmp_path.resolve()}/data/sebastian.db"


def test_workspace_dir_under_user_data(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.workspace_dir == (tmp_path / "data" / "workspace").resolve()


def test_extensions_dir_under_user_data(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.extensions_dir == (tmp_path / "data" / "extensions").resolve()


def test_resolved_secret_key_under_user_data(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.resolved_secret_key_path() == (tmp_path / "data" / "secret.key").resolve()


def test_sessions_dir_removed() -> None:
    # 显式断言旧属性已移除
    assert not hasattr(Settings, "sessions_dir")


def test_memory_dir_under_user_data(tmp_path: Path) -> None:
    """ensure_data_dir should create memory/ under user_data_dir."""
    import unittest.mock

    s = _settings(tmp_path)
    # patch settings used inside ensure_data_dir
    with unittest.mock.patch("sebastian.config.settings", s):
        # migrate_layout_v2 must also be patched to avoid touching real dirs
        with unittest.mock.patch("sebastian.store.migration.migrate_layout_v2"):
            from sebastian.config import ensure_data_dir

            ensure_data_dir()
    memory_dir = tmp_path / "data" / "memory"
    assert memory_dir.exists(), "memory/ subdir should be created by ensure_data_dir"
