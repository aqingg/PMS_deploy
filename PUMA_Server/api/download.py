# FASTAPI_SERVER/api/download.py
from fastapi import APIRouter
from fastapi.responses import FileResponse
from utils.path_config import DOWNLOADS_DIR
import os

router = APIRouter()

@router.get("/download/client")
def download_client():
    file_path = DOWNLOADS_DIR / "Client.exe"
    
    # 如果文件不存在，返回错误
    if not file_path.exists():
        return {"error": "Client.exe 未找到，请联系管理员"}

    return FileResponse(
        path=str(file_path),
        filename="Client.exe",
        media_type="application/octet-stream"
    )
