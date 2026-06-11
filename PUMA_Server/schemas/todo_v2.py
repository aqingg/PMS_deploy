from datetime import date
from typing import List, Optional, Dict
from pydantic import BaseModel


# =========================
# Create
# =========================
class TodoCreateV2(BaseModel):
    title: str
    due_date: date
    comment: Optional[str] = ""
    tags: List[str] = []
    link: Optional[str] = ""

    assignee_ids: List[str]      # ⭐ 核心
    operator_id: str

# =========================
# Update
# =========================
class TodoUpdateV2(BaseModel):
    id: int
    operator_id: str

    title: Optional[str] = None
    due_date: Optional[date] = None
    comment: Optional[str] = None
    tags: Optional[List[str]] = None
    progress: Dict[str, int] = None
    link: Optional[str] = None
    assignee_ids: Optional[List[str]] = None
    
# =========================
# Reorder
# =========================
class TodoReorderItem(BaseModel):
    id: int
    order_index: int


class TodoReorderV2(BaseModel):
    operator_id: str
    items: List[TodoReorderItem]


# =========================
# Delete
# =========================
class TodoDeleteV2(BaseModel):
    id: int
    operator_id: str


# =========================
# Output
# =========================
class TodoOutV2(BaseModel):
    id: int
    title: str
    due_date: date
    comment: str
    tags: List[str]
    # progress per user: { user_id: progress }
    progress: Dict[str, int]
    order_index: int
    link: Optional[str] = ""

    assignee_ids: List[str]
    creator_id: str

    class Config:
        orm_mode = True
