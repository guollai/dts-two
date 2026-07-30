from pathlib import Path

from dts_gen.core.ir.models import Component, HardwareIR
from dts_gen.core.ir.store import IrStore


def test_save_creates_v1_and_returns_ref(tmp_path: Path):
    store = IrStore(base_dir=tmp_path)
    ir = HardwareIR(board="board-x", soc="sa8775p")

    ref = store.save("task001", ir)

    assert ref == "ir/v1.json"
    assert (tmp_path / "task001" / "ir" / "v1.json").exists()


def test_save_twice_increments_version_and_keeps_old_file(tmp_path: Path):
    store = IrStore(base_dir=tmp_path)
    ir1 = HardwareIR(board="board-x", soc="sa8775p")
    ir2 = HardwareIR(
        board="board-x",
        soc="sa8775p",
        components=[Component(id="soc_usb0", type="usb-controller", name="dwc3")],
    )

    ref1 = store.save("task001", ir1)
    ref2 = store.save("task001", ir2)

    assert ref1 == "ir/v1.json"
    assert ref2 == "ir/v2.json"
    assert (tmp_path / "task001" / "ir" / "v1.json").exists()
    assert (tmp_path / "task001" / "ir" / "v2.json").exists()


def test_load_returns_equivalent_ir(tmp_path: Path):
    store = IrStore(base_dir=tmp_path)
    original = HardwareIR(board="board-x", soc="sa8775p")
    ref = store.save("task001", original)

    loaded = store.load("task001", ref)

    assert loaded.board == "board-x"
    assert loaded.soc == "sa8775p"


def test_latest_ref_returns_none_when_no_versions(tmp_path: Path):
    store = IrStore(base_dir=tmp_path)

    assert store.latest_ref("task001") is None


def test_latest_ref_returns_highest_version(tmp_path: Path):
    store = IrStore(base_dir=tmp_path)
    ir = HardwareIR(board="board-x", soc="sa8775p")
    store.save("task001", ir)
    store.save("task001", ir)

    assert store.latest_ref("task001") == "ir/v2.json"
