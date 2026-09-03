import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Dict, List

from sqlalchemy.orm import Session
from sqlalchemy import func, update, exists, select, or_
from models.todo import Todo
from sqlalchemy.orm import aliased
from schemas.todo_v2 import (
    TodoCreateV2,
    TodoUpdateV2,
    TodoReorderItem,
)
from utils.path_config import BASE_RUNTIME_DIR


TODO_COMPLETION_MODES_PATH = BASE_RUNTIME_DIR / "todo_completion_modes.json"


def _load_completion_modes() -> Dict[str, str]:
    """Return valid persisted completion modes; old or missing data defaults to AND."""
    try:
        with TODO_COMPLETION_MODES_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}

    return {
        str(todo_id): mode
        for todo_id, mode in data.items()
        if mode in {"AND", "OR"}
    }


def get_completion_mode(todo_id: int) -> str:
    return _load_completion_modes().get(str(todo_id), "AND")


def _write_completion_modes(modes: Dict[str, str]) -> None:
    """Atomically replace the configuration file after a complete JSON write."""
    TODO_COMPLETION_MODES_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None

    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=TODO_COMPLETION_MODES_PATH.parent,
            prefix=f".{TODO_COMPLETION_MODES_PATH.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(modes, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporary_path, TODO_COMPLETION_MODES_PATH)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def set_completion_mode(todo_id: int, completion_mode: str) -> None:
    modes = _load_completion_modes()
    modes[str(todo_id)] = completion_mode
    _write_completion_modes(modes)

def is_creator_or_assignee(todo: Todo, operator_id: str) -> bool:
    if operator_id == todo.creator_id:
        return True
    return operator_id in (todo.assignee_ids or [])

# =========================
# List
# =========================
def list_todos(db: Session, operator_id: str) -> List[Todo]:
    je = func.json_each(Todo.assignee_ids).table_valued("value").alias("je")

    return (
        db.query(Todo)
        .filter(
            or_(
                Todo.creator_id == operator_id,
                exists(
                    select(1)
                    .select_from(je)
                    .where(je.c.value == operator_id)
                )
            )
        )
        .order_by(Todo.order_index.asc(), Todo.id.asc())
        .all()
    )

# =========================
# Create
# =========================
def create_todo(db: Session, payload: TodoCreateV2) -> Todo:
    # 1️⃣ 所有已有 Todo 后移一位
    db.execute(
        update(Todo)
        .values(order_index=Todo.order_index + 1)
    )

    # 创建者始终是 assignee；前端选择的是额外分配的成员。
    assignee_ids = list(dict.fromkeys([payload.operator_id, *payload.assignee_ids]))

    # 2️⃣ 初始化 per-user progress
    progress_map = {
        uid: 0 for uid in assignee_ids
    }
    # creator 也有自己的视角
    progress_map[payload.operator_id] = 0

     # 3️⃣ 新 Todo 插到最前
    todo = Todo(
        title=payload.title,
        due_date=payload.due_date,
        comment=payload.comment,
        tags=payload.tags,
        link=payload.link or "",
        progress=progress_map,
        order_index=1,                    # ⭐ 固定为第一个
        assignee_ids=assignee_ids,
        creator_id=payload.operator_id,
    )

    db.add(todo)
    db.commit()
    db.refresh(todo)
    set_completion_mode(todo.id, payload.completion_mode)
    return todo

# =========================
# Update
# =========================
def update_todo(db: Session, payload: TodoUpdateV2) -> Todo:
    print("=== [DEBUG] update_todo payload ===")
    print("payload.id =", payload.id)
    print("payload.operator_id =", payload.operator_id)
    print("payload.progress =", payload.progress, type(payload.progress))

    todo = db.get(Todo, payload.id)
    if not todo:
        raise ValueError("Todo not found")

    print("=== [DEBUG] before update ===")
    print("todo.progress =", todo.progress, type(todo.progress))

    if not is_creator_or_assignee(todo, payload.operator_id):
        raise PermissionError("No permission")

    for field in ["title", "due_date", "comment", "tags", "link"]:
        value = getattr(payload, field)
        if value is not None:
            setattr(todo, field, value)

    # =========================
    # Update assignee_ids + sync progress
    # =========================
    if payload.assignee_ids is not None:
        old_assignees = set(todo.assignee_ids or [])
        new_assignee_ids = list(dict.fromkeys([
            todo.creator_id,
            *payload.assignee_ids,
        ]))
        new_assignees = set(new_assignee_ids)

        # 1️⃣ 创建者始终保留在 assignee_ids 中
        todo.assignee_ids = new_assignee_ids

        # 2️⃣ 初始化 progress（兜底）
        if not isinstance(todo.progress, dict):
            todo.progress = {}

        # 3️⃣ 新增 assignee → progress = 0
        for uid in new_assignees - old_assignees:
            todo.progress[uid] = 0

        # 4️⃣ 移除 assignee → 删除 progress
        for uid in old_assignees - new_assignees:
            todo.progress.pop(uid, None)

        # 5️⃣ creator 永远保留自己的视角
        todo.progress.setdefault(todo.creator_id, 0)

    if payload.progress is not None:
        if not isinstance(todo.progress, dict):
            todo.progress = {}
        for user_id, value in payload.progress.items():
            todo.progress[user_id] = value

    print("=== [DEBUG] after merge (before commit) ===")
    print("todo.progress =", todo.progress, type(todo.progress))

    db.commit()
    db.refresh(todo)

    print("=== [DEBUG] after commit ===")
    print("todo.progress =", todo.progress, type(todo.progress))

    if payload.completion_mode is not None:
        set_completion_mode(todo.id, payload.completion_mode)

    return todo


# =========================
# Reorder
# =========================
def reorder_todos(db: Session, operator_id: str, items: List[TodoReorderItem]):
    ids = [i.id for i in items]

    todos = (
        db.query(Todo)
        .filter(Todo.id.in_(ids))
        .all()
    )

    for todo in todos:
        if not is_creator_or_assignee(todo, operator_id):
            raise PermissionError("No permission")

    index_map = {i.id: i.order_index for i in items}

    for todo in todos:
        todo.order_index = index_map[todo.id]

    db.commit()

# =========================
# Delete
# =========================
def delete_todo(db: Session, todo_id: int, operator_id: str):
    todo = db.query(Todo).get(todo_id)
    if not todo:
        return

    # V2: only creator can delete
    if operator_id != todo.creator_id:
        raise PermissionError("No permission")

    db.delete(todo)
    db.commit()
