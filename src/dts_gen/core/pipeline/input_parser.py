from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from pypdf import PdfReader


class InputFile(BaseModel):
    path: str
    type: str


class PageAsset(BaseModel):
    page_number: int
    source_path: str


class ParsedInputResult(BaseModel):
    pages: list[PageAsset] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


def parse_input(files: list[InputFile]) -> ParsedInputResult:
    pages: list[PageAsset] = []
    for file in files:
        path = Path(file.path)
        if not path.exists():
            raise FileNotFoundError(file.path)
        reader = PdfReader(str(path))
        for page_number in range(1, len(reader.pages) + 1):
            pages.append(PageAsset(page_number=page_number, source_path=file.path))
    return ParsedInputResult(pages=pages, metadata={"stub": True})
