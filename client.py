from threading import Thread

import base64
import cgi
import getpass
import json
import mimetypes
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import List, Optional
from urllib.parse import unquote, urlparse

import pystray
import requests
import uvicorn
from fastapi import Body, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from google.protobuf.json_format import MessageToDict
from PIL import Image
from pydantic import BaseModel, Field

import dataprovider_pb2

# ---- 强制前置窗口依赖 ----
# 说明：PUMA Client 主要运行在 Windows。这里做兜底，避免非 Windows 调试时直接 import 失败。
try:
    import win32con
    import win32gui
    import win32process
except Exception:  # pragma: no cover - only for non-Windows/dev environments
    win32con = None
    win32gui = None
    win32process = None


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
# ⭐ PyInstaller 资源路径兼容函数
# =================================================================================
def resource_path(relative_path):
    """确保 PyInstaller 打包后也能找到图标文件"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


# =================================================================================
# 托盘退出逻辑
# =================================================================================
def on_exit(icon, item):
    icon.stop()
    os._exit(0)


# =================================================================================
# 托盘逻辑（自动加载 icon）
# =================================================================================
tray_icon = None


def run_tray():
    global tray_icon
    try:
        icon_image = Image.open(resource_path("favicon.ico"))
    except Exception as e:
        write_startup_log(f"Failed to load tray icon: {e}")
        show_error_box(
            "PUMA Client 启动失败",
            f"托盘图标加载失败:\n{e}\n\n请查看同目录 client_startup.log",
        )
        return

    tray_icon = pystray.Icon(
        "PUMA Client",
        icon_image,
        "PUMA Client",
        menu=pystray.Menu(pystray.MenuItem("Exit", on_exit)),
    )

    def on_ready(icon):
        icon.visible = True
        icon.notify("PUMA Client is working!", "PUMA Client")

    tray_icon.run(setup=on_ready)


# =================================================================================
# FastAPI App
# =================================================================================
app = FastAPI(
    title="PUMA Client",
    description="本地服务：用户目录、打开路径、复制路径等",
    version="2.1.0",
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


class CopyRequest(BaseModel):
    destination_path: str = Field(
        ...,
        example=r"C:\AppTools\00.APP-PMS\WUE7SZH\SomeProject",
        description="Project root path. The template 40.Application folder will be copied into this path.",
    )


class CopyApplicationTemplateRequest(BaseModel):
    destination_application_dir: Optional[str] = Field(
        default=None,
        example=r"C:\AppTools\00.APP-PMS\WUE7SZH\SomeProject\40.Application",
        description="Target 40.Application directory on the local machine.",
    )
    destination_path: Optional[str] = Field(
        default=None,
        example=r"C:\AppTools\00.APP-PMS\WUE7SZH\SomeProject",
        description="Project root path. Used only when destination_application_dir is not provided.",
    )
    calibration_ids: Optional[List[str]] = Field(
        default=None,
        example=["ACQ_CaliID", "VAL_CaliID"],
        description="CalibrationID folder names to create under 40.Application\\C.Calibration.",
    )


# =================================================================================
# Template Copy 配置
# =================================================================================
# Source 40.Application template folder on the mapped N drive.
SOURCE_CALIBRATION_TEMPLATE = (
    r"N:\Prj\PS\32_Application\EPD5-File-Templates"
    r"\20.1_Template of folder structure\40.Application"
)

CALIBRATION_FOLDER_NAME = "C.Calibration"
PARAMETER_STRUCTURE_TEMPLATE_NAME = "20.1_Template of parameter structure"
DEFAULT_CALIBRATION_IDS = ["ACQ_CaliID", "VAL_CaliID"]


# =================================================================================
# TCD08 本地适配层配置
# =================================================================================
# 生产环境默认指向服务器 8086 的对外地址；如本地调试，可在启动 Client 前设置环境变量：
# set PUMA_SERVER_TCD08_URL=http://127.0.0.1:8086/report/fillTCD08Report
DEFAULT_SERVER_BASE_URL = os.environ.get(
    "PUMA_SERVER_BASE_URL",
    # "https://oss-dthub.apac.bosch.com/app-puma",
    "http://127.0.0.1:8086",
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
        .../C.Calibration/{CalibrationID}/06_Official_Release/TCD08_Report

    Preferred derived email_dir:
        .../C.Calibration/{CalibrationID}/03_Results/Customer_Approval_Email

    如果前端/后端显式传入 email_dir，则不会使用这个兜底推导。
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


def _filename_from_response(response: requests.Response, fallback: str = "TCD08_Report.docm") -> str:
    """
    Parse Content-Disposition filename safely.
    Supports both:
        filename=xxx.docm
        filename*=utf-8''xxx%20xxx.docm
    """
    cd = response.headers.get("content-disposition") or response.headers.get("Content-Disposition") or ""

    m = re.search(r"filename\*\s*=\s*(?:UTF-8''|utf-8'')?([^;]+)", cd, flags=re.IGNORECASE)
    if m:
        filename = unquote(m.group(1).strip().strip('"'))
        filename = os.path.basename(filename)
        if filename:
            return filename

    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, flags=re.IGNORECASE)
    if m:
        filename = os.path.basename(m.group(1).strip().strip('"'))
        if filename:
            return filename

    return fallback


def _save_binary_response(response: requests.Response, output_dir: Path, fallback_name: str = "TCD08_Report.docm") -> str:
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
    if not win32gui or not win32process or not win32con:
        return False

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
    if not win32gui or not win32con:
        return False

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
    time.sleep(0.5)

    folder_name = os.path.basename(path.rstrip("\\/"))
    ok = bring_explorer_to_front_by_title(folder_name)
    if ok:
        return "Opened in Explorer (foreground OK)"
    return "Opened but could not force foreground"


# =================================================================================
# ✨ URL/文件/文件夹 三合一打开工具
# =================================================================================
def is_url(path: str) -> bool:
    try:
        r = urlparse(path)
        return all([r.scheme, r.netloc])
    except Exception:
        return False


def open_resource(path: str):
    """自动判断并打开资源（URL / 文件夹 / 文件）"""
    if is_url(path):
        webbrowser.open(path)
        return "Opened URL in default browser"

    if platform.system() == "Windows":
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as e:
                return f"Failed to create folder: {e}"

        if os.path.isdir(path):
            return open_in_explorer(path)
        if os.path.isfile(path):
            return open_in_explorer(path)

    cmd = "open" if platform.system() == "Darwin" else "xdg-open"
    subprocess.Popen([cmd, path])
    return "Opened resource"


def is_web_url(value: str) -> bool:
    try:
        r = urlparse(value.strip())
        return r.scheme in ("http", "https")
    except Exception:
        return False


def is_file_url(value: str) -> bool:
    try:
        r = urlparse(value.strip())
        return r.scheme == "file"
    except Exception:
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

    if is_web_url(link):
        webbrowser.open(link)
        return "Opened web URL in default browser"

    if is_file_url(link):
        link = file_url_to_path(link)

    if platform.system() == "Windows":
        if os.path.isdir(link):
            subprocess.Popen(["explorer", os.path.normpath(link)])
            return "Opened folder in Explorer"
        if os.path.isfile(link):
            os.startfile(os.path.normpath(link))
            return "Opened file with default application"
        return "Not found: path does not exist"

    if os.path.exists(link):
        cmd = "open" if platform.system() == "Darwin" else "xdg-open"
        subprocess.Popen([cmd, link])
        return "Opened local resource"

    try:
        webbrowser.open(link)
        return "Tried opening as URL/protocol"
    except Exception:
        return "Not found: resource does not exist"


# =================================================================================
# Safe template copy helpers
# =================================================================================
def _resolve_application_destination(destination_application_dir: Optional[str], destination_path: Optional[str]) -> Path:
    """
    Resolve target 40.Application path.

    - destination_application_dir: already points to ...\40.Application
    - destination_path: project root; 40.Application will be appended
    """
    if destination_application_dir and str(destination_application_dir).strip():
        return _norm_path(destination_application_dir)

    if destination_path and str(destination_path).strip():
        project_root = _norm_path(destination_path)
        if project_root.name.lower() == "40.application":
            return project_root
        return project_root / "40.Application"

    raise ValueError("destination_application_dir or destination_path is required")


def _resolve_source_application_template() -> Path:
    """Resolve and validate source 40.Application template folder."""
    source_application_dir = Path(SOURCE_CALIBRATION_TEMPLATE)
    if not source_application_dir.exists() or not source_application_dir.is_dir():
        raise FileNotFoundError(f"Source 40.Application template folder not found: {source_application_dir}")
    return source_application_dir


def _resolve_parameter_structure_template() -> Path:
    """
    Resolve the parameter-structure template folder.

    Correct source layout:
        SOURCE_CALIBRATION_TEMPLATE\\C.Calibration\\20.1_Template of parameter structure

    This folder is a mother template. By default it is NOT copied as a folder named
    '20.1_Template of parameter structure' into the local project. Its children are
    expanded into each CalibrationID folder.
    """
    source_application_dir = _resolve_source_application_template()
    parameter_template_dir = (
        source_application_dir
        / CALIBRATION_FOLDER_NAME
        / PARAMETER_STRUCTURE_TEMPLATE_NAME
    )

    if not parameter_template_dir.exists() or not parameter_template_dir.is_dir():
        raise FileNotFoundError(f"Parameter structure template folder not found: {parameter_template_dir}")

    return parameter_template_dir


def _normalize_calibration_ids(calibration_ids: Optional[List[str]]) -> List[str]:
    """
    Normalize CalibrationID names coming from frontend workflow.

    The frontend should pass IDs read from workflow C.Calibration children.
    If nothing valid is passed, fall back to the default two IDs.
    """
    raw_ids = calibration_ids or DEFAULT_CALIBRATION_IDS
    normalized = []
    seen = set()

    invalid_exact = {
        PARAMETER_STRUCTURE_TEMPLATE_NAME.lower(),
        "20.1_template of parameter structure",
    }
    invalid_chars = set('<>:"/\\|?*')

    for item in raw_ids:
        value = str(item or "").strip()
        if not value:
            continue

        value_lower = value.lower()
        # The template folder is not a CalibrationID and must never become a target ID.
        if value_lower in invalid_exact or "template" in value_lower:
            continue

        if value in {".", ".."} or any(ch in invalid_chars for ch in value):
            raise ValueError(f"Invalid CalibrationID folder name: {value}")

        if value_lower not in seen:
            normalized.append(value)
            seen.add(value_lower)

    if not normalized:
        normalized = DEFAULT_CALIBRATION_IDS[:]

    return normalized


def _normcase_abs(path: Path) -> str:
    """Case-insensitive normalized absolute path string for Windows-safe comparisons."""
    return os.path.normcase(os.path.abspath(os.path.normpath(str(path))))


def _is_same_or_child_path(path: Path, parent: Path) -> bool:
    """Return True when path is parent itself or located under parent."""
    path_norm = _normcase_abs(path)
    parent_norm = _normcase_abs(parent)
    try:
        return os.path.commonpath([path_norm, parent_norm]) == parent_norm
    except ValueError:
        return False


def _safe_copy_tree(source_dir: Path, destination_dir: Path, skip_source_dirs: Optional[List[Path]] = None) -> dict:
    """
    Safe recursive copy for folders AND files.

    - source_dir itself is not copied as a named folder; its child content is expanded
      into destination_dir;
    - missing folders are created;
    - missing files are copied;
    - existing files are NOT overwritten;
    - existing local folders/content are NOT deleted.
    """
    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError(f"Source template folder not found: {source_dir}")

    skip_dirs = [Path(p) for p in (skip_source_dirs or [])]

    created_dirs = []
    existing_dirs = []
    copied_files = []
    skipped_existing_files = []
    skipped_template_dirs = []
    seen_targets = set()

    for root, dirs, files in os.walk(source_dir):
        root_path = Path(root)

        # If current root itself is inside a skipped source directory, skip it entirely.
        if any(_is_same_or_child_path(root_path, skip_dir) for skip_dir in skip_dirs):
            skipped_template_dirs.append(str(root_path))
            dirs[:] = []
            continue

        # Prevent os.walk from entering skipped child directories.
        kept_dirs = []
        for dirname in dirs:
            child_dir = root_path / dirname
            if any(_is_same_or_child_path(child_dir, skip_dir) for skip_dir in skip_dirs):
                skipped_template_dirs.append(str(child_dir))
                continue
            kept_dirs.append(dirname)
        dirs[:] = kept_dirs

        rel_root = root_path.relative_to(source_dir)
        target_root = destination_dir if str(rel_root) == "." else destination_dir / rel_root
        target_key = os.path.normcase(os.path.normpath(str(target_root)))

        if target_key not in seen_targets:
            seen_targets.add(target_key)
            if target_root.exists():
                existing_dirs.append(str(target_root))
            else:
                target_root.mkdir(parents=True, exist_ok=True)
                created_dirs.append(str(target_root))

        for filename in files:
            source_file = root_path / filename
            target_file = target_root / filename
            if target_file.exists():
                skipped_existing_files.append(str(target_file))
                continue
            target_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source_file), str(target_file))
            copied_files.append(str(target_file))

    return {
        "source": str(source_dir),
        "destination": str(destination_dir),
        "created_count": len(created_dirs),
        "existing_count": len(existing_dirs),
        "copied_files_count": len(copied_files),
        "skipped_existing_files_count": len(skipped_existing_files),
        "skipped_template_dirs_count": len(set(skipped_template_dirs)),
        "created_dirs": created_dirs,
        "existing_dirs": existing_dirs,
        "copied_files": copied_files,
        "skipped_existing_files": skipped_existing_files,
        "skipped_template_dirs": sorted(set(skipped_template_dirs)),
        "mode": "safe_copy_folders_and_files_no_overwrite",
    }


def _copy_full_application_template(destination_application_dir: Path) -> dict:
    """
    Copy the whole source 40.Application template into local 40.Application.

    The parameter-template folder under C.Calibration is skipped here because it is a
    mother template. Its contents are expanded into every CalibrationID folder later.
    This keeps local 40.Application\\C.Calibration clean while still preserving A/B/D
    and all other normal 40.Application content.
    """
    source_application_dir = _resolve_source_application_template()
    parameter_template_dir = _resolve_parameter_structure_template()
    destination_application_dir.mkdir(parents=True, exist_ok=True)

    return _safe_copy_tree(
        source_application_dir,
        destination_application_dir,
        skip_source_dirs=[parameter_template_dir],
    )


def _copy_parameter_structure_to_calibration_ids(
    destination_application_dir: Path,
    calibration_ids: Optional[List[str]],
) -> dict:
    """
    Create CalibrationID folders under local 40.Application\\C.Calibration and
    expand the parameter-structure template into every CalibrationID folder.
    """
    parameter_template_dir = _resolve_parameter_structure_template()
    normalized_ids = _normalize_calibration_ids(calibration_ids)

    destination_application_dir.mkdir(parents=True, exist_ok=True)
    destination_calibration_dir = destination_application_dir / CALIBRATION_FOLDER_NAME
    destination_calibration_dir.mkdir(parents=True, exist_ok=True)

    total_created_dirs = []
    total_existing_dirs = []
    total_copied_files = []
    total_skipped_existing_files = []
    per_id_results = []
    target_dirs = []

    for calibration_id in normalized_ids:
        target_calibration_dir = destination_calibration_dir / calibration_id
        result = _safe_copy_tree(parameter_template_dir, target_calibration_dir)
        target_dirs.append(str(target_calibration_dir))
        total_created_dirs.extend(result.get("created_dirs", []))
        total_existing_dirs.extend(result.get("existing_dirs", []))
        total_copied_files.extend(result.get("copied_files", []))
        total_skipped_existing_files.extend(result.get("skipped_existing_files", []))
        per_id_results.append(
            {
                "calibration_id": calibration_id,
                "target_dir": str(target_calibration_dir),
                "created_count": result.get("created_count", 0),
                "existing_count": result.get("existing_count", 0),
                "copied_files_count": result.get("copied_files_count", 0),
                "skipped_existing_files_count": result.get("skipped_existing_files_count", 0),
                "created_dirs": result.get("created_dirs", []),
                "existing_dirs": result.get("existing_dirs", []),
                "copied_files": result.get("copied_files", []),
                "skipped_existing_files": result.get("skipped_existing_files", []),
            }
        )

    return {
        "parameter_template_dir": str(parameter_template_dir),
        "destination_application_dir": str(destination_application_dir),
        "destination_calibration_dir": str(destination_calibration_dir),
        "calibration_ids": normalized_ids,
        "target_dirs": target_dirs,
        "created_count": len(total_created_dirs),
        "existing_count": len(total_existing_dirs),
        "copied_files_count": len(total_copied_files),
        "skipped_existing_files_count": len(total_skipped_existing_files),
        "created_dirs": total_created_dirs,
        "existing_dirs": total_existing_dirs,
        "copied_files": total_copied_files,
        "skipped_existing_files": total_skipped_existing_files,
        "per_id_results": per_id_results,
        "mode": "safe_parameter_structure_to_calibration_ids",
    }


def _copy_application_template_with_calibration_ids(
    destination_application_dir: Path,
    calibration_ids: Optional[List[str]],
) -> dict:
    """
    Correct two-stage Copy flow:

    1. Safe-copy the full 40.Application template into the local 40.Application,
       preserving A/B/C/D and all normal folders/files.
    2. Expand C.Calibration\20.1_Template of parameter structure into every
       CalibrationID folder passed by the frontend workflow.
    """
    app_result = _copy_full_application_template(destination_application_dir)
    parameter_result = _copy_parameter_structure_to_calibration_ids(
        destination_application_dir,
        calibration_ids,
    )

    total_created_count = app_result.get("created_count", 0) + parameter_result.get("created_count", 0)
    total_existing_count = app_result.get("existing_count", 0) + parameter_result.get("existing_count", 0)
    total_copied_files_count = app_result.get("copied_files_count", 0) + parameter_result.get("copied_files_count", 0)
    total_skipped_files_count = app_result.get("skipped_existing_files_count", 0) + parameter_result.get("skipped_existing_files_count", 0)

    return {
        "source": str(Path(SOURCE_CALIBRATION_TEMPLATE)),
        "destination_application_dir": str(destination_application_dir),
        "destination": str(destination_application_dir),
        "parameter_template_dir": parameter_result.get("parameter_template_dir"),
        "destination_calibration_dir": parameter_result.get("destination_calibration_dir"),
        "calibration_ids": parameter_result.get("calibration_ids", []),
        "target_dirs": parameter_result.get("target_dirs", []),
        "created_count": total_created_count,
        "existing_count": total_existing_count,
        "skipped_count": total_existing_count,
        "copied_files_count": total_copied_files_count,
        "skipped_existing_files_count": total_skipped_files_count,
        "application_template_result": app_result,
        "parameter_structure_result": parameter_result,
        "per_id_results": parameter_result.get("per_id_results", []),
        "mode": "safe_full_40_application_plus_parameter_structure",
    }


# =================================================================================
# ✨ API：打开路径
# =================================================================================
@app.get("/userinfo")
def get_user_info():
    username = getpass.getuser()
    return {"machine_id": username.upper()}


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
    ".doc",
    ".docx",
    ".docm",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
)


@app.get("/getOfficeFiles", response_model=List[str])
def getOfficeFiles(folder_path: str):
    if not os.path.isdir(folder_path):
        raise HTTPException(status_code=404, detail=f"文件夹未找到: {folder_path}")

    found_files = []
    try:
        for item_name in os.listdir(folder_path):
            if item_name.lower().endswith(OFFICE_FILE_EXTENSIONS):
                full_path = os.path.join(folder_path, item_name)
                if os.path.isfile(full_path):
                    found_files.append(full_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取目录时出错: {e}")

    return found_files


@app.post("/saveReport")
def save_report_on_server(request: ReportRequest):
    files_to_upload = []
    try:
        for path in request.template_paths:
            try:
                file_content = open(path, "rb")
                file_name = os.path.basename(path)
                files_to_upload.append(("files", (file_name, file_content, "application/octet-stream")))
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail=f"模板文件未在服务器上找到: {path}")

        if not files_to_upload:
            raise HTTPException(status_code=400, detail="没有提供任何有效的模板路径。")

        proxies = {"http": None, "https": None}
        response = requests.post(
            request.url,
            data={"projectid": request.projectid},
            files=files_to_upload,
            proxies=proxies,
            verify=False,
        )

        if response.status_code == 200:
            content_disposition = response.headers.get("content-disposition")
            if content_disposition and "filename=" in content_disposition:
                filename = content_disposition.split("filename=")[-1].strip('"')
            else:
                filename = "generated_report.zip"

            full_save_path = os.path.join(request.save_path, filename)

            try:
                os.makedirs(request.save_path, exist_ok=True)
            except OSError as e:
                raise HTTPException(status_code=500, detail=f"无法创建目录 '{request.save_path}': {e}")

            try:
                with open(full_save_path, "wb") as f:
                    f.write(response.content)
            except IOError as e:
                raise HTTPException(status_code=500, detail=f"无法写入文件到 '{full_save_path}': {e}")

            return {
                "status": "success",
                "message": "报告已成功生成并保存。",
                "saved_path": full_save_path,
            }

        raise HTTPException(status_code=response.status_code, detail=f"文件处理服务调用失败: {response.text}")

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"无法连接到文件处理服务: {e}")
    finally:
        for _, file_tuple in files_to_upload:
            if file_tuple and len(file_tuple) > 1 and not file_tuple[1].closed:
                file_tuple[1].close()


# =================================================================================
# ✨ API：复制路径 / 创建目录 / 复制模板目录结构
# =================================================================================
@app.get("/copyPath")
def api_copy_path(path: str):
    if not path:
        return {"success": False, "message": "path is required"}
    try:
        if platform.system() == "Windows":
            os.system(f"echo {path.strip()} | clip")
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
        raise HTTPException(status_code=500, detail=f"Failed to create local folder '{folder}': {exc}") from exc

    return {
        "success": True,
        "message": "Folders created on local client",
        "folders": created_folders,
    }


@app.post("/copyApplicationTemplate")
def api_copy_application_template(req: CopyApplicationTemplateRequest):
    """
    Initialize local 40.Application from the full template, then expand the
    C.Calibration parameter-structure template into every workflow CalibrationID.

    Correct behavior:
    1. Safe-copy:
        N:/.../40.Application/*
       into:
        <local>/40.Application/*
       preserving A/B/C/D and normal files/folders, without overwriting existing files.

    2. Safe-expand:
        N:/.../40.Application/C.Calibration/20.1_Template of parameter structure/*
       into:
        <local>/40.Application/C.Calibration/<CalibrationID>/*

    The local project does not need to keep the mother template folder itself.
    """
    try:
        destination_application_dir = _resolve_application_destination(
            req.destination_application_dir,
            req.destination_path,
        )
        result = _copy_application_template_with_calibration_ids(
            destination_application_dir=destination_application_dir,
            calibration_ids=req.calibration_ids,
        )
        return {
            "success": True,
            "status": "success",
            "message": "40.Application template copied and CalibrationID folders initialized.",
            **result,
        }
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Template source folder does not exist or is not accessible: {exc}",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Permission error during template copy: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during template copy: {exc}",
        ) from exc


# 兼容旧前端：保留 /copy-folder。没有 calibration_ids 时使用默认 ACQ_CaliID / VAL_CaliID。
@app.post("/copy-folder")
async def copy_folder_to_destination(request_data: CopyRequest):
    try:
        destination_application_dir = _resolve_application_destination(None, request_data.destination_path)
        result = _copy_application_template_with_calibration_ids(
            destination_application_dir=destination_application_dir,
            calibration_ids=DEFAULT_CALIBRATION_IDS,
        )
        return {
            "success": True,
            "status": "success",
            "message": "40.Application template copied and default CalibrationID folders initialized.",
            **result,
        }
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Template source folder does not exist or is not accessible: {exc}",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Permission error during template copy: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during template copy: {exc}",
        ) from exc


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
        print(f"[TCD08 Client] email_dir = {email_dir}")
        print(f"[TCD08 Client] output_dir = {output_dir}")
        print("=" * 80)

        files, handles = _collect_upload_files(email_dir)

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

        if "projectId" not in data and payload.get("projectId") is not None:
            data["projectId"] = str(payload.get("projectId"))
        if "projectid" not in data and payload.get("projectid") is not None:
            data["projectid"] = str(payload.get("projectid"))
        if "taskId" not in data and payload.get("taskId") is not None:
            data["taskId"] = str(payload.get("taskId"))

        try:
            host = (urlparse(server_report_url).hostname or "").lower()
            if host in {"127.0.0.1", "localhost"}:
                session = requests.Session()
                session.trust_env = False
                response = session.post(
                    server_report_url,
                    data=data,
                    files=files,
                    verify=False,
                    timeout=600,
                )
            else:
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

        if "application/json" not in content_type:
            saved_path = _save_binary_response(response, output_dir)
            return {
                "success": True,
                "message": "TCD08 report generated and saved by local client",
                "email_dir": str(email_dir),
                "output_dir": str(output_dir),
                "saved_path": saved_path,
            }

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
        msg = open_resource(req.link)
        return {"success": True, "message": msg, "link": req.link}
    except Exception as e:
        return {"success": False, "error": str(e), "link": req.link}


@app.get("/PMSInfo/{uuid}")
async def get_project_info(uuid: str):
    url = f"https://oss-dthub.apac.bosch.com/temp/api/v1/projects/info/{uuid}"
    no_proxy = {"http": None, "https": None}
    try:
        response = requests.get(url, proxies=no_proxy, verify=False)
        response.raise_for_status()

        project_profile = dataprovider_pb2.ProjectProfile()
        project_profile.ParseFromString(response.content)

        data_dict = MessageToDict(project_profile, preserving_proto_field_name=True)
        return data_dict
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")


@app.get("/GeneralInfo/{projectId}")
async def call_document_processor(projectId: str):
    # target_api_url = "http://127.0.0.1:8088/temp/api/v1/puma/projects/documents"
    target_api_url = "https://oss-dthub.apac.bosch.com/temp/api/v1/puma/projects/documents"
    no_proxy = {"http": None, "https": None}

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
            if filename.lower().endswith((".xlsx", ".xlsm", ".docx", ".docm", ".pptx")):
                file_path = os.path.join(SOURCE_DIRECTORY, filename)
                f = open(file_path, "rb")
                open_files.append(f)
                files_to_upload.append(("files", (filename, f)))

        if not files_to_upload:
            raise HTTPException(status_code=404, detail=f"No suitable template files found in {SOURCE_DIRECTORY}")

        form_data = {"projectid": projectId}
        print(f"Sending {len(files_to_upload)} files to {target_api_url} for projectId: {projectId}...")

        response = requests.post(
            target_api_url,
            data=form_data,
            files=files_to_upload,
            proxies=no_proxy,
            verify=False,
        )
        response.raise_for_status()
        print("API call successful. Receiving response...")

        content_disposition = response.headers.get("Content-Disposition")
        zip_filename = None
        if content_disposition:
            _, params = cgi.parse_header(content_disposition)
            zip_filename = params.get("filename")

        if not zip_filename:
            timestamp = int(time.time())
            zip_filename = f"{projectId}_fallback_{timestamp}.zip"
            print(f"Warning: Filename not in response header. Using fallback: {zip_filename}")

        safe_zip_filename = os.path.basename(zip_filename).strip()
        if not safe_zip_filename:
            raise HTTPException(status_code=400, detail="Invalid filename received from server.")

        destination_path = os.path.join(DESTINATION_DIRECTORY, safe_zip_filename)
        with open(destination_path, "wb") as f_out:
            f_out.write(response.content)

        print(f"Response ZIP file saved to: '{destination_path}'")

        return {
            "status": "success",
            "message": "Successfully called the document processing API and saved the result.",
            "files_sent": [f[1][0] for f in files_to_upload],
            "zip_file_saved_as": destination_path,
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
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=7175,
            log_level="debug",
            reload=False,
            access_log=True,
        )
    else:
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
                show_error_box(
                    "PUMA Client 启动失败",
                    f"本地服务启动失败:\n{e}\n\n请查看同目录 client_startup.log",
                )
                os._exit(1)

        Thread(target=run_uvicorn).start()
        run_tray()
