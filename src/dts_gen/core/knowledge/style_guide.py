from __future__ import annotations

from pathlib import Path


class StyleGuide:
    def __init__(self, data_dir: Path):
        self._data_dir = data_dir

    def naming_rules(self) -> str:
        path = self._data_dir / "styleguide.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")
