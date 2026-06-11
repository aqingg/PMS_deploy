from pydantic import BaseModel
from typing import Dict, Any, List

class ProjectInfoUpdate(BaseModel):
    username: str
    department: str
    projectId: int
    projectName: str | None = None   # 兼容旧前端
    projectInfo: Dict[str, Any]

class WorkFlowUpdate(BaseModel):
    username: str
    department: str
    projectId: int
    projectName: str | None = None
    workflow: Dict[str, Any]

class CreateProjectRequest(BaseModel):
    username: str
    projectName: str
    department: str
    owner: str
    editors: list[str] | None = None
    comment: str = ""
    tags: List[str] = []

class ProjectMetaUpdate(BaseModel):
    username: str
    projectId: int
    projectName: str | None = None   # 保留兼容，但不再必需
    comment: str = ""
    tags: List[str] = []

class ProjectReorderRequest(BaseModel):
    username: str
    items: List[int]   # e.g. [3,1,4,2]

class ProjectDeleteRequest(BaseModel):
    username: str
    projectId: int