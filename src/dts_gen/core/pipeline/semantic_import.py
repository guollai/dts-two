from __future__ import annotations

import re

# "R3 pin 1" / "SU1C pin G37" / "Q54 pin D" / "R544 pin2"（无空格变体）
_LABEL_RE = re.compile(r"^([A-Za-z0-9_\-\.\?]+)\s*pin\s*([A-Za-z0-9]+)$", re.IGNORECASE)
# 跨页引用条目，如 "[22]"、"[7,37,8]"、"[47-C4,47-D4]"
_BRACKET_RE = re.compile(r"^\[.*\]$")


def parse_connected_label(label: str) -> tuple[str, str] | None:
    stripped = label.strip()
    if _BRACKET_RE.match(stripped):
        return None
    match = _LABEL_RE.match(stripped)
    if not match:
        return None
    designator, pin = match.groups()
    if "?" in designator:
        return None
    return (designator, pin)
