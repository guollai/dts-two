from pathlib import Path

from dts_gen.core.knowledge.style_guide import StyleGuide


def test_naming_rules_returns_empty_string_when_missing(tmp_path: Path):
    guide = StyleGuide(data_dir=tmp_path)

    assert guide.naming_rules() == ""


def test_naming_rules_returns_file_content(tmp_path: Path):
    (tmp_path / "styleguide.md").write_text("# Naming\nUse lowercase.", encoding="utf-8")

    guide = StyleGuide(data_dir=tmp_path)

    assert guide.naming_rules() == "# Naming\nUse lowercase."
