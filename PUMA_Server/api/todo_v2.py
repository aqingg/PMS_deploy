from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.sse import event_bus
from models.database import get_db
from crud import todo_v2 as crud
from schemas.todo_v2 import (
    TodoCreateV2,
    TodoUpdateV2,
    TodoReorderV2,
    TodoDeleteV2,
    TodoOutV2,
)

router = APIRouter(prefix="/todo", tags=["TodoV2"])

# =========================
# List
# =========================
@router.get("/list", response_model=list[TodoOutV2])
def list_todos(operator_id: str, db: Session = Depends(get_db)):
    return crud.list_todos(db, operator_id)

# =========================
# Create
# =========================
@router.post("/create", response_model=TodoOutV2)
async def create_todo(payload: TodoCreateV2, db: Session = Depends(get_db)):

    todo = crud.create_todo(db, payload)

    await event_bus.publish({
        "event": "TodoCreated",
        "payload": {
            "id": todo.id,
            "creator_id": todo.creator_id,
            "assignee_ids": todo.assignee_ids,
        }
    })

    return todo

# =========================
# Update
# =========================
@router.post("/update", response_model=TodoOutV2)
async def update_todo(payload: TodoUpdateV2, db: Session = Depends(get_db)):
    try:
        todo = crud.update_todo(db, payload)
    except PermissionError:
        raise HTTPException(status_code=403, detail="No permission")
    except ValueError:
        raise HTTPException(status_code=404, detail="Todo not found")

    await event_bus.publish({
        "event": "TodoUpdated",
        "payload": {
            "id": todo.id
        }
    })

    return todo

# =========================
# Reorder
# =========================
@router.post("/reorder")
async def reorder_todos(payload: TodoReorderV2, db: Session = Depends(get_db)):
    try:
        crud.reorder_todos(db, payload.operator_id, payload.items)
    except PermissionError:
        raise HTTPException(status_code=403, detail="No permission")

    await event_bus.publish({
        "event": "TodoReordered",
        "payload": {
            "operator_id": payload.operator_id
        }
    })

    return {"success": True}

# =========================
# Delete
# =========================
@router.post("/delete")
async def delete_todo(payload: TodoDeleteV2, db: Session = Depends(get_db)):
    try:
        crud.delete_todo(db, payload.id, payload.operator_id)
    except PermissionError:
        raise HTTPException(status_code=403, detail="No permission")

    await event_bus.publish({
        "event": "TodoDeleted",
        "payload": {
            "id": payload.id
        }
    })
    return {"success": True}
