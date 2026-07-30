from pathlib import Path

from dts_gen.core.knowledge.soc_repo import SocRepo


def test_get_reference_dtsi_returns_empty_list_when_soc_dir_missing(tmp_path: Path):
    repo = SocRepo(data_dir=tmp_path)

    assert repo.get_reference_dtsi("sa8775p") == []


def test_get_reference_dtsi_returns_dtsi_files_in_soc_dir(tmp_path: Path):
    soc_dir = tmp_path / "socs" / "sa8775p"
    soc_dir.mkdir(parents=True)
    (soc_dir / "main.dtsi").write_text("/* stub */", encoding="utf-8")
    (soc_dir / "notes.txt").write_text("ignore me", encoding="utf-8")

    repo = SocRepo(data_dir=tmp_path)
    result = repo.get_reference_dtsi("sa8775p")

    assert result == [str(soc_dir / "main.dtsi")]
