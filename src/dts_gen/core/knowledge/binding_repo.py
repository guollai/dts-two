from __future__ import annotations

from pathlib import Path

import yaml


class BindingRepo:
    def __init__(self, data_dir: Path):
        self._data_dir = data_dir

    def get_schema(self, compatible: str) -> dict | None:
        path = self._data_dir / "bindings" / f"{compatible}.yaml"
        if not path.exists():
            return None
        return yaml.safe_load(path.read_text(encoding="utf-8"))
