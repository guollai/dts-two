from __future__ import annotations

import functools
import inspect
import uuid
from dataclasses import dataclass
from pathlib import Path

from dts_gen.core.ir.store import IrStore
from dts_gen.core.knowledge.spec_sync.sync import spec_sync_cache_dir, sync_bindings as _sync_bindings
from dts_gen.core.pipeline.dts_generator import GenerationScope, generate_dts as _generate_dts
from dts_gen.core.pipeline.differ import diff_dts as _diff_dts
from dts_gen.core.pipeline.explainer import explain_node as _explain_node
from dts_gen.core.pipeline.hardware_extractor import extract_hardware_graph as _extract_hardware_graph
from dts_gen.core.pipeline.input_parser import InputFile, parse_input
from dts_gen.core.pipeline.repairer import repair_dts as _repair_dts
from dts_gen.core.pipeline.soc_mapper import map_to_soc
from dts_gen.core.pipeline.validator import validate_dts as _validate_dts
from dts_gen.core.task import Task, TaskEvent, TaskInput, TaskNotFoundError, TaskStore
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


def _get_task_or_error(ctx: ToolContext, task_id: str) -> tuple[Task | None, dict | None]:
    try:
        return ctx.task_store.get(task_id), None
    except TaskNotFoundError:
        return None, generic_error(task_id, "task_not_found", hint=f"no such task: {task_id}")


def _require_ir_ref_or_error(task_id: str, task: Task) -> tuple[str | None, dict | None]:
    try:
        return require_ir_ref(task), None
    except PreconditionError as exc:
        return None, precondition_error(task_id, exc.missing, exc.hint)


def _require_dts_ref_or_error(task_id: str, task: Task) -> tuple[str | None, dict | None]:
    try:
        return require_dts_ref(task), None
    except PreconditionError as exc:
        return None, precondition_error(task_id, exc.missing, exc.hint)


def _extract_task_id(func, args: tuple, kwargs: dict) -> str | None:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        return bound.arguments.get("task_id")
    except TypeError:
        return None


def _with_error_safety_net(func):
    """Safety net: converts any exception that escapes a tool body into a
    structured error dict and marks the task as failed, instead of letting it
    propagate raw to the MCP SDK layer.

    This does not replace the existing precondition-error handling inside each
    tool (those exceptions are already caught before reaching this decorator);
    it only catches whatever is left over (e.g. a corrupted IR file raising a
    pydantic ValidationError deep inside IrStore.load()).
    """

    @functools.wraps(func)
    def wrapper(ctx: ToolContext, *args, **kwargs):
        try:
            return func(ctx, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all safety net
            task_id = _extract_task_id(func, (ctx, *args), kwargs)

            task: Task | None = None
            if task_id is not None:
                try:
                    task = ctx.task_store.get(task_id)
                except Exception:
                    task = None

            if task is not None:
                task.status = "failed"
                task.history.append(
                    TaskEvent(
                        event_id=uuid.uuid4().hex[:12],
                        tool=func.__name__,
                        timestamp=_timestamp(),
                        input_summary={},
                        output_ref=None,
                        status="error",
                        warnings=[],
                        error=str(exc),
                    )
                )
                try:
                    ctx.task_store.save(task)
                except Exception:
                    pass

            return generic_error(task_id, "internal_error", hint=str(exc))

    return wrapper


@_with_error_safety_net
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


@_with_error_safety_net
def extract_hardware_graph(
    ctx: ToolContext, task_id: str, page_range: list[int] | None = None
) -> dict:
    task, error = _get_task_or_error(ctx, task_id)
    if error is not None:
        return error

    range_tuple = (page_range[0], page_range[1]) if page_range else None
    input_files = [InputFile(path=i.path, type=i.type) for i in task.inputs]
    parsed = parse_input(input_files) if input_files else None
    pages = parsed.pages if parsed else []
    result = _extract_hardware_graph(pages, page_range=range_tuple)

    # ExtractResult.unresolved is a sibling field of ExtractResult.ir, not part of
    # the IR itself (result.ir.unresolved is always []). Merge it into the IR before
    # persisting so downstream tools like explain_node (which search ir.unresolved)
    # can find these items later.
    result.ir.unresolved = result.ir.unresolved + result.unresolved

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


@_with_error_safety_net
def identify_soc_mapping(ctx: ToolContext, task_id: str, soc: str) -> dict:
    task, error = _get_task_or_error(ctx, task_id)
    if error is not None:
        return error

    ir_ref, error = _require_ir_ref_or_error(task_id, task)
    if error is not None:
        return error

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
        "unresolved": [item.model_dump() for item in result.ir.unresolved],
    }


@_with_error_safety_net
def generate_dts(ctx: ToolContext, task_id: str, scope: dict | None = None) -> dict:
    task, error = _get_task_or_error(ctx, task_id)
    if error is not None:
        return error

    ir_ref, error = _require_ir_ref_or_error(task_id, task)
    if error is not None:
        return error

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
        "unresolved": [item.model_dump() for item in result.unresolved],
    }


@_with_error_safety_net
def validate_dts(ctx: ToolContext, task_id: str) -> dict:
    task, error = _get_task_or_error(ctx, task_id)
    if error is not None:
        return error

    dts_ref, error = _require_dts_ref_or_error(task_id, task)
    if error is not None:
        return error

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


@_with_error_safety_net
def repair_dts(ctx: ToolContext, task_id: str) -> dict:
    task, error = _get_task_or_error(ctx, task_id)
    if error is not None:
        return error

    dts_ref, error = _require_dts_ref_or_error(task_id, task)
    if error is not None:
        return error

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


@_with_error_safety_net
def diff_dts(ctx: ToolContext, task_id: str, existing_dts_path: str) -> dict:
    task, error = _get_task_or_error(ctx, task_id)
    if error is not None:
        return error

    dts_ref, error = _require_dts_ref_or_error(task_id, task)
    if error is not None:
        return error

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


@_with_error_safety_net
def explain_node(ctx: ToolContext, task_id: str, node_path: str) -> dict:
    task, error = _get_task_or_error(ctx, task_id)
    if error is not None:
        return error

    ir_ref, error = _require_ir_ref_or_error(task_id, task)
    if error is not None:
        return error

    ir = ctx.ir_store.load(task_id, ir_ref)
    result = _explain_node(ir, node_path=node_path)

    return {
        "task_id": task_id,
        "source_refs": [ref.model_dump() for ref in result.source_refs],
        "rule_ids": result.rule_ids,
        "unresolved": [item.model_dump() for item in result.unresolved],
    }


def sync_bindings(ctx: ToolContext) -> dict:
    cache_dir = spec_sync_cache_dir(ctx.dts_dir.parent)
    reports = _sync_bindings(cache_dir)
    return {"reports": [report.model_dump() for report in reports]}
