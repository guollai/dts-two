from pathlib import Path

import pytest

from dts_gen.core.pipeline.input_parser import InputFile, parse_input
from tests.fixtures.make_pdf import make_minimal_pdf


def test_parse_input_counts_pdf_pages(tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=3)

    result = parse_input([InputFile(path=str(pdf_path), type="pdf")])

    assert len(result.pages) == 3
    assert result.pages[0].page_number == 1
    assert result.pages[0].source_path == str(pdf_path)
    assert result.metadata == {"stub": True}


def test_parse_input_raises_for_missing_file(tmp_path: Path):
    missing = tmp_path / "missing.pdf"

    with pytest.raises(FileNotFoundError):
        parse_input([InputFile(path=str(missing), type="pdf")])


def test_parse_input_combines_multiple_files(tmp_path: Path):
    pdf1 = tmp_path / "a.pdf"
    pdf2 = tmp_path / "b.pdf"
    make_minimal_pdf(pdf1, pages=2)
    make_minimal_pdf(pdf2, pages=1)

    result = parse_input(
        [InputFile(path=str(pdf1), type="pdf"), InputFile(path=str(pdf2), type="pdf")]
    )

    assert len(result.pages) == 3
    assert [p.source_path for p in result.pages] == [str(pdf1), str(pdf1), str(pdf2)]


def test_parse_input_raises_for_non_pdf_type(tmp_path: Path):
    txt_file = tmp_path / "document.txt"
    txt_file.write_text("This is a text file, not a PDF")

    with pytest.raises(FileNotFoundError):
        parse_input([InputFile(path=str(txt_file), type="txt")])
