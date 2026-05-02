from __future__ import annotations

from pathlib import Path

import pytest

from sebastian.core.soul_loader import SoulLoader

_BUILTIN = {"sebastian": "You are Sebastian.", "cortana": "You are Cortana."}


@pytest.fixture
def souls_dir(tmp_path: Path) -> Path:
    d = tmp_path / "souls"
    d.mkdir()
    return d


@pytest.fixture
def loader(souls_dir: Path) -> SoulLoader:
    return SoulLoader(souls_dir=souls_dir, builtin_souls=_BUILTIN)


def test_list_souls_empty_dir(loader: SoulLoader) -> None:
    assert loader.list_souls() == []


def test_list_souls_returns_stems(souls_dir: Path, loader: SoulLoader) -> None:
    (souls_dir / "alice.md").write_text("Alice persona")
    (souls_dir / "bob.md").write_text("Bob persona")
    assert loader.list_souls() == ["alice", "bob"]


def test_load_returns_content(souls_dir: Path, loader: SoulLoader) -> None:
    (souls_dir / "alice.md").write_text("Alice persona")
    assert loader.load("alice") == "Alice persona"


def test_load_returns_none_when_missing(loader: SoulLoader) -> None:
    assert loader.load("nonexistent") is None


def test_load_rejects_path_traversal(loader: SoulLoader) -> None:
    assert loader.load("../../etc/passwd") is None
    assert loader.load("../secret") is None
    assert loader.load("/absolute/path") is None


def test_ensure_defaults_creates_missing_files(souls_dir: Path, loader: SoulLoader) -> None:
    loader.ensure_defaults()
    assert (souls_dir / "sebastian.md").read_text() == "You are Sebastian."
    assert (souls_dir / "cortana.md").read_text() == "You are Cortana."


def test_ensure_defaults_does_not_overwrite_existing(souls_dir: Path, loader: SoulLoader) -> None:
    (souls_dir / "sebastian.md").write_text("Custom Sebastian")
    loader.ensure_defaults()
    assert (souls_dir / "sebastian.md").read_text() == "Custom Sebastian"


def test_ensure_defaults_creates_dir_if_missing(tmp_path: Path) -> None:
    souls_dir = tmp_path / "new_souls"
    loader = SoulLoader(souls_dir=souls_dir, builtin_souls=_BUILTIN)
    loader.ensure_defaults()
    assert souls_dir.exists()
    assert (souls_dir / "sebastian.md").exists()


def test_current_soul_default(loader: SoulLoader) -> None:
    assert loader.current_soul == "sebastian"


def test_current_soul_can_be_updated(loader: SoulLoader) -> None:
    loader.current_soul = "cortana"
    assert loader.current_soul == "cortana"
