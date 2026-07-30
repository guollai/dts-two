from pathlib import Path

import yaml

from dts_gen.core.knowledge.binding_repo import BindingRepo


def test_get_schema_returns_none_when_missing(tmp_path: Path):
    repo = BindingRepo(data_dir=tmp_path)

    assert repo.get_schema("snps,dwc3") is None


def test_get_schema_returns_parsed_yaml(tmp_path: Path):
    bindings_dir = tmp_path / "bindings"
    bindings_dir.mkdir(parents=True)
    schema = {"compatible": "snps,dwc3", "properties": {"reg": {}}}
    (bindings_dir / "snps,dwc3.yaml").write_text(yaml.safe_dump(schema), encoding="utf-8")

    repo = BindingRepo(data_dir=tmp_path)
    result = repo.get_schema("snps,dwc3")

    assert result == schema
