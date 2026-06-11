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
