from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import func, update, exists, select, or_
from models.todo import Todo
from sqlalchemy.orm import aliased
from schemas.todo_v2 import (
    TodoCreateV2,
    TodoUpdateV2,
    TodoReorderItem,
)

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

    # 2️⃣ 初始化 per-user progress
    progress_map = {
        uid: 0 for uid in payload.assignee_ids
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
        assignee_ids=payload.assignee_ids,
        creator_id=payload.operator_id,
    )

    db.add(todo)
    db.commit()
    db.refresh(todo)
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
        new_assignees = set(payload.assignee_ids or [])

        # 1️⃣ 更新 assignee_ids
        todo.assignee_ids = list(new_assignees)

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
