from threading import Thread
import pystray
from PIL import Image
import sys
# client.py

import dataprovider_pb2
from google.protobuf.json_format import MessageToDict

from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, Response, status, Body

from fastapi.middleware.cors import CORSMiddleware
import getpass
import uvicorn
import os
import shutil
import json
import webbrowser
import subprocess
import platform
import time
import socket
import cgi
import base64
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from typing import List
import requests

# ---- 强制前置窗口依赖 ----
import win32gui
import win32con
import win32process

from fastapi import Query
from urllib.parse import urlparse, unquote
from pydantic import BaseModel


def show_error_box(title: str, message: str):
    """Show a visible Windows error dialog for startup failures."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        pass


def write_startup_log(message: str):
    """Write startup diagnostics to a local log file for no-console exe mode."""
    try:
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(base, "client_startup.log")
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def is_port_in_use(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False
# =================================================================================
# ⭐ PyInstaller 资源路径兼容函数（必须添加）
# =================================================================================
def resource_path(relative_path):
    """确保 PyInstaller 打包后也能找到图标文件"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# =================================================================================
# 托盘退出逻辑
# =================================================================================
def on_exit(icon, item):
    icon.stop()
    os._exit(0)  # 完整退出 python 程序

# =================================================================================
# 托盘逻辑（自动加载 icon）
# =================================================================================
tray_icon = None  # ⭐ 全局保存图标引用，防止被回收
def run_tray():
    global tray_icon  # ⭐ 使用全局变量保存 Icon

    try:
        icon_image = Image.open(resource_path("favicon.ico"))
    except Exception as e:
        write_startup_log(f"Failed to load tray icon: {e}")
        show_error_box("PUMA Client 启动失败", f"托盘图标加载失败:\n{e}\n\n请查看同目录 client_startup.log")
        return

    tray_icon = pystray.Icon(
        "PUMA Client",
        icon_image,
        "PUMA Client",
        menu=pystray.Menu(
            pystray.MenuItem("Exit", on_exit)
        )
    )

    # ⭐ setup 回调：图标准备好之后会在内部线程里调用
    def on_ready(icon):
        # 可选：确保图标可见（一般会自动）
        icon.visible = True
        # 弹一次气泡通知
        icon.notify("PUMA Client is working!", "PUMA Client")

    # ⭐ 用 run(setup=...)，主线程阻塞在托盘循环里，最稳定
    tray_icon.run(setup=on_ready)

# =================================================================================
# FastAPI App
# =================================================================================
app = FastAPI(
    title="PUMA Client",
    description="本地服务：用户目录、打开路径、复制路径等",
    version="2.0.0"
)

class ReportRequest(BaseModel):
    projectid: str
    url: str
    template_paths: List[str]
    save_path: str


class CreateFoldersRequest(BaseModel):
    folders: List[str] = Field(
        default_factory=list,
        description="Absolute folder paths to create on the local machine.",
    )


# =================================================================================
# TCD08 本地适配层配置
# =================================================================================
# 生产环境默认指向服务器 8086 的对外地址；如本地调试，可在启动 Client 前设置环境变量：
#   set PUMA_SERVER_TCD08_URL=http://127.0.0.1:8086/app-puma/report/fillTCD08Report
DEFAULT_SERVER_BASE_URL = os.environ.get(
    "PUMA_SERVER_BASE_URL",
    "https://oss-dthub.apac.bosch.com/app-puma",
).rstrip("/")

DEFAULT_SERVER_TCD08_URL = os.environ.get(
    "PUMA_SERVER_TCD08_URL",
    f"{DEFAULT_SERVER_BASE_URL}/report/fillTCD08Report",
)


def _norm_path(value: str) -> Path:
    """Normalize a Windows local path for operations on the user's machine."""
    if not value or not str(value).strip():
        raise ValueError("path is empty")
    return Path(os.path.normpath(str(value).strip()))


def _derive_tcd08_email_dir(save_path: str) -> Path:
    """
    Derive Customer_Approval_Email from the frontend-provided TCD08 save_path.

    Expected save_path:
      ...\C.Calibration\{CalibrationID}\06_Official_Release\TCD08_Report

    Derived email_dir:
      ...\C.Calibration\{CalibrationID}\03_Results\Customer_Approval_Email
    """
    output_dir = _norm_path(save_path)
    parts_lower = [p.lower() for p in output_dir.parts]

    if "06_official_release" in parts_lower:
        idx = parts_lower.index("06_official_release")
        calibration_root = Path(*output_dir.parts[:idx])
    elif output_dir.name.lower() == "tcd08_report":
        calibration_root = output_dir.parent.parent
    else:
        # Fallback: assume save_path is under the CalibrationID root or one level below it.
        calibration_root = output_dir.parent

    if not str(calibration_root) or str(calibration_root) == ".":
        raise ValueError(f"Cannot derive calibration root from save_path: {save_path}")

    return calibration_root / "03_Results" / "Customer_Approval_Email"


def _collect_upload_files(folder: Path):
    """Collect files directly under folder for upload to the 8086 server."""
    if not folder.exists():
        raise HTTPException(status_code=404, detail=f"Email folder not found: {folder}")
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Email path is not a folder: {folder}")

    files = []
    handles = []

    for file_path in folder.iterdir():
        if not file_path.is_file():
            continue
        if file_path.name.startswith("~$"):
            continue

        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        fh = open(file_path, "rb")
        handles.append(fh)
        files.append(("email_files", (file_path.name, fh, mime_type)))

    if not files:
        raise HTTPException(status_code=404, detail=f"No files found in email folder: {folder}")

    return files, handles


def _filename_from_response(response: requests.Response, fallback: str = "TCD08_Report.docx") -> str:
    cd = response.headers.get("content-disposition") or response.headers.get("Content-Disposition")
    if cd:
        _, params = cgi.parse_header(cd)
        filename = params.get("filename") or params.get("filename*")
        if filename:
            filename = os.path.basename(str(filename).strip().strip('"'))
            if filename:
                return filename
    return fallback


def _save_binary_response(response: requests.Response, output_dir: Path, fallback_name: str = "TCD08_Report.docx") -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = _filename_from_response(response, fallback=fallback_name)
    save_path = output_dir / filename
    with open(save_path, "wb") as f:
        f.write(response.content)
    return str(save_path)


def _save_json_report_payload(data: dict, output_dir: Path):
    """
    Support JSON-style server responses if the 8086 endpoint returns base64 or download_url.
    Preferred future response remains binary FileResponse.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_paths = []

    # Case 1: {"filename": "x.docx", "content_base64": "..."}
    if data.get("content_base64"):
        filename = os.path.basename(data.get("filename") or "TCD08_Report.docx")
        save_path = output_dir / filename
        with open(save_path, "wb") as f:
            f.write(base64.b64decode(data["content_base64"]))
        saved_paths.append(str(save_path))

    # Case 2: {"files": [{"filename": "x.docx", "content_base64": "..."}, ...]}
    for item in data.get("files") or []:
        if not isinstance(item, dict):
            continue
        if not item.get("content_base64"):
            continue
        filename = os.path.basename(item.get("filename") or "TCD08_Report.docx")
        save_path = output_dir / filename
        with open(save_path, "wb") as f:
            f.write(base64.b64decode(item["content_base64"]))
        saved_paths.append(str(save_path))

    return saved_paths

# =================================================================================
# CORS 设置
# =================================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://cccn.apac.bosch.com",
        "https://cccn.apac.bosch.com/APP-PMS-GATE",
        "https://cccn.apac.bosch.com/APP-PMS-Project",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =================================================================================
# ✨ 工具：返回用户目录
# =================================================================================


BASE_DIR = r"C:\AppTools\00.APP-PMS"

def get_user_dir():
    username = getpass.getuser()
    user_dir = os.path.join(BASE_DIR, username)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


# =================================================================================
# ✨ Explorer 强制前置逻辑（文件夹 & 文件）
# =================================================================================
def bring_to_front_by_pid(pid: int):
    """根据 PID 找窗口并强制前置"""
    hwnds = []

    def enum_handler(hwnd, result):
        tid, window_pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid == window_pid and win32gui.IsWindowVisible(hwnd):
            result.append(hwnd)

    win32gui.EnumWindows(enum_handler, hwnds)

    if hwnds:
        hwnd = hwnds[0]
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return True
    return False

def bring_explorer_to_front_by_title(title_keyword: str):
    """根据窗口标题强制前置 Explorer"""
    hwnds = []

    def enum_handler(hwnd, result):
        if win32gui.IsWindowVisible(hwnd):
            text = win32gui.GetWindowText(hwnd)
            if title_keyword.lower() in text.lower():
                result.append(hwnd)

    win32gui.EnumWindows(enum_handler, hwnds)

    if hwnds:
        hwnd = hwnds[0]
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return True
    return False

def open_in_explorer(path: str):
    """打开文件夹或文件并前置 Explorer"""
    subprocess.Popen(["explorer", path])
    time.sleep(0.5)  # 等待窗口更新

    # 用文件夹名匹配窗口标题
    folder_name = os.path.basename(path.rstrip("\\/"))

    ok = bring_explorer_to_front_by_title(folder_name)
    if ok:
        return "Opened in Explorer (foreground OK)"
    else:
        return "Opened but could not force foreground"


# =================================================================================
# ✨ URL/文件/文件夹 三合一打开工具
# =================================================================================
def is_url(path: str) -> bool:
    try:
        r = urlparse(path)
        return all([r.scheme, r.netloc])
    except:
        return False


def open_resource(path: str):
    """自动判断并打开资源（URL / 文件夹 / 文件）"""

    # URL → 浏览器
    if is_url(path):
        webbrowser.open(path)
        return "Opened URL in default browser"

    # Windows 针对 文件夹 & 文件
    if platform.system() == "Windows":

        # ⭐ 新增：如果路径不存在 → 自动创建
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as e:
                return f"Failed to create folder: {e}"

        # 文件夹
        if os.path.isdir(path):
            return open_in_explorer(path)

        # 文件
        elif os.path.isfile(path):
            return open_in_explorer(path)

    # Linux / Mac 简单兼容
    cmd = "open" if platform.system() == "Darwin" else "xdg-open"
    subprocess.Popen([cmd, path])
    return "Opened resource"

def is_web_url(value: str) -> bool:
    try:
        r = urlparse(value.strip())
        return r.scheme in ("http", "https")
    except:
        return False

def is_file_url(value: str) -> bool:
    try:
        r = urlparse(value.strip())
        return r.scheme == "file"
    except:
        return False

def file_url_to_path(file_url: str) -> str:
    # file:///C:/a/b.txt -> C:\a\b.txt
    r = urlparse(file_url)
    p = unquote(r.path)

    if platform.system() == "Windows":
        # 处理 /C:/... 这种开头
        if p.startswith("/") and len(p) >= 3 and p[2] == ":":
            p = p[1:]
        p = p.replace("/", "\\")
    return p

def open_link(link: str) -> str:
    link = link.strip()

    # 1) http/https -> browser
    if is_web_url(link):
        webbrowser.open(link)
        return "Opened web URL in default browser"

    # 2) file:// -> 转成本地路径再处理
    if is_file_url(link):
        link = file_url_to_path(link)

    # 3) 本地路径（文件/文件夹）
    if platform.system() == "Windows":
        # 文件夹
        if os.path.isdir(link):
            subprocess.Popen(["explorer", os.path.normpath(link)])
            return "Opened folder in Explorer"

        # 文件：用默认程序打开（最符合“open”的语义）
        if os.path.isfile(link):
            os.startfile(os.path.normpath(link))
            return "Opened file with default application"

        # 不存在/不可识别
        return "Not found: path does not exist"

    # macOS / Linux 兜底
    if os.path.exists(link):
        cmd = "open" if platform.system() == "Darwin" else "xdg-open"
        subprocess.Popen([cmd, link])
        return "Opened local resource"
    else:
        # 最后兜底：当作 URL 尝试（例如自定义协议）
        try:
            webbrowser.open(link)
            return "Tried opening as URL/protocol"
        except:
            return "Not found: resource does not exist"


# =================================================================================
# ✨ API：打开路径
# =================================================================================
@app.get("/userinfo")
def get_user_info():
    username = getpass.getuser()
    return {
        "machine_id": username.upper()
    }

@app.get("/openPath")
def api_open_path(path: str):
    if not path:
        return {"success": False, "message": "path is required"}

    try:
        msg = open_resource(path)
        return {"success": True, "message": msg, "path": path}
    except Exception as e:
        return {"success": False, "error": str(e), "path": path}

OFFICE_FILE_EXTENSIONS = (
    '.doc', '.docx', 
    'docm',
    '.xls', '.xlsx',
    '.ppt', '.pptx'
)

@app.get("/getOfficeFiles", response_model=List[str])
def getOfficeFiles(folder_path: str):
    # 1. 验证路径是否存在且为文件夹
    if not os.path.isdir(folder_path):
        raise HTTPException(
            status_code=404,
            detail=f"文件夹未找到: {folder_path}"
        )

    found_files = []
    try:
        # 2. 遍历文件夹中的所有项目
        for item_name in os.listdir(folder_path):
            # 3. 检查文件扩展名（不区分大小写）
            if item_name.lower().endswith(OFFICE_FILE_EXTENSIONS):
                full_path = os.path.join(folder_path, item_name)
                # 4. 确保它是一个文件，而不是一个碰巧有类似扩展名的文件夹
                if os.path.isfile(full_path):
                    found_files.append(full_path)
    except Exception as e:
        # 5. 处理读取目录时可能出现的权限错误等问题
        raise HTTPException(
            status_code=500,
            detail=f"读取目录时出错: {e}"
        )

    # 6. 返回找到的文件路径列表
    return found_files

@app.post("/saveReport")
def save_report_on_server(request: ReportRequest):
    files_to_upload = []
    try:
        # 准备要上传的文件列表
        for path in request.template_paths:
            try:
                # 以二进制读取模式打开文件
                file_content = open(path, 'rb')
                file_name = os.path.basename(path) # 使用 os.path.basename 更可靠
                files_to_upload.append(('files', (file_name, file_content, 'application/octet-stream')))
            except FileNotFoundError:
                raise HTTPException(
                    status_code=404,
                    detail=f"模板文件未在服务器上找到: {path}"
                )

        if not files_to_upload:
            raise HTTPException(status_code=400, detail="没有提供任何有效的模板路径。")

        # 发送POST请求到文件处理服务
        proxies = {
        "http": None,
        "https": None,
        }
        response = requests.post(request.url, data={"projectid": request.projectid }, files=files_to_upload, proxies=proxies, verify=False)

        # 对下游服务的响应进行健壮性检查
        if response.status_code == 200:
            # a. 从响应头中获取文件名，提供默认值
            content_disposition = response.headers.get('content-disposition')
            if content_disposition and 'filename=' in content_disposition:
                filename = content_disposition.split('filename=')[-1].strip('"')
            else:
                filename = "generated_report.zip" # 如果没有获取到，使用默认文件名

            # b. 构造完整的文件保存路径
            full_save_path = os.path.join(request.save_path, filename)

            # c. 确保目标目录存在，如果不存在则创建
            try:
                os.makedirs(request.save_path, exist_ok=True)
            except OSError as e:
                # 如果因为权限等问题无法创建目录，则抛出异常
                raise HTTPException(status_code=500, detail=f"无法创建目录 '{request.save_path}': {e}")

            # d. 将响应内容以二进制模式写入文件
            try:
                with open(full_save_path, 'wb') as f:
                    f.write(response.content)
            except IOError as e:
                # 如果因为权限或磁盘空间问题无法写入，则抛出异常
                raise HTTPException(status_code=500, detail=f"无法写入文件到 '{full_save_path}': {e}")
            
            # e. 返回一个成功的JSON响应，告知客户端文件已保存
            return {
                "status": "success",
                "message": "报告已成功生成并保存。",
                "saved_path": full_save_path
            }
        else:
            # 将下游服务的错误信息透传给前端
            raise HTTPException(
                status_code=response.status_code,
                detail=f"文件处理服务调用失败: {response.text}"
            )

    except requests.exceptions.RequestException as e:
        # 网络或连接错误
        raise HTTPException(
            status_code=502, # 502 Bad Gateway
            detail=f"无法连接到文件处理服务: {e}"
        )
    finally:
        # --- 3. 改进的资源管理 ---
        # 确保所有打开的文件句柄都被关闭，无论成功或失败
        for _, file_tuple in files_to_upload:
            # file_tuple is (filename, file_content_object, content_type)
            if file_tuple and len(file_tuple) > 1 and not file_tuple[1].closed:
                file_tuple[1].close()

# =================================================================================
# ✨ API：复制路径
# =================================================================================
@app.get("/copyPath")
def api_copy_path(path: str):
    if not path:
        return {"success": False, "message": "path is required"}

    try:
        if platform.system() == "Windows":
            os.system(f'echo {path.strip()} | clip')
            return {"success": True, "message": "Path copied to clipboard", "path": path}

        return {"success": False, "message": "Copy only supported on Windows."}

    except Exception as e:
        return {"success": False, "error": str(e), "path": path}


@app.post("/createFolders")
def api_create_folders(req: CreateFoldersRequest):
    folders = [str(folder).strip() for folder in req.folders if str(folder).strip()]

    if not folders:
        raise HTTPException(status_code=400, detail="folders is required")

    created_folders = []

    try:
        for folder in folders:
            path = Path(folder)
            path.mkdir(parents=True, exist_ok=True)
            created_folders.append(str(path))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create local folder '{folder}': {exc}",
        ) from exc

    return {
        "success": True,
        "message": "Folders created on local client",
        "folders": created_folders,
    }



@app.post("/report/fillTCD08Report")
def client_fill_tcd08_report(payload: dict = Body(...)):
    """
    TCD08 local adapter.

    Correct architecture:
      Browser -> 7175 Client -> 8086 Server -> 7175 saves to user's C drive.

    This endpoint receives the same JSON body previously sent to the 8086 server.
    It reads local Customer_Approval_Email files, uploads them to 8086, receives the
    generated report, and saves it to the local TCD08_Report directory.
    """
    try:
        save_path_raw = payload.get("save_path") or payload.get("output_path")
        if not save_path_raw:
            raise HTTPException(status_code=400, detail="save_path is required")

        output_dir = _norm_path(save_path_raw)
        email_dir_raw = payload.get("email_dir") or payload.get("email_path")
        email_dir = _norm_path(email_dir_raw) if email_dir_raw else _derive_tcd08_email_dir(str(output_dir))

        server_report_url = (
            payload.get("server_report_url")
            or payload.get("backend_report_url")
            or payload.get("target_report_url")
            or DEFAULT_SERVER_TCD08_URL
        )

        print("=" * 80)
        print("[TCD08 Client] Start local TCD08 fill")
        print(f"[TCD08 Client] server_report_url = {server_report_url}")
        print(f"[TCD08 Client] email_dir         = {email_dir}")
        print(f"[TCD08 Client] output_dir        = {output_dir}")
        print("=" * 80)

        files, handles = _collect_upload_files(email_dir)

        # Send form-data to the 8086 server. Complex objects are serialized as JSON strings.
        data = {}
        for key, value in payload.items():
            if key in {
                "template_paths",
                "save_path",
                "output_path",
                "email_dir",
                "email_path",
                "server_report_url",
                "backend_report_url",
                "target_report_url",
            }:
                continue

            if isinstance(value, (dict, list)):
                data[key] = json.dumps(value, ensure_ascii=False)
            elif value is None:
                data[key] = ""
            else:
                data[key] = str(value)

        # Compatibility aliases for backend parameter naming.
        if "projectId" not in data and payload.get("projectId") is not None:
            data["projectId"] = str(payload.get("projectId"))
        if "projectid" not in data and payload.get("projectid") is not None:
            data["projectid"] = str(payload.get("projectid"))
        if "taskId" not in data and payload.get("taskId") is not None:
            data["taskId"] = str(payload.get("taskId"))

        try:
            response = requests.post(
                server_report_url,
                data=data,
                files=files,
                verify=False,
                timeout=600,
            )
        finally:
            for fh in handles:
                try:
                    fh.close()
                except Exception:
                    pass

        if response.status_code < 200 or response.status_code >= 300:
            detail = response.text[:2000] if response.text else response.reason
            raise HTTPException(
                status_code=response.status_code,
                detail=f"8086 TCD08 report generation failed: {detail}",
            )

        content_type = (response.headers.get("content-type") or "").lower()

        # Preferred: server returns FileResponse / binary report.
        if "application/json" not in content_type:
            saved_path = _save_binary_response(response, output_dir)
            return {
                "success": True,
                "message": "TCD08 report generated and saved by local client",
                "email_dir": str(email_dir),
                "output_dir": str(output_dir),
                "saved_path": saved_path,
            }

        # Compatibility: server returns JSON with base64 content or a normal status payload.
        try:
            json_data = response.json()
        except Exception:
            saved_path = _save_binary_response(response, output_dir)
            return {
                "success": True,
                "message": "TCD08 report generated and saved by local client",
                "email_dir": str(email_dir),
                "output_dir": str(output_dir),
                "saved_path": saved_path,
            }

        saved_paths = _save_json_report_payload(json_data, output_dir)
        if saved_paths:
            return {
                "success": True,
                "message": "TCD08 report generated and saved by local client",
                "email_dir": str(email_dir),
                "output_dir": str(output_dir),
                "saved_paths": saved_paths,
                "server_response": json_data,
            }

        # If server only returns JSON status, pass it through for debugging.
        return {
            "success": bool(json_data.get("success", True)),
            "message": json_data.get("message", "8086 returned JSON without report binary"),
            "email_dir": str(email_dir),
            "output_dir": str(output_dir),
            "server_response": json_data,
        }

    except HTTPException:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Local TCD08 client failed: {exc}")

class OpenLinkRequest(BaseModel):
    link: str
@app.post("/open/link")
def api_open_link(req: OpenLinkRequest):
    try:
        msg = open_resource(req.link)  # ← 关键：用同一套逻辑
        return {
            "success": True,
            "message": msg,
            "link": req.link
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "link": req.link
        }

@app.get("/PMSInfo/{uuid}")
async def get_project_info(uuid: str):
    url = f"https://oss-dthub.apac.bosch.com/temp/api/v1/projects/info/{uuid}"

    no_proxy = {
        "http": None,
        "https": None,
    }

    try:
        response = requests.get(url, proxies=no_proxy, verify=False)
        response.raise_for_status()

        project_profile = dataprovider_pb2.ProjectProfile()

        project_profile.ParseFromString(response.content)
        
        data_dict = MessageToDict(
            project_profile, 
            preserving_proto_field_name=True
        )

        return data_dict

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {e}")
    except Exception as e:
        # Protobuf解析失败等其他错误
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")

@app.get("/GeneralInfo/{projectId}")
async def call_document_processor(projectId: str):
    # target_api_url = "http://127.0.0.1:8088/temp/api/v1/puma/projects/documents"
    target_api_url = "https://oss-dthub.apac.bosch.com/temp/api/v1/puma/projects/documents"

    no_proxy = { 
        "http": None, 
        "https": None 
    }
    
    SOURCE_DIRECTORY = "C:/Users/ASY6SZH/Downloads/testinput/"
    DESTINATION_DIRECTORY = "C:/Users/ASY6SZH/Downloads/testoutput/"

    os.makedirs(SOURCE_DIRECTORY, exist_ok=True)
    os.makedirs(DESTINATION_DIRECTORY, exist_ok=True)

    files_to_upload = []
    open_files = []

    try:
        if not os.path.isdir(SOURCE_DIRECTORY):
            raise HTTPException(status_code=404, detail=f"Source directory not found: {SOURCE_DIRECTORY}")

        for filename in os.listdir(SOURCE_DIRECTORY):
            if filename.lower().endswith(('.xlsx', '.xlsm', '.docx', '.docm', '.pptx')):
                file_path = os.path.join(SOURCE_DIRECTORY, filename)
                
                f = open(file_path, 'rb')
                open_files.append(f)
                
                files_to_upload.append(('files', (filename, f)))
        
        if not files_to_upload:
            raise HTTPException(status_code=404, detail=f"No suitable template files found in {SOURCE_DIRECTORY}")

        form_data = {'projectid': projectId}

        print(f"Sending {len(files_to_upload)} files to {target_api_url} for projectId: {projectId}...")

        response = requests.post(
            target_api_url,
            data=form_data,
            files=files_to_upload,
            proxies=no_proxy,
            verify=False
        )

        response.raise_for_status()
        print("API call successful. Receiving response...")

        content_disposition = response.headers.get('Content-Disposition')
        zip_filename = None
        if content_disposition:
            _, params = cgi.parse_header(content_disposition)
            zip_filename = params.get('filename')

        if not zip_filename:
            timestamp = int(time.time())
            zip_filename = f"{projectId}_fallback_{timestamp}.zip"
            print(f"Warning: Filename not in response header. Using fallback: {zip_filename}")
        
        safe_zip_filename = os.path.basename(zip_filename).strip()
        if not safe_zip_filename:
            raise HTTPException(status_code=400, detail="Invalid filename received from server.")
        
        destination_path = os.path.join(DESTINATION_DIRECTORY, safe_zip_filename)

        with open(destination_path, 'wb') as f_out:
            f_out.write(response.content)
        
        print(f"Response ZIP file saved to: '{destination_path}'")

        return {
            "status": "success",
            "message": "Successfully called the document processing API and saved the result.",
            "files_sent": [f[1][0] for f in files_to_upload],
            "zip_file_saved_as": destination_path
        }

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Failed to communicate with the document API: {e}")
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"An unexpected internal error occurred: {e}")
    finally:
        for f in open_files:
            f.close()
        print("All source files have been closed.")        

class CopyRequest(BaseModel):
    destination_path: str = Field(
        ...,
        example="/tmp/my_new_project_folder",
        description="The absolute path where the source folder should be copied to.",
    )

@app.post("/copy-folder")
async def copy_folder_to_destination(request_data: CopyRequest):
    des = f"{request_data.destination_path}\\40.Application"
    destination = os.path.abspath(des.strip())

    SOURCE_FOLDER_PATH = r"\\bosch.com\dfsrb\DfsCN\DIV\CC\Prj\PS\00_General\10_Migrated_2_ILM\20.1_Template of folder structure\40.Application"
    if not os.path.isdir(SOURCE_FOLDER_PATH):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server configuration error: The source folder '{SOURCE_FOLDER_PATH}' does not exist or is not a directory.",
        )

    try:
        shutil.copytree(SOURCE_FOLDER_PATH, destination, dirs_exist_ok=True)
    
    except PermissionError:
        # 如果没有权限在目标位置创建文件夹或文件。
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server permission error: Insufficient permissions to write to the destination path '{destination}'.",
        )
    
    except Exception as e:
        # 捕获其他所有可能的异常。
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during the copy operation: {e}",
        )

    return {
        "status": "success",
        "message": f"Folder successfully copied from '{SOURCE_FOLDER_PATH}' to '{destination}'.",
        "destination": destination,
    }

# =================================================================================
# 启动服务
# =================================================================================
DEBUG = False

if __name__ == "__main__":

    if is_port_in_use("127.0.0.1", 7175):
        msg = "端口 7175 已被占用，PUMA Client 无法启动本地服务。\n请关闭占用进程后重试。"
        write_startup_log(msg)
        show_error_box("PUMA Client 启动失败", msg)
        os._exit(1)

    if DEBUG:
        # ✅ 调试模式：Uvicorn 跑在主线程
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=7175,
            log_level="debug",
            reload=False,
            access_log=True,
        )
    else:
        # 🚀 正常模式：托盘 + 后台服务
        def run_uvicorn():
            try:
                uvicorn.run(
                    app,
                    host="0.0.0.0",
                    port=7175,
                    log_config=None,
                    access_log=False,
                )
            except Exception as e:
                write_startup_log(f"Uvicorn startup failed: {e}")
                show_error_box("PUMA Client 启动失败", f"本地服务启动失败:\n{e}\n\n请查看同目录 client_startup.log")
                os._exit(1)

        Thread(target=run_uvicorn).start()
        run_tray()