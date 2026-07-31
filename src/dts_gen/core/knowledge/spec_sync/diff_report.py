from __future__ import annotations

import difflib

from pydantic import BaseModel


class DiffReport(BaseModel):
    filename: str
    diff: str | None = None
    has_changes: bool = False
    first_sync: bool = False
    fetch_error: str | None = None


def build_diff_report(old_text: str | None, new_text: str, filename: str) -> DiffReport:
    if old_text is None:
        return DiffReport(filename=filename, first_sync=True)

    diff_text = "\n".join(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=f"{filename} (previous)",
            tofile=f"{filename} (latest)",
        )
    )
    return DiffReport(filename=filename, diff=diff_text or None, has_changes=bool(diff_text))
