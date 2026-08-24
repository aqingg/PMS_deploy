from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from utils.file_loader import (
    load_template,
    build_local_workspace_paths,
)
from crud.project import (
    get_project,
    create_project,
    import_project,
    update_project_info,
    update_workflow,
    list_projects,
    update_project_meta,
    delete_project,
    reorder_projects,
)
from models.project import Project
from models.database import get_db
from services.path_resolver import (
    PathResolverError,
    resolve_path,
)
import uuid
from schemas.project import (
    ProjectInfoUpdate,
    WorkFlowUpdate,
    CreateProjectRequest,
    ProjectMetaUpdate,
    ProjectReorderRequest,
    ProjectDeleteRequest,
    ProjectImportRequest,
)
import json
import os
import copy
import re
from datetime import datetime, timezone
from urllib.parse import quote

# ⭐ 新增：使用统一 SSE 事件系统（替代 WebSocket）
from api.sse import event_bus

router = APIRouter(
    prefix="/project",
    tags=["Project API"]
)


# ===============================================================
# GET /project/getProject
# ===============================================================
@router.get("/getProject")
def get_project_api(username: str, projectId: int, db: Session = Depends(get_db)):

    project = db.query(Project).filter(Project.id == projectId).first()
    if not project:
        unified = load_template("unified.json")
        departments = [item["department"] for item in unified]
        return {
            "exists": False,
            "departments": departments
        }

    team_members = load_template("TeamMembers.json")
    account_to_name = {tm["account"]: tm["name"] for tm in team_members}
    user_name = account_to_name.get(username)

    if not user_name:
        return {"exists": False, "reason": "unauthorized_user"}

    meta = json.loads(project.projectInfo)
    owner = meta.get("owner", {}).get("value", "")
    proxies = meta.get("proxies", {}).get("value", "")
    can_access = (
        user_name == owner or
        (proxies and user_name in proxies)
    )

    if not can_access:
        return {"exists": False, "reason": "no_permission"}

    return {
        "exists": True,
        "data": project.to_dict()
    }


# ===============================================================
# UUID 生成
# ===============================================================
def assign_uuid_to_tasktree_and_details(task_tree, task_details):
    uuid_detail_map = {}

    def dfs(node):
        node_id = str(uuid.uuid4())
        node["id"] = node_id

        task_name = node["taskName"]
        detail = task_details.get(task_name)

        uuid_detail_map[node_id] = detail if detail else {
            "inputs": [],
            "outputs": [],
            "operation": {},
            "description": f"No detail found for {task_name}"
        }

        for child in node.get("children", []):
            dfs(child)

    for root in task_tree:
        dfs(root)

    return uuid_detail_map


# ===============================================================
# POST /project/createProject
# ===============================================================
@router.post("/createProject")
async def create_project_api(data: CreateProjectRequest, db: Session = Depends(get_db)):

    existing = (
        db.query(Project)
        .filter(
            Project.username == data.username,
            Project.projectName == data.projectName,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Project already exists")

    team_members = load_template("TeamMembers.json")
    account_to_name = {
        tm["account"]: tm["name"]
        for tm in team_members
        if "account" in tm and "name" in tm
    }

    owner_name = account_to_name.get(data.username)
    if not owner_name:
        raise HTTPException(status_code=400, detail="User not found in TeamMembers.json")

    unified = load_template("unified.json")
    dept_data = next((x for x in unified if x.get("department") == data.department), None)

    if not dept_data:
        raise HTTPException(status_code=400, detail="Department template not found")

    dept_info = copy.deepcopy(dept_data)

    owner_block = dept_info.get("owner") or {}
    if not isinstance(owner_block, dict):
        owner_block = {"label": "Owner", "value": ""}

    owner_block["value"] = owner_name
    dept_info["owner"] = owner_block

    proxies_block = dept_info.get("proxies") or {}
    if not isinstance(proxies_block, dict):
        proxies_block = {"label": "Proxies", "value": ""}

    proxies_block["value"] = ""
    dept_info["proxies"] = proxies_block

    project_info_payload = {
        "projectInfo": copy.deepcopy(dept_info.get("projectInfo", [])),
        "owner": dept_info["owner"],
        "proxies": dept_info["proxies"],
    }

    original_tree = dept_data["taskTree"]
    original_details = {}
    new_task_details = assign_uuid_to_tasktree_and_details(original_tree, original_details)

    workflow_payload = {
        "taskTree": original_tree,
        "taskDetails": new_task_details,
    }

    created = create_project(
        db,
        username=data.username,
        department=data.department,
        projectName=data.projectName,
        projectInfo=project_info_payload,
        workFlow=workflow_payload,
        owner=owner_name,
        editors=data.editors or [],
        comment=data.comment or "",
        tags=data.tags or [],
    )

    # ⭐ SSE 推送（替代 WebSocket）
    await event_bus.publish({
        "event": "ProjectCreated",
        "payload": {
            "projectName": data.projectName,
            "username": data.username
        }
    })
    return {"message": "Project created", "data": created.to_dict()}


# ===============================================================
# Transfer Data helpers
# ===============================================================
def _load_project_json_field(raw_value, field_name, default):
    if not raw_value:
        return copy.deepcopy(default)
    try:
        value = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"{field_name} JSON decode error: {exc}",
        ) from exc
    return value


def _get_team_user_name(username: str):
    team_members = load_template("TeamMembers.json")
    account_to_name = {
        tm["account"]: tm["name"]
        for tm in team_members
        if "account" in tm and "name" in tm
    }
    return account_to_name.get(username)


def _normalize_proxy_names(raw_value):
    if isinstance(raw_value, list):
        return [str(x).strip() for x in raw_value if str(x).strip()]
    return [x.strip() for x in str(raw_value or "").split(",") if x.strip()]


def _ensure_transfer_access(project: Project, username: str):
    user_name = _get_team_user_name(username)
    if not user_name:
        raise HTTPException(status_code=403, detail="Unauthorized user")

    meta = _load_project_json_field(project.projectInfo, "projectInfo", {})
    owner = meta.get("owner", {}).get("value", "")
    proxies = _normalize_proxy_names(meta.get("proxies", {}).get("value", ""))

    if user_name != owner and user_name not in proxies:
        raise HTTPException(status_code=403, detail="No permission to transfer this project")

    return user_name, meta


def _validate_import_file(project_data: dict):
    if not isinstance(project_data, dict):
        raise HTTPException(status_code=400, detail="Invalid Project data file")

    if project_data.get("format") != "PUMA_PROJECT":
        raise HTTPException(
            status_code=400,
            detail="Invalid Project data file: format must be PUMA_PROJECT",
        )

    if project_data.get("version") != 1:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported Project data version: {project_data.get('version')}",
        )

    payload = project_data.get("project")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid Project data file: project is missing")

    required = ["projectName", "department", "projectInfo", "projectWorkFlow"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid Project data file: missing {', '.join(missing)}",
        )

    if not isinstance(payload.get("projectName"), str) or not payload["projectName"].strip():
        raise HTTPException(status_code=400, detail="projectName must be a non-empty string")

    if not isinstance(payload.get("department"), str) or not payload["department"].strip():
        raise HTTPException(status_code=400, detail="department must be a non-empty string")

    if not isinstance(payload.get("projectInfo"), dict):
        raise HTTPException(status_code=400, detail="projectInfo must be an object")

    workflow = payload.get("projectWorkFlow")
    if not isinstance(workflow, dict):
        raise HTTPException(status_code=400, detail="projectWorkFlow must be an object")
    if not isinstance(workflow.get("taskTree", []), list):
        raise HTTPException(status_code=400, detail="projectWorkFlow.taskTree must be a list")
    if not isinstance(workflow.get("taskDetails", {}), dict):
        raise HTTPException(status_code=400, detail="projectWorkFlow.taskDetails must be an object")

    tags = payload.get("tags", [])
    if tags is not None and not isinstance(tags, list):
        raise HTTPException(status_code=400, detail="tags must be a list")

    return payload


# ===============================================================
# GET /project/downloadProject
# Download 当前 Project 的一条完整业务数据到本地 JSON。
# 不导出 SQLite id / orderIndex / progress。
# ===============================================================
@router.get("/downloadProject")
def download_project_data(
    username: str,
    projectId: int,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == projectId).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    _ensure_transfer_access(project, username)

    project_info = _load_project_json_field(
        project.projectInfo,
        "projectInfo",
        {},
    )
    workflow = _load_project_json_field(
        project.projectWorkFlow,
        "projectWorkFlow",
        {"taskTree": [], "taskDetails": {}},
    )
    editors = _load_project_json_field(project.editors, "editors", [])
    tags = _load_project_json_field(project.tags, "tags", [])

    export_payload = {
        "format": "PUMA_PROJECT",
        "version": 1,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "project": {
            "projectName": project.projectName,
            "department": project.department,
            "projectInfo": project_info,
            "projectWorkFlow": workflow,
            "comment": project.comment or "",
            "tags": tags if isinstance(tags, list) else [],
            # 这两个字段不是 Import 的必要条件，但保留有助于项目迁移。
            "owner": project.owner or "",
            "editors": editors if isinstance(editors, list) else [],
        },
    }

    content = json.dumps(export_payload, ensure_ascii=False, indent=2)

    raw_name = str(project.projectName or "Project").strip()
    ascii_fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._") or "Project"
    download_name = f"{raw_name or 'Project'}.puma.json"
    encoded_name = quote(download_name)

    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_fallback}.puma.json"; '
            f"filename*=UTF-8''{encoded_name}"
        )
    }

    return Response(
        content=content.encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers=headers,
    )


# ===============================================================
# POST /project/importProject
# 读取 Download 文件并创建一个新的 Project row。
# SQLite id 始终重新生成。
# ===============================================================
@router.post("/importProject")
async def import_project_data(
    data: ProjectImportRequest,
    db: Session = Depends(get_db),
):
    importer_name = _get_team_user_name(data.username)
    if not importer_name:
        raise HTTPException(status_code=400, detail="User not found in TeamMembers.json")

    source = _validate_import_file(data.projectData)

    project_name = source["projectName"].strip()
    department = source["department"].strip()
    project_info = copy.deepcopy(source["projectInfo"])
    workflow = copy.deepcopy(source["projectWorkFlow"])
    comment = str(source.get("comment") or "")
    tags = copy.deepcopy(source.get("tags") or [])

    # 保留原 Owner；如果导入者不是原 Owner，则把导入者加入 Proxies，
    # 否则导入成功后当前用户可能无法再次打开自己刚导入的 Project。
    owner_block = project_info.get("owner")
    if not isinstance(owner_block, dict):
        owner_block = {"label": "Owner", "value": ""}
    owner_block.setdefault("label", "Owner")

    source_owner = str(owner_block.get("value") or source.get("owner") or "").strip()
    if not source_owner:
        source_owner = importer_name
    owner_block["value"] = source_owner
    project_info["owner"] = owner_block

    proxies_block = project_info.get("proxies")
    if not isinstance(proxies_block, dict):
        proxies_block = {"label": "Proxies", "value": ""}
    proxies_block.setdefault("label", "Proxies")

    proxy_names = _normalize_proxy_names(proxies_block.get("value", ""))
    if importer_name != source_owner and importer_name not in proxy_names:
        proxy_names.append(importer_name)
    proxies_block["value"] = ", ".join(proxy_names)
    project_info["proxies"] = proxies_block

    editors = source.get("editors", [])
    if not isinstance(editors, list):
        editors = []
    editors = [str(item) for item in editors if str(item).strip()]
    if data.username not in editors:
        editors.append(data.username)

    try:
        created = import_project(
            db=db,
            username=data.username,
            department=department,
            projectName=project_name,
            projectInfo=project_info,
            workFlow=workflow,
            owner=source_owner,
            editors=editors,
            comment=comment,
            tags=tags,
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to import Project data: {exc}",
        ) from exc

    await event_bus.publish({
        "event": "ProjectCreated",
        "payload": {
            "projectId": created.id,
            "projectName": created.projectName,
            "username": data.username,
        },
    })

    return {
        "success": True,
        "message": "Project imported",
        "data": created.to_dict(),
    }


# ===============================================================
# POST /project/updateProjectInfo
# ===============================================================
@router.post("/updateProjectInfo")
async def update_project_info_api(data: ProjectInfoUpdate, db: Session = Depends(get_db)):

    project = db.query(Project).filter(Project.id == data.projectId).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    team_members = load_template("TeamMembers.json")
    account_to_name = {tm["account"]: tm["name"] for tm in team_members}
    user_name = account_to_name.get(data.username)

    meta = json.loads(project.projectInfo)
    owner = meta.get("owner", {}).get("value", "")
    proxies = meta.get("proxies", {}).get("value", "")

    if user_name != owner and user_name not in proxies:
        raise HTTPException(status_code=403, detail="No permission to edit")

    updated = update_project_info(db, project, data.projectInfo)

    # ⭐ SSE 推送
    await event_bus.publish({
        "event": "ProjectUpdated",
        "payload": {
            "projectId": data.projectId,
            "field": "projectInfo",
            "username": data.username
        }
    })

    return {"message": "ProjectInfo updated", "data": updated.to_dict()}


# ===============================================================
# POST /project/updateWorkFlow
# ===============================================================
@router.post("/updateWorkFlow")
async def update_workflow_api(data: WorkFlowUpdate, db: Session = Depends(get_db)):

    project = db.query(Project).filter(Project.id == data.projectId).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    team_members = load_template("TeamMembers.json")
    account_to_name = {tm["account"]: tm["name"] for tm in team_members}
    user_name = account_to_name.get(data.username)

    meta = json.loads(project.projectInfo)
    owner = meta.get("owner", {}).get("value", "")
    proxies = [x.strip() for x in meta.get("proxies", {}).get("value", "").split(",") if x.strip()]

    if user_name != owner and user_name not in proxies:
        raise HTTPException(status_code=403, detail="No permission to edit workflow")

    updated = update_workflow(db, project, data.workflow)

    # ⭐ SSE 推送
    await event_bus.publish({
        "event": "ProjectUpdated",
        "payload": {
            "projectId": data.projectId,
            "field": "workflow",
            "username": data.username
        }
    })

    return {"message": "Workflow updated", "data": updated.to_dict()}


# ===============================================================
# GET /project/getWorkFlowTemplate
# ===============================================================
@router.get("/getWorkFlowTemplate")
def get_workflow_template():
    try:
        template = load_template("WorkFlow.json")
        return {"success": True, "data": template}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ===============================================================
# GET /project/listProjects
# ===============================================================
@router.get("/listProjects")
def list_projects_api(username: str, db: Session = Depends(get_db)):

    team_members = load_template("TeamMembers.json")

    account_to_name = {tm["account"]: tm["name"] for tm in team_members}
    user_name = account_to_name.get(username)

    if not user_name:
        return {"projects": []}
    all_projects = db.query(Project).order_by(Project.orderIndex.asc()).all()

    visible_projects = []

    for p in all_projects:

        try:
            meta = json.loads(p.projectInfo)
        except Exception:
            meta = {}

        owner = meta.get("owner", {}).get("value", "")
        proxies = meta.get("proxies", {}).get("value", "")

        if user_name == owner or (proxies and user_name in proxies):
            project_dict = p.to_dict()
            if hasattr(p, "calc_progress"):
                project_dict["progress"] = p.calc_progress()
            else:
                project_dict["progress"] = 0

            visible_projects.append(project_dict)

    return {"projects": visible_projects}


# ===============================================================
# POST /project/editProjectMeta
# ===============================================================
@router.post("/editProjectMeta")
async def edit_project_meta_api(meta: ProjectMetaUpdate, db: Session = Depends(get_db)):

    proj = db.query(Project).filter(Project.id == meta.projectId).first()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    team_members = load_template("TeamMembers.json")
    account_to_name = {tm["account"]: tm["name"] for tm in team_members}

    editor_name = account_to_name.get(meta.username, meta.username)

    updated = update_project_meta(db, proj, meta)

    # ⭐ SSE 推送（包含 username）
    await event_bus.publish({
        "event": "ProjectUpdated",
        "payload": {
            "projectId": meta.projectId,
            "field": "meta",
            "username": editor_name
        }
    })

    return {"message": "Project updated", "data": updated.to_dict()}


# ===============================================================
# POST /project/deleteProject
# ===============================================================
@router.post("/deleteProject")
async def delete_project_api(req: ProjectDeleteRequest, db: Session = Depends(get_db)):

    deleted = delete_project(db, req.projectId)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")

    # ⭐ SSE 推送
    await event_bus.publish({
        "event": "ProjectDeleted",
        "payload": {
            "projectId": req.projectId,
            "username": req.username
        }
    })

    return {"message": "Project deleted"}


# ===============================================================
# POST /project/reorderProjects
# ===============================================================
@router.post("/reorderProjects")
async def reorder_projects_api(req: ProjectReorderRequest, db: Session = Depends(get_db)):

    reorder_projects(db, req.items)

    # ⭐ SSE 推送
    await event_bus.publish({
        "event": "ProjectReordered",
        "payload": {
            "items": req.items,
            "username": req.username
        }
    })

    return {"message": "Order updated"}


# ===============================================================
# GET /project/getPath
# ===============================================================
@router.get("/getPath")
def get_path(
    label: str,
    taskId: str,
    projectId: int,
    username: str,
    department: str,
    type: str = "",
    db: Session = Depends(get_db)
):
    project = db.query(Project).filter(Project.id == projectId).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        meta = json.loads(project.projectInfo)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"projectInfo JSON decode error: {e}")

    projectInfo = meta.get("projectInfo")
    if not isinstance(projectInfo, list):
        raise HTTPException(status_code=500, detail="projectInfo structure invalid")

    try:
        project_workflow = json.loads(project.projectWorkFlow)
        return resolve_path(
            project_info=projectInfo,
            project_workflow=project_workflow,
            label=label,
            task_id=taskId,
            requested_type=type,
        )
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"projectWorkFlow JSON decode error: {e}") from e
    except PathResolverError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ===============================================================
# POST /project/createCalibrationWorkspace
# ===============================================================
@router.post("/createCalibrationWorkspace")
def create_calibration_workspace_api(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """
    根据当前项目 Local Link 和 CalibrationID 计算本地工作区路径。

    请求体示例：
    {
        "projectId": 365,
        "username": "WUE7SZH",
        "calibrationId": "TCD08"
    }
    """

    project_id = payload.get("projectId")
    username = payload.get("username")
    calibration_id = (
        payload.get("calibrationId")
        or payload.get("CalibrationID")
        or payload.get("calibrationID")
    )

    if not project_id:
        raise HTTPException(status_code=400, detail="projectId is required")

    if not username:
        raise HTTPException(status_code=400, detail="username is required")

    if not calibration_id:
        raise HTTPException(status_code=400, detail="calibrationId is required")
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 解析 projectInfo
    try:
        meta = json.loads(project.projectInfo)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"projectInfo JSON decode error: {e}",
        )

    # 权限校验：复用 updateWorkFlow 的思路
    team_members = load_template("TeamMembers.json")
    account_to_name = {
        tm["account"]: tm["name"]
        for tm in team_members
        if "account" in tm and "name" in tm
    }

    user_name = account_to_name.get(username)

    owner = meta.get("owner", {}).get("value", "")
    proxies_raw = meta.get("proxies", {}).get("value", "")
    proxies = [x.strip() for x in proxies_raw.split(",") if x.strip()]

    if user_name != owner and user_name not in proxies:
        raise HTTPException(
            status_code=403,
            detail="No permission to create calibration workspace",
        )

    # 仅计算路径，不在 8086 上执行 mkdir
    try:
        paths = build_local_workspace_paths(
            projectInfo=meta,
            calibration_id=calibration_id,
            create=False,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error when resolving calibration workspace: {e}",
        )

    return {
        "success": True,
        "message": "Calibration workspace paths resolved",
        "projectId": project_id,
        "calibrationId": calibration_id,
        "paths": paths,
    }


@router.delete("/clearAll")
def clear_all_projects(db: Session = Depends(get_db)):

    try:
        num_deleted = db.query(Project).delete()
        db.commit()

        return {
            "success": True,
            "deleted": num_deleted
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to clear projects: {e}")


@router.get("/getAllProjectTags")
def get_all_project_tags(db: Session = Depends(get_db)):

    all_projects = db.query(Project).all()

    total = len(all_projects)
    quotation = 0
    running = 0
    sop = 0

    for p in all_projects:
        try:
            tags = json.loads(p.tags) if isinstance(p.tags, str) else p.tags
            if not isinstance(tags, list):
                tags = []
        except Exception:
            tags = []

        if not tags:
            continue

        tag = tags[0].strip().lower()

        if "quotation" in tag:
            quotation += 1
        elif "running" in tag:
            running += 1
        elif "sop" in tag:
            sop += 1

    return {
        "success": True,
        "total": total,
        "Quotation": quotation,
        "Running": running,
        "SOP": sop,
    }


@router.get("/getProjectUUID/{project_id}")
def get_project_uuid(project_id: int, db: Session = Depends(get_db)):
    uuid_value = db.query(func.json_extract(Project.projectInfo, '$.uuid.value')).filter(Project.id == project_id).scalar()
    if not uuid_value:
        raise HTTPException(
            status_code=404,
            detail=f"Project with ID {project_id} not found or has no UUID"
        )

    return {"project_id": project_id, "uuid": uuid_value}
