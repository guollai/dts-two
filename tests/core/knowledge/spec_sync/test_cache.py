import json
from pathlib import Path

from dts_gen.core.knowledge.spec_sync.cache import read_cached, rotate_and_write, write_sync_meta


def test_read_cached_returns_none_when_file_missing(tmp_path: Path):
    assert read_cached(tmp_path, "gpio.txt", "latest") is None


def test_rotate_and_write_creates_latest_file(tmp_path: Path):
    rotate_and_write(tmp_path, "gpio.txt", "first version text")

    assert read_cached(tmp_path, "gpio.txt", "latest") == "first version text"
    assert read_cached(tmp_path, "gpio.txt", "previous") is None


def test_rotate_and_write_moves_latest_to_previous_on_second_call(tmp_path: Path):
    rotate_and_write(tmp_path, "gpio.txt", "first version text")
    rotate_and_write(tmp_path, "gpio.txt", "second version text")

    assert read_cached(tmp_path, "gpio.txt", "latest") == "second version text"
    assert read_cached(tmp_path, "gpio.txt", "previous") == "first version text"


def test_write_sync_meta_records_source_url_and_timestamp(tmp_path: Path):
    write_sync_meta(tmp_path, "gpio.txt", source_url="https://example.com/gpio.txt")

    meta_path = tmp_path / "sync_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["gpio.txt"]["source_url"] == "https://example.com/gpio.txt"
    assert "synced_at" in meta["gpio.txt"]


def test_write_sync_meta_merges_multiple_files_without_overwriting_others(tmp_path: Path):
    write_sync_meta(tmp_path, "gpio.txt", source_url="https://example.com/gpio.txt")
    write_sync_meta(tmp_path, "regulator.yaml", source_url="https://example.com/regulator.yaml")

    meta_path = tmp_path / "sync_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert set(meta.keys()) == {"gpio.txt", "regulator.yaml"}
