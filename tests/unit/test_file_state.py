from __future__ import annotations

import pytest


def _clear():
    from sebastian.capabilities.tools import _file_state
    _file_state._file_mtimes.clear()


def test_record_read_stores_mtime(tmp_path):
    _clear()
    from sebastian.capabilities.tools import _file_state
    f = tmp_path / "a.txt"
    f.write_text("hello")
    _file_state.record_read(str(f))
    assert str(f) in _file_state._file_mtimes


def test_check_write_new_file_allowed(tmp_path):
    _clear()
    from sebastian.capabilities.tools import _file_state
    path = str(tmp_path / "new.txt")  # does not exist
    _file_state.check_write(path)  # must not raise


def test_check_write_requires_read_first(tmp_path):
    _clear()
    from sebastian.capabilities.tools import _file_state
    f = tmp_path / "existing.txt"
    f.write_text("content")
    with pytest.raises(ValueError, match="not been read"):
        _file_state.check_write(str(f))


def test_check_write_rejects_stale_mtime(tmp_path):
    _clear()
    from sebastian.capabilities.tools import _file_state
    f = tmp_path / "stale.txt"
    f.write_text("content")
    # Manually set a fake old mtime in cache (simulate "read a long time ago")
    _file_state._file_mtimes[str(f)] = 0.0
    with pytest.raises(ValueError, match="modified externally"):
        _file_state.check_write(str(f))


def test_check_write_passes_after_read(tmp_path):
    _clear()
    from sebastian.capabilities.tools import _file_state
    f = tmp_path / "ok.txt"
    f.write_text("content")
    _file_state.record_read(str(f))
    _file_state.check_write(str(f))  # must not raise


def test_invalidate_updates_cache(tmp_path):
    _clear()
    from sebastian.capabilities.tools import _file_state
    f = tmp_path / "out.txt"
    f.write_text("v1")
    _file_state.record_read(str(f))
    old_mtime = _file_state._file_mtimes[str(f)]
    f.write_text("v2")
    _file_state.invalidate(str(f))
    assert _file_state._file_mtimes[str(f)] != old_mtime


def test_record_read_nonexistent_path_does_not_raise():
    _clear()
    from sebastian.capabilities.tools import _file_state
    _file_state.record_read("/nonexistent/path/that/does/not/exist.txt")
    # Should not raise; path should not be in cache
    assert "/nonexistent/path/that/does/not/exist.txt" not in _file_state._file_mtimes


def test_invalidate_nonexistent_path_removes_key():
    _clear()
    from sebastian.capabilities.tools import _file_state
    # Pre-populate cache with a stale entry for a path that no longer exists
    _file_state._file_mtimes["/gone/file.txt"] = 1234.0
    _file_state.invalidate("/gone/file.txt")
    # Key should be removed since the file doesn't exist (OSError branch)
    assert "/gone/file.txt" not in _file_state._file_mtimes
