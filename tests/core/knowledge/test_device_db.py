from pathlib import Path

import json

from dts_gen.core.knowledge.device_db import DeviceDb


def test_lookup_returns_none_when_missing(tmp_path: Path):
    db = DeviceDb(data_dir=tmp_path)

    assert db.lookup("tusb2e11") is None


def test_lookup_returns_parsed_json(tmp_path: Path):
    devices_dir = tmp_path / "devices"
    devices_dir.mkdir(parents=True)
    template = {"part_number": "tusb2e11", "type": "usb-redriver", "compatible": "ti,tusb2e11"}
    (devices_dir / "tusb2e11.json").write_text(json.dumps(template), encoding="utf-8")

    db = DeviceDb(data_dir=tmp_path)
    result = db.lookup("tusb2e11")

    assert result == template
