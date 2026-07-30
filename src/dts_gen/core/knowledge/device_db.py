from __future__ import annotations

import json
from pathlib import Path


class DeviceDb:
    def __init__(self, data_dir: Path):
        self._data_dir = data_dir

    def lookup(self, part_number: str) -> dict | None:
        path = self._data_dir / "devices" / f"{part_number}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
