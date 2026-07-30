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
