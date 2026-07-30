from dts_gen.core.pipeline.hardware_extractor import extract_hardware_graph
from dts_gen.core.pipeline.input_parser import PageAsset


def test_extract_returns_empty_ir_with_not_implemented_marker():
    pages = [PageAsset(page_number=1, source_path="a.pdf")]

    result = extract_hardware_graph(pages)

    assert result.ir.components == []
    assert result.ir.nets == []
    assert len(result.unresolved) == 1
    assert result.unresolved[0].field == "*"
    assert "not implemented" in result.unresolved[0].reason.lower()


def test_extract_records_requested_page_range_in_unresolved():
    pages = [PageAsset(page_number=n, source_path="a.pdf") for n in range(1, 6)]

    result = extract_hardware_graph(pages, page_range=(2, 4))

    assert result.unresolved[0].page == 2
