# api/database.py

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from datetime import datetime
import shutil
import logging

from models.database import get_db
from models.project import Project

import httpx
import json
from enum import Enum
from pathlib import Path
from sqlalchemy.orm import Session

from utils.path_config import DB_PATH, HISTORY_DIR, LOGS_DIR, BASE_RUNTIME_DIR

router = APIRouter(
    prefix="/database",
    tags=["Database Runtime API"]
)


def _timestamp():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _init_logger(log_file):
    logger = logging.getLogger("db_snapshot")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.FileHandler(str(log_file), encoding="utf-8")
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


@router.post("/snapshot")
def create_db_snapshot(mode: str = "manual"):
    """
    Create a full SQLite DB snapshot.

    mode:
      - manual (default)
      - reserved for future extension
    """

    if not DB_PATH.exists():
        raise HTTPException(status_code=500, detail="Database file not found")

    ts = _timestamp()

    if mode == "manual":
        db_name = f"app_manual_{ts}.db"
        log_name = f"app_manual_{ts}.log"
    else:
        db_name = f"app_{ts}.db"
        log_name = f"app_{ts}.log"

    db_snapshot_path = HISTORY_DIR / db_name
    log_path = LOGS_DIR / log_name

    logger = _init_logger(log_path)

    logger.info("DB snapshot started")
    logger.info(f"Source DB: {DB_PATH}")
    logger.info(f"Target DB: {db_snapshot_path}")

    try:
        shutil.copy2(DB_PATH, db_snapshot_path)
        logger.info("DB snapshot completed successfully")
    except Exception as e:
        logger.error(f"DB snapshot failed: {e}")
        raise HTTPException(status_code=500, detail="DB snapshot failed")

    return {
        "success": True,
        "snapshot": db_name,
        "log": log_name,
        "timestamp": ts
    }

def find_json_files() -> dict[str, str]:
    """
    动态扫描 DB 目录并返回所有 .json 文件的相对路径字典。
    """
    if not BASE_RUNTIME_DIR.is_dir():
        return {}
    
    json_files = BASE_RUNTIME_DIR.rglob('*.json')
    
    # 值是文件的相对路径字符串
    file_dict = {
        path.relative_to(BASE_RUNTIME_DIR).as_posix(): path.relative_to(BASE_RUNTIME_DIR).as_posix()
        for path in json_files
    }
    return file_dict

def validate_and_resolve_path(relative_path_str: str) -> Path:
    """
    一个健壮的安全函数，用于验证和解析路径。
    - 防止路径遍历攻击 (../)
    - 确保路径在允许的基目录内
    - 返回一个绝对路径对象
    """
    # 规范化路径，防止如 "data_source/../user_settings.json" 这样的路径
    # as_posix() 确保使用 '/' 作为分隔符
    normalized_path = Path(relative_path_str).as_posix()
    if ".." in normalized_path.split("/"):
        raise HTTPException(
            status_code=400,
            detail="Security Error: Path traversal ('..') is not allowed."
        )

    # 构造文件的绝对路径
    target_file_path = (BASE_RUNTIME_DIR / normalized_path).resolve()

    # 安全检查：确保解析后的路径仍在 BASE_RUNTIME_DIR 内部
    if BASE_RUNTIME_DIR.resolve() not in target_file_path.parents:
        raise HTTPException(
            status_code=400,
            detail="Security Error: Path is outside the allowed directory."
        )
    
    return target_file_path

async def validate_uploaded_json(uploaded_file: UploadFile) -> bytes:
    """
    读取上传的文件内容并验证其是否为有效的 JSON。
    """
    content_bytes = await uploaded_file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    
    try:
        json.loads(content_bytes)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Invalid file content: The uploaded file is not a valid JSON."
        )
    return content_bytes

@router.get("/editable_files", response_model=list[str])
async def get_editable_files():
    """
    获取当前所有可编辑的 JSON 文件列表。
    
    调用此接口以获取最新的文件列表，用于后续的更新或创建操作。
    """
    # 每次调用都重新扫描文件系统
    return list(find_json_files().keys())

@router.put("/update")
async def update_json_file(
    target_file: str = Form(..., description="要更新的目标文件的相对路径 (例如 'data_source/config.json')。"),
    content_bytes: bytes = Depends(validate_uploaded_json),
):
    """
    通过上传新文件来更新 DB 目录中指定的现有 JSON 文件。

    **使用流程:**
    1. 调用 `GET /database/editable_files` 获取可用文件列表。
    2. 将列表中的一个路径复制到 **target_file** 字段。
    3. 在 **uploaded_file** 处选择本地的 JSON 文件。
    4. 点击 "Execute"。
    """
    target_file_path = validate_and_resolve_path(target_file)

    if not target_file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"File not found: The target file '{target_file}' does not exist."
        )

    try:
        with open(target_file_path, "wb") as f:
            f.write(content_bytes)
    except IOError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to write to file: {e}"
        )

    return {
        "success": True,
        "message": f"Successfully updated file: {target_file}",
    }

@router.post("/create")
async def create_json_file(
    new_file_path: str = Form(..., description="要创建的新文件的相对路径 (例如 'new_folder/new_config.json')。必须以 .json 结尾。"),
    content_bytes: bytes = Depends(validate_uploaded_json),
):
    """
    在 DB 目录中创建一个新的 JSON 文件。

    如果目录不存在，将会自动创建。如果文件已存在，操作将失败。
    """
    if not new_file_path.endswith('.json'):
        raise HTTPException(status_code=400, detail="File path must end with .json")

    target_file_path = validate_and_resolve_path(new_file_path)

    if target_file_path.exists():
        raise HTTPException(
            status_code=409,  # 409 Conflict is appropriate for existing resources
            detail=f"File already exists: Cannot create '{new_file_path}'."
        )

    try:
        # 确保父目录存在
        target_file_path.parent.mkdir(parents=True, exist_ok=True)
        # 以二进制写入模式创建新文件
        with open(target_file_path, "wb") as f:
            f.write(content_bytes)
    except IOError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create file: {e}"
        )

    return {
        "success": True,
        "message": f"Successfully created new file: {new_file_path}",
    }

@router.get('/getinfo')
async def getinfo(projectid: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == projectid).first()

    if not project:
        raise HTTPException(status_code=404, detail=f"Project with id {projectid} not found")

    postbody = {
        'projectName': project.projectName
    }

    if project.projectInfo:
        try:
            additional_info = json.loads(project.projectInfo)
            
            if isinstance(additional_info, dict):
                postbody.update(additional_info)
            else:
                postbody['projectInfo'] = additional_info
        except json.JSONDecodeError:
            postbody['projectInfo_raw'] = project.projectInfo
            
    return postbody
    