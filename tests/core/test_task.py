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
