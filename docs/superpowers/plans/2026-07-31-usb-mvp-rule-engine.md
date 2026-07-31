# USB 子系统 MVP：规则引擎 + 模板生成 + 规范同步机制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `generate_dts`/`validate_dts` 从诚实 stub 填成基于规则引擎+结构化节点构建器的真实实现（覆盖 USB 子系统 5 类 component + 3 类 relation），并新增一个规范/binding 同步机制（第 9 个 MCP Tool + CLI 子命令），用于定期追踪 Linux 内核 devicetree binding 文档和 devicetree-specification 规范源文件的变化。

**Architecture:** `dts_generator.py` 内新增确定性规则引擎（模块级 `RULES` 字典）+ `DtsNode`/`DtsProperty` 结构化中间对象 + 序列化器；`validator.py` 内新增三条正则驱动的内部结构校验，检测到 `dtc` 存在则叠加语法校验；新增独立模块 `core/knowledge/spec_sync/`（fetcher/cache/diff_report/sync）实现"版本化缓存+全文diff"的规范同步机制，通过 CLI 子命令和第 9 个 MCP Tool 暴露。

**Tech Stack:** Python 3.10+，pydantic v2，pytest，`requests`（新增依赖，用于 HTTP 拉取，已验证可绕开本机 Windows Schannel 证书吊销校验问题）。

## Global Constraints

- 规则引擎必须是纯确定性代码（无 AI 参与），任何字段缺失或格式不匹配都产出 `UnresolvedItem`，绝不猜测/编造属性值、GPIO 编号、compatible 字符串、寄存器地址。
- `DtsNode.label` 直接使用 `component.id`（`soc_mapper` 仍为 stub，无真实平台 label 可用）。
- 无任何属性的 `DtsNode`（即从未被任何 relation 填充过属性的节点）不单独输出为 DTS 节点块。
- `GenerationScope.subsystem` 字段本次仅预留接口，不实际过滤任何节点。
- `generate_dts` 产出的 `unresolved` 只出现在 MCP 工具输出字典里，**不**合并写回 IR 文件（区别于 `extract_hardware_graph` 的合并写回行为）。`explain_node` 本次不负责查找这类 unresolved。
- 若 `dts_text` 为空字符串（IR 无可用 relation 时的合法结果），`validate_dts` 三条内部检查均返回空列表，不视为错误。
- `dtc` 语法校验完全是可选叠加项：`shutil.which("dtc") is None` 时只产出一条 warning，不阻塞、不报错。
- `spec_sync` 相关代码使用真实网络和真实文件系统测试，不使用 mock（已在本机验证 `requests` 库可正常访问 `raw.githubusercontent.com`/`api.github.com`；`curl`/裸 TLS 在本机因 Windows Schannel 证书吊销校验失败不可用，因此新增依赖使用 `requests` 而非标准库 `urllib`）。
- `sync_bindings` 的 devicetree-specification 部分追踪范围：仅 `github.com/devicetree-org/devicetree-specification` 仓库 `source/` 根目录下、文件名以 `.rst` 结尾的文件，通过 GitHub Contents API (`https://api.github.com/repos/devicetree-org/devicetree-specification/contents/source`) 动态发现，不递归进 `extensions/` 子目录，不硬编码章节文件名列表。
- `sync_bindings` 单文件拉取失败只影响该条（`DiffReport.fetch_error` 非空），不中断其余文件的同步；devicetree-specification 目录列举本身失败时，退化为只同步 3 个内核 binding 文件，并追加一条标记目录列举失败的 `DiffReport`。
- 新增的 MCP Tool `sync_bindings` **不带 `task_id` 参数**，输出字典也不含 `task_id` 字段——它与 8 个任务流程 Tool 的 task_id 约束无关，是独立的运维/知识库维护操作。
- 本次不新增顶层业务模块文件用于生成/校验逻辑（改动集中在 `dts_generator.py`/`validator.py`/`tools.py` 内部），但 `spec_sync` 是全新独立能力，允许新增 `core/knowledge/spec_sync/` 目录。

---

## Task 1: `dts_generator.py` — 数据结构与规则引擎（`rule_supply`）

**Files:**
- Modify: `src/dts_gen/core/pipeline/dts_generator.py`
- Test: `tests/core/pipeline/test_dts_generator.py`

**Interfaces:**
- Consumes: `dts_gen.core.ir.models.Relation`（`kind`/`from_`/`to`/`property`/`active` 字段）、`dts_gen.core.ir.models.HardwareIR`
- Produces: `DtsProperty`（dataclass：`name: str`, `value: str`, `rule_id: str`, `source_relation: Relation | None = None`）、`DtsNode`（dataclass：`label: str`, `properties: list[DtsProperty]`, `component_id: str | None`, 方法 `add_property(name, value, rule_id, relation=None)`）、`RuleFn = Callable[[Relation, HardwareIR], tuple[str, str] | None]`、函数 `rule_supply(rel: Relation, ir: HardwareIR) -> tuple[str, str] | None`— 供 Task 2/3 使用

现有文件内容（`dts_generator.py`）：
```python
from __future__ import annotations

from pydantic import BaseModel, Field

from dts_gen.core.ir.models import HardwareIR, NodeSourceRef


class GenerationScope(BaseModel):
    subsystem: str | None = None


class GenerateResult(BaseModel):
    dts_text: str = ""
    node_sources: list[NodeSourceRef] = Field(default_factory=list)


def generate_dts(ir: HardwareIR, board: str | None, scope: GenerationScope) -> GenerateResult:
    return GenerateResult(dts_text="", node_sources=[])
```

- [ ] **Step 1: 写失败测试——`rule_supply` 正例与反例**

在 `tests/core/pipeline/test_dts_generator.py` 现有两个测试之上新增（保留现有两个测试不变，它们会在 Task 6 更新）：

```python
from dts_gen.core.ir.models import HardwareIR, Relation
from dts_gen.core.pipeline.dts_generator import GenerationScope, generate_dts, rule_supply


def test_rule_supply_returns_property_and_phandle_reference():
    rel = Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0", property="vbus-supply")
    ir = HardwareIR()

    result = rule_supply(rel, ir)

    assert result == ("vbus-supply", "<&pmic_ldo3>")


def test_rule_supply_returns_none_when_property_missing():
    rel = Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0")
    ir = HardwareIR()

    assert rule_supply(rel, ir) is None


def test_rule_supply_returns_none_when_from_missing():
    rel = Relation(kind="supply", to="usb_ctrl0", property="vbus-supply")
    ir = HardwareIR()

    assert rule_supply(rel, ir) is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/core/pipeline/test_dts_generator.py -v`
Expected: `ImportError: cannot import name 'rule_supply'`（或 `AttributeError`）

- [ ] **Step 3: 实现 `DtsProperty`/`DtsNode`/`rule_supply`**

把 `dts_generator.py` 的 import 区（文件最开头到 `from dts_gen.core.ir.models import HardwareIR, NodeSourceRef` 这一行）改为：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel, Field

from dts_gen.core.ir.models import HardwareIR, NodeSourceRef, Relation, UnresolvedItem
```

在 `class GenerationScope(BaseModel): subsystem: str | None = None` 这个类定义**之后**、`class GenerateResult(BaseModel):` 这个类定义**之前**，插入以下新代码（`GenerateResult`/`generate_dts` 保持原样不动，留在文件最后，Task 5 才会修改它们）：

```python
@dataclass
class DtsProperty:
    name: str
    value: str
    rule_id: str
    source_relation: Relation | None = None


@dataclass
class DtsNode:
    label: str
    properties: list[DtsProperty] = field(default_factory=list)
    component_id: str | None = None

    def add_property(
        self, name: str, value: str, rule_id: str, relation: Relation | None = None
    ) -> None:
        self.properties.append(DtsProperty(name, value, rule_id, relation))


RuleFn = Callable[[Relation, HardwareIR], "tuple[str, str] | None"]


def rule_supply(rel: Relation, ir: HardwareIR) -> "tuple[str, str] | None":
    if rel.property is None or rel.from_ is None:
        return None
    return (rel.property, f"<&{rel.from_}>")
```

文件最终结构自上而下为：import 区 → `GenerationScope` → `DtsProperty` → `DtsNode` → `RuleFn` → `rule_supply` → `GenerateResult`（原样不变） → `generate_dts`（原样不变，仍返回空结果）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/core/pipeline/test_dts_generator.py -v`
Expected: 5 passed（3 个新测试 + 2 个原有测试）

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/dts_generator.py tests/core/pipeline/test_dts_generator.py
git commit -m "feat: add DtsNode/DtsProperty structures and rule_supply rule function"
```

---

## Task 2: `dts_generator.py` — GPIO 控制规则（`rule_control_gpio`）

**Files:**
- Modify: `src/dts_gen/core/pipeline/dts_generator.py`
- Test: `tests/core/pipeline/test_dts_generator.py`

**Interfaces:**
- Consumes: Task 1 的 `Relation`、`RuleFn`
- Produces: `GPIO_ENDPOINT_RE`（模块级编译正则）、`parse_gpio_endpoint(endpoint: str | None) -> tuple[str, int] | None`、`rule_control_gpio(rel: Relation, ir: HardwareIR) -> tuple[str, str] | None` — 供 Task 3/4 使用

- [ ] **Step 1: 写失败测试**

追加到 `tests/core/pipeline/test_dts_generator.py`：

```python
from dts_gen.core.pipeline.dts_generator import parse_gpio_endpoint, rule_control_gpio


def test_parse_gpio_endpoint_extracts_controller_and_pin():
    assert parse_gpio_endpoint("soc_tlmm:gpio23") == ("soc_tlmm", 23)


def test_parse_gpio_endpoint_returns_none_for_malformed_string():
    assert parse_gpio_endpoint("soc_tlmm-gpio23") is None
    assert parse_gpio_endpoint(None) is None


def test_rule_control_gpio_returns_active_high_reference():
    rel = Relation(
        kind="control", from_="soc_tlmm:gpio23", to="redriver0",
        property="enable-gpios", active="high",
    )
    ir = HardwareIR()

    result = rule_control_gpio(rel, ir)

    assert result == ("enable-gpios", "<&soc_tlmm 23 GPIO_ACTIVE_HIGH>")


def test_rule_control_gpio_returns_active_low_reference():
    rel = Relation(
        kind="control", from_="soc_tlmm:gpio5", to="redriver0",
        property="reset-gpios", active="low",
    )
    ir = HardwareIR()

    result = rule_control_gpio(rel, ir)

    assert result == ("reset-gpios", "<&soc_tlmm 5 GPIO_ACTIVE_LOW>")


def test_rule_control_gpio_returns_none_for_unknown_property():
    rel = Relation(
        kind="control", from_="soc_tlmm:gpio23", to="redriver0",
        property="unknown-prop", active="high",
    )
    ir = HardwareIR()

    assert rule_control_gpio(rel, ir) is None


def test_rule_control_gpio_returns_none_for_malformed_from_endpoint():
    rel = Relation(
        kind="control", from_="soc_tlmm-gpio23", to="redriver0",
        property="enable-gpios", active="high",
    )
    ir = HardwareIR()

    assert rule_control_gpio(rel, ir) is None


def test_rule_control_gpio_returns_none_for_missing_active():
    rel = Relation(
        kind="control", from_="soc_tlmm:gpio23", to="redriver0",
        property="enable-gpios",
    )
    ir = HardwareIR()

    assert rule_control_gpio(rel, ir) is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/core/pipeline/test_dts_generator.py -v`
Expected: `ImportError: cannot import name 'parse_gpio_endpoint'`

- [ ] **Step 3: 实现**

在 `dts_generator.py` 里 `rule_supply` 函数之后追加：

```python
import re

GPIO_ENDPOINT_RE = re.compile(r"^(\w+):gpio(\d+)$")


def parse_gpio_endpoint(endpoint: str | None) -> "tuple[str, int] | None":
    if endpoint is None:
        return None
    match = GPIO_ENDPOINT_RE.match(endpoint)
    if not match:
        return None
    return (match.group(1), int(match.group(2)))


def rule_control_gpio(rel: Relation, ir: HardwareIR) -> "tuple[str, str] | None":
    if rel.property not in ("enable-gpios", "reset-gpios"):
        return None
    if rel.active not in ("high", "low"):
        return None
    gpio_ref = parse_gpio_endpoint(rel.from_)
    if gpio_ref is None:
        return None
    controller, pin = gpio_ref
    flag = "GPIO_ACTIVE_HIGH" if rel.active == "high" else "GPIO_ACTIVE_LOW"
    return (rel.property, f"<&{controller} {pin} {flag}>")
```

将 `import re` 移到文件顶部的 import 区（与 `from __future__ import annotations` 等放在一起），不要留在函数下方。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/core/pipeline/test_dts_generator.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/dts_generator.py tests/core/pipeline/test_dts_generator.py
git commit -m "feat: add rule_control_gpio rule function for GPIO enable/reset relations"
```

---

## Task 3: `dts_generator.py` — PHY 引用规则（`rule_phy_reference`）与 `RULES` 表

**Files:**
- Modify: `src/dts_gen/core/pipeline/dts_generator.py`
- Test: `tests/core/pipeline/test_dts_generator.py`

**Interfaces:**
- Consumes: Task 1/2 的 `rule_supply`/`rule_control_gpio`/`RuleFn`
- Produces: `rule_phy_reference(rel, ir) -> tuple[str, str] | None`、模块级常量 `RULES: dict[str, list[RuleFn]]` — 供 Task 4（`build_nodes`）使用

- [ ] **Step 1: 写失败测试**

追加到 `tests/core/pipeline/test_dts_generator.py`：

```python
from dts_gen.core.pipeline.dts_generator import RULES, rule_phy_reference


def test_rule_phy_reference_returns_phys_property():
    rel = Relation(kind="phy-reference", from_="redriver0", to="usb_phy0")
    ir = HardwareIR()

    result = rule_phy_reference(rel, ir)

    assert result == ("phys", "<&usb_phy0>")


def test_rule_phy_reference_returns_none_for_wrong_kind():
    rel = Relation(kind="supply", from_="redriver0", to="usb_phy0")
    ir = HardwareIR()

    assert rule_phy_reference(rel, ir) is None


def test_rules_table_maps_all_three_kinds():
    assert set(RULES.keys()) == {"supply", "control", "phy-reference"}
    assert RULES["supply"] == [rule_supply]
    assert RULES["control"] == [rule_control_gpio]
    assert RULES["phy-reference"] == [rule_phy_reference]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/core/pipeline/test_dts_generator.py -v`
Expected: `ImportError: cannot import name 'RULES'`

- [ ] **Step 3: 实现**

在 `dts_generator.py` 里 `rule_control_gpio` 之后追加：

```python
def rule_phy_reference(rel: Relation, ir: HardwareIR) -> "tuple[str, str] | None":
    if rel.kind != "phy-reference":
        return None
    return ("phys", f"<&{rel.to}>")


RULES: dict[str, list[RuleFn]] = {
    "supply": [rule_supply],
    "control": [rule_control_gpio],
    "phy-reference": [rule_phy_reference],
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/core/pipeline/test_dts_generator.py -v`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/dts_generator.py tests/core/pipeline/test_dts_generator.py
git commit -m "feat: add rule_phy_reference rule function and RULES dispatch table"
```

---

## Task 4: `dts_generator.py` — `build_nodes` 节点构建器

**Files:**
- Modify: `src/dts_gen/core/pipeline/dts_generator.py`
- Test: `tests/core/pipeline/test_dts_generator.py`

**Interfaces:**
- Consumes: Task 1-3 的 `DtsNode`、`RULES`、`dts_gen.core.ir.models.UnresolvedItem`
- Produces: `build_nodes(ir: HardwareIR) -> tuple[list[DtsNode], list[UnresolvedItem]]` — 供 Task 5（`generate_dts` 组装）使用

- [ ] **Step 1: 写失败测试**

追加到 `tests/core/pipeline/test_dts_generator.py`：

```python
from dts_gen.core.ir.models import Component
from dts_gen.core.pipeline.dts_generator import build_nodes


def test_build_nodes_creates_one_node_per_component():
    ir = HardwareIR(
        components=[
            Component(id="usb_ctrl0", type="usb-controller", name="dwc3"),
            Component(id="pmic_ldo3", type="regulator", name="ldo3"),
        ],
    )

    nodes, unresolved = build_nodes(ir)

    labels = sorted(n.label for n in nodes)
    assert labels == ["pmic_ldo3", "usb_ctrl0"]
    assert unresolved == []


def test_build_nodes_applies_supply_rule_to_target_node():
    ir = HardwareIR(
        components=[
            Component(id="usb_ctrl0", type="usb-controller", name="dwc3"),
            Component(id="pmic_ldo3", type="regulator", name="ldo3"),
        ],
        relations=[
            Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0", property="vbus-supply"),
        ],
    )

    nodes, unresolved = build_nodes(ir)

    usb_node = next(n for n in nodes if n.label == "usb_ctrl0")
    assert len(usb_node.properties) == 1
    assert usb_node.properties[0].name == "vbus-supply"
    assert usb_node.properties[0].value == "<&pmic_ldo3>"
    assert usb_node.properties[0].rule_id == "rule_supply"
    assert unresolved == []


def test_build_nodes_applies_phy_reference_rule_to_from_node():
    ir = HardwareIR(
        components=[
            Component(id="usb_ctrl0", type="usb-controller", name="dwc3"),
            Component(id="usb_phy0", type="usb-phy", name="qcom-usb3-phy"),
        ],
        relations=[
            Relation(kind="phy-reference", from_="usb_ctrl0", to="usb_phy0"),
        ],
    )

    nodes, unresolved = build_nodes(ir)

    ctrl_node = next(n for n in nodes if n.label == "usb_ctrl0")
    assert ctrl_node.properties[0].name == "phys"
    assert ctrl_node.properties[0].value == "<&usb_phy0>"


def test_build_nodes_reports_unresolved_for_missing_target_component():
    ir = HardwareIR(
        components=[Component(id="pmic_ldo3", type="regulator", name="ldo3")],
        relations=[
            Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0", property="vbus-supply"),
        ],
    )

    nodes, unresolved = build_nodes(ir)

    assert len(unresolved) == 1
    assert "usb_ctrl0" in unresolved[0].reason


def test_build_nodes_reports_unresolved_for_unmatched_rule():
    ir = HardwareIR(
        components=[Component(id="redriver0", type="usb-redriver", name="tusb2e11")],
        relations=[
            Relation(kind="control", from_="soc_tlmm:gpio23", to="redriver0", property="unknown-prop"),
        ],
    )

    nodes, unresolved = build_nodes(ir)

    assert len(unresolved) == 1
    redriver_node = next(n for n in nodes if n.label == "redriver0")
    assert redriver_node.properties == []


def test_build_nodes_handles_empty_relations():
    ir = HardwareIR(components=[Component(id="usb_ctrl0", type="usb-controller", name="dwc3")])

    nodes, unresolved = build_nodes(ir)

    assert len(nodes) == 1
    assert nodes[0].properties == []
    assert unresolved == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/core/pipeline/test_dts_generator.py -v`
Expected: `ImportError: cannot import name 'build_nodes'`

- [ ] **Step 3: 实现**

在 `dts_generator.py` 里 `RULES` 定义之后追加：

```python
def build_nodes(ir: HardwareIR) -> "tuple[list[DtsNode], list[UnresolvedItem]]":
    nodes: dict[str, DtsNode] = {
        comp.id: DtsNode(label=comp.id, component_id=comp.id) for comp in ir.components
    }
    unresolved: list[UnresolvedItem] = []

    for rel in ir.relations:
        target_id = rel.from_ if rel.kind == "phy-reference" else rel.to
        target_node = nodes.get(target_id)
        if target_node is None:
            unresolved.append(
                UnresolvedItem(
                    field=f"relation:{rel.kind}",
                    reason=f"目标节点 {target_id} 不存在于 components 中",
                )
            )
            continue

        matched = False
        for rule_fn in RULES.get(rel.kind, []):
            result = rule_fn(rel, ir)
            if result is not None:
                prop_name, prop_value = result
                target_node.add_property(prop_name, prop_value, rule_id=rule_fn.__name__, relation=rel)
                matched = True
                break
        if not matched:
            unresolved.append(
                UnresolvedItem(
                    field=f"relation:{rel.kind}:{rel.property}",
                    reason="没有匹配的规则，或缺少必要字段",
                )
            )

    return list(nodes.values()), unresolved
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/core/pipeline/test_dts_generator.py -v`
Expected: 21 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/dts_generator.py tests/core/pipeline/test_dts_generator.py
git commit -m "feat: add build_nodes to dispatch relations through the rule engine"
```

---

## Task 5: `dts_generator.py` — 序列化器、`node_sources` 构建与 `generate_dts` 组装

**Files:**
- Modify: `src/dts_gen/core/pipeline/dts_generator.py`
- Test: `tests/core/pipeline/test_dts_generator.py`

**Interfaces:**
- Consumes: Task 4 的 `build_nodes`
- Produces: `serialize_node(node: DtsNode, indent: str = "    ") -> str`、`serialize_dts(nodes: list[DtsNode]) -> str`、`build_node_sources(nodes: list[DtsNode]) -> list[NodeSourceRef]`、更新后的 `GenerateResult`（新增 `unresolved` 字段）、更新后的 `generate_dts(ir, board, scope) -> GenerateResult` — 供 Task 8（`tools.py`）使用

**注意**：此任务会修改现有测试 `test_generate_dts_returns_empty_text_when_not_implemented`（该测试针对 stub 行为，行为将改变）。

- [ ] **Step 1: 写失败测试**

在 `tests/core/pipeline/test_dts_generator.py` 中，**替换**现有的 `test_generate_dts_returns_empty_text_when_not_implemented`：

```python
def test_generate_dts_returns_empty_text_for_ir_without_components():
    ir = HardwareIR(board="board-x", soc="sa8775p")

    result = generate_dts(ir, board="board-x", scope=GenerationScope())

    assert result.dts_text == ""
    assert result.node_sources == []
    assert result.unresolved == []
```

并追加：

```python
def test_serialize_node_skips_nodes_without_properties():
    node = DtsNode(label="pmic_ldo3", component_id="pmic_ldo3")

    assert serialize_dts([node]) == ""


def test_serialize_node_renders_status_and_properties():
    node = DtsNode(label="usb_ctrl0", component_id="usb_ctrl0")
    node.add_property("vbus-supply", "<&pmic_ldo3>", rule_id="rule_supply")

    text = serialize_node(node)

    assert text == '&usb_ctrl0 {\n    status = "okay";\n    vbus-supply = <&pmic_ldo3>;\n};'


def test_serialize_dts_joins_multiple_nodes_with_blank_line():
    node_a = DtsNode(label="usb_ctrl0", component_id="usb_ctrl0")
    node_a.add_property("vbus-supply", "<&pmic_ldo3>", rule_id="rule_supply")
    node_b = DtsNode(label="redriver0", component_id="redriver0")
    node_b.add_property("enable-gpios", "<&soc_tlmm 23 GPIO_ACTIVE_HIGH>", rule_id="rule_control_gpio")

    text = serialize_dts([node_a, node_b])

    assert "\n\n" in text
    assert text.count("&usb_ctrl0") == 1
    assert text.count("&redriver0") == 1


def test_build_node_sources_extracts_rule_id_and_component_id():
    node = DtsNode(label="usb_ctrl0", component_id="usb_ctrl0")
    node.add_property("vbus-supply", "<&pmic_ldo3>", rule_id="rule_supply")

    sources = build_node_sources([node])

    assert len(sources) == 1
    assert sources[0].node == "&usb_ctrl0"
    assert sources[0].component_id == "usb_ctrl0"
    assert sources[0].rule_id == "rule_supply"


def test_generate_dts_end_to_end_usb_topology():
    ir = HardwareIR(
        board="hamoa-evb", soc="hamoa",
        components=[
            Component(id="usb_ctrl0", type="usb-controller", name="dwc3"),
            Component(id="usb_phy0", type="usb-phy", name="qcom-usb3-phy"),
            Component(id="redriver0", type="usb-redriver", name="tusb2e11"),
            Component(id="connector0", type="usb-connector", name="typec"),
            Component(id="pmic_ldo3", type="regulator", name="ldo3"),
        ],
        relations=[
            Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0", property="vbus-supply"),
            Relation(kind="control", from_="soc_tlmm:gpio23", to="redriver0", property="enable-gpios", active="high"),
            Relation(kind="phy-reference", from_="usb_ctrl0", to="usb_phy0"),
        ],
    )

    result = generate_dts(ir, board="hamoa-evb", scope=GenerationScope())

    assert "&usb_ctrl0" in result.dts_text
    assert "vbus-supply = <&pmic_ldo3>;" in result.dts_text
    assert "phys = <&usb_phy0>;" in result.dts_text
    assert "&redriver0" in result.dts_text
    assert "enable-gpios = <&soc_tlmm 23 GPIO_ACTIVE_HIGH>;" in result.dts_text
    assert "&usb_phy0" not in result.dts_text
    assert "&connector0" not in result.dts_text
    assert "&pmic_ldo3 {" not in result.dts_text
    assert len(result.node_sources) == 3
    assert result.unresolved == []


def test_generate_dts_returns_unresolved_when_relation_target_missing():
    ir = HardwareIR(
        components=[Component(id="pmic_ldo3", type="regulator", name="ldo3")],
        relations=[Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0", property="vbus-supply")],
    )

    result = generate_dts(ir, board=None, scope=GenerationScope())

    assert result.dts_text == ""
    assert len(result.unresolved) == 1
```

同时在文件顶部 import 区新增：`from dts_gen.core.pipeline.dts_generator import (DtsNode, build_node_sources, serialize_dts, serialize_node)`（与已有 import 合并，不要重复行）。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/core/pipeline/test_dts_generator.py -v`
Expected: `ImportError: cannot import name 'serialize_node'`

- [ ] **Step 3: 实现**

在 `dts_generator.py` 里 `build_nodes` 定义之后、`GenerateResult` 类定义之前，插入：

```python
def serialize_node(node: DtsNode, indent: str = "    ") -> str:
    lines = [f"&{node.label} {{", f'{indent}status = "okay";']
    for prop in node.properties:
        lines.append(f"{indent}{prop.name} = {prop.value};")
    lines.append("};")
    return "\n".join(lines)


def serialize_dts(nodes: list[DtsNode]) -> str:
    return "\n\n".join(serialize_node(n) for n in nodes if n.properties)


def build_node_sources(nodes: list[DtsNode]) -> list[NodeSourceRef]:
    return [
        NodeSourceRef(node=f"&{node.label}", component_id=node.component_id, rule_id=prop.rule_id)
        for node in nodes
        for prop in node.properties
    ]
```

**替换**现有的 `GenerateResult` 类和 `generate_dts` 函数（文件末尾原样保留至今的两处定义）为：

```python
class GenerateResult(BaseModel):
    dts_text: str = ""
    node_sources: list[NodeSourceRef] = Field(default_factory=list)
    unresolved: list[UnresolvedItem] = Field(default_factory=list)


def generate_dts(ir: HardwareIR, board: str | None, scope: GenerationScope) -> GenerateResult:
    nodes, unresolved = build_nodes(ir)
    dts_text = serialize_dts(nodes)
    node_sources = build_node_sources(nodes)
    return GenerateResult(dts_text=dts_text, node_sources=node_sources, unresolved=unresolved)
```

`GenerationScope` 类不受影响，保持在文件靠前位置不动。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/core/pipeline/test_dts_generator.py -v`
Expected: 27 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/dts_generator.py tests/core/pipeline/test_dts_generator.py
git commit -m "feat: implement DTS serializer and wire generate_dts to rule engine"
```

---

## Task 6: `validator.py` — 三条内部结构校验

**Files:**
- Modify: `src/dts_gen/core/pipeline/validator.py`
- Test: `tests/core/pipeline/test_validator.py`

**Interfaces:**
- Consumes: `dts_gen.core.pipeline.base.DtsError`
- Produces: `find_defined_labels(text: str) -> set[str]`、`find_referenced_labels(text: str) -> set[str]`、`check_undefined_references(text: str) -> list[DtsError]`、`check_property_syntax(text: str) -> list[DtsError]`、`check_duplicate_labels(text: str) -> list[DtsError]`、更新后的 `validate_dts(dts_text, target_platform=None) -> ValidateResult` — 供 Task 7（`run_dtc_check` 叠加）和 Task 8（`tools.py`）使用

**注意**：此任务会替换现有两个测试（针对旧 stub 行为的 "not implemented" 断言）。

现有文件内容（`validator.py`）：
```python
from __future__ import annotations

from pydantic import BaseModel, Field

from dts_gen.core.pipeline.base import DtsError


class ValidateResult(BaseModel):
    errors: list[DtsError] = Field(default_factory=list)
    warnings: list[DtsError] = Field(default_factory=list)


def validate_dts(dts_text: str, target_platform: str | None = None) -> ValidateResult:
    return ValidateResult(
        errors=[],
        warnings=[
            DtsError(
                message="validator stage not implemented yet; dtc/dtbs_check were not run",
                node=None,
                severity="warning",
            )
        ],
    )
```

- [ ] **Step 1: 写失败测试**

**替换** `tests/core/pipeline/test_validator.py` 全部内容为：

```python
import shutil
from unittest.mock import patch

from dts_gen.core.pipeline.validator import (
    check_duplicate_labels,
    check_property_syntax,
    check_undefined_references,
    find_defined_labels,
    find_referenced_labels,
    validate_dts,
)


def test_find_defined_labels_extracts_label_names():
    text = '&usb_ctrl0 {\n    status = "okay";\n};\n\n&redriver0 {\n    status = "okay";\n};'

    assert find_defined_labels(text) == {"usb_ctrl0", "redriver0"}


def test_find_referenced_labels_extracts_phandle_references():
    text = '&usb_ctrl0 {\n    vbus-supply = <&pmic_ldo3>;\n};'

    assert find_referenced_labels(text) == {"pmic_ldo3"}


def test_check_undefined_references_reports_missing_target():
    text = '&usb_ctrl0 {\n    vbus-supply = <&pmic_ldo3>;\n};'

    errors = check_undefined_references(text)

    assert len(errors) == 1
    assert "pmic_ldo3" in errors[0].message
    assert errors[0].severity == "error"


def test_check_undefined_references_passes_when_target_defined():
    text = '&usb_ctrl0 {\n    vbus-supply = <&pmic_ldo3>;\n};\n\n&pmic_ldo3 {\n    status = "okay";\n};'

    assert check_undefined_references(text) == []


def test_check_property_syntax_reports_missing_angle_brackets():
    text = '&usb_ctrl0 {\n    vbus-supply = &pmic_ldo3;\n};'

    errors = check_property_syntax(text)

    assert len(errors) == 1
    assert "vbus-supply" in errors[0].message


def test_check_property_syntax_reports_missing_quotes_for_status():
    text = '&usb_ctrl0 {\n    status = okay;\n};'

    errors = check_property_syntax(text)

    assert len(errors) == 1
    assert "status" in errors[0].message


def test_check_property_syntax_passes_for_well_formed_properties():
    text = '&usb_ctrl0 {\n    status = "okay";\n    vbus-supply = <&pmic_ldo3>;\n};'

    assert check_property_syntax(text) == []


def test_check_duplicate_labels_reports_repeated_definition():
    text = '&usb_ctrl0 {\n    status = "okay";\n};\n\n&usb_ctrl0 {\n    status = "okay";\n};'

    errors = check_duplicate_labels(text)

    assert len(errors) == 1
    assert "usb_ctrl0" in errors[0].message


def test_check_duplicate_labels_passes_for_unique_labels():
    text = '&usb_ctrl0 {\n    status = "okay";\n};\n\n&redriver0 {\n    status = "okay";\n};'

    assert check_duplicate_labels(text) == []


def test_validate_dts_returns_no_errors_for_well_formed_text():
    text = '&usb_ctrl0 {\n    status = "okay";\n    vbus-supply = <&pmic_ldo3>;\n};'

    with patch.object(shutil, "which", return_value=None):
        result = validate_dts(text)

    assert result.errors == []


def test_validate_dts_returns_empty_for_empty_text():
    with patch.object(shutil, "which", return_value=None):
        result = validate_dts("")

    assert result.errors == []


def test_validate_dts_warns_when_dtc_not_installed():
    with patch.object(shutil, "which", return_value=None):
        result = validate_dts("")

    assert len(result.warnings) == 1
    assert "dtc" in result.warnings[0].message.lower()


def test_validate_dts_aggregates_multiple_error_types():
    text = (
        '&usb_ctrl0 {\n'
        '    status = okay;\n'
        '    vbus-supply = <&pmic_ldo3>;\n'
        '};\n\n'
        '&usb_ctrl0 {\n'
        '    status = "okay";\n'
        '};'
    )

    with patch.object(shutil, "which", return_value=None):
        result = validate_dts(text)

    messages = [e.message for e in result.errors]
    assert any("pmic_ldo3" in m for m in messages)
    assert any("status" in m for m in messages)
    assert any("usb_ctrl0" in m and "重复" in m for m in messages)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/core/pipeline/test_validator.py -v`
Expected: `ImportError: cannot import name 'find_defined_labels'`

- [ ] **Step 3: 实现**

**替换** `validator.py` 全部内容为：

```python
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
```

（`run_dtc_check` 叠加逻辑留给 Task 7 添加，本步骤先让 `dtc` 不存在时的路径完整工作。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/core/pipeline/test_validator.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/validator.py tests/core/pipeline/test_validator.py
git commit -m "feat: implement internal structural validation (undefined refs, property syntax, duplicate labels)"
```

---

## Task 7: `validator.py` — 可选 `dtc` 语法校验叠加

**Files:**
- Modify: `src/dts_gen/core/pipeline/validator.py`
- Test: `tests/core/pipeline/test_validator.py`

**Interfaces:**
- Consumes: Task 6 的 `validate_dts`
- Produces: `run_dtc_check(dts_text: str) -> list[DtsError]`，`validate_dts` 在 `shutil.which("dtc")` 非 None 时调用它 — 无后续任务直接依赖，但补全设计文档承诺的行为

- [ ] **Step 1: 写失败测试**

追加到 `tests/core/pipeline/test_validator.py`：

```python
import subprocess

from dts_gen.core.pipeline.validator import run_dtc_check


def test_validate_dts_calls_run_dtc_check_when_dtc_available():
    with patch.object(shutil, "which", return_value="/usr/bin/dtc"):
        with patch(
            "dts_gen.core.pipeline.validator.run_dtc_check", return_value=[]
        ) as mock_check:
            result = validate_dts('&usb_ctrl0 { status = "okay"; };')

    mock_check.assert_called_once()
    assert result.warnings == []


def test_run_dtc_check_returns_empty_list_on_success():
    fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch("subprocess.run", return_value=fake_result):
        errors = run_dtc_check('&usb_ctrl0 { status = "okay"; };')

    assert errors == []


def test_run_dtc_check_parses_stderr_lines_into_errors_on_failure():
    fake_result = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="ERROR: line 3: syntax error\n"
    )
    with patch("subprocess.run", return_value=fake_result):
        errors = run_dtc_check("garbage input")

    assert len(errors) == 1
    assert "syntax error" in errors[0].message
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/core/pipeline/test_validator.py -v`
Expected: `ImportError: cannot import name 'run_dtc_check'`

- [ ] **Step 3: 实现**

在 `validator.py` 顶部 import 区新增 `import os` 和 `import subprocess`；在 `validate_dts` 函数之后追加：

```python
def run_dtc_check(dts_text: str) -> list[DtsError]:
    result = subprocess.run(
        ["dtc", "-O", "dtb", "-o", os.devnull, "-"],
        input=dts_text,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        return []
    return [
        DtsError(message=line.strip(), severity="error")
        for line in result.stderr.splitlines()
        if line.strip()
    ]
```

并把 `validate_dts` 里的 warnings 分支改为：

```python
    warnings: list[DtsError] = []
    if shutil.which("dtc") is None:
        warnings.append(DtsError(message="dtc 未安装，跳过语法级编译校验", severity="warning"))
    else:
        errors += run_dtc_check(dts_text)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/core/pipeline/test_validator.py -v`
Expected: 16 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/validator.py tests/core/pipeline/test_validator.py
git commit -m "feat: add optional dtc syntax check when dtc binary is available"
```

---

## Task 8: `mcp_app/tools.py` — `generate_dts` 输出新增 `unresolved` 字段

**Files:**
- Modify: `src/dts_gen/mcp_app/tools.py`
- Test: `tests/mcp_app/test_tools.py`

**Interfaces:**
- Consumes: Task 5 的 `GenerateResult.unresolved`
- Produces: `tools.generate_dts(ctx, task_id, scope=None)` 返回字典新增 `"unresolved"` 键

- [ ] **Step 1: 写失败测试**

追加到 `tests/mcp_app/test_tools.py`：

```python
from dts_gen.core.ir.models import Component, HardwareIR, Relation


def test_generate_dts_includes_unresolved_field_in_output(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]
    tools.extract_hardware_graph(ctx, task_id=task_id)

    result = tools.generate_dts(ctx, task_id=task_id)

    assert "unresolved" in result
    assert result["unresolved"] == []


def test_generate_dts_reports_unresolved_relation_targets(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]

    ir = HardwareIR(
        components=[Component(id="pmic_ldo3", type="regulator", name="ldo3")],
        relations=[Relation(kind="supply", from_="pmic_ldo3", to="usb_ctrl0", property="vbus-supply")],
    )
    ctx.ir_store.save(task_id, ir)
    task = ctx.task_store.get(task_id)
    task.ir_ref = ctx.ir_store.latest_ref(task_id)
    task.status = "extracted"
    ctx.task_store.save(task)

    result = tools.generate_dts(ctx, task_id=task_id)

    assert len(result["unresolved"]) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/mcp_app/test_tools.py -v`
Expected: `KeyError: 'unresolved'`

- [ ] **Step 3: 实现**

在 `tools.py` 的 `generate_dts` 函数（`mcp_app/tools.py:270-306`）的返回字典里新增一行：

```python
    return {
        "task_id": task_id,
        "status": "generated",
        "dts_ref": dts_ref,
        "dts_text": result.dts_text,
        "node_sources": [ref.model_dump() for ref in result.node_sources],
        "unresolved": [item.model_dump() for item in result.unresolved],
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/mcp_app/test_tools.py -v`
Expected: 全部通过（原有 + 2 个新测试）

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/mcp_app/tools.py tests/mcp_app/test_tools.py
git commit -m "feat: surface generate_dts unresolved items in MCP tool output"
```

---

## Task 9: `spec_sync/fetcher.py` — HTTP 拉取与 `.rst` 目录发现

**Files:**
- Create: `src/dts_gen/core/knowledge/spec_sync/__init__.py`
- Create: `src/dts_gen/core/knowledge/spec_sync/fetcher.py`
- Test: `tests/core/knowledge/spec_sync/__init__.py`
- Test: `tests/core/knowledge/spec_sync/test_fetcher.py`

**Interfaces:**
- Consumes: `requests`（已在 `pyproject.toml` 依赖之外，本机已安装；Task 14 会把它加入 `pyproject.toml` 声明）
- Produces: `FetchError(Exception)`、`fetch(url: str) -> str`、`TrackedFile`（dataclass：`filename: str`, `source_url: str`）、`list_rst_files(api_url: str) -> list[TrackedFile]` — 供 Task 12（`sync.py`）使用

本任务使用真实网络（Global Constraints 已声明），测试会实际访问 `raw.githubusercontent.com` 和 `api.github.com`。

- [ ] **Step 1: 创建空 `__init__.py` 文件**

```bash
mkdir -p src/dts_gen/core/knowledge/spec_sync tests/core/knowledge/spec_sync
touch src/dts_gen/core/knowledge/spec_sync/__init__.py
touch tests/core/knowledge/spec_sync/__init__.py
```

- [ ] **Step 2: 写失败测试**

创建 `tests/core/knowledge/spec_sync/test_fetcher.py`：

```python
import pytest

from dts_gen.core.knowledge.spec_sync.fetcher import FetchError, TrackedFile, fetch, list_rst_files

GPIO_BINDING_URL = (
    "https://raw.githubusercontent.com/torvalds/linux/master/"
    "Documentation/devicetree/bindings/gpio/gpio.txt"
)
DT_SPEC_CONTENTS_API_URL = (
    "https://api.github.com/repos/devicetree-org/devicetree-specification/contents/source"
)


def test_fetch_returns_nonempty_text_for_real_url():
    text = fetch(GPIO_BINDING_URL)

    assert isinstance(text, str)
    assert len(text) > 0


def test_fetch_raises_fetch_error_for_invalid_url():
    with pytest.raises(FetchError):
        fetch("https://raw.githubusercontent.com/does-not-exist/does-not-exist/main/nope.txt")


def test_list_rst_files_returns_only_rst_files_from_source_root():
    files = list_rst_files(DT_SPEC_CONTENTS_API_URL)

    assert len(files) > 0
    assert all(isinstance(f, TrackedFile) for f in files)
    assert all(f.filename.endswith(".rst") for f in files)
    assert all("/extensions/" not in f.source_url for f in files)


def test_list_rst_files_raises_fetch_error_for_invalid_api_url():
    with pytest.raises(FetchError):
        list_rst_files("https://api.github.com/repos/does-not-exist/does-not-exist/contents/source")
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/core/knowledge/spec_sync/test_fetcher.py -v`
Expected: `ModuleNotFoundError: No module named 'dts_gen.core.knowledge.spec_sync.fetcher'`

- [ ] **Step 4: 实现**

创建 `src/dts_gen/core/knowledge/spec_sync/fetcher.py`：

```python
from __future__ import annotations

from dataclasses import dataclass

import requests


class FetchError(Exception):
    def __init__(self, url: str, reason: str):
        super().__init__(f"failed to fetch {url}: {reason}")
        self.url = url
        self.reason = reason


@dataclass
class TrackedFile:
    filename: str
    source_url: str


def fetch(url: str) -> str:
    try:
        response = requests.get(url, timeout=10)
    except requests.RequestException as exc:
        raise FetchError(url, str(exc)) from exc
    if response.status_code != 200:
        raise FetchError(url, f"HTTP {response.status_code}")
    return response.text


def list_rst_files(api_url: str) -> list[TrackedFile]:
    try:
        response = requests.get(api_url, timeout=10)
    except requests.RequestException as exc:
        raise FetchError(api_url, str(exc)) from exc
    if response.status_code != 200:
        raise FetchError(api_url, f"HTTP {response.status_code}")

    entries = response.json()
    return [
        TrackedFile(filename=entry["name"], source_url=entry["download_url"])
        for entry in entries
        if entry.get("type") == "file" and entry.get("name", "").endswith(".rst")
    ]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/core/knowledge/spec_sync/test_fetcher.py -v`
Expected: 4 passed（需要真实网络连通）

- [ ] **Step 6: Commit**

```bash
git add src/dts_gen/core/knowledge/spec_sync/__init__.py src/dts_gen/core/knowledge/spec_sync/fetcher.py tests/core/knowledge/spec_sync/__init__.py tests/core/knowledge/spec_sync/test_fetcher.py
git commit -m "feat: add spec_sync fetcher for HTTP downloads and GitHub directory discovery"
```

---

## Task 10: `spec_sync/cache.py` — 版本化缓存

**Files:**
- Create: `src/dts_gen/core/knowledge/spec_sync/cache.py`
- Test: `tests/core/knowledge/spec_sync/test_cache.py`

**Interfaces:**
- Consumes: 无（纯文件系统操作，无网络）
- Produces: `read_cached(cache_dir: Path, filename: str, slot: str) -> str | None`、`rotate_and_write(cache_dir: Path, filename: str, new_text: str) -> None`、`write_sync_meta(cache_dir: Path, filename: str, source_url: str) -> None` — 供 Task 12（`sync.py`）使用

- [ ] **Step 1: 写失败测试**

创建 `tests/core/knowledge/spec_sync/test_cache.py`：

```python
import json
from pathlib import Path

from dts_gen.core.knowledge.spec_sync.cache import read_cached, rotate_and_write, write_sync_meta


def test_read_cached_returns_none_when_file_missing(tmp_path: Path):
    assert read_cached(tmp_path, "gpio.txt", "latest") is None


def test_rotate_and_write_creates_latest_file(tmp_path: Path):
    rotate_and_write(tmp_path, "gpio.txt", "first version text")

    assert read_cached(tmp_path, "gpio.txt", "latest") == "first version text"
    assert read_cached(tmp_path, "gpio.txt", "previous") is None


def test_rotate_and_write_moves_latest_to_previous_on_second_call(tmp_path: Path):
    rotate_and_write(tmp_path, "gpio.txt", "first version text")
    rotate_and_write(tmp_path, "gpio.txt", "second version text")

    assert read_cached(tmp_path, "gpio.txt", "latest") == "second version text"
    assert read_cached(tmp_path, "gpio.txt", "previous") == "first version text"


def test_write_sync_meta_records_source_url_and_timestamp(tmp_path: Path):
    write_sync_meta(tmp_path, "gpio.txt", source_url="https://example.com/gpio.txt")

    meta_path = tmp_path / "sync_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["gpio.txt"]["source_url"] == "https://example.com/gpio.txt"
    assert "synced_at" in meta["gpio.txt"]


def test_write_sync_meta_merges_multiple_files_without_overwriting_others(tmp_path: Path):
    write_sync_meta(tmp_path, "gpio.txt", source_url="https://example.com/gpio.txt")
    write_sync_meta(tmp_path, "regulator.yaml", source_url="https://example.com/regulator.yaml")

    meta_path = tmp_path / "sync_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert set(meta.keys()) == {"gpio.txt", "regulator.yaml"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/core/knowledge/spec_sync/test_cache.py -v`
Expected: `ModuleNotFoundError: No module named 'dts_gen.core.knowledge.spec_sync.cache'`

- [ ] **Step 3: 实现**

创建 `src/dts_gen/core/knowledge/spec_sync/cache.py`：

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _slot_path(cache_dir: Path, filename: str, slot: str) -> Path:
    return cache_dir / f"{filename}.{slot}"


def read_cached(cache_dir: Path, filename: str, slot: str) -> str | None:
    path = _slot_path(cache_dir, filename, slot)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def rotate_and_write(cache_dir: Path, filename: str, new_text: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    latest_path = _slot_path(cache_dir, filename, "latest")
    previous_path = _slot_path(cache_dir, filename, "previous")

    if latest_path.exists():
        previous_path.write_text(latest_path.read_text(encoding="utf-8"), encoding="utf-8")

    latest_path.write_text(new_text, encoding="utf-8")


def write_sync_meta(cache_dir: Path, filename: str, source_url: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    meta_path = cache_dir / "sync_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta[filename] = {
        "source_url": source_url,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/core/knowledge/spec_sync/test_cache.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/knowledge/spec_sync/cache.py tests/core/knowledge/spec_sync/test_cache.py
git commit -m "feat: add version-rotated file cache for spec_sync"
```

---

## Task 11: `spec_sync/diff_report.py` — 全文 diff 报告

**Files:**
- Create: `src/dts_gen/core/knowledge/spec_sync/diff_report.py`
- Test: `tests/core/knowledge/spec_sync/test_diff_report.py`

**Interfaces:**
- Consumes: 无（纯字符串处理）
- Produces: `DiffReport`（pydantic BaseModel：`filename: str`, `diff: str | None = None`, `has_changes: bool = False`, `first_sync: bool = False`, `fetch_error: str | None = None`）、`build_diff_report(old_text: str | None, new_text: str, filename: str) -> DiffReport` — 供 Task 12（`sync.py`）使用

- [ ] **Step 1: 写失败测试**

创建 `tests/core/knowledge/spec_sync/test_diff_report.py`：

```python
from dts_gen.core.knowledge.spec_sync.diff_report import DiffReport, build_diff_report


def test_build_diff_report_marks_first_sync_when_no_previous_text():
    report = build_diff_report(None, "new content", "gpio.txt")

    assert report.first_sync is True
    assert report.has_changes is False
    assert report.diff is None


def test_build_diff_report_detects_no_changes_for_identical_text():
    report = build_diff_report("same content", "same content", "gpio.txt")

    assert report.has_changes is False
    assert report.diff is None
    assert report.first_sync is False


def test_build_diff_report_produces_unified_diff_for_changed_text():
    report = build_diff_report("line one\nline two\n", "line one\nline three\n", "gpio.txt")

    assert report.has_changes is True
    assert "line two" in report.diff
    assert "line three" in report.diff


def test_diff_report_defaults_fetch_error_to_none():
    report = DiffReport(filename="gpio.txt")

    assert report.fetch_error is None
    assert report.first_sync is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/core/knowledge/spec_sync/test_diff_report.py -v`
Expected: `ModuleNotFoundError: No module named 'dts_gen.core.knowledge.spec_sync.diff_report'`

- [ ] **Step 3: 实现**

创建 `src/dts_gen/core/knowledge/spec_sync/diff_report.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/core/knowledge/spec_sync/test_diff_report.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/knowledge/spec_sync/diff_report.py tests/core/knowledge/spec_sync/test_diff_report.py
git commit -m "feat: add unified-diff report builder for spec_sync"
```

---

## Task 12: `spec_sync/sync.py` — 顶层协调与单文件隔离失败

**Files:**
- Create: `src/dts_gen/core/knowledge/spec_sync/sync.py`
- Test: `tests/core/knowledge/spec_sync/test_sync.py`

**Interfaces:**
- Consumes: Task 9 的 `fetch`/`list_rst_files`/`FetchError`/`TrackedFile`，Task 10 的 `read_cached`/`rotate_and_write`/`write_sync_meta`，Task 11 的 `DiffReport`/`build_diff_report`
- Produces: `KERNEL_BINDING_FILES: list[TrackedFile]`、`DT_SPEC_CONTENTS_API_URL: str`、`sync_bindings(cache_dir: Path) -> list[DiffReport]` — 供 Task 13（`mcp_app/tools.py`）和 Task 14（`cli.py`）使用

本任务使用真实网络（Global Constraints 已声明）。

- [ ] **Step 1: 写失败测试**

创建 `tests/core/knowledge/spec_sync/test_sync.py`：

```python
from pathlib import Path
from unittest.mock import patch

from dts_gen.core.knowledge.spec_sync.fetcher import FetchError, TrackedFile
from dts_gen.core.knowledge.spec_sync.sync import KERNEL_BINDING_FILES, sync_bindings


def test_sync_bindings_first_run_marks_all_files_as_first_sync(tmp_path: Path):
    reports = sync_bindings(tmp_path)

    kernel_reports = [r for r in reports if r.filename in {f.filename for f in KERNEL_BINDING_FILES}]
    assert len(kernel_reports) == len(KERNEL_BINDING_FILES)
    assert all(r.first_sync for r in kernel_reports)
    assert any(r.filename.endswith(".rst") for r in reports)


def test_sync_bindings_second_run_detects_no_changes_for_stable_files(tmp_path: Path):
    sync_bindings(tmp_path)
    second_reports = sync_bindings(tmp_path)

    kernel_reports = [
        r for r in second_reports if r.filename in {f.filename for f in KERNEL_BINDING_FILES}
    ]
    assert all(not r.first_sync for r in kernel_reports)
    # Real upstream files might change between the two calls in rare cases,
    # but fetch_error must never be set for a successful second run.
    assert all(r.fetch_error is None for r in kernel_reports)


def test_sync_bindings_isolates_single_file_fetch_failure(tmp_path: Path):
    broken_file = TrackedFile(filename="broken.txt", source_url="https://raw.githubusercontent.com/does-not-exist/does-not-exist/main/nope.txt")

    with patch(
        "dts_gen.core.knowledge.spec_sync.sync.KERNEL_BINDING_FILES",
        [*KERNEL_BINDING_FILES, broken_file],
    ):
        reports = sync_bindings(tmp_path)

    broken_report = next(r for r in reports if r.filename == "broken.txt")
    assert broken_report.fetch_error is not None

    other_reports = [r for r in reports if r.filename != "broken.txt" and r.filename in {f.filename for f in KERNEL_BINDING_FILES}]
    assert all(r.fetch_error is None for r in other_reports)


def test_sync_bindings_falls_back_to_kernel_files_when_directory_listing_fails(tmp_path: Path):
    with patch(
        "dts_gen.core.knowledge.spec_sync.sync.DT_SPEC_CONTENTS_API_URL",
        "https://api.github.com/repos/does-not-exist/does-not-exist/contents/source",
    ):
        reports = sync_bindings(tmp_path)

    kernel_reports = [r for r in reports if r.filename in {f.filename for f in KERNEL_BINDING_FILES}]
    assert len(kernel_reports) == len(KERNEL_BINDING_FILES)
    assert all(r.fetch_error is None for r in kernel_reports)

    directory_failure = [r for r in reports if r.filename == "devicetree-specification/source"]
    assert len(directory_failure) == 1
    assert directory_failure[0].fetch_error is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/core/knowledge/spec_sync/test_sync.py -v`
Expected: `ModuleNotFoundError: No module named 'dts_gen.core.knowledge.spec_sync.sync'`

- [ ] **Step 3: 实现**

创建 `src/dts_gen/core/knowledge/spec_sync/sync.py`：

```python
from __future__ import annotations

from pathlib import Path

from dts_gen.core.knowledge.spec_sync.cache import read_cached, rotate_and_write, write_sync_meta
from dts_gen.core.knowledge.spec_sync.diff_report import DiffReport, build_diff_report
from dts_gen.core.knowledge.spec_sync.fetcher import FetchError, TrackedFile, fetch, list_rst_files

KERNEL_BINDING_FILES: list[TrackedFile] = [
    TrackedFile(
        "regulator.yaml",
        "https://raw.githubusercontent.com/torvalds/linux/master/Documentation/devicetree/bindings/regulator/regulator.yaml",
    ),
    TrackedFile(
        "gpio.txt",
        "https://raw.githubusercontent.com/torvalds/linux/master/Documentation/devicetree/bindings/gpio/gpio.txt",
    ),
    TrackedFile(
        "phy-bindings.txt",
        "https://raw.githubusercontent.com/torvalds/linux/master/Documentation/devicetree/bindings/phy/phy-bindings.txt",
    ),
]

DT_SPEC_CONTENTS_API_URL = "https://api.github.com/repos/devicetree-org/devicetree-specification/contents/source"


def sync_bindings(cache_dir: Path) -> list[DiffReport]:
    try:
        dt_spec_files = list_rst_files(DT_SPEC_CONTENTS_API_URL)
        directory_error: DiffReport | None = None
    except FetchError as exc:
        dt_spec_files = []
        directory_error = DiffReport(filename="devicetree-specification/source", fetch_error=str(exc))

    reports: list[DiffReport] = []
    for entry in [*KERNEL_BINDING_FILES, *dt_spec_files]:
        try:
            new_text = fetch(entry.source_url)
        except FetchError as exc:
            reports.append(DiffReport(filename=entry.filename, fetch_error=str(exc)))
            continue

        old_text = read_cached(cache_dir, entry.filename, "latest")
        rotate_and_write(cache_dir, entry.filename, new_text)
        write_sync_meta(cache_dir, entry.filename, source_url=entry.source_url)

        reports.append(build_diff_report(old_text, new_text, entry.filename))

    if directory_error is not None:
        reports.append(directory_error)
    return reports
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/core/knowledge/spec_sync/test_sync.py -v`
Expected: 4 passed（需要真实网络连通，运行时间较长因为会拉取全部 devicetree-specification `.rst` 文件两次）

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/knowledge/spec_sync/sync.py tests/core/knowledge/spec_sync/test_sync.py
git commit -m "feat: add sync_bindings top-level coordinator with per-file isolation"
```

---

## Task 13: `mcp_app/tools.py` — 新增 `sync_bindings` 工具函数（第 9 个 Tool，无 task_id）

**Files:**
- Modify: `src/dts_gen/mcp_app/tools.py`
- Modify: `src/dts_gen/mcp_app/server.py`
- Test: `tests/mcp_app/test_tools.py`
- Test: `tests/mcp_app/test_server.py`

**Interfaces:**
- Consumes: Task 12 的 `sync_bindings` core 函数（重命名引用避免与新工具函数同名冲突：`from dts_gen.core.knowledge.spec_sync.sync import sync_bindings as _sync_bindings`）
- Produces: `tools.sync_bindings(ctx: ToolContext) -> dict`（返回 `{"reports": [...]}`，不含 `task_id`），MCP server 新增注册的 `sync_bindings` tool

先读取现有 `tests/mcp_app/test_server.py` 了解测试风格：

- [ ] **Step 1: 写失败测试**

追加到 `tests/mcp_app/test_tools.py`：

```python
def test_sync_bindings_returns_reports_list_without_task_id(ctx):
    result = tools.sync_bindings(ctx)

    assert "task_id" not in result
    assert "reports" in result
    assert isinstance(result["reports"], list)
    assert len(result["reports"]) > 0
```

追加到 `tests/mcp_app/test_server.py`：**替换**现有的 `test_server_registers_all_eight_tools` 测试为（该测试的固定名字集合需要新增 `sync_bindings`）：

```python
def test_server_registers_all_nine_tools(tmp_path: Path):
    server = build_server(base_dir=tmp_path)

    tools = asyncio.run(server.list_tools())
    tool_names = {tool.name for tool in tools}

    assert tool_names == {
        "ingest_input",
        "extract_hardware_graph",
        "identify_soc_mapping",
        "generate_dts",
        "validate_dts",
        "repair_dts",
        "diff_dts",
        "explain_node",
        "sync_bindings",
    }
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/mcp_app/test_tools.py::test_sync_bindings_returns_reports_list_without_task_id -v`
Expected: `AttributeError: module 'dts_gen.mcp_app.tools' has no attribute 'sync_bindings'`

- [ ] **Step 3: 实现**

在 `mcp_app/tools.py` 顶部 import 区新增：

```python
from dts_gen.core.knowledge.spec_sync.sync import sync_bindings as _sync_bindings
```

在文件末尾（`explain_node` 函数之后）追加：

```python
def sync_bindings(ctx: ToolContext) -> dict:
    cache_dir = ctx.dts_dir.parent / "knowledge" / "data" / "dt_spec"
    reports = _sync_bindings(cache_dir)
    return {"reports": [report.model_dump() for report in reports]}
```

**注意**：`sync_bindings` **不**使用 `@_with_error_safety_net` 装饰器——该装饰器的实现（`_extract_task_id`）依赖函数签名里存在 `task_id` 参数，`sync_bindings` 没有这个参数，套用装饰器会导致 `_extract_task_id` 返回 `None` 后续逻辑仍能跑通但语义不符（装饰器是为"任务失败标记"设计的，`sync_bindings` 不属于任何任务）。若同步过程内部异常，让异常直接抛出即可（这是运维命令，异常应该让调用方看到完整堆栈，不是任务流程的一部分）。

在 `mcp_app/server.py` 里 `explain_node` 工具注册之后（`return server` 之前）新增：

```python
    @server.tool()
    def sync_bindings() -> dict:
        return tools.sync_bindings(tool_ctx)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/mcp_app/test_tools.py tests/mcp_app/test_server.py -v`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/mcp_app/tools.py src/dts_gen/mcp_app/server.py tests/mcp_app/test_tools.py tests/mcp_app/test_server.py
git commit -m "feat: register sync_bindings as the 9th MCP tool (no task_id)"
```

---

## Task 14: `cli.py` — `sync-bindings` 子命令与 `pyproject.toml` 依赖声明

**Files:**
- Modify: `src/dts_gen/cli.py`
- Modify: `pyproject.toml`
- Test: `tests/test_cli.py`（新建）

**Interfaces:**
- Consumes: Task 12 的 `sync_bindings` core 函数
- Produces: `dts-gen sync-bindings` 子命令，逐文件打印 diff/无变化/首次同步/拉取失败

现有 `cli.py` 内容：
```python
from __future__ import annotations

from dts_gen.mcp_app.server import main as run_server


def main() -> None:
    run_server()


if __name__ == "__main__":
    main()
```

- [ ] **Step 1: 写失败测试**

创建 `tests/test_cli.py`：

```python
import sys
from pathlib import Path
from unittest.mock import patch

from dts_gen.cli import main


def test_main_with_no_args_runs_mcp_server():
    with patch("dts_gen.cli.run_server") as mock_run_server:
        with patch.object(sys, "argv", ["dts-gen"]):
            main()

    mock_run_server.assert_called_once()


def test_main_with_sync_bindings_arg_calls_sync_and_prints_reports(tmp_path: Path, capsys):
    from dts_gen.core.knowledge.spec_sync.diff_report import DiffReport

    fake_reports = [
        DiffReport(filename="gpio.txt", first_sync=True),
        DiffReport(filename="regulator.yaml", has_changes=True, diff="--- a\n+++ b"),
        DiffReport(filename="phy-bindings.txt", has_changes=False),
        DiffReport(filename="broken.txt", fetch_error="HTTP 404"),
    ]

    with patch("dts_gen.cli.run_sync_bindings", return_value=fake_reports) as mock_sync:
        with patch.object(sys, "argv", ["dts-gen", "sync-bindings"]):
            main()

    mock_sync.assert_called_once()
    captured = capsys.readouterr()
    assert "gpio.txt" in captured.out
    assert "首次同步" in captured.out
    assert "regulator.yaml" in captured.out
    assert "phy-bindings.txt" in captured.out
    assert "无变化" in captured.out
    assert "broken.txt" in captured.out
    assert "HTTP 404" in captured.out
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_cli.py -v`
Expected: `ImportError: cannot import name 'run_sync_bindings'`

- [ ] **Step 3: 实现**

**替换** `cli.py` 全部内容为：

```python
from __future__ import annotations

import sys
from pathlib import Path

from dts_gen.core.knowledge.spec_sync.diff_report import DiffReport
from dts_gen.core.knowledge.spec_sync.sync import sync_bindings as run_sync_bindings
from dts_gen.mcp_app.server import main as run_server


def _print_report(report: DiffReport) -> None:
    if report.fetch_error is not None:
        print(f"{report.filename}: 拉取失败: {report.fetch_error}")
    elif report.first_sync:
        print(f"{report.filename}: 首次同步")
    elif report.has_changes:
        print(f"{report.filename}: 有变化")
        print(report.diff)
    else:
        print(f"{report.filename}: 无变化")


def _sync_bindings_command() -> None:
    cache_dir = Path.cwd() / ".dts-gen" / "knowledge" / "data" / "dt_spec"
    reports = run_sync_bindings(cache_dir)
    for report in reports:
        _print_report(report)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "sync-bindings":
        _sync_bindings_command()
    else:
        run_server()


if __name__ == "__main__":
    main()
```

在 `pyproject.toml` 的 `dependencies` 列表里新增一行：

```toml
dependencies = [
    "pydantic>=2.0,<3.0",
    "PyYAML>=6.0,<7.0",
    "pypdf>=6.0,<7.0",
    "mcp>=2.0,<3.0",
    "requests>=2.31,<3.0",
]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_cli.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/cli.py pyproject.toml tests/test_cli.py
git commit -m "feat: add sync-bindings CLI subcommand and declare requests dependency"
```

---

## Task 15: 全量回归与端到端验收

**Files:**
- No new files. Verification-only task.

**Interfaces:**
- Consumes: 全部前置任务的实现
- Produces: 无新接口，验证 Global Constraints 里的端到端验收用例（对应设计文档 6.1 节）在真实工具链路径（`mcp_app.tools`）下也能跑通

- [ ] **Step 1: 运行全量测试套件**

Run: `python -m pytest -v`
Expected: 全部通过（包含 Task 1-14 新增的所有测试 + 原有 74 个测试，且原有测试中 `test_full_happy_path_through_validate` 等依赖 `validate_dts`/`generate_dts` 旧 stub 行为的测试需要人工确认其断言在新实现下是否仍然成立——若断言过时（例如硬编码了旧的"1条warning"数字且 dtc 不可用环境下该数字仍然是1，则不需要改；若因为新校验逻辑对该测试用的 IR 产出了新的 warning/error，需要按 Task 6 的方式更新断言使其匹配新行为，不要放宽断言掩盖真实问题）

- [ ] **Step 2: 手工验证设计文档 6.1 节端到端用例**

创建一个临时脚本手工跑一遍（不写入仓库，仅用于本步骤验证，验证后删除）：

```bash
python -c "
from dts_gen.core.ir.models import Component, HardwareIR, Relation
from dts_gen.core.pipeline.dts_generator import GenerationScope, generate_dts
from dts_gen.core.pipeline.validator import validate_dts

ir = HardwareIR(
    board='hamoa-evb', soc='hamoa',
    components=[
        Component(id='usb_ctrl0', type='usb-controller', name='dwc3'),
        Component(id='usb_phy0', type='usb-phy', name='qcom-usb3-phy'),
        Component(id='redriver0', type='usb-redriver', name='tusb2e11'),
        Component(id='connector0', type='usb-connector', name='typec'),
        Component(id='pmic_ldo3', type='regulator', name='ldo3'),
    ],
    relations=[
        Relation(kind='supply', from_='pmic_ldo3', to='usb_ctrl0', property='vbus-supply'),
        Relation(kind='control', from_='soc_tlmm:gpio23', to='redriver0', property='enable-gpios', active='high'),
        Relation(kind='phy-reference', from_='usb_ctrl0', to='usb_phy0'),
    ],
)

result = generate_dts(ir, board='hamoa-evb', scope=GenerationScope())
print(result.dts_text)
print('---')
print('node_sources:', len(result.node_sources))
print('unresolved:', result.unresolved)

validated = validate_dts(result.dts_text)
print('---')
print('errors:', validated.errors)
"
```

Expected 输出：`dts_text` 含 `&usb_ctrl0`（`vbus-supply`+`phys`）和 `&redriver0`（`enable-gpios`），不含 `&usb_phy0`/`&connector0`/`&pmic_ldo3` 节点块；`node_sources` 长度 3；`unresolved` 为空列表；`errors` 为空列表。

- [ ] **Step 3: 手工验证 `sync-bindings` CLI 命令真实运行**

Run: `python -m dts_gen.cli sync-bindings`（或若已 `pip install -e .`：`dts-gen sync-bindings`）
Expected: 逐行打印 9 个左右文件（3 个内核 binding + 若干 devicetree-specification `.rst` 文件）的"首次同步"状态，无异常抛出

- [ ] **Step 4: 无需 Commit（本任务不产生代码改动）**

若 Step 2 发现任何断言不匹配，回到对应任务修复后重新运行本任务的 Step 1-3。

---

## 与设计文档的对照表（供实施后自查）

| 设计文档章节 | 对应任务 |
|---|---|
| 三（`dts_generator.py`，3.1-3.6） | Task 1-5 |
| 三 3.7（`tools.py` 新增 `unresolved`） | Task 8 |
| 四（`validator.py`） | Task 6-7 |
| 五（`spec_sync`，5.2-5.5） | Task 9-12 |
| 五 5.6（CLI + MCP Tool） | Task 13-14 |
| 五 5.7（新增依赖） | Task 14 |
| 六（端到端验收用例） | Task 15 |
