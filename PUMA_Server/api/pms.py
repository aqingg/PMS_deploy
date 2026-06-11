# api/pms.py
import os
import json
import httpx
import copy
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from models.database import get_db
from models.project import Project as ProjectModel
from utils.file_loader import (
    load_data_source,
    load_template,
)
from utils.path_config import DATA_SOURCE_DIR, TEMPLATES_DIR
from api.project import assign_uuid_to_tasktree_and_details
router = APIRouter(prefix="/pms", tags=["PMS"])

PMS_JSON_PATH = DATA_SOURCE_DIR / "PMS.json"

@router.post("/refresh")
async def refresh_pms():
    """
    从 PMS 外部接口拉取最新数据并写入 data_source/PMS.json。
    不进行任何数据库同步操作。
    """

    PMS_URL = "http://apiroutecccn.apac.bosch.com/openapi/pmsserverprod/api/vms/pbi/CustomerProjects/ALL?gatewayKey=PN9rSrBi6770yG35WSoN25yAPiWaqbBS"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(PMS_URL)

        if response.status_code != 200:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch PMS data: HTTP {response.status_code}"
            )

        # ⭐ 外部 API 的 JSON（保持原样存储）
        pms_data = response.json()

        DATA_SOURCE_DIR.mkdir(parents=True, exist_ok=True)

        with open(PMS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "meta": {
                        "updatedAt": response.headers.get("Date"),
                        "count": len(pms_data) if isinstance(pms_data, list) else 1
                    },
                    "data": pms_data
                },
                f,
                ensure_ascii=False,
                indent=2
            )

        return {
            "success": True,
            "message": "PMS data refreshed successfully.",
            "count": len(pms_data) if isinstance(pms_data, list) else 1
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PMS refresh failed: {e}")

@router.get("/preview")
def preview_pms(limit: int = 20):
    """
    快速预览 PMS.json 中的项目信息。
    默认返回前 20 条，可通过 limit 调整数量。
    """

    if not PMS_JSON_PATH.exists():
        raise HTTPException(status_code=404, detail="PMS.json not found. Please refresh first.")

    try:
        with open(PMS_JSON_PATH, "r", encoding="utf-8") as f:
            content = json.load(f)

        data = content.get("data", [])
        total = len(data)

        # 限制最大单次预览数量，避免前端压力
        limit = min(limit, 200)

        preview_data = data[:limit]

        return {
            "success": True,
            "total": total,
            "returned": len(preview_data),
            "preview": preview_data
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to preview PMS.json: {e}")

@router.post("/sync")
def sync_pms_to_puma(department: str, db: Session = Depends(get_db)):
    """
    从 PMS.json 同步项目到 PUMA（仅新增不会覆盖）
    """

    # -----------------------------
    # 0. 校验 department
    # -----------------------------
    if not department:
        raise HTTPException(status_code=400, detail="department is required")

    # -----------------------------
    # 1. 加载 PMS
    # -----------------------------
    pms_content = load_data_source("PMS.json")
    pms_list = pms_content.get("data", [])
    if not isinstance(pms_list, list):
        raise HTTPException(status_code=500, detail="PMS.json format invalid")

    # -----------------------------
    # 2. 读取 unified.json 模板
    # -----------------------------
    unified_templates = load_template("unified.json")
    dept_template = next((x for x in unified_templates if x.get("department") == department), None)

    if not dept_template:
        raise HTTPException(status_code=400, detail=f"No template found for {department}")

    # -----------------------------
    # 3. TeamMembers → account→name 映射
    # -----------------------------
    team_members_path = TEMPLATES_DIR / "TeamMembers.json"
    account_to_name = {}

    if team_members_path.exists():
        with open(team_members_path, "r", encoding="utf-8") as f:
            for tm in json.load(f):
                account = tm.get("account")
                name = tm.get("name")
                if account and name:
                    account_to_name[account.upper()] = name

    # -----------------------------
    # 4. 加载字段映射（可选）
    # -----------------------------
    mapping_path = DATA_SOURCE_DIR / "DataMapping.json"
    field_mapping = {}
    collections_mapping = {}

    if mapping_path.exists():
        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping_content = json.load(f)
            field_mapping = mapping_content.get("fieldMapping", {}) or {}
            collections_mapping = mapping_content.get("collections", {}) or {}

    # -----------------------------
    # 5. 遍历 PMS 项目进行创建
    # -----------------------------
    created_count = 0
    skipped_count = 0

    for item in pms_list:

        project_name = item.get("ProjectName")
        if not project_name:
            skipped_count += 1
            continue

        # 已存在？
        exists = db.query(ProjectModel).filter(ProjectModel.projectName == project_name).first()
        if exists:
            skipped_count += 1
            continue

        # -----------------------------
        # 5.3 计算 proxies
        # -----------------------------
        proxies_names = set()

        pms_team = item.get("TeamMembers") or item.get("teamMembers") or []
        if isinstance(pms_team, list):
            for member in pms_team:
                uid = member.get("UID") or member.get("Uid") or member.get("uid") or member.get("account")
                if uid and uid in account_to_name:
                    proxies_names.add(account_to_name[uid])

        # 如果无人属于本部门 → 跳过
        if not proxies_names:
            skipped_count += 1
            continue

        proxies_value = ", ".join(sorted(proxies_names))

        # -----------------------------
        # 5.4 正确构造 projectInfo 结构
        # -----------------------------
        tpl_owner = dept_template.get("owner", {})
        tpl_proxies = dept_template.get("proxies", {})

        owner_block = {
            "label": tpl_owner.get("label", "Owner"),
            "value": ""   # PMS 创建的项目 owner 永远为空
        }

        proxies_block = {
            "label": tpl_proxies.get("label", "Proxies"),
            "value": proxies_value
        }

        proj_info = {
            "projectInfo": copy.deepcopy(dept_template.get("projectInfo", [])),
            "owner": owner_block,
            "proxies": proxies_block,
        }

        # grid 用于字段映射
        grid = proj_info["projectInfo"]

        # -----------------------------
        # 5.5 字段映射
        # -----------------------------
        for pms_key, puma_label in field_mapping.items():
            if pms_key not in item:
                continue

            val = item.get(pms_key)
            if val in (None, ""):
                continue

            for row in grid:
                if not isinstance(row, list):
                    continue
                for cell in row:
                    if isinstance(cell, dict) and cell.get("label") == puma_label:
                        cell["value"] = str(val)
                        break

        # -----------------------------
        # 5.6 集合映射
        # -----------------------------
        for collection_label, cfg in collections_mapping.items():
            keywords = [kw.lower() for kw in cfg.get("include", [])]
            if not keywords:
                continue

            values = []

            for key, v in item.items():
                if v in (None, ""):
                    continue
                if any(kw in str(key).lower() for kw in keywords):
                    values.append(str(v))

            if values:
                combined = ", ".join(sorted(set(values)))

                for row in grid:
                    for cell in row:
                        if isinstance(cell, dict) and cell.get("label") == collection_label:
                            cell["value"] = combined
                            break

        # -----------------------------
        # projectInfo JSON
        # -----------------------------
        project_info_str = json.dumps(proj_info, ensure_ascii=False)

        # -----------------------------
        # 5.7 生成 workflow（UUID 版）
        # -----------------------------
        original_tree = copy.deepcopy(dept_template.get("taskTree", []))
        original_details = {}

        new_task_details = assign_uuid_to_tasktree_and_details(original_tree, original_details)

        workflow_dict = {
            "taskTree": original_tree,
            "taskDetails": new_task_details,
        }

        project_workflow_str = json.dumps(workflow_dict, ensure_ascii=False)

        # -----------------------------
        # 5.8 生成 tags（自动写入 Status）
        # -----------------------------
        status_value = (
            item.get("Status")
            or item.get("ProjectStatus")
            or item.get("status")
            or ""
        )

        tag_list = []
        if isinstance(status_value, str) and status_value.strip():
            tag_list.append(status_value.strip())

        tags_str = json.dumps(tag_list, ensure_ascii=False)

        # -----------------------------
        # 创建记录
        # -----------------------------
        new_project = ProjectModel(
            username="SYSTEM",
            owner="",
            editors=json.dumps([]),
            department=department,
            projectName=project_name,
            projectInfo=project_info_str,
            projectWorkFlow=project_workflow_str,
            comment="",
            tags=tags_str,   # ⭐ 自动写入 status tags
            orderIndex=0,
        )

        db.add(new_project)
        created_count += 1

    db.commit()

    return {
        "success": True,
        "created": created_count,
        "skipped": skipped_count,
    }
