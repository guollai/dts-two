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
