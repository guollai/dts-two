# block_semantic.json → IR 转换层设计

日期：2026-08-06

## 〇、背景与范围

`dts_one`（独立项目，`C:\Users\guollai\LAI\dts_one`）已经实现了 PDF 原理图的两阶段结构化管线：

1. **几何还原层**：PDF → `geometry.json`（矢量图元：线条/曲线/矩形+文字，带坐标），用 SSIM 图像相似度验证还原精度，已在 3 份真实硬件原理图（126页）上验证 95%+ 达标。
2. **语义提取层**：`geometry.json` → `block_semantic.json`（空间聚类分块 + 逐块视觉模型提取），识别出每个电路块内的器件（`components`）和网络连接（`nets`）。该项目自身的设计文档记录了一次重要的负结果——纯几何规则引擎（正则匹配器件编号 + union-find合并线段端点）在真实数据上无法可靠工作（126页批量测试发现超25%的识别结果荒谬），根因是符号本体构造线与真实网络连线在几何图元层面无法区分，因此转向了视觉模型辅助提取，这条路径已用真实API调用在真实原理图上验证可行。

**两个项目的最终目标是合并成一个完整工具。** 任务边界划分为并行推进：
- `dts_one`（另一项目，本次不涉及）：负责跨页/跨块的 net 解析——把 `block_semantic.json` 里 `connectedLabels` 中形如 `[22]`、`[7,37,8]`、`[47-C4,47-D4]` 的括号跨页引用，真正解析成"指向哪一页哪个连接点"。
- `dts-gen`（本次任务）：负责"`block_semantic.json` → IR"这一层转换——把 `dts_one` 产出的松散字典（自由文本标签、无pydantic约束）转换、校验成 `dts-gen` 严格定义的 IR 模型（`Component`/`Net`/`UnresolvedItem`）。

**本次范围明确排除**：
- 不解析跨页/跨块括号引用（交给 `dts_one` 后续完成，本次遇到直接忽略，不产出 unresolved）
- 不推断 `Relation`（语义关系，如"这是supply关系还是control关系"）——只做 `Net`（连接事实）转换。命名规律推断Relation存在真实的歧义（如`RAPID_SHUTDOWN`介于control和开关拓扑之间），留给独立后续任务
- 不接入 `extract_hardware_graph` 的调用链路——本次只交付一个独立、可单测的转换函数，MCP工具层接入是下一个任务
- 仅处理单页输入，不处理跨页/跨block合并
- 不对 `Component.type` 做词汇规范化——直接存 `dts_one` 给出的自由文本原文（如`"transistor (MOSFET, PJE138K SOT-523)"`），归类到USB MVP现有受限词汇（`usb-controller`等）是后续任务

## 一、`block_semantic.json` 输入格式（已从真实样本确认）

```json
{
  "sourceGeometryFile": "verification/SOM-6820_A101-2/geometry/page006.geometry.json",
  "blocks": [
    {
      "blockId": "block_0003",
      "bbox": [28.3, 33.7, 465.2, 342.2],
      "pathIds": ["path_0064", "..."],
      "textIds": ["text_0027", "..."],
      "nets": [
        {"netNameLabel": "PCIE4_REFCLK_100M+", "connectedLabels": ["PCIE4_REFCLK_100M+", "R3 pin 1", "R5 pin 1"]},
        {"netNameLabel": null, "connectedLabels": ["C? pin 1"]}
      ],
      "components": [
        {"designator": "R3", "componentType": "resistor", "pinCount": 2}
      ]
    }
  ]
}
```

真实样本中观察到的关键复杂性：
- **`netNameLabel` 大量为 `null`**（如某些block内所有net都是null）
- **`connectedLabels` 混杂多种条目**：正常引脚引用（`"R3 pin 1"`）、裸网络名自引用（`"PCIE4_REFCLK_100M+"`）、跨页括号引用（`"[22]"`、`"[7,37,8]"`、`"[47-C4,47-D4]"`）、不确定标记（`"C? pin 1"`）
- **`connectedLabels` 引用的designator不一定在同block的`components`列表里出现**（可能只在其他block/页面被列出）
- **`componentType` 是完全自由文本**，与 `dts-gen` 现有IR的受限词汇体系（`usb-controller`/`usb-phy`等）完全不同体系
- **引脚标识格式不统一**：同类器件有的写`"pin D"`有的写`"pin 1"`

## 二、模块结构

新增单一文件，不新增顶层目录：

```
src/dts_gen/core/pipeline/semantic_import.py
  - _LABEL_RE, _BRACKET_RE          # 模块级正则常量
  - parse_connected_label(label)     # 单条label解析
  - class ImportResult(BaseModel)    # ir: HardwareIR, unresolved: list[UnresolvedItem]
  - import_block_semantic(data, page=None)  # 顶层入口
```

放在 `core/pipeline/` 里，与 `hardware_extractor.py`/`soc_mapper.py` 同级——性质上同属"数据形态转换"阶段。

**输入契约**：`import_block_semantic` 接收**已解析好的 Python dict**（不是文件路径），文件IO是调用方的责任，函数本身可用手写dict直接单测。

## 三、`parse_connected_label` 解析规则

```python
import re

# "R3 pin 1" / "SU1C pin G37" / "Q54 pin D" / "R544 pin2"（无空格变体）
_LABEL_RE = re.compile(r"^([A-Za-z0-9_\-\.\?]+)\s*pin\s*([A-Za-z0-9]+)$", re.IGNORECASE)
# 跨页引用条目，如 "[22]"、"[7,37,8]"、"[47-C4,47-D4]"
_BRACKET_RE = re.compile(r"^\[.*\]$")


def parse_connected_label(label: str) -> tuple[str, str] | None:
    stripped = label.strip()
    if _BRACKET_RE.match(stripped):
        return None  # 跨页引用，本次忽略（既不解析也不进unresolved）
    match = _LABEL_RE.match(stripped)
    if not match:
        return None  # 解析失败：裸网络名自引用（"VDD_CX"）、粘连文本等
    designator, pin = match.groups()
    if "?" in designator:
        return None  # designator本身含不确定标记，视为解析失败
    return (designator, pin)
```

### 三种"返回None"场景的区别处理（在调用方`import_block_semantic`里区分）

`parse_connected_label` 本身只负责"能解析就解析，不能就返回None"，不负责判断是否要记录unresolved——这个判断留给调用方，依据"这条label本来看起来是想表达什么"：

1. **括号跨页引用**（`_BRACKET_RE`匹配）→ 静默跳过，不进 `unresolved`（属于 `dts_one` 后续任务范围，本次视为正常情况）
2. **裸网络名自引用**（不含"pin"关键字，不匹配 `_LABEL_RE`）→ 静默跳过，不进 `unresolved`（这不是错误，只是这条label不代表一个具体引脚连接）
3. **含"pin"关键字但designator带`?`，或格式其他方式损坏**（调用方通过检测字符串中是否包含"pin"关键字来判断"看起来像是想表达引脚引用但解析失败"）→ 产出 `UnresolvedItem`，不写入`Net.members`

## 四、`import_block_semantic` 顶层逻辑

```python
from __future__ import annotations

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
                unresolved.append(UnresolvedItem(
                    field=f"component:{block_id}",
                    reason=f"组件缺少 designator 或 componentType 字段: {comp!r}",
                    page=page,
                ))
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
                        unresolved.append(UnresolvedItem(
                            field=f"net:{name}",
                            reason=f"无法解析连接标签: {label!r}",
                            page=page,
                        ))
                    continue
                designator, pin = parsed
                if designator not in components:
                    components[designator] = Component(id=designator, type="unknown", name=designator)
                members.append(f"{designator}:{pin}")
            nets.append(Net(name=name, members=members))

    ir = HardwareIR(components=list(components.values()), nets=nets, unresolved=unresolved)
    return ImportResult(ir=ir, unresolved=unresolved)
```

### 字段映射对照表

| block_semantic.json 字段 | IR 字段 | 处理规则 |
|---|---|---|
| `component.designator` | `Component.id` / `Component.name` | 原样存，二者取同一值（无独立型号字段可用） |
| `component.componentType` | `Component.type` | 原样存原文，不规范化 |
| `component.pinCount` | （无对应字段） | 本次丢弃，不新增IR字段 |
| `net.netNameLabel` | `Net.name` | 为空时生成占位名 `net_{blockId}_{序号:03d}` |
| `net.connectedLabels[i]`（解析成功） | `Net.members` 追加 `"{designator}:{pin}"` | 见上方解析规则 |
| `net.connectedLabels[i]`（括号引用/裸网络名） | 无 | 静默跳过 |
| `net.connectedLabels[i]`（含pin但解析失败） | `UnresolvedItem` | 不写入members |

### 容错策略

对输入dict结构本身的缺失容错（`dts_one`仍在快速迭代，字段完整性不能完全信任）：

- `data` 缺 `"blocks"` 键 → `.get("blocks", [])`，返回空IR，不报错
- `block` 缺 `"nets"`/`"components"` 键 → 同样 `.get(..., [])`
- `component` 缺 `"designator"`/`"componentType"` → 跳过该条，产出 `UnresolvedItem(field="component:{block_id}")`，不让局部脏数据崩溃整体转换
- `net` 缺 `"connectedLabels"` 键 → 视为空列表，net仍创建（`members=[]`）

## 五、Component 去重与补建

同一 `designator` 可能：
1. 在某个block的 `components` 列表里被显式列出（有 `componentType`）
2. 只在某个 `net.connectedLabels` 里被引用，从未出现在任何 `components` 列表（真实样本已验证存在此情况）

处理顺序：**先遍历所有block的`components`建立已知器件表，再遍历所有block的`nets`；解析出的designator如果不在已知器件表里，自动补建一个`type="unknown"`的最小Component**，保证 `Net.members` 引用的每个 `component_id` 在最终IR的 `components` 列表里都能找到。

## 六、测试策略与端到端验收用例

### 端到端验收用例（基于真实样本 `_pick_SOM6820_page006.block_semantic.json` 的 block_0003 简化）

```python
sample = {
    "blocks": [
        {
            "blockId": "block_0003",
            "nets": [
                {"netNameLabel": "PCIE4_REFCLK_100M+", "connectedLabels": ["PCIE4_REFCLK_100M+", "R3 pin 1", "R5 pin 1"]},
                {"netNameLabel": "CLKGEN_CLK3_100M+", "connectedLabels": ["R3 pin 2", "CLKGEN_CLK3_100M+ [13]"]},
            ],
            "components": [
                {"designator": "R3", "componentType": "resistor", "pinCount": 2},
                {"designator": "R5", "componentType": "resistor", "pinCount": 2},
            ],
        }
    ]
}
```

验证点：
1. `ir.components` 含 `R3`(type="resistor")、`R5`(type="resistor")，共2个
2. 第一个net：`name="PCIE4_REFCLK_100M+"`，`members == ["R3:1", "R5:1"]`（裸网络名自引用条目静默跳过）
3. 第二个net：`name="CLKGEN_CLK3_100M+"`，`members == ["R3:2"]`（`"CLKGEN_CLK3_100M+ [13]"`不含"pin"关键字，按裸网络名自引用处理，静默跳过，不进unresolved）
4. `ir.unresolved == []`

### 单元测试覆盖范围

**`parse_connected_label`**：
- 正例：`"R3 pin 1"` → `("R3", "1")`；`"SU1C pin G37"` → `("SU1C", "G37")`；无空格变体 `"R544 pin2"` → `("R544", "2")`
- 括号跨页引用返回None：`"[22]"`、`"[7,37,8]"`、`"[47-C4,47-D4]"`
- 裸网络名返回None：`"VDD_CX"`、`"GND"`
- 含不确定标记返回None：`"C? pin 1"`

**`import_block_semantic`**：
- 器件补建：`connectedLabels`引用的designator不在该block的`components`列表 → 自动补建`type="unknown"`的Component
- `netNameLabel`为null → 生成占位名，格式`net_{blockId}_{序号:03d}`（多个null的net序号递增不重复）
- 含"pin"关键字但解析失败（如`"C? pin 1"`）→ 产出对应`UnresolvedItem`，且该label不进入`Net.members`
- 缺失字段容错：`data`无`"blocks"`键、`net`无`"connectedLabels"`键、`component`缺`"designator"`键（后者产出UnresolvedItem，不崩溃）
- 多block合并：不同block各自的components/nets都能正确聚合进同一份`HardwareIR`

### 文件影响范围

新增（不修改任何现有文件）：
- `src/dts_gen/core/pipeline/semantic_import.py`
- `tests/core/pipeline/test_semantic_import.py`

## 七、后续任务（不在本次范围内）

- 接入 `extract_hardware_graph` 调用链路，让MCP工具真正消费 `import_block_semantic` 的转换结果
- Relation（语义关系）推断：基于网络命名规律（`+V*`/`VDD_*`→supply候选，`*_N`/`*EN*`→control候选）+ 器件类型联合判断，推不出就留空，不强行匹配
- `Component.type` 规范化：把自由文本（`"transistor (MOSFET, PJE138K SOT-523)"`）归类到受限词汇体系，或扩展受限词汇覆盖更多器件类型
- 多页/跨block合并逻辑：待`dts_one`完成跨页括号引用解析后，设计如何把多个`block_semantic.json`（多页）合并成一份完整的跨页HardwareIR
- 与`dts_one`的仓库整合方式（当前`pdf_schematic`代码存放位置——`core/pipeline/hardware_extractor/`内部子模块 vs 独立顶层包，此问题在本次讨论中被暂时搁置）
