# block_semantic.json → IR 转换层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个独立的转换函数 `import_block_semantic()`，把 `dts_one` 项目产出的 `block_semantic.json`（松散字典，自由文本器件/网络标签）转换成 `dts-gen` 严格定义的 pydantic IR 模型（`Component`/`Net`/`UnresolvedItem`），本次只做连接事实（`Net`）转换，不推断语义关系（`Relation`），不接入 MCP 工具链路。

**Architecture:** 单文件模块 `src/dts_gen/core/pipeline/semantic_import.py`，与现有 `hardware_extractor.py`/`soc_mapper.py` 同级，暴露 `parse_connected_label()`（单条label解析）+ `import_block_semantic()`（顶层入口）两个函数。纯函数，接收已解析好的Python dict，不做文件IO。

**Tech Stack:** Python 3.10+，pydantic v2（复用现有 `dts_gen.core.ir.models`），pytest。

## Global Constraints

- 本次**只产出 `Net`**（连接事实），**不推断 `Relation`**（语义关系）——`HardwareIR.relations` 字段在本次转换结果中始终为空列表，不做任何填充。
- **不解析跨页/跨块括号引用**（如 `"[22]"`、`"[7,37,8]"`、`"[47-C4,47-D4]"`）——这类 `connectedLabels` 条目静默跳过，既不写入 `Net.members`，也不产出 `UnresolvedItem`。
- **`Component.type` 不做词汇规范化**——`componentType` 原文直接存入 `Component.type`（如 `"transistor (MOSFET, PJE138K SOT-523)"`），不归类到 USB MVP 现有受限词汇（`usb-controller` 等）。
- **不接入 `extract_hardware_graph`**——本次交付的 `import_block_semantic()` 是独立、可单测的函数，不修改 `hardware_extractor.py`，不修改 `mcp_app/tools.py`。
- **仅处理单页输入**——`import_block_semantic(data, page=None)` 的 `data` 参数是单份 `block_semantic.json` 内容（一个PDF页面的结果），不处理多页合并逻辑。
- **裸网络名自引用条目**（`connectedLabels` 里出现的、不含"pin"关键字、无法被 `_LABEL_RE` 匹配的字符串，如 `"VDD_CX"`、`"PCIE4_REFCLK_100M+"`）**静默跳过**，不产出 `UnresolvedItem`——这不是错误，只是这条 label 不代表一个具体引脚连接。
- **含"pin"关键字但解析失败**的条目（如 `"C? pin 1"`，designator 含 `?`）——产出 `UnresolvedItem(field=f"net:{name}", reason=...)`，且该 label **不**写入 `Net.members`。
- `import_block_semantic` 接收**已经用 `json.load` 解析好的 Python dict**，不接收文件路径，不在函数内部做文件读取。
- 对输入 dict 结构本身的缺失做容错，不抛异常：`data` 缺 `"blocks"` 键 → 视为空列表；`block` 缺 `"nets"`/`"components"` 键 → 视为空列表；`net` 缺 `"connectedLabels"` 键 → 视为空列表。
- `component` 缺 `"designator"` 或 `"componentType"` 字段 → 跳过该条组件，产出 `UnresolvedItem(field=f"component:{block_id}", ...)`，不让局部脏数据中断整体转换。
- `Net.name` 为空（`netNameLabel` 是 `null`）时，自动生成占位名 `f"net_{block_id}_{net_seq:03d}"`（`net_seq` 从1开始，按该 block 内 net 出现顺序递增，不跨block共享序号）。
- `connectedLabels` 里解析出的 designator，若不在任何 block 的 `components` 列表中出现，自动补建一个 `Component(id=designator, type="unknown", name=designator)`，保证 `Net.members` 引用的每个 component id 都能在最终 `HardwareIR.components` 里找到。
- `Component.id` 和 `Component.name` 取同一个值（`designator`）——没有独立型号字段可用，不编造。
- `component.pinCount` 字段本次丢弃，不新增 IR 字段承接它。
- 本次不新增顶层模块目录，新文件放在已有的 `src/dts_gen/core/pipeline/` 目录内。

---

## Task 1: `parse_connected_label` 单条标签解析函数

**Files:**
- Create: `src/dts_gen/core/pipeline/semantic_import.py`
- Test: `tests/core/pipeline/test_semantic_import.py`

**Interfaces:**
- Consumes: 无（纯字符串处理，无外部依赖）
- Produces: 模块级常量 `_LABEL_RE`（编译后的正则）、`_BRACKET_RE`（编译后的正则）、函数 `parse_connected_label(label: str) -> tuple[str, str] | None` — 供 Task 2（`import_block_semantic`）使用

- [ ] **Step 1: 写失败测试**

创建 `tests/core/pipeline/test_semantic_import.py`：

```python
from dts_gen.core.pipeline.semantic_import import parse_connected_label


def test_parse_connected_label_extracts_designator_and_pin():
    assert parse_connected_label("R3 pin 1") == ("R3", "1")


def test_parse_connected_label_handles_alphanumeric_pin():
    assert parse_connected_label("SU1C pin G37") == ("SU1C", "G37")


def test_parse_connected_label_handles_no_space_before_pin_number():
    assert parse_connected_label("R544 pin2") == ("R544", "2")


def test_parse_connected_label_returns_none_for_single_bracket_reference():
    assert parse_connected_label("[22]") is None


def test_parse_connected_label_returns_none_for_multi_page_bracket_reference():
    assert parse_connected_label("[7,37,8]") is None


def test_parse_connected_label_returns_none_for_coordinate_bracket_reference():
    assert parse_connected_label("[47-C4,47-D4]") is None


def test_parse_connected_label_returns_none_for_bare_net_name():
    assert parse_connected_label("VDD_CX") is None


def test_parse_connected_label_returns_none_for_ground_label():
    assert parse_connected_label("GND") is None


def test_parse_connected_label_returns_none_for_uncertain_designator():
    assert parse_connected_label("C? pin 1") is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/core/pipeline/test_semantic_import.py -v`
Expected: `ModuleNotFoundError: No module named 'dts_gen.core.pipeline.semantic_import'`

- [ ] **Step 3: 实现**

创建 `src/dts_gen/core/pipeline/semantic_import.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/core/pipeline/test_semantic_import.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/semantic_import.py tests/core/pipeline/test_semantic_import.py
git commit -m "feat: add parse_connected_label for block_semantic.json label parsing"
```

---

## Task 2: `import_block_semantic` — Component 转换与去重补建

**Files:**
- Modify: `src/dts_gen/core/pipeline/semantic_import.py`
- Test: `tests/core/pipeline/test_semantic_import.py`

**Interfaces:**
- Consumes: Task 1 的 `parse_connected_label`；`dts_gen.core.ir.models.Component`/`HardwareIR`/`UnresolvedItem`
- Produces: `class ImportResult(BaseModel)`（字段：`ir: HardwareIR`, `unresolved: list[UnresolvedItem] = Field(default_factory=list)`）、函数骨架 `import_block_semantic(data: dict, page: int | None = None) -> ImportResult`（本任务只完成 Component 收集部分，Net 部分留给 Task 3） — 供 Task 3（Net 转换）扩展、Task 4（端到端场景）使用

本任务先把 `components` 列表的转换逻辑（含缺字段容错）写完，`import_block_semantic` 暂时只处理 `components`，不处理 `nets`（`ir.nets` 暂时保持空列表，返回值里 `HardwareIR` 已经可用 `components` 字段验证）。

- [ ] **Step 1: 写失败测试**

追加到 `tests/core/pipeline/test_semantic_import.py`：

```python
from dts_gen.core.pipeline.semantic_import import ImportResult, import_block_semantic


def test_import_block_semantic_converts_components_with_designator_and_type():
    data = {
        "blocks": [
            {
                "blockId": "block_0003",
                "components": [
                    {"designator": "R3", "componentType": "resistor", "pinCount": 2},
                    {"designator": "R5", "componentType": "resistor", "pinCount": 2},
                ],
            }
        ]
    }

    result = import_block_semantic(data)

    assert isinstance(result, ImportResult)
    ids = {c.id for c in result.ir.components}
    assert ids == {"R3", "R5"}
    r3 = next(c for c in result.ir.components if c.id == "R3")
    assert r3.type == "resistor"
    assert r3.name == "R3"


def test_import_block_semantic_merges_components_across_multiple_blocks():
    data = {
        "blocks": [
            {"blockId": "block_0001", "components": [{"designator": "R3", "componentType": "resistor"}]},
            {"blockId": "block_0002", "components": [{"designator": "C1", "componentType": "capacitor"}]},
        ]
    }

    result = import_block_semantic(data)

    ids = {c.id for c in result.ir.components}
    assert ids == {"R3", "C1"}


def test_import_block_semantic_reports_unresolved_for_component_missing_designator():
    data = {
        "blocks": [
            {"blockId": "block_0001", "components": [{"componentType": "resistor"}]},
        ]
    }

    result = import_block_semantic(data)

    assert result.ir.components == []
    assert len(result.unresolved) == 1
    assert result.unresolved[0].field == "component:block_0001"


def test_import_block_semantic_reports_unresolved_for_component_missing_type():
    data = {
        "blocks": [
            {"blockId": "block_0001", "components": [{"designator": "R3"}]},
        ]
    }

    result = import_block_semantic(data)

    assert result.ir.components == []
    assert len(result.unresolved) == 1


def test_import_block_semantic_handles_missing_blocks_key():
    result = import_block_semantic({})

    assert result.ir.components == []
    assert result.unresolved == []


def test_import_block_semantic_handles_block_missing_components_key():
    data = {"blocks": [{"blockId": "block_0001"}]}

    result = import_block_semantic(data)

    assert result.ir.components == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/core/pipeline/test_semantic_import.py -v`
Expected: `ImportError: cannot import name 'ImportResult'`

- [ ] **Step 3: 实现**

在 `semantic_import.py` 顶部 import 区新增，并在 `parse_connected_label` 之后追加：

```python
from pydantic import BaseModel, Field

from dts_gen.core.ir.models import Component, HardwareIR, Net, UnresolvedItem


class ImportResult(BaseModel):
    ir: HardwareIR
    unresolved: list[UnresolvedItem] = Field(default_factory=list)


def import_block_semantic(data: dict, page: int | None = None) -> ImportResult:
    components: dict[str, Component] = {}
    unresolved: list[UnresolvedItem] = []

    for block in data.get("blocks", []):
        block_id = block.get("blockId", "unknown_block")
        for comp in block.get("components", []):
            designator = comp.get("designator")
            component_type = comp.get("componentType")
            if designator is None or component_type is None:
                unresolved.append(
                    UnresolvedItem(
                        field=f"component:{block_id}",
                        reason=f"组件缺少 designator 或 componentType 字段: {comp!r}",
                        page=page,
                    )
                )
                continue
            components[designator] = Component(id=designator, type=component_type, name=designator)

    ir = HardwareIR(components=list(components.values()), nets=[], unresolved=unresolved)
    return ImportResult(ir=ir, unresolved=unresolved)
```

（`Net` 已导入但本任务尚未使用，Task 3 会用到，先导入不会造成lint错误因为Python不检查未使用的import在运行时报错——但为避免困惑，若使用的linter严格检查未使用import，可暂时忽略，Task 3马上会用上。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/core/pipeline/test_semantic_import.py -v`
Expected: 15 passed（9个Task1 + 6个本任务新增）

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/semantic_import.py tests/core/pipeline/test_semantic_import.py
git commit -m "feat: convert block_semantic.json components into IR Component list"
```

---

## Task 3: `import_block_semantic` — Net 转换、标签分类与器件补建

**Files:**
- Modify: `src/dts_gen/core/pipeline/semantic_import.py`
- Test: `tests/core/pipeline/test_semantic_import.py`

**Interfaces:**
- Consumes: Task 1 的 `parse_connected_label`/`_BRACKET_RE`，Task 2 的 `import_block_semantic`（本任务在其基础上补全 Net 处理逻辑）
- Produces: 完整版 `import_block_semantic`（`ir.nets` 字段被正确填充，含占位命名、成员解析、器件补建、unresolved上报） — 供 Task 4（端到端场景验证）使用

- [ ] **Step 1: 写失败测试**

追加到 `tests/core/pipeline/test_semantic_import.py`：

```python
def test_import_block_semantic_builds_net_with_parsed_members():
    data = {
        "blocks": [
            {
                "blockId": "block_0003",
                "nets": [
                    {"netNameLabel": "PCIE4_REFCLK_100M+", "connectedLabels": ["R3 pin 1", "R5 pin 1"]},
                ],
                "components": [
                    {"designator": "R3", "componentType": "resistor"},
                    {"designator": "R5", "componentType": "resistor"},
                ],
            }
        ]
    }

    result = import_block_semantic(data)

    assert len(result.ir.nets) == 1
    net = result.ir.nets[0]
    assert net.name == "PCIE4_REFCLK_100M+"
    assert net.members == ["R3:1", "R5:1"]


def test_import_block_semantic_skips_bare_net_name_self_reference():
    data = {
        "blocks": [
            {
                "blockId": "block_0003",
                "nets": [
                    {"netNameLabel": "PCIE4_REFCLK_100M+", "connectedLabels": ["PCIE4_REFCLK_100M+", "R3 pin 1"]},
                ],
                "components": [{"designator": "R3", "componentType": "resistor"}],
            }
        ]
    }

    result = import_block_semantic(data)

    assert result.ir.nets[0].members == ["R3:1"]
    assert result.unresolved == []


def test_import_block_semantic_skips_bracket_reference_without_unresolved():
    data = {
        "blocks": [
            {
                "blockId": "block_0003",
                "nets": [
                    {"netNameLabel": "DOCK_VDM_PWR_ON", "connectedLabels": ["SQ17 pin 1", "[5]"]},
                ],
                "components": [{"designator": "SQ17", "componentType": "transistor"}],
            }
        ]
    }

    result = import_block_semantic(data)

    assert result.ir.nets[0].members == ["SQ17:1"]
    assert result.unresolved == []


def test_import_block_semantic_reports_unresolved_for_uncertain_pin_label():
    data = {
        "blocks": [
            {
                "blockId": "block_0003",
                "nets": [
                    {"netNameLabel": None, "connectedLabels": ["C? pin 1"]},
                ],
            }
        ]
    }

    result = import_block_semantic(data)

    assert result.ir.nets[0].members == []
    assert len(result.unresolved) == 1
    assert "C? pin 1" in result.unresolved[0].reason


def test_import_block_semantic_generates_placeholder_name_for_null_net_label():
    data = {
        "blocks": [
            {
                "blockId": "block_0002",
                "nets": [
                    {"netNameLabel": None, "connectedLabels": ["SU1D pin G39"]},
                    {"netNameLabel": None, "connectedLabels": ["SU1D pin G40"]},
                ],
                "components": [{"designator": "SU1D", "componentType": "ic"}],
            }
        ]
    }

    result = import_block_semantic(data)

    names = [n.name for n in result.ir.nets]
    assert names == ["net_block_0002_001", "net_block_0002_002"]


def test_import_block_semantic_auto_creates_unknown_component_for_undeclared_designator():
    data = {
        "blocks": [
            {
                "blockId": "block_0001",
                "nets": [
                    {"netNameLabel": "SOME_NET", "connectedLabels": ["Q99 pin 1"]},
                ],
                "components": [],
            }
        ]
    }

    result = import_block_semantic(data)

    q99 = next(c for c in result.ir.components if c.id == "Q99")
    assert q99.type == "unknown"
    assert q99.name == "Q99"
    assert result.ir.nets[0].members == ["Q99:1"]


def test_import_block_semantic_handles_net_missing_connected_labels_key():
    data = {
        "blocks": [
            {"blockId": "block_0001", "nets": [{"netNameLabel": "SOME_NET"}]},
        ]
    }

    result = import_block_semantic(data)

    assert result.ir.nets[0].name == "SOME_NET"
    assert result.ir.nets[0].members == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/core/pipeline/test_semantic_import.py -v`
Expected: `AssertionError`（`ir.nets` 目前始终为空列表，因为Task 2的实现还没处理nets）

- [ ] **Step 3: 实现**

**替换** `import_block_semantic` 函数体（保留函数签名和Component收集部分不变，在其后追加Net处理逻辑）：

```python
def import_block_semantic(data: dict, page: int | None = None) -> ImportResult:
    components: dict[str, Component] = {}
    unresolved: list[UnresolvedItem] = []

    for block in data.get("blocks", []):
        block_id = block.get("blockId", "unknown_block")
        for comp in block.get("components", []):
            designator = comp.get("designator")
            component_type = comp.get("componentType")
            if designator is None or component_type is None:
                unresolved.append(
                    UnresolvedItem(
                        field=f"component:{block_id}",
                        reason=f"组件缺少 designator 或 componentType 字段: {comp!r}",
                        page=page,
                    )
                )
                continue
            components[designator] = Component(id=designator, type=component_type, name=designator)

    nets: list[Net] = []
    for block in data.get("blocks", []):
        block_id = block.get("blockId", "unknown_block")
        for net_seq, net_entry in enumerate(block.get("nets", []), start=1):
            name = net_entry.get("netNameLabel") or f"net_{block_id}_{net_seq:03d}"
            members: list[str] = []
            for label in net_entry.get("connectedLabels", []):
                parsed = parse_connected_label(label)
                if parsed is None:
                    if "pin" in label.lower() and not _BRACKET_RE.match(label.strip()):
                        unresolved.append(
                            UnresolvedItem(
                                field=f"net:{name}",
                                reason=f"无法解析连接标签: {label!r}",
                                page=page,
                            )
                        )
                    continue
                designator, pin = parsed
                if designator not in components:
                    components[designator] = Component(id=designator, type="unknown", name=designator)
                members.append(f"{designator}:{pin}")
            nets.append(Net(name=name, members=members))

    ir = HardwareIR(components=list(components.values()), nets=nets, unresolved=unresolved)
    return ImportResult(ir=ir, unresolved=unresolved)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/core/pipeline/test_semantic_import.py -v`
Expected: 22 passed（15个Task1-2 + 7个本任务新增）

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/semantic_import.py tests/core/pipeline/test_semantic_import.py
git commit -m "feat: convert block_semantic.json nets into IR Net list with member parsing"
```

---

## Task 4: 端到端验收用例（基于真实样本简化）

**Files:**
- Modify: `tests/core/pipeline/test_semantic_import.py`
- No source changes — this task is verification-only against the design spec's §6.1 acceptance scenario.

**Interfaces:**
- Consumes: Task 3 完成后的 `import_block_semantic`
- Produces: 无新接口，验证设计文档 §6.1 端到端场景在真实实现下产出预期结果

- [ ] **Step 1: 写测试**

追加到 `tests/core/pipeline/test_semantic_import.py`：

```python
def test_import_block_semantic_end_to_end_real_sample_shape():
    data = {
        "blocks": [
            {
                "blockId": "block_0003",
                "nets": [
                    {
                        "netNameLabel": "PCIE4_REFCLK_100M+",
                        "connectedLabels": ["PCIE4_REFCLK_100M+", "R3 pin 1", "R5 pin 1"],
                    },
                    {
                        "netNameLabel": "CLKGEN_CLK3_100M+",
                        "connectedLabels": ["R3 pin 2", "CLKGEN_CLK3_100M+ [13]"],
                    },
                ],
                "components": [
                    {"designator": "R3", "componentType": "resistor", "pinCount": 2},
                    {"designator": "R5", "componentType": "resistor", "pinCount": 2},
                ],
            }
        ]
    }

    result = import_block_semantic(data)

    ids = {c.id for c in result.ir.components}
    assert ids == {"R3", "R5"}

    net_by_name = {n.name: n for n in result.ir.nets}
    assert net_by_name["PCIE4_REFCLK_100M+"].members == ["R3:1", "R5:1"]
    assert net_by_name["CLKGEN_CLK3_100M+"].members == ["R3:2"]

    assert result.ir.unresolved == []
    assert result.ir.relations == []
```

Note: `"CLKGEN_CLK3_100M+ [13]"` 整体不匹配 `_LABEL_RE`（不含独立的"pin"词，且整体格式不符），按裸网络名自引用类静默跳过处理——这是设计文档§6.1明确记录的预期行为（不产出unresolved）。

- [ ] **Step 2: 运行测试确认通过（无需实现变更）**

Run: `python -m pytest tests/core/pipeline/test_semantic_import.py -v`
Expected: 23 passed

若此测试失败，说明 Task 1-3 的实现与设计文档 §6.1 描述的预期行为有偏差，回到对应任务修正后重新运行本任务。

- [ ] **Step 3: 运行完整测试套件确认无回归**

Run: `python -m pytest -q`
Expected: 全部通过（新增23个测试，此前140个通过测试不受影响；若看到 `tests/core/knowledge/spec_sync/` 下1-2个真实网络测试因GitHub API限流失败——这是已知的、与本次改动无关的环境性问题，不视为回归，可用 `python -m pytest -q --deselect <失败的测试路径>` 重跑确认其余测试通过）

- [ ] **Step 4: Commit**

```bash
git add tests/core/pipeline/test_semantic_import.py
git commit -m "test: add end-to-end acceptance case for block_semantic.json import"
```

---

## 与设计文档的对照表（供实施后自查）

| 设计文档章节 | 对应任务 |
|---|---|
| 三（`parse_connected_label` 解析规则） | Task 1 |
| 四（`import_block_semantic` 顶层逻辑 — Component部分）、五（Component去重与补建的前半：建立已知器件表） | Task 2 |
| 四（`import_block_semantic` 顶层逻辑 — Net部分）、五（Component去重与补建的后半：补建unknown组件） | Task 3 |
| 六（端到端验收用例） | Task 4 |
