from sqlalchemy import Column, Integer, String, Date, Text, JSON
from models.database import Base
from sqlalchemy.ext.mutable import MutableDict
class Todo(Base):
    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String(255), nullable=False)
    due_date = Column(Date, nullable=False)
    comment = Column(Text, default="")
    tags = Column(JSON, default=list)
    link = Column(String(512), default="")
    # progress per user: { user_id: progress }
    progress = Column(MutableDict.as_mutable(JSON), default=dict)
    order_index = Column(Integer, default=0)

    # ⭐ Todo V2 核心字段
    assignee_ids = Column(JSON, nullable=False, default=list)
    creator_id = Column(String(64), index=True, nullable=False)
