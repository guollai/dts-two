# MCP Server 架构骨架设计

日期：2026-07-30

## 〇、背景与范围

本文档是对 `AI驱动的硬件原理图到设备树代码生成工具设计方案.md`（以下简称"总体方案"）中第 2.3 节"MCP Server 能力规划"的落地设计。总体方案已经确定了整体思路：确定性引擎 + AI 推理层 + 验证闭环，MCP 作为"AI 接入层"而非"业务内核"。

**本文档的范围**：只设计 MCP Server 的架构骨架——模块划分、任务状态机、8 个 Tool 的接口（输入/输出 schema）、Resources 与 Prompts 的注册方式、`core` 与 `mcp` 两层的边界与测试策略。

**不在本文档范围内**：每个 pipeline 阶段的具体算法实现（PDF 视觉识别、SoC 映射规则、DTS 生成规则引擎、dtc/dtbs_check 封装细节等）。这些将作为后续独立的设计任务逐个展开。本次骨架中，这些阶段的内部实现只是 stub（返回"未实现"占位结果），但接口签名和数据结构在本次就要定稳，避免后续填实现时反复调整骨架。

**技术选型**：Python 实现，MCP 传输方式采用 stdio（本地进程通信，适配 Claude Code/Claude Desktop 等本地 AI 客户端），业务内核（`core/`）设计上与传输方式无关，未来若需要升级到 HTTP/SSE 部署，只需新增一层 transport 适配，不需要改动 `core/` 和 Tool 的业务逻辑。

## 一、总体架构与模块划分

```
dts_gen/
  core/                     # 业务内核，不依赖MCP，可被CLI/测试/未来HTTP直接调用
    task.py                 # Task模型 + TaskStore(本地文件持久化)
    ir/
      models.py             # Component/Pin/Net/Relation/Bus/Supply/Control/Constraint/
                             # PinctrlGroup/SocMapping/UnresolvedItem/NodeSourceRef等pydantic模型
      store.py               # IR的序列化/反序列化(读写JSON)，挂在task目录下
    pipeline/
      base.py                # 各阶段Stage的公共接口约定(StageResult等)
      input_parser.py          # 对应 ingest_input
      hardware_extractor.py     # 对应 extract_hardware_graph
      soc_mapper.py             # 对应 identify_soc_mapping
      dts_generator.py          # 对应 generate_dts
      validator.py              # 对应 validate_dts
      repairer.py               # 对应 repair_dts
      differ.py                 # 对应 diff_dts
      explainer.py              # 对应 explain_node
    knowledge/                # Resources对应的知识库加载器
      soc_repo.py               # SoC参考dtsi/资源库
      binding_repo.py            # Device Tree binding yaml schema
      device_db.py               # 器件知识库(PMIC/PHY/Codec/桥接芯片 compatible模板)
      style_guide.py              # 命名规范/内部最佳实践
  mcp/
    server.py                 # MCP server入口，stdio transport
    tools.py                  # 8个Tool的MCP wrapper，负责协议层入参校验+调用core
    resources.py                # 注册Resources
    prompts.py                  # 注册Prompts
  cli.py                      # 可选：命令行直接调用core，用于测试/调试(不经过MCP)
```

**关键原则**：

- `mcp/tools.py` 中每个函数体量很薄——只做参数转换、调用 `core.pipeline.*`、把结果序列化回 MCP 响应格式。所有可测试的业务逻辑都在 `core/` 下，用普通 pytest 直接测，不需要起 MCP 进程。
- `core/` 下所有模块不 import 任何 `mcp` 相关包，保证可以脱离 MCP 协议独立导入和单元测试。`mcp/tools.py` 是唯一同时 import 两边的文件。
- Tool 之间通过 `task_id` 共享状态，而不是把整个 IR/DTS 在每次调用时来回传递——AI 客户端只需要记住一个 `task_id` 字符串，具体数据留在服务端文件系统里。

## 二、任务模型与状态机

### 2.1 用一个场景说明工作流程

以"工程师为新板卡生成 USB 相关 devicetree"为例：

1. AI 调用 `ingest_input("usb_schematic.pdf")` → 系统新建 `.dts-gen/tasks/task001/`，拷贝 PDF 进去，返回 `task_id = "task001"`。此时任务状态为 `created`，还没有任何识别结果。
2. AI 调用 `extract_hardware_graph(task_id="task001")` → 系统让 AI 识别原理图内容，把结果存为 `ir/v1.json`，任务状态变为 `extracted`。
3. AI 调用 `generate_dts(task_id="task001")` → 系统读取 `ir/v1.json`，生成 DTS 代码，存为 `dts/v1.dts`，任务状态变为 `generated`。
4. AI 调用 `validate_dts(task_id="task001")` → 系统读取 `dts/v1.dts` 跑 `dtc` 检查，生成报告文件，任务状态变为 `validated`。

**状态本质上就是"这个任务文件夹里的产出物做到第几步了"**，用来防止 AI 跳步骤调用（比如还没识别就想直接生成）。状态不代表"结果好不好"——哪怕第 4 步校验查出错误，任务仍然是 `validated`（代表"校验这一步已经跑完"），不会被标记为失败。只有工具执行本身抛出不可恢复异常（比如 PDF 完全打不开、识别不出任何内容）才会进入 `failed`。

### 2.2 状态机

```
created → extracted → mapped ─┐
              │                ├→ generated → validated ⟲ (repair_dts后仍为validated)
              └────(跳过mapped，见2.4)┘

任意阶段执行异常 → failed → (人工介入/重新ingest_input后可恢复到对应阶段)
```

（`parsing` 为瞬时态，不在图中单独列出，说明见下文。）

### 2.3 各状态下的任务字段取值

| 状态 | `ir_ref` | `dts_ref` | 触发该状态的 Tool | 可调用的下一个 Tool |
|---|---|---|---|---|
| `created` | `None` | `None` | `ingest_input` | `extract_hardware_graph` |
| `extracted` | `ir/v1.json` | `None` | `extract_hardware_graph` | `identify_soc_mapping` 或 `generate_dts`（见2.4） |
| `mapped` | `ir/v2.json` | `None` | `identify_soc_mapping` | `generate_dts` |
| `generated` | 最新 | `dts/v1.dts` | `generate_dts` | `validate_dts` |
| `validated` | 最新 | 最新（`repair_dts`后递增版本） | `validate_dts` / `repair_dts` | `repair_dts` / `diff_dts` / `explain_node` |
| `failed` | 失败前最后一次成功版本 | 同上 | 任意 Tool 执行异常 | `ingest_input`（追加输入后重试） |

关于 `parsing` 瞬时态：MCP Tool 调用在 stdio 传输下是同步阻塞的单次请求-响应，没有"进行中"轮询机制，所以 `parsing` 只在内存里短暂经过，不会被外部观察到，其存在意义仅是让 `history` 事件流完整。若未来引入异步长任务（原理图页数很多、AI 视觉调用很慢），需要真正可观察的中间态和轮询/回调机制，本次骨架不做，留作扩展点。

### 2.4 是否强制经过 `identify_soc_mapping`

`generate_dts` 的前置条件只要求 `ir_ref` 存在，不强制要求先经过 `mapped` 状态——如果 `extract_hardware_graph` 阶段已经能确定 SoC 型号信息，`identify_soc_mapping` 可能只是补充确认而非硬性阻塞项。但如果 IR 中存在未解析的 SoC 端点引用，`generate_dts` 应在结果里返回警告（而非报错），提示"建议先调用 identify_soc_mapping"。这样保留灵活性，同时不违反总体方案中"不虚构映射关系"的硬性原则。

### 2.5 版本化与回退

- 每次改动 IR/DTS 都追加新版本文件（`ir/v1.json`, `v2.json`...），`task.ir_ref`/`task.dts_ref` 始终指向最新版本，旧版本保留供 `diff_dts` 和 `explain_node` 回溯对比。
- `identify_soc_mapping`、`repair_dts` 等"修改而非新建"的操作，同样走新增版本而非覆盖，确保 `history` 里每条事件都能精确对应一个版本号。
- 重复调用同一个 Tool（如两次 `extract_hardware_graph`）视为"重新提取"，产生新版本，不覆盖旧版本。

### 2.6 TaskEvent 结构

```python
class TaskEvent(BaseModel):
    event_id: str
    tool: str                      # 触发本事件的Tool名，如 "generate_dts"
    timestamp: datetime
    input_summary: dict            # 调用参数摘要，不内嵌完整IR/DTS，避免task.json膨胀
    output_ref: str | None         # 指向产出的版本文件路径，如 "dts/v1.dts"
    status: Literal["ok", "warning", "error"]
    warnings: list[str]
    error: str | None
```

`explain_node` 的实现依据：遍历 `history`，找到最近一次改动了目标 node_path 相关 IR 字段的事件，从对应版本文件中取出 `source`（原理图页码、器件ID）和规则 ID——这也是为什么 IR 中每个端点都要求带 `confidence`/`source` 字段（见总体方案 3.1.2 节）。

### 2.7 并发、幂等与失败恢复

- 同一 `task_id` 不支持并发调用（stdio 场景下天然是单一 AI 客户端会话）。`TaskStore.save()` 采用整体读写模式，不做文件锁；若后续升级到 HTTP/SSE 多会话场景，加锁或换数据库的改动完全封装在 `core/task.py` 内部，不影响 Tool 接口。
- 进入 `failed` 后 `task_id` 不失效，工程师可针对同一任务重新调用出错的 Tool（如追加更清晰的原理图后重新 `ingest_input`），状态从 `failed` 回到对应阶段，不需要新建 task。失败记录始终保留在 `history` 中，不因后续成功而抹除。

## 三、8 个 Tool 的接口定义

统一规则：

- 所有输出都带 `task_id`。
- 改动 IR 或 DTS 的工具（`extract_hardware_graph`/`identify_soc_mapping`/`generate_dts`/`repair_dts`）都返回新的 `ir_ref`/`dts_ref` 版本号，从不覆盖旧文件。
- 出错时统一返回 `{"error": "...", "hint": "..."}` 格式，不裸抛异常给 AI 客户端；前置条件不满足时返回 `{"error": "precondition_failed", "missing": "...", "hint": "..."}`，便于 AI 自我纠正调用顺序。

### 3.1 `ingest_input`

导入原理图/图片/结构化数据，建立任务上下文。

```json
// 输入
{
  "files": [{"path": "usb_schematic.pdf", "type": "pdf"}],
  "project": "sa8775p-board-x",
  "soc": "sa8775p",
  "board": "board-x"
}
// 输出
{
  "task_id": "task001",
  "status": "created",
  "input_summary": [{"path": "usb_schematic.pdf", "pages": 24}]
}
```

### 3.2 `extract_hardware_graph`

抽取器件与连接图，产出 IR。

```json
// 输入
{"task_id": "task001", "page_range": [10, 15]}
// 输出
{
  "task_id": "task001",
  "status": "extracted",
  "ir_ref": "ir/v1.json",
  "summary": {"components": 5, "nets": 8, "relations": 6},
  "unresolved": [
    {"field": "redriver0.vcc-supply", "reason": "原理图上该引脚连线不清晰", "page": 12}
  ]
}
```

### 3.3 `identify_soc_mapping`

把 IR 中的抽象角色映射到 SoC 具体控制器实例。

```json
// 输入
{"task_id": "task001", "soc": "sa8775p"}
// 输出
{
  "task_id": "task001",
  "status": "mapped",
  "ir_ref": "ir/v2.json",
  "mapping_report": [
    {"role": "usb-controller", "mapped_to": "usb_0", "confidence": 0.95},
    {"role": "usb-phy", "mapped_to": "usb_0_qmpphy", "confidence": 0.88}
  ],
  "unresolved": []
}
```

### 3.4 `generate_dts`

生成 dts/dtsi 片段。

```json
// 输入
{"task_id": "task001", "scope": {"subsystem": "usb"}}
// 输出
{
  "task_id": "task001",
  "status": "generated",
  "dts_ref": "dts/v1.dts",
  "dts_text": "&usb_0 {\n  status = \"okay\";\n  ...\n};\n",
  "node_sources": [
    {"node": "&usb_0", "source_page": 12, "component_id": "soc_usb0", "rule_id": "usb-controller-enable"}
  ]
}
```

### 3.5 `validate_dts`

编译和 schema 校验。校验结果不影响任务状态（详见 2.1 节）。

```json
// 输入
{"task_id": "task001"}
// 输出
{
  "task_id": "task001",
  "status": "validated",
  "report_ref": "reports/validate_v1.json",
  "errors": [],
  "warnings": [{"message": "missing 'vbus-supply' property", "node": "&usb_0", "severity": "warning"}]
}
```

### 3.6 `repair_dts`

根据校验报告最小化修复。

```json
// 输入
{"task_id": "task001"}
// 输出
{
  "task_id": "task001",
  "status": "validated",
  "dts_ref": "dts/v2.dts",
  "applied_fixes": [{"node": "&usb_0", "change": "added vbus-supply = <&pmic_ldo3>;", "reason": "missing required property"}]
}
```

### 3.7 `diff_dts`

对比已有 DTS 与生成结果。

```json
// 输入
{"task_id": "task001", "existing_dts_path": "/path/to/current/board.dts"}
// 输出
{
  "task_id": "task001",
  "patch": "--- a/board.dts\n+++ b/board.dts\n...",
  "risk_notes": ["&usb_0 的 status 属性将被覆盖，请确认现有配置不是有意关闭"]
}
```

### 3.8 `explain_node`

解释单个 DTS 节点或属性的生成依据。

```json
// 输入
{"task_id": "task001", "node_path": "&usb_0"}
// 输出
{
  "task_id": "task001",
  "source_refs": [{"page": 12, "component_id": "soc_usb0"}],
  "rule_ids": ["usb-controller-enable"],
  "unresolved": []
}
```

## 四、Resources 与 Prompts

### 4.1 Resources

| Resource | URI 示例 | 内容 | 存储位置 |
|---|---|---|---|
| SoC 参考 dtsi | `soc://sa8775p/dtsi/main` | SoC 官方主 dtsi 文本 | `knowledge/data/socs/sa8775p/*.dtsi` |
| Device Tree binding | `binding://snps,dwc3` | 该 compatible 对应的 yaml schema | `knowledge/data/bindings/*.yaml` |
| 器件知识库 | `device://tusb2e11` | 型号→类型→compatible→属性模板 | `knowledge/data/devices/*.json` |
| 命名规范 | `styleguide://naming` | 节点命名、label 风格规则 | `knowledge/data/styleguide.md` |

本次骨架只在 `resources.py` 中注册这 4 类 URI scheme 的 list/read 接口，指向 `core/knowledge/*` 对应加载器方法。加载器内部数据目录本次为空，返回明确的"数据未填充"提示；具体数据填充（如 SA8775P 全套 dtsi/binding）是后续独立任务。

### 4.2 Prompts

| Prompt 名称 | 用途 |
|---|---|
| `schematic_understanding` | 引导 AI 在识别原理图时只输出结构化结果，禁止直接跳到写 DTS |
| `dts_generation` | 引导 AI 生成 DTS 时严格基于 IR 和 binding 资源，不可编造寄存器地址/中断号 |
| `error_repair` | 引导 AI 修复时只根据 `validate_dts` 报告做最小化修改，不动无关节点 |

本次只写模板文本骨架（含 `{ir_summary}`、`{validate_report}` 等占位变量），具体 prompt 措辞需要用真实原理图测试后迭代，属于后续任务。

## 五、`core` 与 `mcp` 的边界与测试策略

- **边界**：`core/` 不 import 任何 `mcp` 相关包，保证可脱离 MCP 协议独立导入和测试。`mcp/tools.py` 是唯一同时依赖两边的文件，职责仅为「取任务状态 → 调用 core 纯函数 → 存回新状态 → 记录事件 → 序列化响应」，不含业务判断。
- **测试策略**：
  - `core/` 下每个 pipeline stage、`TaskStore`、IR 模型都有对应 `tests/core/...` 单元测试，用 pytest 直接调用，不需要起 MCP server 进程。
  - `mcp/` 层只需少量集成测试，验证"Tool 调用 → 正确路由到 core 对应函数 → 响应格式符合 schema"。
  - 本次骨架阶段，pipeline stage 内部实现为 stub（返回空 IR 或 `{"status": "not_implemented"}`），对应测试先验证"接口调得通、数据结构对得上"，不验证真实识别准确率——真实算法实现和准确率验证留给后续任务。

## 六、后续任务（不在本次范围内）

- `input_parser`：PDF/图片解析（OCR、图元检测、多模态识别）具体实现
- `hardware_extractor`：原理图→IR 的视觉理解与结构化转换算法
- `soc_mapper`：SoC 实例映射规则库（SA8775P 等平台的控制器/PHY/GPIO 资源数据）
- `dts_generator`：模板库、规则引擎、pinctrl/pinmux 建模的具体规则
- `validator`/`repairer`：`dtc`/`dtbs_check` 调用封装、结构化错误解析、自动修复规则
- `knowledge/data/*`：SoC dtsi、binding schema、器件知识库、命名规范的实际数据填充
- Prompts 的具体措辞调优（需要真实原理图测试验证）
- 若未来需要多会话/长任务：HTTP/SSE transport 适配、异步任务轮询机制、`TaskStore` 并发控制
