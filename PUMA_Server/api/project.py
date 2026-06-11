from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from utils.file_loader import load_json, extract_root_paths, load_folder_mapping, load_template
from crud.project import (
    get_project,
    create_project,
    update_project_info,
    update_workflow,
    list_projects,
    update_project_meta,
    delete_project,
    reorder_projects
)
from models.project import Project
from models.database import get_db
import uuid
from schemas.project import (
    ProjectInfoUpdate,
    WorkFlowUpdate,
    CreateProjectRequest,
    ProjectMetaUpdate,
    ProjectReorderRequest,
    ProjectDeleteRequest
)
import json
import os
import copy

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
    account_to_name = {tm["account"]: tm["name"] for tm in team_members if "account" in tm and "name" in tm}

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
        except:
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

    # 从 TeamMembers.json 解析用户名 → 显示用
    team_members = load_template("TeamMembers.json")
    account_to_name = {tm["account"]: tm["name"] for tm in team_members}

    # ⚠ 从 meta 里拿不到 username，因此前端必须传 username
    editor_name = account_to_name.get(meta.username, meta.username)

    updated = update_project_meta(db, proj, meta)

    # ⭐ SSE 推送（包含 username）
    await event_bus.publish({
        "event": "ProjectUpdated",
        "payload": {
            "projectId": meta.projectId,
            "field": "meta",
            "username": editor_name   # ★ 这里改成正确值
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
            "username": req.username        # ⭐ 建议加上
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
            "username": req.username      # ⭐ 建议加上
        }
    })

    return {"message": "Order updated"}

# ===============================================================
# GET /project/getPath
# ===============================================================
def get_path_mapping(label: str):
    """
    从 folder_mapping.json 中读取:
    {
        "TagName": "...",
        "RelativePath": "...",
        "AbsolutePath": "..."   # optional
    }
    """
    mappings = load_folder_mapping()
    for item in mappings:
        if item["TagName"] == label:

            # ⭐ 返回结构统一
            return {
                "relative": item.get("RelativePath"),
                "absolute": item.get("AbsolutePath")
            }

    return None


def find_level1_parent_name(taskTree, targetTaskId):
    for node in taskTree:
        children1 = node.get("children", [])
        for child1 in children1:
            if child1.get("id") == targetTaskId:
                return child1["taskName"]

            for child2 in child1.get("children", []):
                if child2.get("id") == targetTaskId:
                    return child1["taskName"]

    return None


def find_level1_name_under_root(taskTree, targetTaskId):
    for node in taskTree:
        for child1 in node.get("children", []):
            if child1.get("id") == targetTaskId:
                return child1["taskName"]

            for child2 in child1.get("children", []):
                if child2.get("id") == targetTaskId:
                    return child1["taskName"]

    return None


@router.get("/getPath")
def get_path(
    label: str,
    taskId: str,
    projectId: int,
    username: str,
    department: str,
    type: str,
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

    # ============================================================
    # ⭐ 1. 从 JSON 读取 mapping（包含 absolute & relative）
    # ============================================================
    mapping = get_path_mapping(label)
    if not mapping:
        raise HTTPException(status_code=400, detail=f"No mapping found for label={label}")

    absolute_path = mapping.get("absolute")
    relative = mapping.get("relative")

    # ============================================================
    # ⭐ 2. absolutePath 优先逻辑
    # ============================================================
    if absolute_path:
        final_path = absolute_path

        # ---------------- AlgoID 替换 ----------------
        if "AlgoID" in final_path:
            workflow = json.loads(project.projectWorkFlow)
            taskTree = workflow.get("taskTree", [])
            level1_name = find_level1_parent_name(taskTree, taskId)
            if not level1_name:
                raise HTTPException(status_code=400, detail=f"Cannot find level1 parent for taskId {taskId}")
            final_path = final_path.replace("AlgoID", level1_name)

        # -------- ProjectID_Parameter_ID 替换 --------
        if "ProjectID_Parameter_ID" in final_path:
            workflow = json.loads(project.projectWorkFlow)
            taskTree = workflow.get("taskTree", [])
            p1 = find_level1_name_under_root(taskTree, taskId)
            if not p1:
                raise HTTPException(status_code=400, detail=f"Cannot find parameter-level1 parent for taskId {taskId}")
            final_path = final_path.replace("ProjectID_Parameter_ID", p1)

        return {
            "success": True,
            "root": "(absolute)",
            "path": final_path
        }

    # ============================================================
    # ⭐ 3. 没有 absolutePath → 使用 relative（你原来的逻辑）
    # ============================================================
    if not relative:
        raise HTTPException(status_code=400, detail=f"No RelativePath found for label={label}")

    root_paths = extract_root_paths(projectInfo)
    root = root_paths.get(type)
    if not root:
        raise HTTPException(status_code=400, detail=f"No root path for type={type}")

    # -------------------- Relative AlgoID Logic --------------------
    if "AlgoID" in relative:
        workflow_raw = project.projectWorkFlow
        try:
            workflow = json.loads(workflow_raw)
        except:
            raise HTTPException(status_code=500, detail="Failed to parse projectWorkFlow JSON")

        taskTree = workflow.get("taskTree", [])
        level1_name = find_level1_parent_name(taskTree, taskId)
        if not level1_name:
            raise HTTPException(status_code=400, detail=f"Cannot find level1 parent for taskId {taskId}")

        relative = relative.replace("AlgoID", level1_name)

    # -------- Relative ProjectID_Parameter_ID Logic --------
    if "ProjectID_Parameter_ID" in relative:
        workflow_raw = project.projectWorkFlow
        try:
            workflow = json.loads(workflow_raw)
        except:
            raise HTTPException(status_code=500, detail="Failed to parse projectWorkFlow JSON")

        taskTree = workflow.get("taskTree", [])
        p1 = find_level1_name_under_root(taskTree, taskId)
        if not p1:
            raise HTTPException(status_code=400, detail=f"Cannot find calibration-level1 parent for taskId {taskId}")

        relative = relative.replace("ProjectID_Parameter_ID", p1)

    # -------------------- Final Path Combination --------------------
    if type == "cloud":
        final_path = root.rstrip("/") + "/" + relative.lstrip("\\/")
    else:
        final_path = root.rstrip("\\") + "\\" + relative.lstrip("\\")

    return {
        "success": True,
        "root": root,
        "path": final_path
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
        except:
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
    uuid = db.query(func.json_extract(Project.projectInfo, '$.uuid.value')).filter(Project.id == project_id).scalar()
    if not uuid:
        raise HTTPException(
            status_code=404, 
            detail=f"Project with ID {project_id} not found or has no UUID"
        )
        
    return {"project_id": project_id, "uuid": uuid}
