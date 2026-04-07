from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sebastian.capabilities.tools._path_utils import resolve_path


def test_relative_path_resolves_to_workspace(tmp_path: Path) -> None:
    with patch("sebastian.capabilities.tools._path_utils.settings") as mock_settings:
        mock_settings.workspace_dir = tmp_path
        result = resolve_path("foo/bar.txt")
    assert result == (tmp_path / "foo/bar.txt").resolve()


def test_absolute_path_within_workspace_resolves_as_is(tmp_path: Path) -> None:
    with patch("sebastian.capabilities.tools._path_utils.settings") as mock_settings:
        mock_settings.workspace_dir = tmp_path
        abs_path = str(tmp_path / "sub" / "file.py")
        result = resolve_path(abs_path)
    assert result == Path(abs_path).resolve()


def test_absolute_path_outside_workspace_resolves_as_is(tmp_path: Path) -> None:
    with patch("sebastian.capabilities.tools._path_utils.settings") as mock_settings:
        mock_settings.workspace_dir = tmp_path
        result = resolve_path("/tmp/evil.txt")
    assert result == Path("/tmp/evil.txt").resolve()
