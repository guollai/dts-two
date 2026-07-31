# USB 子系统 MVP：规则引擎 + 模板生成设计

日期：2026-07-31

## 〇、背景与范围

MCP Server 架构骨架（`docs/superpowers/specs/2026-07-30-mcp-server-architecture-design.md`）已经落地，8 个 Tool 均已定义接口，但 `dts_generator`/`validator`/`soc_mapper` 内部仍是"诚实 stub"（不产出任何真实数据）。

本文档设计**阶段 1：最小可用版本**（对应总体方案`AI驱动的硬件原理图到设备树代码生成工具设计方案.md`第四节）中的核心能力：把 `generate_dts` 从 stub 填成基于**规则引擎 + 结构化节点构建器**的真实实现，并给 `validate_dts` 加上不依赖外部工具的内部结构校验。范围聚焦单一子系统：USB。

**明确不做的事**（后续独立任务）：
- 不接入任何 Hamoa（或其他真实 SoC）平台资料。`identify_soc_mapping` 继续保持 stub（直通不变），`generate_dts` 直接使用 IR 里的 `component.id` 作为 DTS 节点标签，不做真实 SoC 实例映射。
- 不做 PDF/原理图视觉识别（`hardware_extractor` 不在本次范围）。输入形式是结构化 IR JSON（通过测试直接构造，或未来由其他工具产出）。
- 不依赖 `dtc`/`dtbs_check` 二进制工具或真实 binding yaml schema 库。`validate_dts` 只做"生成文本内部一致性"级别的结构校验；若运行环境检测到 `dtc` 存在，则额外调用之做语法校验，不存在则跳过并给出提示（不阻塞）。
- `repair_dts`、`soc_mapper` 的真实实现不在本次范围。

**参考基础**：规则引擎和模板设计基于 Linux 内核 devicetree-bindings 规范（USB 子系统常见属性：`vbus-supply`、`enable-gpios`、`reset-gpios`、`phys`）与社区典型 dtsi 写法，不依赖任何厂商私有资料。

## 一、整体架构与数据流

```
IR (JSON, 手工/测试构造，覆盖5类component + 3类relation)
  → soc_mapper (仍是stub，直通不变)
  → dts_generator (本次核心工作)
       ├─ build_nodes(ir): 规则引擎(RULES字典) 逐条relation派发 → 填充DtsNode.properties (+unresolved)
       ├─ serialize_dts(nodes): 序列化器，跳过无属性节点
       └─ build_node_sources(nodes): 从DtsNode.properties提取rule_id/component_id
  → validator (本次核心工作)
       └─ 三条内部结构校验：phandle引用存在性 / 属性值语法形式 / 重复label检测
          (若检测到本机有dtc，额外跑一次dtc语法校验；没有则跳过+提示)
```

**关键原则（延续骨架阶段）**：
- 规则引擎是纯确定性代码（无 AI 参与），查不到就进 `unresolved`，绝不猜测/编造属性值、GPIO 编号、compatible 字符串。
- 生成/校验相关改动集中在已有文件内部（`dts_generator.py`、`validator.py`、`tools.py`）；规范同步机制（第五节）新增独立模块 `core/knowledge/spec_sync/`，因为它是与生成/校验流程无关的独立能力。

## 二、IR 输入契约

本次规则引擎只认识以下 5 类 `component.type` 和 3 类 `relation.kind`；其余类型的 component 会被忽略（不生成节点、不报错），其余 kind 的 relation 进入 `unresolved`。

### 2.1 五类 Component

| type | 示例 id | 说明 |
|---|---|---|
| `usb-controller` | `usb_ctrl0` | dwc3 类控制器 |
| `usb-phy` | `usb_phy0` | PHY |
| `usb-redriver` | `redriver0` | redriver/repeater |
| `usb-connector` | `connector0` | Type-C connector |
| `regulator` | `pmic_ldo3` | VBUS 供电 |

### 2.2 三类 Relation

**`kind="supply"`** — 供电关系
```json
{"kind": "supply", "from": "pmic_ldo3", "to": "usb_ctrl0", "property": "vbus-supply"}
```
规则：在 `to` 节点上生成 `{property} = <&{from}>;`。`property` 必须由 IR 显式提供，规则引擎不猜测属性名。缺少 `property` 或 `from` → `unresolved`。

**`kind="control"`** — GPIO 控制关系（enable/reset）
```json
{"kind": "control", "from": "soc_tlmm:gpio23", "to": "redriver0", "property": "enable-gpios", "active": "high"}
```
规则：仅认识 `property` 为 `enable-gpios` 或 `reset-gpios`；`from` 必须匹配 `^(\w+):gpio(\d+)$`（如 `soc_tlmm:gpio23`）；`active` 为 `"high"`/`"low"`，映射为 `GPIO_ACTIVE_HIGH`/`GPIO_ACTIVE_LOW`。生成 `{property} = <&{controller} {pin} {flag}>;`。任一条件不满足 → `unresolved`。

**`kind="phy-reference"`** — PHY 引用关系
```json
{"kind": "phy-reference", "from": "redriver0", "to": "usb_phy0"}
```
规则：在 `from` 节点上生成固定属性名 `phys = <&{to}>;`（属性名 `"phys"` 由规则引擎硬编码，因为这是 DTS 里 PHY 引用的标准属性名，不依赖 IR 提供）。`to` 在 `components` 中找不到 → `unresolved`。

### 2.3 无法匹配 → `UnresolvedItem`

以下情况产出 `UnresolvedItem(field=..., reason=...)`，不中断整体生成流程：
- `relation.to`（或 `phy-reference` 的 `from`）在 `components` 里找不到对应 id
- `control` 的 `property` 不是 `enable-gpios`/`reset-gpios`，或 `active` 不是 `"high"`/`"low"`，或 `from` 不满足 `xxx:gpioN` 格式
- `supply` 缺少 `property` 或 `from` 字段
- `relation.kind` 不属于上述三类

若 IR 的 `relations` 为空，或所有 relation 均解析失败：`generate_dts` 仍正常返回 `status="generated"`，`dts_text` 为空字符串，`unresolved` 列出具体原因——不视为错误，不阻塞流程。

## 三、`dts_generator.py` 内部设计（方案 C：规则引擎 + 结构化节点构建器）

### 3.1 数据结构

```python
@dataclass
class DtsProperty:
    name: str            # "vbus-supply"
    value: str           # "<&pmic_ldo3>"  （已经是DTS语法里的字面值）
    rule_id: str         # 规则函数名，用于node_sources追溯
    source_relation: Relation | None = None

@dataclass
class DtsNode:
    label: str                          # 直接用component.id（本次soc_mapper是stub，无真实平台label）
    properties: list[DtsProperty] = field(default_factory=list)
    component_id: str | None = None

    def add_property(self, name: str, value: str, rule_id: str, relation: Relation | None = None):
        self.properties.append(DtsProperty(name, value, rule_id, relation))
```

规则引擎不直接吐字符串，而是往 `DtsNode.properties` 追加结构化 `DtsProperty`，每条自带 `rule_id`。序列化成文本是最后一步，与"决定属性值该是什么"完全分开。

### 3.2 规则引擎——模块级常量字典，不引入注册机制

```python
RuleFn = Callable[[Relation, HardwareIR], tuple[str, str] | None]
# 返回 (property_name, property_value)；查不到返回None（不猜测）

def rule_supply(rel: Relation, ir: HardwareIR) -> tuple[str, str] | None:
    if rel.property is None or rel.from_ is None:
        return None
    return (rel.property, f"<&{rel.from_}>")

GPIO_ENDPOINT_RE = re.compile(r"^(\w+):gpio(\d+)$")

def parse_gpio_endpoint(endpoint: str | None) -> tuple[str, int] | None:
    if endpoint is None:
        return None
    m = GPIO_ENDPOINT_RE.match(endpoint)
    if not m:
        return None
    return (m.group(1), int(m.group(2)))

def rule_control_gpio(rel: Relation, ir: HardwareIR) -> tuple[str, str] | None:
    if rel.property not in ("enable-gpios", "reset-gpios"):
        return None
    if rel.active not in ("high", "low"):
        return None
    gpio_ref = parse_gpio_endpoint(rel.from_)   # "soc_tlmm:gpio23" -> ("soc_tlmm", 23)
    if gpio_ref is None:
        return None
    controller, pin = gpio_ref
    flag = "GPIO_ACTIVE_HIGH" if rel.active == "high" else "GPIO_ACTIVE_LOW"
    return (rel.property, f"<&{controller} {pin} {flag}>")

def rule_phy_reference(rel: Relation, ir: HardwareIR) -> tuple[str, str] | None:
    if rel.kind != "phy-reference":
        return None
    return ("phys", f"<&{rel.to}>")

RULES: dict[str, list[RuleFn]] = {
    "supply": [rule_supply],
    "control": [rule_control_gpio],
    "phy-reference": [rule_phy_reference],
}
```

`list[RuleFn]`（而非单函数）为同一 `kind` 未来叠加多条规则判断留出空间，本次每个 kind 只填一个函数。RULES 是模块级常量字典，不引入插件/装饰器注册机制。

### 3.3 节点构建器

```python
def build_nodes(ir: HardwareIR) -> tuple[list[DtsNode], list[UnresolvedItem]]:
    nodes: dict[str, DtsNode] = {
        comp.id: DtsNode(label=comp.id, component_id=comp.id) for comp in ir.components
    }
    unresolved: list[UnresolvedItem] = []

    for rel in ir.relations:
        target_id = rel.from_ if rel.kind == "phy-reference" else rel.to
        target_node = nodes.get(target_id)
        if target_node is None:
            unresolved.append(UnresolvedItem(
                field=f"relation:{rel.kind}",
                reason=f"目标节点 {target_id} 不存在于 components 中",
            ))
            continue

        matched = False
        for rule_fn in RULES.get(rel.kind, []):
            result = rule_fn(rel, ir)
            if result:
                prop_name, prop_value = result
                target_node.add_property(prop_name, prop_value, rule_id=rule_fn.__name__, relation=rel)
                matched = True
                break
        if not matched:
            unresolved.append(UnresolvedItem(
                field=f"relation:{rel.kind}:{rel.property}",
                reason="没有匹配的规则，或缺少必要字段",
            ))

    return list(nodes.values()), unresolved
```

### 3.4 序列化器——唯一负责文本格式的地方

```python
def serialize_node(node: DtsNode, indent: str = "    ") -> str:
    lines = [f"&{node.label} {{", f'{indent}status = "okay";']
    for prop in node.properties:
        lines.append(f"{indent}{prop.name} = {prop.value};")
    lines.append("};")
    return "\n".join(lines)

def serialize_dts(nodes: list[DtsNode]) -> str:
    return "\n\n".join(serialize_node(n) for n in nodes if n.properties)
    # 没有任何属性的节点不单独输出（如pmic_ldo3只是被引用的目标，本身无relation把它当to/from填属性）
```

### 3.5 `node_sources` 构建

```python
def build_node_sources(nodes: list[DtsNode]) -> list[NodeSourceRef]:
    return [
        NodeSourceRef(node=f"&{node.label}", component_id=node.component_id, rule_id=prop.rule_id)
        for node in nodes for prop in node.properties
    ]
```

因规则引擎往 `DtsNode` 贴属性时已记录 `rule_id`，此步骤只是遍历导出，无需额外维护并行追溯表。

### 3.6 `generate_dts` 顶层组装

```python
class GenerateResult(BaseModel):
    dts_text: str = ""
    node_sources: list[NodeSourceRef] = Field(default_factory=list)
    unresolved: list[UnresolvedItem] = Field(default_factory=list)   # 本次新增字段

def generate_dts(ir: HardwareIR, board: str | None, scope: GenerationScope) -> GenerateResult:
    nodes, unresolved = build_nodes(ir)
    dts_text = serialize_dts(nodes)
    node_sources = build_node_sources(nodes)
    return GenerateResult(dts_text=dts_text, node_sources=node_sources, unresolved=unresolved)
```

`GenerationScope.subsystem` 字段本次仅预留接口，不实际过滤任何节点（因为本次 IR 输入本身就只含 USB 子系统数据，过滤逻辑留给后续多子系统共存时再做）。

### 3.7 MCP 工具层改动（`mcp_app/tools.py`）

`generate_dts` 工具函数的返回字典新增 `unresolved` 字段（`[item.model_dump() for item in result.unresolved]`），与 `extract_hardware_graph`/`identify_soc_mapping` 保持一致风格。这些 `unresolved` 项**不**合并写回 IR 文件——它们是"生成阶段发现的"，不是 IR 本身的问题，`explain_node` 本次不负责查找这类 unresolved。

## 四、`validator.py` 内部设计——三条内部结构校验

无真实 `dtc`/binding yaml 数据可用，只能做"生成文本内部是否自相一致"级别的语法检查，不做 schema 校验或平台规则校验（这两层在设计方案中明确依赖外部知识库，留给后续任务）。

### 4.1 检查 1：phandle 引用存在性

```python
def find_defined_labels(text: str) -> set[str]:
    return set(re.findall(r"&(\w+)\s*\{", text))

def find_referenced_labels(text: str) -> set[str]:
    return set(re.findall(r"<\s*&(\w+)", text))

def check_undefined_references(text: str) -> list[DtsError]:
    defined = find_defined_labels(text)
    referenced = find_referenced_labels(text)
    return [
        DtsError(message=f"引用的节点 &{label} 未定义", node=None, severity="error")
        for label in sorted(referenced - defined)
    ]
```

### 4.2 检查 2：属性值语法形式

```python
PROP_LINE = re.compile(r'^\s*([\w,-]+)\s*=\s*(.+);\s*$')

def check_property_syntax(text: str) -> list[DtsError]:
    errors = []
    for line in text.splitlines():
        m = PROP_LINE.match(line)
        if not m:
            continue
        prop_name, value = m.groups()
        value = value.strip()
        if value.startswith("&") and not (value.startswith("<") and value.endswith(">")):
            errors.append(DtsError(message=f"属性 {prop_name} 的引用值 {value} 缺少 <...> 包裹", severity="error"))
        elif value in ("okay", "disabled"):
            errors.append(DtsError(message=f"属性 {prop_name} 的值 {value} 应为带引号字符串", severity="error"))
    return errors
```

范围有限：只覆盖"引用漏 `<>`"和"status 常见值漏引号"两种规则引擎自身可能犯的错，不是通用 DTS 语法解析器。

### 4.3 检查 3：重复 label 检测

```python
def check_duplicate_labels(text: str) -> list[DtsError]:
    labels = re.findall(r"&(\w+)\s*\{", text)
    counts = Counter(labels)
    return [
        DtsError(message=f"节点 &{label} 被重复定义 {count} 次", severity="error")
        for label, count in counts.items() if count > 1
    ]
```

### 4.4 组装与 dtc 可选叠加

```python
def validate_dts(dts_text: str, target_platform: str | None = None) -> ValidateResult:
    errors = []
    errors += check_undefined_references(dts_text)
    errors += check_property_syntax(dts_text)
    errors += check_duplicate_labels(dts_text)

    warnings = []
    if shutil.which("dtc") is None:
        warnings.append(DtsError(message="dtc 未安装，跳过语法级编译校验", severity="warning"))
    else:
        errors += run_dtc_check(dts_text)

    return ValidateResult(errors=errors, warnings=warnings)


def run_dtc_check(dts_text: str) -> list[DtsError]:
    """Invoke the local dtc binary as a subprocess to compile dts_text and
    parse stderr into DtsError entries. Only called when shutil.which("dtc")
    already confirmed the binary exists.
    """
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

若 `dts_text` 为空字符串（IR 无可用 relation 时的合法结果），三条检查均自然返回空列表，不报错。

## 五、规范/Binding 同步机制

### 5.1 为什么需要，以及能做到什么程度

`dts_generator.py` 里的三条规则（`rule_supply`/`rule_control_gpio`/`rule_phy_reference`）是把 Linux 内核 binding 文档（`regulator.yaml`/`gpio.txt`/`phy-bindings.txt`）和 devicetree-specification 通用规范里规定的属性名/格式**手工翻译**成的确定性代码，本质上是"抄文档"。这些文档会随时间演进，需要一个机制提醒人工"源文档变了，去看看规则是否需要跟进"。

**如实说明能力边界**：本次采用"版本化缓存 + 全文 diff"，而非"关键字段名比对"（后者对断崖式改名/删除的抓取率约60-70%，但对"属性语义变了但名字没变"这类更常见的情况基本抓不到）。全文 diff 不需要预先声明"哪些字段值得关注"，能覆盖任意文本改动，但代价是需要人工阅读 diff 过滤噪音（无关措辞改动也会出现在 diff 里）。**这是一个提醒人去复核的早期预警机制，不做自动代码生成，不做通过/失败判定**——决策权始终在人。

### 5.2 追踪的文件与来源

**内核 binding（3个，静态列表）**：

| 文件 | 拉取源 | 关联规则 |
|---|---|---|
| `regulator.yaml` | `raw.githubusercontent.com/torvalds/linux/master/Documentation/devicetree/bindings/regulator/regulator.yaml` | `rule_supply` |
| `gpio.txt` | 内核 `Documentation/devicetree/bindings/gpio/gpio.txt` | `rule_control_gpio` |
| `phy-bindings.txt` | 内核 `Documentation/devicetree/bindings/phy/phy-bindings.txt` | `rule_phy_reference` |

**devicetree-specification（动态发现，非固定文件名）**：三条规则共同依赖的基础语法（属性值格式、phandle 引用写法）来自 `github.com/devicetree-org/devicetree-specification` 仓库的 `source/` 目录。该目录混杂 `.rst` 文本、图片、`conf.py` 等非文本资源，且内容按章节拆分成多个文件（截至设计时为 `acknowledgements.rst`/`chapter1-introduction.rst`/`chapter2-devicetree-basics.rst`/`chapter3-devicenodes.rst`/`chapter4-device-bindings.rst`/`chapter5-flattened-format.rst`/`chapter6-source-language.rst`/`index.rst`/`license.rst`/`references.rst`/`revhistory.rst`，另有一个 `extensions/` 子目录**不追踪**）。

追踪范围：**通过 GitHub Contents API 列出 `source/` 根目录，动态筛选出所有 `.rst` 结尾的文件名**，不递归进子目录，不硬编码文件名列表——因为章节文件将来可能增减，硬编码列表会静默漏掉新章节。

### 5.3 模块结构（新增 `core/knowledge/spec_sync/`）

```
core/knowledge/spec_sync/
  __init__.py
  fetcher.py        # fetch(url) -> str，用requests.get()发HTTP请求，超时/非200抛FetchError
                     # list_rst_files(api_url) -> list[TrackedFile]，调用GitHub Contents API，
                     #   筛选type=="file"且name以".rst"结尾的条目，取其download_url
  cache.py           # rotate_and_write(cache_dir, filename, new_text) -> None
                      # read_cached(cache_dir, filename, slot) -> str | None  (slot: "latest"|"previous")
                      # write_sync_meta(...)
  diff_report.py     # DiffReport(BaseModel): filename, diff: str | None, has_changes: bool,
                      #                        first_sync: bool, fetch_error: str | None
                      # build_diff_report(old_text, new_text, filename) -> DiffReport
  sync.py            # KERNEL_BINDING_FILES常量列表(3个) + DT_SPEC_CONTENTS_API_URL常量
                      # sync_bindings(cache_dir) -> list[DiffReport]
                      # 顶层协调函数：先调用list_rst_files()动态发现devicetree-specification文件，
                      # 与3个内核binding文件合并成本次要同步的完整列表，逐文件隔离失败
```

### 5.4 缓存目录结构

```
knowledge/data/dt_spec/
  regulator.yaml.previous
  regulator.yaml.latest
  gpio.txt.previous
  gpio.txt.latest
  phy-bindings.txt.previous
  phy-bindings.txt.latest
  chapter1-introduction.rst.previous
  chapter1-introduction.rst.latest
  ...（devicetree-specification各章节.rst文件，按动态发现结果生成，数量不固定）
  sync_meta.json    # {"<filename>": {"synced_at": "...", "source_url": "..."}}
```

### 5.5 核心函数签名与行为

```python
@dataclass
class TrackedFile:
    filename: str
    source_url: str

KERNEL_BINDING_FILES: list[TrackedFile] = [
    TrackedFile("regulator.yaml", "https://raw.githubusercontent.com/torvalds/linux/master/Documentation/devicetree/bindings/regulator/regulator.yaml"),
    TrackedFile("gpio.txt", "https://raw.githubusercontent.com/torvalds/linux/master/Documentation/devicetree/bindings/gpio/gpio.txt"),
    TrackedFile("phy-bindings.txt", "https://raw.githubusercontent.com/torvalds/linux/master/Documentation/devicetree/bindings/phy/phy-bindings.txt"),
]

DT_SPEC_CONTENTS_API_URL = "https://api.github.com/repos/devicetree-org/devicetree-specification/contents/source"


def list_rst_files(api_url: str) -> list[TrackedFile]:
    response = requests.get(api_url, timeout=10)
    response.raise_for_status()
    entries = response.json()
    return [
        TrackedFile(filename=entry["name"], source_url=entry["download_url"])
        for entry in entries
        if entry["type"] == "file" and entry["name"].endswith(".rst")
    ]


class DiffReport(BaseModel):
    filename: str
    diff: str | None = None
    has_changes: bool = False
    first_sync: bool = False
    fetch_error: str | None = None


def sync_bindings(cache_dir: Path) -> list[DiffReport]:
    try:
        dt_spec_files = list_rst_files(DT_SPEC_CONTENTS_API_URL)
    except FetchError as exc:
        # 目录列举失败：整体退化为只同步3个内核binding文件，额外追加一条标记该失败的DiffReport
        dt_spec_files = []
        directory_error = DiffReport(filename="devicetree-specification/source", fetch_error=str(exc))
    else:
        directory_error = None

    reports = []
    for entry in KERNEL_BINDING_FILES + dt_spec_files:
        try:
            new_text = fetch(entry.source_url)
        except FetchError as exc:
            reports.append(DiffReport(filename=entry.filename, fetch_error=str(exc)))
            continue   # 单文件隔离失败：本条报错，其余文件照常同步

        old_text = read_cached(cache_dir, entry.filename, "latest")
        rotate_and_write(cache_dir, entry.filename, new_text)
        write_sync_meta(cache_dir, entry.filename, source_url=entry.source_url)

        reports.append(build_diff_report(old_text, new_text, entry.filename))

    if directory_error is not None:
        reports.append(directory_error)
    return reports


def build_diff_report(old_text: str | None, new_text: str, filename: str) -> DiffReport:
    if old_text is None:
        return DiffReport(filename=filename, first_sync=True)
    diff_text = "\n".join(difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(),
        fromfile=f"{filename} (previous)", tofile=f"{filename} (latest)",
    ))
    return DiffReport(filename=filename, diff=diff_text or None, has_changes=bool(diff_text))
```

**单文件隔离失败**：任一文件 HTTP 请求失败只影响该条（`DiffReport.fetch_error` 非空），其余文件照常同步。**目录列举失败**（`list_rst_files` 本身失败，如 GitHub API 限流）：devicetree-specification 部分整体跳过，仅同步 3 个内核 binding 文件，并追加一条标记目录列举失败的 `DiffReport`。命令/Tool 整体仍返回成功（只要至少有一部分成功），调用方通过遍历 `reports` 里的 `fetch_error` 字段获知哪些失败。

### 5.6 暴露方式：CLI 命令 + MCP Tool（第 9 个 Tool）

**CLI**：`src/dts_gen/cli.py` 新增 `sync-bindings` 子命令，调用 `sync_bindings(cache_dir)`，逐文件打印 diff（或"无变化"/"首次同步"/"拉取失败: ..."）。

**MCP Tool**：新增第 9 个 Tool `sync_bindings`，**不带 `task_id`**（因为这个能力不属于任何任务流程，是独立的运维/知识库维护操作，与 8 个任务流程 Tool 的 task_id 约束无关）：

```json
// 输入
{}
// 输出
{
  "reports": [
    {"filename": "regulator.yaml", "diff": "--- regulator.yaml (previous)\n+++ ...", "has_changes": true, "first_sync": false, "fetch_error": null},
    {"filename": "chapter4-device-bindings.rst", "diff": null, "has_changes": false, "first_sync": true, "fetch_error": null}
  ]
}
```

CLI 和 MCP Tool 共享同一个 `sync_bindings()` core 函数，Tool 侧只是薄封装（符合骨架阶段确立的 core/mcp_app 边界原则）。

### 5.7 新增依赖

`pyproject.toml` 新增 `requests>=2.31,<3.0` 依赖，用于 HTTP 拉取（替代标准库 `urllib`，代码更简洁，且能绕开本机 Windows Schannel 证书吊销校验导致的 `curl`/`urllib` 连接失败问题——已在本机验证 `requests` 可正常访问 GitHub，`curl`/纯 TLS 握手会因 `CRYPT_E_NO_REVOCATION_CHECK` 失败）。

## 六、测试策略与端到端验收用例

### 6.1 端到端验收用例（对应总体方案 3.6 节示例）

IR 输入：
```json
{
  "board": "hamoa-evb", "soc": "hamoa",
  "components": [
    {"id": "usb_ctrl0", "type": "usb-controller", "name": "dwc3"},
    {"id": "usb_phy0", "type": "usb-phy", "name": "qcom-usb3-phy"},
    {"id": "redriver0", "type": "usb-redriver", "name": "tusb2e11"},
    {"id": "connector0", "type": "usb-connector", "name": "typec"},
    {"id": "pmic_ldo3", "type": "regulator", "name": "ldo3"}
  ],
  "relations": [
    {"kind": "supply", "from": "pmic_ldo3", "to": "usb_ctrl0", "property": "vbus-supply"},
    {"kind": "control", "from": "soc_tlmm:gpio23", "to": "redriver0", "property": "enable-gpios", "active": "high"},
    {"kind": "phy-reference", "from": "usb_ctrl0", "to": "usb_phy0"}
  ]
}
```

验证点：
1. `generate_dts` → `dts_text` 含 `&usb_ctrl0`（带 `vbus-supply` + `phys`）和 `&redriver0`（带 `enable-gpios`），**不含** `&usb_phy0`/`&connector0`/`&pmic_ldo3`（无属性节点不输出）
2. `node_sources` 长度为 3，每条含正确 `rule_id`/`component_id`
3. `validate_dts` 对该输出运行三条校验 → 0 errors
4. `unresolved` 为空列表

### 6.2 单元测试覆盖范围

- **规则函数**：`rule_supply`/`rule_control_gpio`/`rule_phy_reference` 各自的正例 + 反例（如 `control` 的 `from` 格式错误 → 返回 `None`）
- **`build_nodes`**：relation 目标节点不存在 → 产出对应 `UnresolvedItem`；relations 为空 → 返回全部无属性节点、`unresolved` 为空
- **`serialize_dts`**：无属性节点被跳过；多节点间以空行分隔
- **`validator.py` 三个检查函数**：各自的正例（无错误）+ 反例（手工构造含未定义引用/漏引号/重复 label 的 DTS 文本）单元测试
- **`tools.py`**：`generate_dts` 工具函数输出新增 `unresolved` 字段的序列化正确性
- **`spec_sync` 模块**（真实网络，不 mock；本机已验证 `requests` 库可正常访问 `raw.githubusercontent.com`/`api.github.com`，即使 `curl`/裸 TLS 因 Windows Schannel 证书吊销校验失败也不受影响）：
  - `fetcher.fetch()`：对 3 个内核 binding 真实 URL 发起真实 HTTP GET，验证返回内容非空且状态码 200
  - `fetcher.list_rst_files()`：真实调用 GitHub Contents API 拉取 `devicetree-specification` 的 `source/` 目录列表，验证返回的文件名全部以 `.rst` 结尾、且不包含 `extensions/` 子目录内容
  - `cache.rotate_and_write()`/`read_cached()`：用真实临时目录（`tmp_path` fixture）验证 latest→previous 轮换和读取，不需要网络
  - `diff_report.build_diff_report()`：用手写字符串构造新旧文本验证 diff 生成正确性，不需要网络
  - `sync.sync_bindings()`：集成测试，真实拉取 3 个内核 binding 文件 + 动态发现的全部 devicetree-specification `.rst` 文件到临时目录，验证首次同步 `first_sync=True`，第二次同步（文本不变）`has_changes=False`
  - 单文件隔离失败：构造一个含无效 URL 的 `TrackedFile` 验证 `fetch_error` 被正确捕获、不影响其他文件
  - 目录列举失败：用无效的 Contents API URL 验证 `sync_bindings` 仍能同步 3 个内核 binding 文件，并追加一条目录列举失败的 `DiffReport`

### 6.3 文件影响范围

本次不新增顶层文件（`dts_generator.py`/`validator.py`/`tools.py`/`cli.py` 均为已有文件的内部改动），但新增一个模块目录：
- `src/dts_gen/core/pipeline/dts_generator.py`（新增 `DtsNode`/`DtsProperty`/`RULES`/`build_nodes`/`serialize_dts`/`build_node_sources`；`GenerateResult` 新增 `unresolved` 字段）
- `src/dts_gen/core/pipeline/validator.py`（新增三个检查函数及组装逻辑）
- `src/dts_gen/mcp_app/tools.py`（`generate_dts` 工具函数输出新增 `unresolved` 字段；新增 `sync_bindings` 工具函数）
- `src/dts_gen/mcp_app/server.py`（注册第 9 个 Tool `sync_bindings`）
- `src/dts_gen/cli.py`（新增 `sync-bindings` 子命令）
- 新增 `src/dts_gen/core/knowledge/spec_sync/`（`__init__.py`/`fetcher.py`/`cache.py`/`diff_report.py`/`sync.py`）
- `pyproject.toml`（新增 `requests` 依赖）
- 对应测试文件：`tests/core/pipeline/test_dts_generator.py`、`tests/core/pipeline/test_validator.py`、`tests/mcp_app/test_tools.py`、新增 `tests/core/knowledge/spec_sync/test_fetcher.py`、`test_cache.py`、`test_diff_report.py`、`test_sync.py`

## 七、后续任务（不在本次范围内）

- `identify_soc_mapping` 真实实现：接入真实 Hamoa（或其他平台）SoC 资源库，把 `component.id` 映射为真实平台 label（如 `usb_0`）
- `hardware_extractor`：原理图/PDF 视觉识别
- `validator` 的 schema 校验层（真实 binding yaml 数据）与平台规则校验层
- `repair_dts` 真实实现
- 规则引擎扩展到 PCIe/I2C/SPI/音频/显示/PMIC 等其他子系统
- 若需要真实 `dtc` 校验，环境需另行安装（如 `conda install -c conda-forge dtc`），代码已预留检测接口
- 同步机制目前只做全文 diff 呈现给人工，未来可考虑更细粒度的语义级 diff（如按 YAML 字段结构化比对）以降低阅读噪音
- 同步的"定期"触发目前仅提供手动/外部调度入口（CLI/Tool），实际定时调度（cron/CI）配置留给部署方自行决定
