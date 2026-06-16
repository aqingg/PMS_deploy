import json
import os
from pathlib import Path

from utils.path_config import (
    TEMPLATES_DIR,
    DATA_SOURCE_DIR,
)

# ============================================
#  通用 JSON 加载工具
# ============================================

def load_json(path: str | Path):
    """
    加载任意 JSON 文件（支持绝对路径和相对路径）
    """
    path = Path(path)

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_template(filename: str):
    """
    加载 templates 下的 JSON 文件
    """
    path = TEMPLATES_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_data_source(filename: str):
    """
    加载 data_source 下的 JSON 文件
    """
    path = DATA_SOURCE_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================
#  JSON 写入工具
# ============================================

def write_json(path: str, data):
    """
    保存 JSON 文件（会自动创建目录）
    """
    path = Path(path)

    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================
#  与 ProjectInfo 相关的业务逻辑工具（可保留）
# ============================================

def extract_root_paths(projectInfo: list):
    """
    从 projectInfo 结构中解析 Local Link / Public Link / SharePoint 根路径
    """

    root_paths = {
        "local": None,
        "public": None,
        "cloud": None,
    }

    for group in projectInfo:   # projectInfo 是一个二维数组
        for item in group:      # 每个 group 里是 label/value 对象
            label = item.get("label")
            value = item.get("value")

            if label == "Local Link":
                root_paths["local"] = value

            elif label == "Public Link":
                root_paths["public"] = value

            elif label == "SharePoint":
                root_paths["cloud"] = value

    return root_paths


def load_folder_mapping():
    """
    专门读取模板里的 FolderLinkMapping.json
    """
    path = TEMPLATES_DIR / "FolderLinkMapping.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================
# CalibrationID 本地工作区创建工具
# ============================================

def _normalize_project_info_rows(project_info_or_meta):
    """
    兼容两种输入：
    1. projectInfo 二维数组
    2. 完整 meta dict: {"projectInfo": [...], "owner": ..., "proxies": ...}
    """
    if isinstance(project_info_or_meta, dict):
        rows = project_info_or_meta.get("projectInfo", [])
    else:
        rows = project_info_or_meta

    if not isinstance(rows, list):
        raise ValueError("projectInfo structure invalid")

    return rows


def _validate_calibration_id(calibration_id: str) -> str:
    """
    校验 CalibrationID，防止非法路径字符和路径穿越。
    """
    cid = str(calibration_id or "").strip()

    if not cid:
        raise ValueError("CalibrationID is empty")

    invalid_chars = '<>:"/\\|?*'
    if any(ch in cid for ch in invalid_chars):
        raise ValueError(f"CalibrationID contains invalid path character: {cid}")

    if cid in [".", ".."] or ".." in cid:
        raise ValueError(f"CalibrationID contains unsafe path segment: {cid}")

    return cid


def build_local_workspace_paths(projectInfo, calibration_id, create=True):
    """
    根据当前项目的 Local Link 和 CalibrationID 创建专属本地工作区。

    目标目录：
    Local Link/
      40.Application/
        C.Calibration/
          {CalibrationID}/
            03_Results/
              Customer_Approval_Email/
            06_Official_Release/
              TCD08_Report/

    返回：
    {
        "local_root": "...",
        "calibration_root": "...",
        "email_dir": "...",
        "tcd08_report_dir": "..."
    }
    """
    rows = _normalize_project_info_rows(projectInfo)
    root_paths = extract_root_paths(rows)

    local_link = root_paths.get("local")
    if not local_link or not str(local_link).strip():
        raise ValueError("No Local Link configured")

    cid = _validate_calibration_id(calibration_id)

    local_root = Path(str(local_link).strip())
    calibration_root = local_root / "40.Application" / "C.Calibration" / cid

    email_dir = calibration_root / "03_Results" / "Customer_Approval_Email"
    tcd08_report_dir = calibration_root / "06_Official_Release" / "TCD08_Report"

    paths = {
        "local_root": local_root,
        "calibration_root": calibration_root,
        "email_dir": email_dir,
        "tcd08_report_dir": tcd08_report_dir,
    }

    if create:
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)

    return {key: str(value) for key, value in paths.items()}
