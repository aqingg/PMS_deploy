from fastapi import APIRouter, HTTPException
from utils.file_loader import load_template
from utils.file_loader import load_data_source
from utils.path_config import DATA_SOURCE_DIR

router = APIRouter(
    prefix="/template",
    tags=["Template API"]
)

# ------------------------------
# 1) 获取任务详情
# ------------------------------
@router.get("/getTaskDetail")
def get_task_detail(taskName: str):
    """
    从 templates/TaskDetailJob.json 查找指定任务详情
    """
    data = load_template("TaskDetailJob.json")

    for item in data:
        if item.get("taskName") == taskName:
            return item

    raise HTTPException(status_code=404, detail=f"Task '{taskName}' not found")


# ------------------------------
# 2) 获取 Unified 模板
# ------------------------------
@router.get("/getUnified")
def get_unified_template():
    """
    返回 unified.json（部门与任务树模板）
    """
    return load_template("unified.json")


# ------------------------------
# 3) 获取 Team Members
# ------------------------------
@router.get("/teamMembers")
def get_team_members():
    """
    返回 TeamMembers.json 中的成员信息
    - members：只包含 name
    - raw：完整条目（包含 account / mail）
    """
    data = load_template("TeamMembers.json")
    names = [item.get("name") for item in data if "name" in item]

    return {
        "success": True,
        "members": names,
        "raw": data
    }

# ------------------------------
# 4) 获取 Standard Links
# ------------------------------
@router.get("/standardLinks")
def get_standard_links():
    """
    返回系统预置的快捷链接（StandardLinks.json）
    Source: DB/data_source/StandardLinks.json
    """
    try:
        data = load_data_source("StandardLinks.json")
        links = data.get("links", [])
        return sorted(
           links,
           key=lambda l: l.get("title", "").lower()
       )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="StandardLinks.json not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
