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
