from __future__ import annotations

from pathlib import Path


class SoulLoader:
    def __init__(self, souls_dir: Path, builtin_souls: dict[str, str]) -> None:
        self._souls_dir = souls_dir
        self._builtin_souls = builtin_souls
        self.current_soul: str = "sebastian"

    def list_souls(self) -> list[str]:
        if not self._souls_dir.exists():
            return []
        return sorted(p.stem for p in self._souls_dir.glob("*.md"))

    def load(self, soul_name: str) -> str | None:
        if soul_name != Path(soul_name).name:  # reject path separators / traversal
            return None
        path = self._souls_dir / f"{soul_name}.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def ensure_defaults(self) -> None:
        self._souls_dir.mkdir(parents=True, exist_ok=True)
        for name, content in self._builtin_souls.items():
            path = self._souls_dir / f"{name}.md"
            if not path.exists():
                path.write_text(content, encoding="utf-8")
