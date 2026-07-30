# MCP Server 架构骨架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 `dts-gen` 项目的 MCP Server 架构骨架——一个可以被 Claude Code/Claude Desktop 等本地 AI 客户端通过 stdio 调用的 MCP 服务，暴露 8 个 Tool、4 个 Resource、3 个 Prompt，内部业务逻辑（`core/`）与协议层（`mcp/`）分离，pipeline 各阶段先以 stub 形式跑通全链路。

**Architecture:** `core/` 是不依赖 MCP SDK 的纯 Python 业务内核（任务状态机、IR 数据模型、8 个 pipeline stage 的接口与 stub 实现、知识库加载器），`mcp/` 是薄的协议适配层，把 MCP Tool/Resource/Prompt 调用路由到 `core/` 对应函数并序列化响应。任务状态持久化为本地 JSON 文件（`.dts-gen/tasks/<task_id>/`），不使用数据库。

**Tech Stack:** Python 3.13（要求 `>=3.10`），`pydantic>=2.0,<3.0`（已安装 2.13.2），`mcp>=2.0,<3.0`（官方 MCP Python SDK，`mcp.server.mcpserver.MCPServer`），`PyYAML>=6.0,<7.0`，`pypdf>=6.0,<7.0`，`pytest>=8.0,<9.0`。

## Global Constraints

- Python 版本下限：`>=3.10`（对应 `docs/superpowers/specs/2026-07-30-mcp-server-architecture-design.md` 技术选型：Python 实现）。
- MCP 传输方式：仅 stdio，不实现 HTTP/SSE（spec 〇节：本次范围排除 transport 扩展）。
- `core/` 目录下任何模块禁止 `import mcp` 或从 `mcp.*` 导入任何符号（spec 五节：core 与 mcp 边界）。
- 所有 Tool 输出必须包含 `task_id` 字段；改动 IR/DTS 的 Tool 必须返回新版本号，不覆盖旧文件（spec 三节：统一规则）。
- 出错必须返回结构化 `{"error": "...", "hint": "..."}`，前置条件不满足时返回 `{"error": "precondition_failed", "missing": "...", "hint": "..."}`，禁止裸抛异常给 MCP 客户端（spec 三节：统一规则）。
- pipeline 各阶段（`input_parser`/`hardware_extractor`/`soc_mapper`/`dts_generator`/`validator`/`repairer`/`differ`/`explainer`）本次只实现接口与 stub，不实现真实算法（spec 〇节：不在本文档范围内）。
- `validate_dts` 查出的 `errors`/`warnings` 不代表任务失败，任务状态仍为 `validated`；只有 Tool 执行本身抛出不可恢复异常才进入 `failed`（spec 2.1/2.3 节）。
- IR 端点字段须包含 `confidence` 和 `source`（spec 2.6 节：`explain_node` 依赖这两个字段做溯源）。

---

## File Structure

```
pyproject.toml                          # 新建：项目元数据、依赖、pytest配置
src/dts_gen/
  __init__.py
  core/
    __init__.py
    task.py                             # Task、TaskStatus、TaskEvent、TaskInput模型 + TaskStore
    ir/
      __init__.py
      models.py                        # Component/Pin/Net/Relation/Endpoint/PinctrlGroup/
                                        # SocMappingEntry/UnresolvedItem/NodeSourceRef/HardwareIR
      store.py                          # IrStore：IR版本的读写(ir/vN.json)
    pipeline/
      __init__.py
      base.py                          # StageResult基类、DtsError、FixNote等公共类型
      input_parser.py                   # parse_input() stub
      hardware_extractor.py             # extract_hardware_graph() stub
      soc_mapper.py                     # map_to_soc() stub
      dts_generator.py                  # generate_dts() stub
      validator.py                      # validate_dts() stub
      repairer.py                       # repair_dts() stub
      differ.py                         # diff_dts() stub
      explainer.py                      # explain_node() stub
    knowledge/
      __init__.py
      soc_repo.py                        # SocRepo加载器
      binding_repo.py                    # BindingRepo加载器
      device_db.py                       # DeviceDb加载器
      style_guide.py                     # StyleGuide加载器
      data/
        socs/.gitkeep
        bindings/.gitkeep
        devices/.gitkeep
        styleguide.md
  mcp_app/
    __init__.py
    server.py                          # MCPServer实例创建、run(transport="stdio")入口
    tools.py                            # 8个@server.tool()包装函数
    resources.py                        # 4个@server.resource()注册
    prompts.py                          # 3个@server.prompt()注册
    errors.py                           # 统一的错误响应构造函数
  cli.py                                # 命令行入口，直接调用core，不经过MCP
tests/
  core/
    test_task.py
    ir/
      test_models.py
      test_store.py
    pipeline/
      test_input_parser.py
      test_hardware_extractor.py
      test_soc_mapper.py
      test_dts_generator.py
      test_validator.py
      test_repairer.py
      test_differ.py
      test_explainer.py
    knowledge/
      test_soc_repo.py
      test_binding_repo.py
      test_device_db.py
      test_style_guide.py
  mcp_app/
    test_tools.py
    test_resources.py
    test_prompts.py
  fixtures/
    make_pdf.py                        # 生成最小可用测试PDF的helper
```

**说明**：`mcp_app` 而非 `mcp`，是为了避免包名与已安装的第三方 `mcp` SDK 冲突（Python import 时会先匹配同名的本地包）。

---

## Task 1: 项目骨架与依赖声明

**Files:**
- Create: `pyproject.toml`
- Create: `src/dts_gen/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/fixtures/__init__.py`
- Create: `tests/fixtures/make_pdf.py`
- Create: `.gitignore`

**Interfaces:**
- Produces: `make_minimal_pdf(path: pathlib.Path, pages: int = 1) -> None` — 供后续测试生成最小可用 PDF fixture，不依赖仓库根目录的真实 datasheet。

- [ ] **Step 1: 创建 `pyproject.toml`**

```toml
[project]
name = "dts-gen"
version = "0.1.0"
description = "AI驱动的硬件原理图到设备树代码生成工具"
requires-python = ">=3.10"
dependencies = [
    "pydantic>=2.0,<3.0",
    "PyYAML>=6.0,<7.0",
    "pypdf>=6.0,<7.0",
    "mcp>=2.0,<3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0,<9.0",
]

[project.scripts]
dts-gen = "dts_gen.cli:main"

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: 创建包初始化文件**

`src/dts_gen/__init__.py`:
```python
```

`tests/__init__.py`:
```python
```

`tests/fixtures/__init__.py`:
```python
```

- [ ] **Step 3: 创建 `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
.dts-gen/
```

- [ ] **Step 4: 创建 PDF 测试 fixture helper**

`tests/fixtures/make_pdf.py`:
```python
from pathlib import Path

from pypdf import PdfWriter


def make_minimal_pdf(path: Path, pages: int = 1) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as f:
        writer.write(f)
```

- [ ] **Step 5: 安装依赖并验证导入**

Run: `pip install -e ".[dev]"`
Expected: 安装成功，`dts-gen` 作为 editable 包注册（复用已存在的 `.pth` 映射到 `src/`）。

Run: `python -c "from tests.fixtures.make_pdf import make_minimal_pdf; import pathlib; make_minimal_pdf(pathlib.Path('/tmp/t.pdf'), 2); print('ok')"`
Expected: 输出 `ok`，且 `/tmp/t.pdf` 存在。

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/dts_gen/__init__.py tests/__init__.py tests/fixtures/__init__.py tests/fixtures/make_pdf.py .gitignore
git commit -m "chore: scaffold dts-gen package structure and dependencies"
```

---

## Task 2: IR 数据模型

**Files:**
- Create: `src/dts_gen/core/__init__.py`
- Create: `src/dts_gen/core/ir/__init__.py`
- Create: `src/dts_gen/core/ir/models.py`
- Test: `tests/core/__init__.py`
- Test: `tests/core/ir/__init__.py`
- Test: `tests/core/ir/test_models.py`

**Interfaces:**
- Produces（供 Task 3 起所有 pipeline/task 模块使用）:
  - `Endpoint(component_id: str, pin_name: str, signal_type: str | None, pair: str | None, direction: str | None, function: str | None, polarity: str | None, impedance: str | None, drive_strength: str | None, confidence: float, source: str)`
  - `Component(id: str, type: str, name: str)`
  - `Net(name: str, members: list[str], signal_type: str | None = None, pull: str | None = None)`
  - `Relation(kind: str, from_: str | None = None, to: str | None = None, bus: str | None = None, device: str | None = None, property: str | None = None, active: str | None = None, net: str | None = None)`
  - `PinctrlGroup(name: str, function: str, pins: list[str], drive_strength: str | None = None, bias: str | None = None)`
  - `SocMappingEntry(role: str, mapped_to: str, confidence: float)`
  - `UnresolvedItem(field: str, reason: str, page: int | None = None)`
  - `NodeSourceRef(node: str, source_page: int | None = None, component_id: str | None = None, rule_id: str | None = None)`
  - `HardwareIR(board: str | None, soc: str | None, components: list[Component], nets: list[Net], relations: list[Relation], pinctrl_groups: list[PinctrlGroup], soc_mapping: list[SocMappingEntry], endpoints: list[Endpoint], unresolved: list[UnresolvedItem])`

- [ ] **Step 1: 写失败测试**

`tests/core/__init__.py`:
```python
```

`tests/core/ir/__init__.py`:
```python
```

`tests/core/ir/test_models.py`:
```python
from dts_gen.core.ir.models import (
    Component,
    Endpoint,
    HardwareIR,
    Net,
    NodeSourceRef,
    PinctrlGroup,
    Relation,
    SocMappingEntry,
    UnresolvedItem,
)


def test_hardware_ir_round_trip_json():
    ir = HardwareIR(
        board="board-x",
        soc="sa8775p",
        components=[Component(id="soc_usb0", type="usb-controller", name="dwc3")],
        nets=[Net(name="USB0_HS_DP", members=["soc_usb0:dp", "redriver0:dp"])],
        relations=[
            Relation(
                kind="control",
                from_="soc_tlmm:gpio23",
                to="redriver0",
                property="enable-gpios",
                active="high",
            )
        ],
        pinctrl_groups=[
            PinctrlGroup(name="usb0_default", function="gpio", pins=["gpio23"])
        ],
        soc_mapping=[SocMappingEntry(role="usb-controller", mapped_to="usb_0", confidence=0.95)],
        endpoints=[
            Endpoint(
                component_id="redriver0",
                pin_name="dp",
                signal_type="hs",
                pair="dp",
                direction="bidirectional",
                function="usb2_dp",
                polarity="positive",
                impedance="90ohm-diff",
                drive_strength=None,
                confidence=0.92,
                source="schematic:page12",
            )
        ],
        unresolved=[UnresolvedItem(field="redriver0.vcc-supply", reason="连线不清晰", page=12)],
    )

    dumped = ir.model_dump_json()
    restored = HardwareIR.model_validate_json(dumped)

    assert restored.board == "board-x"
    assert restored.components[0].id == "soc_usb0"
    assert restored.relations[0].from_ == "soc_tlmm:gpio23"
    assert restored.endpoints[0].confidence == 0.92
    assert restored.unresolved[0].page == 12


def test_hardware_ir_defaults_to_empty_collections():
    ir = HardwareIR(board=None, soc=None)

    assert ir.components == []
    assert ir.nets == []
    assert ir.relations == []
    assert ir.pinctrl_groups == []
    assert ir.soc_mapping == []
    assert ir.endpoints == []
    assert ir.unresolved == []


def test_node_source_ref_optional_fields_default_none():
    ref = NodeSourceRef(node="&usb_0")

    assert ref.source_page is None
    assert ref.component_id is None
    assert ref.rule_id is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/core/ir/test_models.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.core'`

- [ ] **Step 3: 实现 IR 模型**

`src/dts_gen/core/__init__.py`:
```python
```

`src/dts_gen/core/ir/__init__.py`:
```python
```

`src/dts_gen/core/ir/models.py`:
```python
from __future__ import annotations

from pydantic import BaseModel, Field


class Component(BaseModel):
    id: str
    type: str
    name: str


class Endpoint(BaseModel):
    component_id: str
    pin_name: str
    signal_type: str | None = None
    pair: str | None = None
    direction: str | None = None
    function: str | None = None
    polarity: str | None = None
    impedance: str | None = None
    drive_strength: str | None = None
    confidence: float
    source: str


class Net(BaseModel):
    name: str
    members: list[str] = Field(default_factory=list)
    signal_type: str | None = None
    pull: str | None = None


class Relation(BaseModel):
    kind: str
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    bus: str | None = None
    device: str | None = None
    property: str | None = None
    active: str | None = None
    net: str | None = None

    model_config = {"populate_by_name": True}


class PinctrlGroup(BaseModel):
    name: str
    function: str
    pins: list[str] = Field(default_factory=list)
    drive_strength: str | None = None
    bias: str | None = None


class SocMappingEntry(BaseModel):
    role: str
    mapped_to: str
    confidence: float


class UnresolvedItem(BaseModel):
    field: str
    reason: str
    page: int | None = None


class NodeSourceRef(BaseModel):
    node: str
    source_page: int | None = None
    component_id: str | None = None
    rule_id: str | None = None


class HardwareIR(BaseModel):
    board: str | None = None
    soc: str | None = None
    components: list[Component] = Field(default_factory=list)
    nets: list[Net] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    pinctrl_groups: list[PinctrlGroup] = Field(default_factory=list)
    soc_mapping: list[SocMappingEntry] = Field(default_factory=list)
    endpoints: list[Endpoint] = Field(default_factory=list)
    unresolved: list[UnresolvedItem] = Field(default_factory=list)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/core/ir/test_models.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/__init__.py src/dts_gen/core/ir/__init__.py src/dts_gen/core/ir/models.py tests/core/__init__.py tests/core/ir/__init__.py tests/core/ir/test_models.py
git commit -m "feat: add HardwareIR pydantic models"
```

---

## Task 3: IR 版本存储（IrStore）

**Files:**
- Create: `src/dts_gen/core/ir/store.py`
- Test: `tests/core/ir/test_store.py`

**Interfaces:**
- Consumes: `HardwareIR`（Task 2）
- Produces（供 Task 4 的 TaskStore 和 Task 6-13 的 pipeline stage 使用）:
  - `IrStore(base_dir: pathlib.Path)`
  - `IrStore.save(task_id: str, ir: HardwareIR) -> str` — 返回相对路径如 `"ir/v2.json"`，自动递增版本号
  - `IrStore.load(task_id: str, ir_ref: str) -> HardwareIR`
  - `IrStore.latest_ref(task_id: str) -> str | None`

- [ ] **Step 1: 写失败测试**

`tests/core/ir/test_store.py`:
```python
from pathlib import Path

from dts_gen.core.ir.models import Component, HardwareIR
from dts_gen.core.ir.store import IrStore


def test_save_creates_v1_and_returns_ref(tmp_path: Path):
    store = IrStore(base_dir=tmp_path)
    ir = HardwareIR(board="board-x", soc="sa8775p")

    ref = store.save("task001", ir)

    assert ref == "ir/v1.json"
    assert (tmp_path / "task001" / "ir" / "v1.json").exists()


def test_save_twice_increments_version_and_keeps_old_file(tmp_path: Path):
    store = IrStore(base_dir=tmp_path)
    ir1 = HardwareIR(board="board-x", soc="sa8775p")
    ir2 = HardwareIR(
        board="board-x",
        soc="sa8775p",
        components=[Component(id="soc_usb0", type="usb-controller", name="dwc3")],
    )

    ref1 = store.save("task001", ir1)
    ref2 = store.save("task001", ir2)

    assert ref1 == "ir/v1.json"
    assert ref2 == "ir/v2.json"
    assert (tmp_path / "task001" / "ir" / "v1.json").exists()
    assert (tmp_path / "task001" / "ir" / "v2.json").exists()


def test_load_returns_equivalent_ir(tmp_path: Path):
    store = IrStore(base_dir=tmp_path)
    original = HardwareIR(board="board-x", soc="sa8775p")
    ref = store.save("task001", original)

    loaded = store.load("task001", ref)

    assert loaded.board == "board-x"
    assert loaded.soc == "sa8775p"


def test_latest_ref_returns_none_when_no_versions(tmp_path: Path):
    store = IrStore(base_dir=tmp_path)

    assert store.latest_ref("task001") is None


def test_latest_ref_returns_highest_version(tmp_path: Path):
    store = IrStore(base_dir=tmp_path)
    ir = HardwareIR(board="board-x", soc="sa8775p")
    store.save("task001", ir)
    store.save("task001", ir)

    assert store.latest_ref("task001") == "ir/v2.json"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/core/ir/test_store.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.core.ir.store'`

- [ ] **Step 3: 实现 IrStore**

`src/dts_gen/core/ir/store.py`:
```python
from __future__ import annotations

import re
from pathlib import Path

from dts_gen.core.ir.models import HardwareIR

_VERSION_PATTERN = re.compile(r"^v(\d+)\.json$")


class IrStore:
    def __init__(self, base_dir: Path):
        self._base_dir = base_dir

    def _ir_dir(self, task_id: str) -> Path:
        return self._base_dir / task_id / "ir"

    def _existing_versions(self, task_id: str) -> list[int]:
        ir_dir = self._ir_dir(task_id)
        if not ir_dir.exists():
            return []
        versions = []
        for entry in ir_dir.iterdir():
            match = _VERSION_PATTERN.match(entry.name)
            if match:
                versions.append(int(match.group(1)))
        return sorted(versions)

    def save(self, task_id: str, ir: HardwareIR) -> str:
        ir_dir = self._ir_dir(task_id)
        ir_dir.mkdir(parents=True, exist_ok=True)
        versions = self._existing_versions(task_id)
        next_version = (versions[-1] + 1) if versions else 1
        filename = f"v{next_version}.json"
        (ir_dir / filename).write_text(ir.model_dump_json(indent=2), encoding="utf-8")
        return f"ir/{filename}"

    def load(self, task_id: str, ir_ref: str) -> HardwareIR:
        filename = ir_ref.split("/", 1)[1]
        path = self._ir_dir(task_id) / filename
        return HardwareIR.model_validate_json(path.read_text(encoding="utf-8"))

    def latest_ref(self, task_id: str) -> str | None:
        versions = self._existing_versions(task_id)
        if not versions:
            return None
        return f"ir/v{versions[-1]}.json"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/core/ir/test_store.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/ir/store.py tests/core/ir/test_store.py
git commit -m "feat: add IrStore for versioned IR persistence"
```

---

## Task 4: Task 模型与 TaskStore

**Files:**
- Create: `src/dts_gen/core/task.py`
- Test: `tests/core/test_task.py`

**Interfaces:**
- Produces（供 Task 5-13 的 pipeline 集成和 Task 14 的 mcp/tools.py 使用）:
  - `TaskStatus = Literal["created", "extracted", "mapped", "generated", "validated", "failed"]`
  - `TaskInput(path: str, type: str)`
  - `TaskEvent(event_id: str, tool: str, timestamp: str, input_summary: dict, output_ref: str | None, status: Literal["ok", "warning", "error"], warnings: list[str], error: str | None)`
  - `Task(task_id: str, project: str | None, soc: str | None, board: str | None, created_at: str, status: TaskStatus, inputs: list[TaskInput], ir_ref: str | None, dts_ref: str | None, history: list[TaskEvent])`
  - `TaskStore(base_dir: pathlib.Path)`
  - `TaskStore.create(project: str | None, soc: str | None = None, board: str | None = None, task_id: str | None = None) -> Task`
  - `TaskStore.get(task_id: str) -> Task`（不存在时抛 `TaskNotFoundError`）
  - `TaskStore.save(task: Task) -> None`
  - `TaskStore.append_event(task_id: str, event: TaskEvent) -> Task`
  - `TaskNotFoundError(Exception)`

- [ ] **Step 1: 写失败测试**

`tests/core/test_task.py`:
```python
from pathlib import Path

import pytest

from dts_gen.core.task import Task, TaskEvent, TaskNotFoundError, TaskStore


def test_create_generates_task_with_created_status(tmp_path: Path):
    store = TaskStore(base_dir=tmp_path)

    task = store.create(project="sa8775p-board-x", soc="sa8775p", board="board-x")

    assert task.status == "created"
    assert task.project == "sa8775p-board-x"
    assert task.soc == "sa8775p"
    assert task.board == "board-x"
    assert task.ir_ref is None
    assert task.dts_ref is None
    assert task.history == []
    assert (tmp_path / task.task_id / "task.json").exists()


def test_create_with_explicit_task_id_uses_it(tmp_path: Path):
    store = TaskStore(base_dir=tmp_path)

    task = store.create(project="p", task_id="task001")

    assert task.task_id == "task001"


def test_get_returns_saved_task(tmp_path: Path):
    store = TaskStore(base_dir=tmp_path)
    created = store.create(project="p", task_id="task001")

    fetched = store.get("task001")

    assert fetched.task_id == created.task_id
    assert fetched.project == "p"


def test_get_raises_for_unknown_task(tmp_path: Path):
    store = TaskStore(base_dir=tmp_path)

    with pytest.raises(TaskNotFoundError):
        store.get("does-not-exist")


def test_save_persists_field_changes(tmp_path: Path):
    store = TaskStore(base_dir=tmp_path)
    task = store.create(project="p", task_id="task001")
    task.status = "extracted"
    task.ir_ref = "ir/v1.json"

    store.save(task)
    reloaded = store.get("task001")

    assert reloaded.status == "extracted"
    assert reloaded.ir_ref == "ir/v1.json"


def test_append_event_adds_to_history(tmp_path: Path):
    store = TaskStore(base_dir=tmp_path)
    store.create(project="p", task_id="task001")
    event = TaskEvent(
        event_id="evt1",
        tool="extract_hardware_graph",
        timestamp="2026-07-30T00:00:00",
        input_summary={"page_range": [1, 5]},
        output_ref="ir/v1.json",
        status="ok",
        warnings=[],
        error=None,
    )

    updated = store.append_event("task001", event)

    assert len(updated.history) == 1
    assert updated.history[0].tool == "extract_hardware_graph"
    reloaded = store.get("task001")
    assert len(reloaded.history) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/core/test_task.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.core.task'`

- [ ] **Step 3: 实现 Task 与 TaskStore**

`src/dts_gen/core/task.py`:
```python
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

TaskStatus = Literal["created", "extracted", "mapped", "generated", "validated", "failed"]


class TaskNotFoundError(Exception):
    def __init__(self, task_id: str):
        super().__init__(f"task not found: {task_id}")
        self.task_id = task_id


class TaskInput(BaseModel):
    path: str
    type: str


class TaskEvent(BaseModel):
    event_id: str
    tool: str
    timestamp: str
    input_summary: dict
    output_ref: str | None = None
    status: Literal["ok", "warning", "error"]
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class Task(BaseModel):
    task_id: str
    project: str | None = None
    soc: str | None = None
    board: str | None = None
    created_at: str
    status: TaskStatus = "created"
    inputs: list[TaskInput] = Field(default_factory=list)
    ir_ref: str | None = None
    dts_ref: str | None = None
    history: list[TaskEvent] = Field(default_factory=list)


class TaskStore:
    def __init__(self, base_dir: Path):
        self._base_dir = base_dir

    def _task_path(self, task_id: str) -> Path:
        return self._base_dir / task_id / "task.json"

    def create(
        self,
        project: str | None,
        soc: str | None = None,
        board: str | None = None,
        task_id: str | None = None,
    ) -> Task:
        resolved_id = task_id or uuid.uuid4().hex[:12]
        task = Task(
            task_id=resolved_id,
            project=project,
            soc=soc,
            board=board,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.save(task)
        return task

    def get(self, task_id: str) -> Task:
        path = self._task_path(task_id)
        if not path.exists():
            raise TaskNotFoundError(task_id)
        return Task.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, task: Task) -> None:
        path = self._task_path(task.task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(task.model_dump_json(indent=2), encoding="utf-8")

    def append_event(self, task_id: str, event: TaskEvent) -> Task:
        task = self.get(task_id)
        task.history.append(event)
        self.save(task)
        return task
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/core/test_task.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/task.py tests/core/test_task.py
git commit -m "feat: add Task model and TaskStore for local task persistence"
```

---

## Task 5: Pipeline 公共类型（base.py）

**Files:**
- Create: `src/dts_gen/core/pipeline/__init__.py`
- Create: `src/dts_gen/core/pipeline/base.py`
- Test: `tests/core/pipeline/__init__.py`

**Interfaces:**
- Consumes: `UnresolvedItem`, `NodeSourceRef`（Task 2）
- Produces（供 Task 6-13 使用）:
  - `DtsError(message: str, node: str | None, severity: Literal["error", "warning"])`
  - `FixNote(node: str, change: str, reason: str)`
  - `StageResult(BaseModel)` — 基类，含 `ok: bool`、`warnings: list[str]`

本任务不含独立单测（纯类型定义，行为在后续 stage 测试中间接覆盖），仅需人工验证可导入。

- [ ] **Step 1: 创建包初始化与 base 模块**

`src/dts_gen/core/pipeline/__init__.py`:
```python
```

`tests/core/pipeline/__init__.py`:
```python
```

`src/dts_gen/core/pipeline/base.py`:
```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StageResult(BaseModel):
    ok: bool
    warnings: list[str] = Field(default_factory=list)


class DtsError(BaseModel):
    message: str
    node: str | None = None
    severity: Literal["error", "warning"] = "error"


class FixNote(BaseModel):
    node: str
    change: str
    reason: str
```

- [ ] **Step 2: 验证可导入**

Run: `python -c "from dts_gen.core.pipeline.base import StageResult, DtsError, FixNote; print(StageResult(ok=True))"`
Expected: 输出 `ok=True warnings=[]`

- [ ] **Step 3: Commit**

```bash
git add src/dts_gen/core/pipeline/__init__.py src/dts_gen/core/pipeline/base.py tests/core/pipeline/__init__.py
git commit -m "feat: add pipeline base types (StageResult, DtsError, FixNote)"
```

---

## Task 6: input_parser stage（对应 ingest_input）

**Files:**
- Create: `src/dts_gen/core/pipeline/input_parser.py`
- Test: `tests/core/pipeline/test_input_parser.py`

**Interfaces:**
- Consumes: `TaskInput`（Task 4）
- Produces（供 Task 14 的 `mcp_app/tools.py::ingest_input` 使用）:
  - `InputFile(path: str, type: str)`
  - `PageAsset(page_number: int, source_path: str)`
  - `ParsedInputResult(pages: list[PageAsset], metadata: dict)`
  - `parse_input(files: list[InputFile]) -> ParsedInputResult`

本次为 stub 实现：对 PDF 文件用 `pypdf` 读取真实页数（这是唯一"确定性可做"的部分，不涉及内容理解），`metadata` 固定返回 `{"stub": True}`；非 PDF/不存在文件报 `FileNotFoundError`。

- [ ] **Step 1: 写失败测试**

`tests/core/pipeline/test_input_parser.py`:
```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/core/pipeline/test_input_parser.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.core.pipeline.input_parser'`

- [ ] **Step 3: 实现 input_parser**

`src/dts_gen/core/pipeline/input_parser.py`:
```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/core/pipeline/test_input_parser.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/input_parser.py tests/core/pipeline/test_input_parser.py
git commit -m "feat: add input_parser stage with real PDF page counting stub"
```

---

## Task 7: hardware_extractor stage（对应 extract_hardware_graph）

**Files:**
- Create: `src/dts_gen/core/pipeline/hardware_extractor.py`
- Test: `tests/core/pipeline/test_hardware_extractor.py`

**Interfaces:**
- Consumes: `PageAsset`（Task 6）、`HardwareIR`, `UnresolvedItem`（Task 2）
- Produces（供 Task 14 的 `mcp_app/tools.py::extract_hardware_graph` 使用）:
  - `ExtractResult(ir: HardwareIR, unresolved: list[UnresolvedItem])`
  - `extract_hardware_graph(pages: list[PageAsset], page_range: tuple[int, int] | None = None) -> ExtractResult`

本次为 stub：不做任何视觉识别，返回空 `HardwareIR`，并在 `unresolved` 中显式声明"未实现"，遵循 spec 中"不可虚构字段"的硬性原则——没有真实识别能力时，绝不能编造假的 component/net 数据。

- [ ] **Step 1: 写失败测试**

`tests/core/pipeline/test_hardware_extractor.py`:
```python
from dts_gen.core.pipeline.hardware_extractor import extract_hardware_graph
from dts_gen.core.pipeline.input_parser import PageAsset


def test_extract_returns_empty_ir_with_not_implemented_marker():
    pages = [PageAsset(page_number=1, source_path="a.pdf")]

    result = extract_hardware_graph(pages)

    assert result.ir.components == []
    assert result.ir.nets == []
    assert len(result.unresolved) == 1
    assert result.unresolved[0].field == "*"
    assert "not implemented" in result.unresolved[0].reason.lower()


def test_extract_records_requested_page_range_in_unresolved():
    pages = [PageAsset(page_number=n, source_path="a.pdf") for n in range(1, 6)]

    result = extract_hardware_graph(pages, page_range=(2, 4))

    assert result.unresolved[0].page == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/core/pipeline/test_hardware_extractor.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.core.pipeline.hardware_extractor'`

- [ ] **Step 3: 实现 hardware_extractor**

`src/dts_gen/core/pipeline/hardware_extractor.py`:
```python
from __future__ import annotations

from pydantic import BaseModel, Field

from dts_gen.core.ir.models import HardwareIR, UnresolvedItem
from dts_gen.core.pipeline.input_parser import PageAsset


class ExtractResult(BaseModel):
    ir: HardwareIR
    unresolved: list[UnresolvedItem] = Field(default_factory=list)


def extract_hardware_graph(
    pages: list[PageAsset], page_range: tuple[int, int] | None = None
) -> ExtractResult:
    start_page = page_range[0] if page_range else (pages[0].page_number if pages else None)
    return ExtractResult(
        ir=HardwareIR(),
        unresolved=[
            UnresolvedItem(
                field="*",
                reason="hardware_extractor stage not implemented yet; no components were identified",
                page=start_page,
            )
        ],
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/core/pipeline/test_hardware_extractor.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/hardware_extractor.py tests/core/pipeline/test_hardware_extractor.py
git commit -m "feat: add hardware_extractor stage stub"
```

---

## Task 8: soc_mapper stage（对应 identify_soc_mapping）

**Files:**
- Create: `src/dts_gen/core/pipeline/soc_mapper.py`
- Test: `tests/core/pipeline/test_soc_mapper.py`

**Interfaces:**
- Consumes: `HardwareIR`, `SocMappingEntry`（Task 2）
- Produces（供 Task 14 使用）:
  - `MappingResult(ir: HardwareIR, mapping_report: list[SocMappingEntry])`
  - `map_to_soc(ir: HardwareIR, soc: str) -> MappingResult`

本次为 stub：原样返回输入 IR（不修改），`mapping_report` 为空列表——同样遵循"没有真实映射规则库时不编造映射关系"的原则。

- [ ] **Step 1: 写失败测试**

`tests/core/pipeline/test_soc_mapper.py`:
```python
from dts_gen.core.ir.models import Component, HardwareIR
from dts_gen.core.pipeline.soc_mapper import map_to_soc


def test_map_to_soc_returns_ir_unchanged_and_empty_report():
    ir = HardwareIR(
        board="board-x",
        soc="sa8775p",
        components=[Component(id="soc_usb0", type="usb-controller", name="dwc3")],
    )

    result = map_to_soc(ir, soc="sa8775p")

    assert result.ir.components == ir.components
    assert result.mapping_report == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/core/pipeline/test_soc_mapper.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.core.pipeline.soc_mapper'`

- [ ] **Step 3: 实现 soc_mapper**

`src/dts_gen/core/pipeline/soc_mapper.py`:
```python
from __future__ import annotations

from pydantic import BaseModel, Field

from dts_gen.core.ir.models import HardwareIR, SocMappingEntry


class MappingResult(BaseModel):
    ir: HardwareIR
    mapping_report: list[SocMappingEntry] = Field(default_factory=list)


def map_to_soc(ir: HardwareIR, soc: str) -> MappingResult:
    return MappingResult(ir=ir, mapping_report=[])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/core/pipeline/test_soc_mapper.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/soc_mapper.py tests/core/pipeline/test_soc_mapper.py
git commit -m "feat: add soc_mapper stage stub"
```

---

## Task 9: dts_generator stage（对应 generate_dts）

**Files:**
- Create: `src/dts_gen/core/pipeline/dts_generator.py`
- Test: `tests/core/pipeline/test_dts_generator.py`

**Interfaces:**
- Consumes: `HardwareIR`, `NodeSourceRef`（Task 2）
- Produces（供 Task 14 使用）:
  - `GenerationScope(subsystem: str | None = None)`
  - `GenerateResult(dts_text: str, node_sources: list[NodeSourceRef])`
  - `generate_dts(ir: HardwareIR, board: str | None, scope: GenerationScope) -> GenerateResult`

本次为 stub：返回空字符串 DTS 和空 `node_sources`——没有规则引擎和模板库时不能编造 DTS 代码。

- [ ] **Step 1: 写失败测试**

`tests/core/pipeline/test_dts_generator.py`:
```python
from dts_gen.core.ir.models import HardwareIR
from dts_gen.core.pipeline.dts_generator import GenerationScope, generate_dts


def test_generate_dts_returns_empty_text_when_not_implemented():
    ir = HardwareIR(board="board-x", soc="sa8775p")

    result = generate_dts(ir, board="board-x", scope=GenerationScope())

    assert result.dts_text == ""
    assert result.node_sources == []


def test_generation_scope_defaults_subsystem_to_none():
    scope = GenerationScope()

    assert scope.subsystem is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/core/pipeline/test_dts_generator.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.core.pipeline.dts_generator'`

- [ ] **Step 3: 实现 dts_generator**

`src/dts_gen/core/pipeline/dts_generator.py`:
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

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/core/pipeline/test_dts_generator.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/dts_generator.py tests/core/pipeline/test_dts_generator.py
git commit -m "feat: add dts_generator stage stub"
```

---

## Task 10: validator stage（对应 validate_dts）

**Files:**
- Create: `src/dts_gen/core/pipeline/validator.py`
- Test: `tests/core/pipeline/test_validator.py`

**Interfaces:**
- Consumes: `DtsError`（Task 5）
- Produces（供 Task 14 使用）:
  - `ValidateResult(errors: list[DtsError], warnings: list[DtsError])`
  - `validate_dts(dts_text: str, target_platform: str | None = None) -> ValidateResult`

本次为 stub：不调用真实 `dtc`/`dtbs_check`（尚未封装），对空文本返回一条警告说明校验器未实现；对非空文本同样返回"未实现"警告，不判定为错误（因为没有真实校验能力，不能编造通过或失败的结论）。

- [ ] **Step 1: 写失败测试**

`tests/core/pipeline/test_validator.py`:
```python
from dts_gen.core.pipeline.validator import validate_dts


def test_validate_dts_returns_not_implemented_warning_for_empty_text():
    result = validate_dts("")

    assert result.errors == []
    assert len(result.warnings) == 1
    assert "not implemented" in result.warnings[0].message.lower()


def test_validate_dts_returns_not_implemented_warning_for_nonempty_text():
    result = validate_dts("&usb_0 { status = \"okay\"; };")

    assert result.errors == []
    assert len(result.warnings) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/core/pipeline/test_validator.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.core.pipeline.validator'`

- [ ] **Step 3: 实现 validator**

`src/dts_gen/core/pipeline/validator.py`:
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

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/core/pipeline/test_validator.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/validator.py tests/core/pipeline/test_validator.py
git commit -m "feat: add validator stage stub"
```

---

## Task 11: repairer stage（对应 repair_dts）

**Files:**
- Create: `src/dts_gen/core/pipeline/repairer.py`
- Test: `tests/core/pipeline/test_repairer.py`

**Interfaces:**
- Consumes: `DtsError`, `FixNote`（Task 5）
- Produces（供 Task 14 使用）:
  - `RepairResult(dts_text: str, applied_fixes: list[FixNote])`
  - `repair_dts(dts_text: str, errors: list[DtsError]) -> RepairResult`

本次为 stub：原样返回输入 `dts_text`，`applied_fixes` 为空——没有修复规则库时不能编造修改。

- [ ] **Step 1: 写失败测试**

`tests/core/pipeline/test_repairer.py`:
```python
from dts_gen.core.pipeline.repairer import repair_dts


def test_repair_dts_returns_input_unchanged_with_no_fixes():
    original = "&usb_0 { status = \"okay\"; };"

    result = repair_dts(original, errors=[])

    assert result.dts_text == original
    assert result.applied_fixes == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/core/pipeline/test_repairer.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.core.pipeline.repairer'`

- [ ] **Step 3: 实现 repairer**

`src/dts_gen/core/pipeline/repairer.py`:
```python
from __future__ import annotations

from pydantic import BaseModel, Field

from dts_gen.core.pipeline.base import DtsError, FixNote


class RepairResult(BaseModel):
    dts_text: str
    applied_fixes: list[FixNote] = Field(default_factory=list)


def repair_dts(dts_text: str, errors: list[DtsError]) -> RepairResult:
    return RepairResult(dts_text=dts_text, applied_fixes=[])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/core/pipeline/test_repairer.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/repairer.py tests/core/pipeline/test_repairer.py
git commit -m "feat: add repairer stage stub"
```

---

## Task 12: differ stage（对应 diff_dts）

**Files:**
- Create: `src/dts_gen/core/pipeline/differ.py`
- Test: `tests/core/pipeline/test_differ.py`

**Interfaces:**
- Produces（供 Task 14 使用）:
  - `DiffResult(patch: str, risk_notes: list[str])`
  - `diff_dts(original: str, generated: str, scope: str | None = None) -> DiffResult`

本次实现真实的文本 diff（用标准库 `difflib.unified_diff`，属于确定性文本处理，不涉及语义理解，因此不算"stub"），`risk_notes` 留空列表（风险判断需要语义理解，本次不做）。

- [ ] **Step 1: 写失败测试**

`tests/core/pipeline/test_differ.py`:
```python
from dts_gen.core.pipeline.differ import diff_dts


def test_diff_dts_produces_unified_diff_for_changed_text():
    original = "&usb_0 {\n  status = \"disabled\";\n};\n"
    generated = "&usb_0 {\n  status = \"okay\";\n};\n"

    result = diff_dts(original, generated)

    assert "-  status = \"disabled\";" in result.patch
    assert "+  status = \"okay\";" in result.patch
    assert result.risk_notes == []


def test_diff_dts_returns_empty_patch_for_identical_text():
    text = "&usb_0 {\n  status = \"okay\";\n};\n"

    result = diff_dts(text, text)

    assert result.patch == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/core/pipeline/test_differ.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.core.pipeline.differ'`

- [ ] **Step 3: 实现 differ**

`src/dts_gen/core/pipeline/differ.py`:
```python
from __future__ import annotations

import difflib

from pydantic import BaseModel, Field


class DiffResult(BaseModel):
    patch: str
    risk_notes: list[str] = Field(default_factory=list)


def diff_dts(original: str, generated: str, scope: str | None = None) -> DiffResult:
    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            generated.splitlines(keepends=True),
            fromfile="existing.dts",
            tofile="generated.dts",
        )
    )
    return DiffResult(patch="".join(diff_lines), risk_notes=[])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/core/pipeline/test_differ.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/differ.py tests/core/pipeline/test_differ.py
git commit -m "feat: add differ stage using difflib unified_diff"
```

---

## Task 13: explainer stage（对应 explain_node）

**Files:**
- Create: `src/dts_gen/core/pipeline/explainer.py`
- Test: `tests/core/pipeline/test_explainer.py`

**Interfaces:**
- Consumes: `HardwareIR`, `NodeSourceRef`, `UnresolvedItem`（Task 2）
- Produces（供 Task 14 使用）:
  - `ExplainResult(source_refs: list[NodeSourceRef], rule_ids: list[str], unresolved: list[UnresolvedItem])`
  - `explain_node(ir: HardwareIR, node_path: str) -> ExplainResult`

本次实现：在 `ir.unresolved` 中查找 `field` 精确等于 `node_path` 的项，回填到结果的 `unresolved`；`source_refs`/`rule_ids` 本次固定为空列表，因为 IR 中还没有"节点路径→来源"的反向索引（`generate_dts`/`soc_mapper` 都是 stub，不产生真实数据可供反查）——这是唯一能在不编造数据前提下做的确定性行为。

- [ ] **Step 1: 写失败测试**

`tests/core/pipeline/test_explainer.py`:
```python
from dts_gen.core.ir.models import HardwareIR, UnresolvedItem
from dts_gen.core.pipeline.explainer import explain_node


def test_explain_node_returns_matching_unresolved_item():
    ir = HardwareIR(
        unresolved=[UnresolvedItem(field="&usb_0", reason="连线不清晰", page=12)]
    )

    result = explain_node(ir, node_path="&usb_0")

    assert result.source_refs == []
    assert result.rule_ids == []
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason == "连线不清晰"


def test_explain_node_returns_empty_unresolved_when_no_match():
    ir = HardwareIR(unresolved=[UnresolvedItem(field="&usb_1", reason="不相关", page=1)])

    result = explain_node(ir, node_path="&usb_0")

    assert result.unresolved == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/core/pipeline/test_explainer.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.core.pipeline.explainer'`

- [ ] **Step 3: 实现 explainer**

`src/dts_gen/core/pipeline/explainer.py`:
```python
from __future__ import annotations

from pydantic import BaseModel, Field

from dts_gen.core.ir.models import HardwareIR, NodeSourceRef, UnresolvedItem


class ExplainResult(BaseModel):
    source_refs: list[NodeSourceRef] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    unresolved: list[UnresolvedItem] = Field(default_factory=list)


def explain_node(ir: HardwareIR, node_path: str) -> ExplainResult:
    matching = [item for item in ir.unresolved if item.field == node_path]
    return ExplainResult(source_refs=[], rule_ids=[], unresolved=matching)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/core/pipeline/test_explainer.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/core/pipeline/explainer.py tests/core/pipeline/test_explainer.py
git commit -m "feat: add explainer stage matching unresolved items by node path"
```

---

## Task 14: knowledge 加载器（Resources 的数据来源）

**Files:**
- Create: `src/dts_gen/core/knowledge/__init__.py`
- Create: `src/dts_gen/core/knowledge/soc_repo.py`
- Create: `src/dts_gen/core/knowledge/binding_repo.py`
- Create: `src/dts_gen/core/knowledge/device_db.py`
- Create: `src/dts_gen/core/knowledge/style_guide.py`
- Create: `src/dts_gen/core/knowledge/data/socs/.gitkeep`
- Create: `src/dts_gen/core/knowledge/data/bindings/.gitkeep`
- Create: `src/dts_gen/core/knowledge/data/devices/.gitkeep`
- Create: `src/dts_gen/core/knowledge/data/styleguide.md`
- Test: `tests/core/knowledge/__init__.py`
- Test: `tests/core/knowledge/test_soc_repo.py`
- Test: `tests/core/knowledge/test_binding_repo.py`
- Test: `tests/core/knowledge/test_device_db.py`
- Test: `tests/core/knowledge/test_style_guide.py`

**Interfaces:**
- Produces（供 Task 16 的 `mcp_app/resources.py` 使用）:
  - `SocRepo(data_dir: pathlib.Path)`; `SocRepo.get_reference_dtsi(soc: str) -> list[str]`（返回文件路径字符串列表）
  - `BindingRepo(data_dir: pathlib.Path)`; `BindingRepo.get_schema(compatible: str) -> dict | None`
  - `DeviceDb(data_dir: pathlib.Path)`; `DeviceDb.lookup(part_number: str) -> dict | None`
  - `StyleGuide(data_dir: pathlib.Path)`; `StyleGuide.naming_rules() -> str`

均为真实文件系统查找逻辑（非语义 stub）：数据目录当前为空，查找不到时返回 `None`/`[]`，不是"未实现"占位——这一层的行为本身就是"从文件系统读数据"，逻辑是完整的，只是数据尚未填充。

- [ ] **Step 1: 写失败测试**

`tests/core/knowledge/__init__.py`:
```python
```

`tests/core/knowledge/test_soc_repo.py`:
```python
from pathlib import Path

from dts_gen.core.knowledge.soc_repo import SocRepo


def test_get_reference_dtsi_returns_empty_list_when_soc_dir_missing(tmp_path: Path):
    repo = SocRepo(data_dir=tmp_path)

    assert repo.get_reference_dtsi("sa8775p") == []


def test_get_reference_dtsi_returns_dtsi_files_in_soc_dir(tmp_path: Path):
    soc_dir = tmp_path / "socs" / "sa8775p"
    soc_dir.mkdir(parents=True)
    (soc_dir / "main.dtsi").write_text("/* stub */", encoding="utf-8")
    (soc_dir / "notes.txt").write_text("ignore me", encoding="utf-8")

    repo = SocRepo(data_dir=tmp_path)
    result = repo.get_reference_dtsi("sa8775p")

    assert result == [str(soc_dir / "main.dtsi")]
```

`tests/core/knowledge/test_binding_repo.py`:
```python
from pathlib import Path

import yaml

from dts_gen.core.knowledge.binding_repo import BindingRepo


def test_get_schema_returns_none_when_missing(tmp_path: Path):
    repo = BindingRepo(data_dir=tmp_path)

    assert repo.get_schema("snps,dwc3") is None


def test_get_schema_returns_parsed_yaml(tmp_path: Path):
    bindings_dir = tmp_path / "bindings"
    bindings_dir.mkdir(parents=True)
    schema = {"compatible": "snps,dwc3", "properties": {"reg": {}}}
    (bindings_dir / "snps,dwc3.yaml").write_text(yaml.safe_dump(schema), encoding="utf-8")

    repo = BindingRepo(data_dir=tmp_path)
    result = repo.get_schema("snps,dwc3")

    assert result == schema
```

`tests/core/knowledge/test_device_db.py`:
```python
from pathlib import Path

import json

from dts_gen.core.knowledge.device_db import DeviceDb


def test_lookup_returns_none_when_missing(tmp_path: Path):
    db = DeviceDb(data_dir=tmp_path)

    assert db.lookup("tusb2e11") is None


def test_lookup_returns_parsed_json(tmp_path: Path):
    devices_dir = tmp_path / "devices"
    devices_dir.mkdir(parents=True)
    template = {"part_number": "tusb2e11", "type": "usb-redriver", "compatible": "ti,tusb2e11"}
    (devices_dir / "tusb2e11.json").write_text(json.dumps(template), encoding="utf-8")

    db = DeviceDb(data_dir=tmp_path)
    result = db.lookup("tusb2e11")

    assert result == template
```

`tests/core/knowledge/test_style_guide.py`:
```python
from pathlib import Path

from dts_gen.core.knowledge.style_guide import StyleGuide


def test_naming_rules_returns_empty_string_when_missing(tmp_path: Path):
    guide = StyleGuide(data_dir=tmp_path)

    assert guide.naming_rules() == ""


def test_naming_rules_returns_file_content(tmp_path: Path):
    (tmp_path / "styleguide.md").write_text("# Naming\nUse lowercase.", encoding="utf-8")

    guide = StyleGuide(data_dir=tmp_path)

    assert guide.naming_rules() == "# Naming\nUse lowercase."
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/core/knowledge/ -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.core.knowledge'`

- [ ] **Step 3: 实现四个加载器**

`src/dts_gen/core/knowledge/__init__.py`:
```python
```

`src/dts_gen/core/knowledge/soc_repo.py`:
```python
from __future__ import annotations

from pathlib import Path


class SocRepo:
    def __init__(self, data_dir: Path):
        self._data_dir = data_dir

    def get_reference_dtsi(self, soc: str) -> list[str]:
        soc_dir = self._data_dir / "socs" / soc
        if not soc_dir.exists():
            return []
        return sorted(str(p) for p in soc_dir.glob("*.dtsi"))
```

`src/dts_gen/core/knowledge/binding_repo.py`:
```python
from __future__ import annotations

from pathlib import Path

import yaml


class BindingRepo:
    def __init__(self, data_dir: Path):
        self._data_dir = data_dir

    def get_schema(self, compatible: str) -> dict | None:
        path = self._data_dir / "bindings" / f"{compatible}.yaml"
        if not path.exists():
            return None
        return yaml.safe_load(path.read_text(encoding="utf-8"))
```

`src/dts_gen/core/knowledge/device_db.py`:
```python
from __future__ import annotations

import json
from pathlib import Path


class DeviceDb:
    def __init__(self, data_dir: Path):
        self._data_dir = data_dir

    def lookup(self, part_number: str) -> dict | None:
        path = self._data_dir / "devices" / f"{part_number}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
```

`src/dts_gen/core/knowledge/style_guide.py`:
```python
from __future__ import annotations

from pathlib import Path


class StyleGuide:
    def __init__(self, data_dir: Path):
        self._data_dir = data_dir

    def naming_rules(self) -> str:
        path = self._data_dir / "styleguide.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")
```

- [ ] **Step 4: 创建数据目录占位与初始命名规范文档**

`src/dts_gen/core/knowledge/data/socs/.gitkeep`:
```
```

`src/dts_gen/core/knowledge/data/bindings/.gitkeep`:
```
```

`src/dts_gen/core/knowledge/data/devices/.gitkeep`:
```
```

`src/dts_gen/core/knowledge/data/styleguide.md`:
```markdown
# 命名规范

本文件待填充。规则应涵盖节点命名、label 风格、注释格式、复位极性写法等内部最佳实践。
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/core/knowledge/ -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add src/dts_gen/core/knowledge/ tests/core/knowledge/
git commit -m "feat: add knowledge loaders (SocRepo/BindingRepo/DeviceDb/StyleGuide)"
```

---

## Task 15: MCP 错误响应工具与 Tool 前置条件检查

**Files:**
- Create: `src/dts_gen/mcp_app/__init__.py`
- Create: `src/dts_gen/mcp_app/errors.py`
- Test: `tests/mcp_app/__init__.py`
- Test: `tests/mcp_app/test_errors.py`

**Interfaces:**
- Produces（供 Task 16 使用）:
  - `precondition_error(task_id: str | None, missing: str, hint: str) -> dict` — 返回 `{"task_id": task_id, "error": "precondition_failed", "missing": missing, "hint": hint}`
  - `generic_error(task_id: str | None, message: str, hint: str) -> dict` — 返回 `{"task_id": task_id, "error": message, "hint": hint}`
  - `require_ir_ref(task) -> str` — 若 `task.ir_ref` 为 `None` 抛 `PreconditionError`；否则返回 `task.ir_ref`
  - `require_dts_ref(task) -> str` — 同上，检查 `task.dts_ref`
  - `PreconditionError(Exception)` — 携带 `missing: str`、`hint: str` 属性

**关于 `task_id` 字段**：Global Constraints 要求"所有 Tool 输出必须包含 `task_id` 字段"，该约束覆盖错误响应。`generic_error`/`precondition_error` 因此都以 `task_id` 为第一个参数，返回字典始终带 `task_id` 键；当错误发生在任务创建之前（例如 `ingest_input` 输入文件不存在，此时还没有 `task_id`），调用方传入 `None`，字段仍存在但值为 `None`——满足"字段始终存在"这一字面要求。此约束只针对 **Tool** 输出，不适用于 Task 17 的 Resource 读取函数（`read_binding`/`read_device` 等）返回的 `{"error": "not_found", ...}`，因为 spec 三节的统一规则原文写的是"所有 Tool 输出"。

- [ ] **Step 1: 写失败测试**

`tests/mcp_app/__init__.py`:
```python
```

`tests/mcp_app/test_errors.py`:
```python
import pytest

from dts_gen.core.task import Task
from dts_gen.mcp_app.errors import (
    PreconditionError,
    generic_error,
    precondition_error,
    require_dts_ref,
    require_ir_ref,
)


def _make_task(**overrides) -> Task:
    defaults = dict(task_id="task001", created_at="2026-07-30T00:00:00")
    defaults.update(overrides)
    return Task(**defaults)


def test_precondition_error_shape():
    result = precondition_error(task_id="task001", missing="ir_ref", hint="call extract_hardware_graph first")

    assert result == {
        "task_id": "task001",
        "error": "precondition_failed",
        "missing": "ir_ref",
        "hint": "call extract_hardware_graph first",
    }


def test_precondition_error_allows_none_task_id():
    result = precondition_error(task_id=None, missing="ir_ref", hint="call extract_hardware_graph first")

    assert result["task_id"] is None


def test_generic_error_shape():
    result = generic_error("task001", "file_not_found", hint="check the input path")

    assert result == {"task_id": "task001", "error": "file_not_found", "hint": "check the input path"}


def test_require_ir_ref_raises_when_missing():
    task = _make_task(ir_ref=None)

    with pytest.raises(PreconditionError) as exc_info:
        require_ir_ref(task)

    assert exc_info.value.missing == "ir_ref"


def test_require_ir_ref_returns_ref_when_present():
    task = _make_task(ir_ref="ir/v1.json")

    assert require_ir_ref(task) == "ir/v1.json"


def test_require_dts_ref_raises_when_missing():
    task = _make_task(dts_ref=None)

    with pytest.raises(PreconditionError) as exc_info:
        require_dts_ref(task)

    assert exc_info.value.missing == "dts_ref"


def test_require_dts_ref_returns_ref_when_present():
    task = _make_task(dts_ref="dts/v1.dts")

    assert require_dts_ref(task) == "dts/v1.dts"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/mcp_app/test_errors.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.mcp_app'`

- [ ] **Step 3: 实现 errors 模块**

`src/dts_gen/mcp_app/__init__.py`:
```python
```

`src/dts_gen/mcp_app/errors.py`:
```python
from __future__ import annotations

from dts_gen.core.task import Task


class PreconditionError(Exception):
    def __init__(self, missing: str, hint: str):
        super().__init__(f"missing precondition: {missing}")
        self.missing = missing
        self.hint = hint


def precondition_error(task_id: str | None, missing: str, hint: str) -> dict:
    return {"task_id": task_id, "error": "precondition_failed", "missing": missing, "hint": hint}


def generic_error(task_id: str | None, message: str, hint: str) -> dict:
    return {"task_id": task_id, "error": message, "hint": hint}


def require_ir_ref(task: Task) -> str:
    if task.ir_ref is None:
        raise PreconditionError(
            missing="ir_ref", hint="call extract_hardware_graph first"
        )
    return task.ir_ref


def require_dts_ref(task: Task) -> str:
    if task.dts_ref is None:
        raise PreconditionError(missing="dts_ref", hint="call generate_dts first")
    return task.dts_ref
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/mcp_app/test_errors.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/mcp_app/__init__.py src/dts_gen/mcp_app/errors.py tests/mcp_app/__init__.py tests/mcp_app/test_errors.py
git commit -m "feat: add MCP error helpers and precondition checks"
```

---

## Task 16: 8 个 MCP Tool 包装（tools.py）

**Files:**
- Create: `src/dts_gen/mcp_app/tools.py`
- Test: `tests/mcp_app/test_tools.py`

**Interfaces:**
- Consumes: 所有 `core/pipeline/*` 函数（Task 6-13）、`TaskStore`/`Task`/`TaskEvent`（Task 4）、`IrStore`（Task 3）、`PreconditionError`/`precondition_error`/`require_ir_ref`/`require_dts_ref`（Task 15）
- Produces（供 Task 18 的 `server.py` 注册使用；本任务中函数是纯 Python 函数，不带 `@server.tool()` 装饰器——装饰器在 Task 18 统一加）:
  - `build_tool_context(base_dir: pathlib.Path) -> ToolContext`（`ToolContext` 内部持有 `TaskStore`、`IrStore`、`dts_dir: Path`、`reports_dir: Path`）
  - `ingest_input(ctx: ToolContext, files: list[dict], project: str, soc: str | None = None, board: str | None = None) -> dict`
  - `extract_hardware_graph(ctx: ToolContext, task_id: str, page_range: list[int] | None = None) -> dict`
  - `identify_soc_mapping(ctx: ToolContext, task_id: str, soc: str) -> dict`
  - `generate_dts(ctx: ToolContext, task_id: str, scope: dict | None = None) -> dict`
  - `validate_dts(ctx: ToolContext, task_id: str) -> dict`
  - `repair_dts(ctx: ToolContext, task_id: str) -> dict`
  - `diff_dts(ctx: ToolContext, task_id: str, existing_dts_path: str) -> dict`
  - `explain_node(ctx: ToolContext, task_id: str, node_path: str) -> dict`

所有函数均返回按 spec 三节定义的字典结构；`task_id` 生成用 `TaskStore.create()` 的自动 uuid（不传 `task_id` 参数）。DTS 文本文件用简单文件读写（无需专门的 `DtsStore` 类，直接在 `tools.py` 内用 `ctx.dts_dir / task_id / f"v{n}.dts"` 路径规则，版本号复用 `IrStore` 里已验证的递增模式，但因逻辑简单且只服务一处调用点，不额外抽象成新类——YAGNI）。

- [ ] **Step 1: 写失败测试**

`tests/mcp_app/test_tools.py`:
```python
from pathlib import Path

import pytest

from dts_gen.mcp_app import tools
from tests.fixtures.make_pdf import make_minimal_pdf


@pytest.fixture()
def ctx(tmp_path: Path):
    return tools.build_tool_context(base_dir=tmp_path)


def test_ingest_input_creates_task_and_returns_page_count(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=2)

    result = tools.ingest_input(
        ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p", soc="sa8775p"
    )

    assert result["status"] == "created"
    assert "task_id" in result
    assert result["input_summary"] == [{"path": str(pdf_path), "pages": 2}]


def test_extract_hardware_graph_requires_existing_task(ctx):
    result = tools.extract_hardware_graph(ctx, task_id="does-not-exist")

    assert result["error"] == "task_not_found"


def test_extract_hardware_graph_transitions_to_extracted(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]

    result = tools.extract_hardware_graph(ctx, task_id=task_id)

    assert result["status"] == "extracted"
    assert result["ir_ref"] == "ir/v1.json"
    assert result["summary"] == {"components": 0, "nets": 0, "relations": 0}
    assert len(result["unresolved"]) == 1


def test_generate_dts_returns_precondition_error_without_extraction(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")

    result = tools.generate_dts(ctx, task_id=created["task_id"])

    assert result["error"] == "precondition_failed"
    assert result["missing"] == "ir_ref"


def test_full_happy_path_through_validate(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]

    tools.extract_hardware_graph(ctx, task_id=task_id)
    tools.identify_soc_mapping(ctx, task_id=task_id, soc="sa8775p")
    generated = tools.generate_dts(ctx, task_id=task_id)
    assert generated["status"] == "generated"
    assert generated["dts_ref"] == "dts/v1.dts"

    validated = tools.validate_dts(ctx, task_id=task_id)
    assert validated["status"] == "validated"
    assert validated["errors"] == []
    assert len(validated["warnings"]) == 1


def test_repair_dts_requires_dts_ref(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")

    result = tools.repair_dts(ctx, task_id=created["task_id"])

    assert result["error"] == "precondition_failed"
    assert result["missing"] == "dts_ref"


def test_diff_dts_returns_patch_against_existing_file(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]
    tools.extract_hardware_graph(ctx, task_id=task_id)
    tools.generate_dts(ctx, task_id=task_id)

    existing = tmp_path / "board.dts"
    existing.write_text("&usb_0 { status = \"disabled\"; };\n", encoding="utf-8")

    result = tools.diff_dts(ctx, task_id=task_id, existing_dts_path=str(existing))

    assert "patch" in result
    assert result["risk_notes"] == []


def test_explain_node_returns_empty_when_no_unresolved_match(ctx, tmp_path: Path):
    pdf_path = tmp_path / "schematic.pdf"
    make_minimal_pdf(pdf_path, pages=1)
    created = tools.ingest_input(ctx, files=[{"path": str(pdf_path), "type": "pdf"}], project="p")
    task_id = created["task_id"]
    tools.extract_hardware_graph(ctx, task_id=task_id)

    result = tools.explain_node(ctx, task_id=task_id, node_path="&usb_0")

    assert result["source_refs"] == []
    assert result["rule_ids"] == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/mcp_app/test_tools.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.mcp_app.tools'`

- [ ] **Step 3: 实现 tools.py**

`src/dts_gen/mcp_app/tools.py`:
```python
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from dts_gen.core.ir.store import IrStore
from dts_gen.core.pipeline.dts_generator import GenerationScope, generate_dts as _generate_dts
from dts_gen.core.pipeline.differ import diff_dts as _diff_dts
from dts_gen.core.pipeline.explainer import explain_node as _explain_node
from dts_gen.core.pipeline.hardware_extractor import extract_hardware_graph as _extract_hardware_graph
from dts_gen.core.pipeline.input_parser import InputFile, parse_input
from dts_gen.core.pipeline.repairer import repair_dts as _repair_dts
from dts_gen.core.pipeline.soc_mapper import map_to_soc
from dts_gen.core.pipeline.validator import validate_dts as _validate_dts
from dts_gen.core.task import TaskEvent, TaskInput, TaskNotFoundError, TaskStore
from dts_gen.mcp_app.errors import PreconditionError, generic_error, precondition_error, require_dts_ref, require_ir_ref


@dataclass
class ToolContext:
    task_store: TaskStore
    ir_store: IrStore
    dts_dir: Path
    reports_dir: Path


def build_tool_context(base_dir: Path) -> ToolContext:
    return ToolContext(
        task_store=TaskStore(base_dir=base_dir),
        ir_store=IrStore(base_dir=base_dir),
        dts_dir=base_dir,
        reports_dir=base_dir,
    )


def _timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _next_dts_version(ctx: ToolContext, task_id: str) -> int:
    dts_dir = ctx.dts_dir / task_id / "dts"
    if not dts_dir.exists():
        return 1
    versions = []
    for entry in dts_dir.glob("v*.dts"):
        try:
            versions.append(int(entry.stem[1:]))
        except ValueError:
            continue
    return (max(versions) + 1) if versions else 1


def _save_dts(ctx: ToolContext, task_id: str, dts_text: str) -> str:
    dts_dir = ctx.dts_dir / task_id / "dts"
    dts_dir.mkdir(parents=True, exist_ok=True)
    version = _next_dts_version(ctx, task_id)
    filename = f"v{version}.dts"
    (dts_dir / filename).write_text(dts_text, encoding="utf-8")
    return f"dts/{filename}"


def _load_dts(ctx: ToolContext, task_id: str, dts_ref: str) -> str:
    filename = dts_ref.split("/", 1)[1]
    return (ctx.dts_dir / task_id / "dts" / filename).read_text(encoding="utf-8")


def ingest_input(
    ctx: ToolContext,
    files: list[dict],
    project: str,
    soc: str | None = None,
    board: str | None = None,
) -> dict:
    input_files = [InputFile(path=f["path"], type=f["type"]) for f in files]
    try:
        parsed = parse_input(input_files)
    except FileNotFoundError as exc:
        return generic_error(None, "file_not_found", hint=f"input file not found: {exc}")

    task = ctx.task_store.create(project=project, soc=soc, board=board)
    task.inputs = [TaskInput(path=f.path, type=f.type) for f in input_files]
    ctx.task_store.save(task)

    pages_by_file: dict[str, int] = {}
    for page in parsed.pages:
        pages_by_file[page.source_path] = pages_by_file.get(page.source_path, 0) + 1

    return {
        "task_id": task.task_id,
        "status": task.status,
        "input_summary": [
            {"path": f.path, "pages": pages_by_file.get(f.path, 0)} for f in input_files
        ],
    }


def extract_hardware_graph(
    ctx: ToolContext, task_id: str, page_range: list[int] | None = None
) -> dict:
    try:
        task = ctx.task_store.get(task_id)
    except TaskNotFoundError:
        return generic_error(task_id, "task_not_found", hint=f"no such task: {task_id}")

    range_tuple = (page_range[0], page_range[1]) if page_range else None
    input_files = [InputFile(path=i.path, type=i.type) for i in task.inputs]
    parsed = parse_input(input_files) if input_files else None
    pages = parsed.pages if parsed else []
    result = _extract_hardware_graph(pages, page_range=range_tuple)

    ir_ref = ctx.ir_store.save(task_id, result.ir)
    task.ir_ref = ir_ref
    task.status = "extracted"
    ctx.task_store.save(task)
    ctx.task_store.append_event(
        task_id,
        TaskEvent(
            event_id=uuid.uuid4().hex[:12],
            tool="extract_hardware_graph",
            timestamp=_timestamp(),
            input_summary={"page_range": page_range},
            output_ref=ir_ref,
            status="ok",
            warnings=[],
        ),
    )

    return {
        "task_id": task_id,
        "status": "extracted",
        "ir_ref": ir_ref,
        "summary": {
            "components": len(result.ir.components),
            "nets": len(result.ir.nets),
            "relations": len(result.ir.relations),
        },
        "unresolved": [item.model_dump() for item in result.unresolved],
    }


def identify_soc_mapping(ctx: ToolContext, task_id: str, soc: str) -> dict:
    try:
        task = ctx.task_store.get(task_id)
    except TaskNotFoundError:
        return generic_error(task_id, "task_not_found", hint=f"no such task: {task_id}")

    try:
        ir_ref = require_ir_ref(task)
    except PreconditionError as exc:
        return precondition_error(task_id, exc.missing, exc.hint)

    ir = ctx.ir_store.load(task_id, ir_ref)
    result = map_to_soc(ir, soc=soc)

    new_ir_ref = ctx.ir_store.save(task_id, result.ir)
    task.ir_ref = new_ir_ref
    task.status = "mapped"
    ctx.task_store.save(task)
    ctx.task_store.append_event(
        task_id,
        TaskEvent(
            event_id=uuid.uuid4().hex[:12],
            tool="identify_soc_mapping",
            timestamp=_timestamp(),
            input_summary={"soc": soc},
            output_ref=new_ir_ref,
            status="ok",
            warnings=[],
        ),
    )

    return {
        "task_id": task_id,
        "status": "mapped",
        "ir_ref": new_ir_ref,
        "mapping_report": [entry.model_dump() for entry in result.mapping_report],
        "unresolved": [],
    }


def generate_dts(ctx: ToolContext, task_id: str, scope: dict | None = None) -> dict:
    try:
        task = ctx.task_store.get(task_id)
    except TaskNotFoundError:
        return generic_error(task_id, "task_not_found", hint=f"no such task: {task_id}")

    try:
        ir_ref = require_ir_ref(task)
    except PreconditionError as exc:
        return precondition_error(task_id, exc.missing, exc.hint)

    ir = ctx.ir_store.load(task_id, ir_ref)
    result = _generate_dts(ir, board=task.board, scope=GenerationScope(**(scope or {})))

    dts_ref = _save_dts(ctx, task_id, result.dts_text)
    task.dts_ref = dts_ref
    task.status = "generated"
    ctx.task_store.save(task)
    ctx.task_store.append_event(
        task_id,
        TaskEvent(
            event_id=uuid.uuid4().hex[:12],
            tool="generate_dts",
            timestamp=_timestamp(),
            input_summary={"scope": scope},
            output_ref=dts_ref,
            status="ok",
            warnings=[],
        ),
    )

    return {
        "task_id": task_id,
        "status": "generated",
        "dts_ref": dts_ref,
        "dts_text": result.dts_text,
        "node_sources": [ref.model_dump() for ref in result.node_sources],
    }


def validate_dts(ctx: ToolContext, task_id: str) -> dict:
    try:
        task = ctx.task_store.get(task_id)
    except TaskNotFoundError:
        return generic_error(task_id, "task_not_found", hint=f"no such task: {task_id}")

    try:
        dts_ref = require_dts_ref(task)
    except PreconditionError as exc:
        return precondition_error(task_id, exc.missing, exc.hint)

    dts_text = _load_dts(ctx, task_id, dts_ref)
    result = _validate_dts(dts_text)

    task.status = "validated"
    ctx.task_store.save(task)
    ctx.task_store.append_event(
        task_id,
        TaskEvent(
            event_id=uuid.uuid4().hex[:12],
            tool="validate_dts",
            timestamp=_timestamp(),
            input_summary={},
            output_ref=None,
            status="ok" if not result.errors else "warning",
            warnings=[w.message for w in result.warnings],
        ),
    )

    return {
        "task_id": task_id,
        "status": "validated",
        "report_ref": None,
        "errors": [e.model_dump() for e in result.errors],
        "warnings": [w.model_dump() for w in result.warnings],
    }


def repair_dts(ctx: ToolContext, task_id: str) -> dict:
    try:
        task = ctx.task_store.get(task_id)
    except TaskNotFoundError:
        return generic_error(task_id, "task_not_found", hint=f"no such task: {task_id}")

    try:
        dts_ref = require_dts_ref(task)
    except PreconditionError as exc:
        return precondition_error(task_id, exc.missing, exc.hint)

    dts_text = _load_dts(ctx, task_id, dts_ref)
    result = _repair_dts(dts_text, errors=[])

    new_dts_ref = _save_dts(ctx, task_id, result.dts_text)
    task.dts_ref = new_dts_ref
    task.status = "validated"
    ctx.task_store.save(task)
    ctx.task_store.append_event(
        task_id,
        TaskEvent(
            event_id=uuid.uuid4().hex[:12],
            tool="repair_dts",
            timestamp=_timestamp(),
            input_summary={},
            output_ref=new_dts_ref,
            status="ok",
            warnings=[],
        ),
    )

    return {
        "task_id": task_id,
        "status": "validated",
        "dts_ref": new_dts_ref,
        "applied_fixes": [f.model_dump() for f in result.applied_fixes],
    }


def diff_dts(ctx: ToolContext, task_id: str, existing_dts_path: str) -> dict:
    try:
        task = ctx.task_store.get(task_id)
    except TaskNotFoundError:
        return generic_error(task_id, "task_not_found", hint=f"no such task: {task_id}")

    try:
        dts_ref = require_dts_ref(task)
    except PreconditionError as exc:
        return precondition_error(task_id, exc.missing, exc.hint)

    existing_path = Path(existing_dts_path)
    if not existing_path.exists():
        return generic_error(task_id, "file_not_found", hint=f"existing dts not found: {existing_dts_path}")

    generated_text = _load_dts(ctx, task_id, dts_ref)
    existing_text = existing_path.read_text(encoding="utf-8")
    result = _diff_dts(existing_text, generated_text)

    return {
        "task_id": task_id,
        "patch": result.patch,
        "risk_notes": result.risk_notes,
    }


def explain_node(ctx: ToolContext, task_id: str, node_path: str) -> dict:
    try:
        task = ctx.task_store.get(task_id)
    except TaskNotFoundError:
        return generic_error(task_id, "task_not_found", hint=f"no such task: {task_id}")

    try:
        ir_ref = require_ir_ref(task)
    except PreconditionError as exc:
        return precondition_error(task_id, exc.missing, exc.hint)

    ir = ctx.ir_store.load(task_id, ir_ref)
    result = _explain_node(ir, node_path=node_path)

    return {
        "task_id": task_id,
        "source_refs": [ref.model_dump() for ref in result.source_refs],
        "rule_ids": result.rule_ids,
        "unresolved": [item.model_dump() for item in result.unresolved],
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/mcp_app/test_tools.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/mcp_app/tools.py tests/mcp_app/test_tools.py
git commit -m "feat: add 8 MCP tool wrapper functions routing to core pipeline"
```

---

## Task 17: Resources 与 Prompts 注册逻辑

**Files:**
- Create: `src/dts_gen/mcp_app/resources.py`
- Create: `src/dts_gen/mcp_app/prompts.py`
- Test: `tests/mcp_app/test_resources.py`
- Test: `tests/mcp_app/test_prompts.py`

**Interfaces:**
- Consumes: `SocRepo`, `BindingRepo`, `DeviceDb`, `StyleGuide`（Task 14）
- Produces（供 Task 18 使用）:
  - `KnowledgeContext(soc_repo: SocRepo, binding_repo: BindingRepo, device_db: DeviceDb, style_guide: StyleGuide)`
  - `build_knowledge_context(data_dir: pathlib.Path) -> KnowledgeContext`
  - `read_soc_dtsi(ctx: KnowledgeContext, soc: str) -> dict` — 返回 `{"soc": soc, "files": [...]}`
  - `read_binding(ctx: KnowledgeContext, compatible: str) -> dict` — 返回 schema 或 `{"error": "not_found", "compatible": compatible}`
  - `read_device(ctx: KnowledgeContext, part_number: str) -> dict` — 返回模板或 `{"error": "not_found", "part_number": part_number}`
  - `read_styleguide(ctx: KnowledgeContext) -> dict` — 返回 `{"content": "..."}`
  - `SCHEMATIC_UNDERSTANDING_PROMPT: str`
  - `DTS_GENERATION_PROMPT: str`
  - `ERROR_REPAIR_PROMPT: str`
  - `render_prompt(template: str, **variables: str) -> str` — 简单 `str.format(**variables)` 包装

- [ ] **Step 1: 写失败测试**

`tests/mcp_app/test_resources.py`:
```python
from pathlib import Path

from dts_gen.mcp_app.resources import build_knowledge_context, read_binding, read_device, read_soc_dtsi, read_styleguide


def test_read_soc_dtsi_returns_empty_files_when_no_data(tmp_path: Path):
    ctx = build_knowledge_context(data_dir=tmp_path)

    result = read_soc_dtsi(ctx, soc="sa8775p")

    assert result == {"soc": "sa8775p", "files": []}


def test_read_binding_returns_not_found_when_missing(tmp_path: Path):
    ctx = build_knowledge_context(data_dir=tmp_path)

    result = read_binding(ctx, compatible="snps,dwc3")

    assert result == {"error": "not_found", "compatible": "snps,dwc3"}


def test_read_device_returns_not_found_when_missing(tmp_path: Path):
    ctx = build_knowledge_context(data_dir=tmp_path)

    result = read_device(ctx, part_number="tusb2e11")

    assert result == {"error": "not_found", "part_number": "tusb2e11"}


def test_read_styleguide_returns_empty_content_when_missing(tmp_path: Path):
    ctx = build_knowledge_context(data_dir=tmp_path)

    result = read_styleguide(ctx)

    assert result == {"content": ""}
```

`tests/mcp_app/test_prompts.py`:
```python
from dts_gen.mcp_app.prompts import (
    DTS_GENERATION_PROMPT,
    ERROR_REPAIR_PROMPT,
    SCHEMATIC_UNDERSTANDING_PROMPT,
    render_prompt,
)


def test_schematic_understanding_prompt_forbids_direct_dts_writing():
    assert "DTS" in SCHEMATIC_UNDERSTANDING_PROMPT
    assert "{ir_summary}" not in SCHEMATIC_UNDERSTANDING_PROMPT  # 无变量的通用引导语


def test_dts_generation_prompt_has_ir_summary_placeholder():
    assert "{ir_summary}" in DTS_GENERATION_PROMPT


def test_error_repair_prompt_has_validate_report_placeholder():
    assert "{validate_report}" in ERROR_REPAIR_PROMPT


def test_render_prompt_substitutes_variables():
    rendered = render_prompt(DTS_GENERATION_PROMPT, ir_summary="5 components, 8 nets")

    assert "5 components, 8 nets" in rendered
    assert "{ir_summary}" not in rendered
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/mcp_app/test_resources.py tests/mcp_app/test_prompts.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.mcp_app.resources'`

- [ ] **Step 3: 实现 resources.py 和 prompts.py**

`src/dts_gen/mcp_app/resources.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dts_gen.core.knowledge.binding_repo import BindingRepo
from dts_gen.core.knowledge.device_db import DeviceDb
from dts_gen.core.knowledge.soc_repo import SocRepo
from dts_gen.core.knowledge.style_guide import StyleGuide


@dataclass
class KnowledgeContext:
    soc_repo: SocRepo
    binding_repo: BindingRepo
    device_db: DeviceDb
    style_guide: StyleGuide


def build_knowledge_context(data_dir: Path) -> KnowledgeContext:
    return KnowledgeContext(
        soc_repo=SocRepo(data_dir=data_dir),
        binding_repo=BindingRepo(data_dir=data_dir),
        device_db=DeviceDb(data_dir=data_dir),
        style_guide=StyleGuide(data_dir=data_dir),
    )


def read_soc_dtsi(ctx: KnowledgeContext, soc: str) -> dict:
    return {"soc": soc, "files": ctx.soc_repo.get_reference_dtsi(soc)}


def read_binding(ctx: KnowledgeContext, compatible: str) -> dict:
    schema = ctx.binding_repo.get_schema(compatible)
    if schema is None:
        return {"error": "not_found", "compatible": compatible}
    return schema


def read_device(ctx: KnowledgeContext, part_number: str) -> dict:
    template = ctx.device_db.lookup(part_number)
    if template is None:
        return {"error": "not_found", "part_number": part_number}
    return template


def read_styleguide(ctx: KnowledgeContext) -> dict:
    return {"content": ctx.style_guide.naming_rules()}
```

`src/dts_gen/mcp_app/prompts.py`:
```python
from __future__ import annotations

SCHEMATIC_UNDERSTANDING_PROMPT = """\
你正在识别一张硬件原理图。只输出结构化的器件、引脚、网络识别结果（Component/Net/Relation），
不要直接编写 devicetree 代码。对识别不确定的字段，明确标记为待确认项，不要猜测填充。
"""

DTS_GENERATION_PROMPT = """\
基于以下中间表示（IR）生成 devicetree 片段，严格依据 IR 和已有 binding 资源，
不可编造寄存器地址、IRQ 编号、GPIO 编号或 compatible 字符串。

IR 摘要：
{ir_summary}
"""

ERROR_REPAIR_PROMPT = """\
根据以下校验报告，对 devicetree 代码做最小化修复，不要修改与报告无关的节点。

校验报告：
{validate_report}
"""


def render_prompt(template: str, **variables: str) -> str:
    return template.format(**variables)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/mcp_app/test_resources.py tests/mcp_app/test_prompts.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/dts_gen/mcp_app/resources.py src/dts_gen/mcp_app/prompts.py tests/mcp_app/test_resources.py tests/mcp_app/test_prompts.py
git commit -m "feat: add Resources knowledge readers and Prompt templates"
```

---

## Task 18: MCP Server 入口（server.py）与 CLI

**Files:**
- Create: `src/dts_gen/mcp_app/server.py`
- Create: `src/dts_gen/cli.py`
- Test: `tests/mcp_app/test_server.py`

**Interfaces:**
- Consumes: 全部 `mcp_app/tools.py` 函数（Task 16）、`mcp_app/resources.py`/`prompts.py`（Task 17）
- Produces: `build_server(base_dir: pathlib.Path) -> MCPServer`；模块级 `main() -> None` 供 `pyproject.toml` 的 `[project.scripts]` 入口调用

本任务是唯一同时 import `mcp` SDK 和 `dts_gen.core`/`dts_gen.mcp_app.tools` 的文件（除 `tools.py`/`resources.py`/`prompts.py` 外，那三个文件本身也不 import mcp SDK——只有 `server.py` 做装饰器注册）。测试策略：不启动真实 stdio 循环（那是集成/手动验证范畴），只验证 `build_server` 返回的 `MCPServer` 实例上注册了预期数量和名称的 tools。

- [ ] **Step 1: 写失败测试**

`tests/mcp_app/test_server.py`:
```python
import asyncio
from pathlib import Path

from dts_gen.mcp_app.server import build_server


def test_server_registers_all_eight_tools(tmp_path: Path):
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
    }


def test_server_registers_four_resources(tmp_path: Path):
    server = build_server(base_dir=tmp_path)

    templates = asyncio.run(server.list_resource_templates())

    assert len(templates.resource_templates) == 4


def test_server_registers_three_prompts(tmp_path: Path):
    server = build_server(base_dir=tmp_path)

    prompts = asyncio.run(server.list_prompts())
    prompt_names = {p.name for p in prompts.prompts}

    assert prompt_names == {"schematic_understanding", "dts_generation", "error_repair"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/mcp_app/test_server.py -v`
Expected: FAIL，报 `ModuleNotFoundError: No module named 'dts_gen.mcp_app.server'`

- [ ] **Step 3: 实现 server.py**

`src/dts_gen/mcp_app/server.py`:
```python
from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer

from dts_gen.mcp_app import prompts as prompt_templates
from dts_gen.mcp_app import resources as knowledge
from dts_gen.mcp_app import tools


def build_server(base_dir: Path) -> MCPServer:
    server = MCPServer(name="dts-gen")

    tool_ctx = tools.build_tool_context(base_dir=base_dir)
    knowledge_ctx = knowledge.build_knowledge_context(data_dir=base_dir / "knowledge")

    @server.tool()
    def ingest_input(files: list[dict], project: str, soc: str | None = None, board: str | None = None) -> dict:
        return tools.ingest_input(tool_ctx, files=files, project=project, soc=soc, board=board)

    @server.tool()
    def extract_hardware_graph(task_id: str, page_range: list[int] | None = None) -> dict:
        return tools.extract_hardware_graph(tool_ctx, task_id=task_id, page_range=page_range)

    @server.tool()
    def identify_soc_mapping(task_id: str, soc: str) -> dict:
        return tools.identify_soc_mapping(tool_ctx, task_id=task_id, soc=soc)

    @server.tool()
    def generate_dts(task_id: str, scope: dict | None = None) -> dict:
        return tools.generate_dts(tool_ctx, task_id=task_id, scope=scope)

    @server.tool()
    def validate_dts(task_id: str) -> dict:
        return tools.validate_dts(tool_ctx, task_id=task_id)

    @server.tool()
    def repair_dts(task_id: str) -> dict:
        return tools.repair_dts(tool_ctx, task_id=task_id)

    @server.tool()
    def diff_dts(task_id: str, existing_dts_path: str) -> dict:
        return tools.diff_dts(tool_ctx, task_id=task_id, existing_dts_path=existing_dts_path)

    @server.tool()
    def explain_node(task_id: str, node_path: str) -> dict:
        return tools.explain_node(tool_ctx, task_id=task_id, node_path=node_path)

    @server.resource("soc://{soc}/dtsi/main")
    def soc_dtsi_resource(soc: str) -> dict:
        return knowledge.read_soc_dtsi(knowledge_ctx, soc=soc)

    @server.resource("binding://{compatible}")
    def binding_resource(compatible: str) -> dict:
        return knowledge.read_binding(knowledge_ctx, compatible=compatible)

    @server.resource("device://{part_number}")
    def device_resource(part_number: str) -> dict:
        return knowledge.read_device(knowledge_ctx, part_number=part_number)

    @server.resource("styleguide://naming")
    def styleguide_resource() -> dict:
        return knowledge.read_styleguide(knowledge_ctx)

    @server.prompt(name="schematic_understanding")
    def schematic_understanding_prompt() -> str:
        return prompt_templates.SCHEMATIC_UNDERSTANDING_PROMPT

    @server.prompt(name="dts_generation")
    def dts_generation_prompt(ir_summary: str) -> str:
        return prompt_templates.render_prompt(
            prompt_templates.DTS_GENERATION_PROMPT, ir_summary=ir_summary
        )

    @server.prompt(name="error_repair")
    def error_repair_prompt(validate_report: str) -> str:
        return prompt_templates.render_prompt(
            prompt_templates.ERROR_REPAIR_PROMPT, validate_report=validate_report
        )

    return server


def main() -> None:
    default_base_dir = Path.cwd() / ".dts-gen" / "tasks"
    server = build_server(base_dir=default_base_dir)
    server.run(transport="stdio")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/mcp_app/test_server.py -v`
Expected: 3 passed

若 `@server.resource("soc://{soc}/dtsi/main")` 装饰器要求 URI 模板参数名与函数参数名严格一致、或对 `list_resource_templates()` 返回结构与测试断言的 `templates.resource_templates` 属性名不符，以已安装的 `mcp==2.0.0` 包内 `mcp/server/mcpserver/server.py` 和 `mcp/server/mcpserver/resources.py` 源码为准调整装饰器调用方式和断言字段名，保持"4 个 resource、3 个 prompt、8 个 tool 全部注册成功"这一测试意图不变。

- [ ] **Step 5: 实现 CLI 入口**

`src/dts_gen/cli.py`:
```python
from __future__ import annotations

from dts_gen.mcp_app.server import main as run_server


def main() -> None:
    run_server()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 手动验证 stdio server 可启动**

Run: `python -c "from dts_gen.mcp_app.server import build_server; from pathlib import Path; s = build_server(Path('/tmp/dts-gen-manual-check')); print(s.name)"`
Expected: 输出 `dts-gen`，无异常抛出。

- [ ] **Step 7: Commit**

```bash
git add src/dts_gen/mcp_app/server.py src/dts_gen/cli.py tests/mcp_app/test_server.py
git commit -m "feat: wire MCP server entry point with all tools/resources/prompts"
```

---

## Task 19: 全量测试与端到端手动验证

**Files:**
- 无新文件，仅验证既有实现

**Interfaces:**
- 无新增接口，本任务是最终验收关卡

- [ ] **Step 1: 运行全量测试套件**

Run: `pytest -v`
Expected: 全部通过，无 skip、无 error（预计约 50+ 个测试用例，覆盖 Task 2-18 的全部单测）。

- [ ] **Step 2: 端到端手动验证完整 8 步工作流（不经过 MCP 协议，直接调用 core 函数验证链路）**

```bash
python << 'EOF'
from pathlib import Path
import shutil

from dts_gen.mcp_app import tools

base_dir = Path("/tmp/dts-gen-e2e-check")
shutil.rmtree(base_dir, ignore_errors=True)
ctx = tools.build_tool_context(base_dir=base_dir)

created = tools.ingest_input(
    ctx,
    files=[{"path": "SOM-6820_A101-2_20250520.pdf", "type": "pdf"}],
    project="e2e-check",
    soc="sa8775p",
)
print("ingest_input:", created)
task_id = created["task_id"]

extracted = tools.extract_hardware_graph(ctx, task_id=task_id)
print("extract_hardware_graph:", extracted)

mapped = tools.identify_soc_mapping(ctx, task_id=task_id, soc="sa8775p")
print("identify_soc_mapping:", mapped)

generated = tools.generate_dts(ctx, task_id=task_id)
print("generate_dts:", generated)

validated = tools.validate_dts(ctx, task_id=task_id)
print("validate_dts:", validated)

repaired = tools.repair_dts(ctx, task_id=task_id)
print("repair_dts:", repaired)

explained = tools.explain_node(ctx, task_id=task_id, node_path="&usb_0")
print("explain_node:", explained)
EOF
```

Expected: 依次打印 7 个步骤的输出字典，每一步 `status`/`error` 字段符合本计划 Task 16 的设计（`ingest_input` 返回真实页数、`extract_hardware_graph` 返回 `status: "extracted"` 且 `unresolved` 含"not implemented"提示、后续步骤依次进入 `mapped`/`generated`/`validated`，无未捕获异常）。此步骤使用仓库根目录已存在的真实 datasheet PDF（`SOM-6820_A101-2_20250520.pdf`），验证 `pypdf` 页数解析在真实文件上可用，而不仅是测试用的最小空白 PDF。

- [ ] **Step 3: 清理手动验证产生的临时目录**

Run: `rm -rf /tmp/dts-gen-e2e-check /tmp/dts-gen-manual-check /tmp/t.pdf`

- [ ] **Step 4: Commit（若前序步骤发现并修复了问题）**

若 Step 1/2 全部一次通过、无需修改代码，本步骤跳过（不产生空 commit）。若发现问题并修复，按 fix 提交：

```bash
git add -A
git commit -m "fix: address issues found in end-to-end verification"
```

---

## Self-Review Notes（供实施者参考，非待办）

- **Spec 覆盖检查**：一节（总体架构）→ Task 1；二节（状态机全部子节 2.1-2.7）→ Task 4/16；三节（8 个 Tool）→ Task 6-13（core 实现）+ Task 16（MCP 包装）；四节（Resources/Prompts）→ Task 14 + Task 17；五节（core/mcp 边界与测试策略）→ 贯穿全部 Task（`core/` 不 import `mcp`，`mcp_app/tools.py` 是唯一桥接点）；六节（后续任务列表）→ 均未在本计划中实现，符合 spec 范围声明。
- **命名一致性**：`ir_ref`/`dts_ref` 字段名、`TaskStatus` 取值、`Endpoint`/`Component`/`Net`/`Relation` 字段名在 Task 2 定义后，Task 6-18 全程复用，未出现改名。
- **包名说明**：spec 中写的目录名是 `mcp/`，本计划改为 `mcp_app/` 以避免与已安装的第三方 `mcp` PyPI 包重名导致的导入冲突——这是本计划对 spec 的一处必要工程调整，已在 File Structure 说明中注明。
