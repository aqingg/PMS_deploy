import json
from models.project import Project
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List

# 查询项目（按 projectId）
def get_project(db: Session, username: str, projectId: int):
    return (
        db.query(Project)
        .filter(Project.username == username, Project.id == projectId)
        .first()
    )

# 按项目名查重（用于创建）
def project_exists_by_name(db: Session, username: str, projectName: str):
    return db.query(Project).filter(
        and_(Project.username == username, Project.projectName == projectName)
    ).first()

# 创建项目
def create_project(db: Session, username, department, projectName, projectInfo, workFlow, owner, editors, comment: str = "", tags: list[str] | None = None,):
    db_project = Project(
        username=username,
        owner=owner,
        editors=json.dumps(editors or []),
        department=department,
        projectName=projectName,
        projectInfo=json.dumps(projectInfo),
        projectWorkFlow=json.dumps(workFlow),
        comment=comment,
        tags=json.dumps(tags) if tags else None,
    )
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project

# 更新项目信息
def update_project_info(db, project, projectInfo):
    project.projectInfo = json.dumps(projectInfo)
    db.commit()
    db.refresh(project)
    return project

# 更新 Workflow
def update_workflow(db, project, workflow):
    project.projectWorkFlow = json.dumps(workflow)
    db.commit()
    db.refresh(project)
    return project

def count_task_nodes(task_tree):
    total = 0
    done = 0
    
    def dfs(node):
        nonlocal total, done
        total += 1
        if node.get("status") in ("Done", "Decline"):
            done += 1
        for c in node.get("children", []):
            dfs(c)

    for root in task_tree:
        dfs(root)

    return total, done

# 列出项目
def list_projects(db: Session, username: str):
    return (
        db.query(Project)
        .filter(Project.username == username)
        .order_by(Project.orderIndex.asc())
        .all()
    )

# 更新项目 Meta（兼容 projectName=None）
def update_project_meta(db: Session, project: Project, meta):
    if meta.projectName is not None:
        project.projectName = meta.projectName

    project.comment = meta.comment
    project.tags = json.dumps(meta.tags)
    db.commit()
    db.refresh(project)
    return project

# 删除
def delete_project(db: Session, project_id: int):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if proj:
        db.delete(proj)
        db.commit()
    return proj

# 重排
def reorder_projects(db: Session, ids: List[int]):
    for idx, pid in enumerate(ids):
        db.query(Project).filter(Project.id == pid).update({
            "orderIndex": idx
        })
    db.commit()
