from __future__ import annotations

from pathlib import Path


class SocRepo:
    def __init__(self, data_dir: Path):
        self._data_dir = data_dir

    def get_reference_dtsi(self, soc: str) -> list[str]:
        soc_dir = self._data_dir / "socs" / soc
        if not soc_dir.exists():
            return []
        return sorted(str(p) for p in soc_dir.glob("*.dtsi"))
