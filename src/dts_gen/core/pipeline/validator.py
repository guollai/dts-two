from __future__ import annotations

import re
import shutil
from collections import Counter

from pydantic import BaseModel, Field

from dts_gen.core.pipeline.base import DtsError

_LABEL_DEF_RE = re.compile(r"&(\w+)\s*\{")
_LABEL_REF_RE = re.compile(r"<\s*&(\w+)")
_PROP_LINE_RE = re.compile(r"^\s*([\w,-]+)\s*=\s*(.+);\s*$")


class ValidateResult(BaseModel):
    errors: list[DtsError] = Field(default_factory=list)
    warnings: list[DtsError] = Field(default_factory=list)


def find_defined_labels(text: str) -> set[str]:
    return set(_LABEL_DEF_RE.findall(text))


def find_referenced_labels(text: str) -> set[str]:
    return set(_LABEL_REF_RE.findall(text))


def check_undefined_references(text: str) -> list[DtsError]:
    defined = find_defined_labels(text)
    referenced = find_referenced_labels(text)
    return [
        DtsError(message=f"引用的节点 &{label} 未定义", node=None, severity="error")
        for label in sorted(referenced - defined)
    ]


def check_property_syntax(text: str) -> list[DtsError]:
    errors: list[DtsError] = []
    for line in text.splitlines():
        match = _PROP_LINE_RE.match(line)
        if not match:
            continue
        prop_name, value = match.groups()
        value = value.strip()
        if value.startswith("&") and not (value.startswith("<") and value.endswith(">")):
            errors.append(
                DtsError(message=f"属性 {prop_name} 的引用值 {value} 缺少 <...> 包裹", severity="error")
            )
        elif value in ("okay", "disabled"):
            errors.append(
                DtsError(message=f"属性 {prop_name} 的值 {value} 应为带引号字符串", severity="error")
            )
    return errors


def check_duplicate_labels(text: str) -> list[DtsError]:
    labels = _LABEL_DEF_RE.findall(text)
    counts = Counter(labels)
    return [
        DtsError(message=f"节点 &{label} 被重复定义 {count} 次", severity="error")
        for label, count in counts.items()
        if count > 1
    ]


def validate_dts(dts_text: str, target_platform: str | None = None) -> ValidateResult:
    errors: list[DtsError] = []
    errors += check_undefined_references(dts_text)
    errors += check_property_syntax(dts_text)
    errors += check_duplicate_labels(dts_text)

    warnings: list[DtsError] = []
    if shutil.which("dtc") is None:
        warnings.append(DtsError(message="dtc 未安装，跳过语法级编译校验", severity="warning"))

    return ValidateResult(errors=errors, warnings=warnings)
