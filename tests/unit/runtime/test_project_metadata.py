from __future__ import annotations

import tomllib
from pathlib import Path


def test_jieba_is_declared_as_runtime_dependency() -> None:
    pyproject_path = Path(__file__).parents[3] / "pyproject.toml"
    metadata = tomllib.loads(pyproject_path.read_text())

    dependencies = metadata["project"]["dependencies"]

    assert any(dep.startswith("jieba") for dep in dependencies)
