from __future__ import annotations

import re
from pathlib import Path

from dts_gen.core.ir.models import HardwareIR

_VERSION_PATTERN = re.compile(r"^v(\d+)\.json$")


class IrStore:
    def __init__(self, base_dir: Path):
        self._base_dir = base_dir

    def _ir_dir(self, task_id: str) -> Path:
        return self._base_dir / task_id / "ir"

    def _existing_versions(self, task_id: str) -> list[int]:
        ir_dir = self._ir_dir(task_id)
        if not ir_dir.exists():
            return []
        versions = []
        for entry in ir_dir.iterdir():
            match = _VERSION_PATTERN.match(entry.name)
            if match:
                versions.append(int(match.group(1)))
        return sorted(versions)

    def save(self, task_id: str, ir: HardwareIR) -> str:
        ir_dir = self._ir_dir(task_id)
        ir_dir.mkdir(parents=True, exist_ok=True)
        versions = self._existing_versions(task_id)
        next_version = (versions[-1] + 1) if versions else 1
        filename = f"v{next_version}.json"
        (ir_dir / filename).write_text(ir.model_dump_json(indent=2), encoding="utf-8")
        return f"ir/{filename}"

    def load(self, task_id: str, ir_ref: str) -> HardwareIR:
        filename = ir_ref.split("/", 1)[1]
        path = self._ir_dir(task_id) / filename
        return HardwareIR.model_validate_json(path.read_text(encoding="utf-8"))

    def latest_ref(self, task_id: str) -> str | None:
        versions = self._existing_versions(task_id)
        if not versions:
            return None
        return f"ir/v{versions[-1]}.json"
