from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _slot_path(cache_dir: Path, filename: str, slot: str) -> Path:
    return cache_dir / f"{filename}.{slot}"


def _atomic_write_text(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


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
        _atomic_write_text(previous_path, latest_path.read_text(encoding="utf-8"))

    _atomic_write_text(latest_path, new_text)


def write_sync_meta(cache_dir: Path, filename: str, source_url: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    meta_path = cache_dir / "sync_meta.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    meta[filename] = {
        "source_url": source_url,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_text(meta_path, json.dumps(meta, indent=2))
