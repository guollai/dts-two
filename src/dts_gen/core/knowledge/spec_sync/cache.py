from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _slot_path(cache_dir: Path, filename: str, slot: str) -> Path:
    return cache_dir / f"{filename}.{slot}"


def read_cached(cache_dir: Path, filename: str, slot: str) -> str | None:
    path = _slot_path(cache_dir, filename, slot)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def rotate_and_write(cache_dir: Path, filename: str, new_text: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    latest_path = _slot_path(cache_dir, filename, "latest")
    previous_path = _slot_path(cache_dir, filename, "previous")

    if latest_path.exists():
        previous_path.write_text(latest_path.read_text(encoding="utf-8"), encoding="utf-8")

    latest_path.write_text(new_text, encoding="utf-8")


def write_sync_meta(cache_dir: Path, filename: str, source_url: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    meta_path = cache_dir / "sync_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta[filename] = {
        "source_url": source_url,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
