from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models.database import get_db
from services.tcd08.report import generate_tcd08_report


router = APIRouter(prefix="/report", tags=["Report"])


class TCD08FillRequest(BaseModel):
    uuid: str
    projectid: Optional[int] = None
    projectId: Optional[int] = None
    taskId: Optional[str] = None
    project_info: Dict[str, Any] = Field(default_factory=dict)
    author: str = ""
    report_date: str = ""
    customer_release_email: str = ""

    # 兼容当前前端仍然会传的字段。
    # 后端现在从 FolderLinkMapping.json 解析模板和保存路径，不再信任请求体里的路径。
    template_paths: List[str] = Field(default_factory=list)
    save_path: str = ""


@router.post("/fillTCD08Report")
async def fill_tcd08_report(request: TCD08FillRequest, db: Session = Depends(get_db)):
    """TCD08 报告生成接口。

    这个 API 文件只保留 HTTP 层职责：
    - 接收并校验请求。
    - 传入数据库 session。
    - 调用 services.tcd08.report 中的生成流程。

    具体的模板路径解析、规则判断、Word 处理顺序都在 service 层完成。
    """
    if not request.uuid:
        raise HTTPException(status_code=400, detail="uuid is required")

    return await generate_tcd08_report(
        uuid=request.uuid,
        project_id=request.projectId or request.projectid,
        task_id=request.taskId,
        project_info=request.project_info,
        author=request.author,
        report_date=request.report_date,
        customer_release_email=request.customer_release_email,
        db=db,
    )
