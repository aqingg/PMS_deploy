from __future__ import annotations

import io
import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models.database import get_db
from models.project import Project
from services.datamerge import (
    apply_project_info_overrides,
    fetch_single_project_details,
    fill_docx_by_placeholders,
)
from services.tcd09 import (
    insert_excel_section_images,
    remove_tcd09_template_instructions,
    remove_unused_sensor_references,
    select_tcd09_files_by_path,
    select_tcd09_template_file,
    select_tcd09_ufs_excel_file,
    insert_tcd09_sensor_layout_shapes,
)
from services.tcd09.sensor_overview import fill_tcd09_sensor_type_rows
from utils.file_loader import extract_root_paths


router = APIRouter(prefix="/report", tags=["Report"])


class TCD09PathReportRequest(BaseModel):
    projectid: str = ""
    template_paths: list[str] = Field(default_factory=list)


def _to_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _parse_project_info_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _extract_pms_uuid_from_project_info(project_info: dict[str, Any]) -> str:
    uuid_item = project_info.get("uuid")
    if isinstance(uuid_item, dict):
        return str(uuid_item.get("value") or "").strip()
    return ""


def _get_tcd09_project_public_root(
    project_identifier: str,
    db: Session,
) -> str:
    project_id = _to_int(project_identifier)
    if project_id is None:
        raise HTTPException(status_code=400, detail="TCD09 projectid must be a project ID.")

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    project_info = _parse_project_info_json(project.projectInfo)
    rows = project_info.get("projectInfo")
    if not isinstance(rows, list):
        raise HTTPException(status_code=500, detail="projectInfo structure is invalid.")

    public_root = str(extract_root_paths(rows).get("public") or "").strip()
    if not public_root:
        raise HTTPException(
            status_code=400,
            detail="Project does not define the Public Link required for TCD09.",
        )
    return public_root


def _build_local_fallback_profile(
    project: Project | None,
    project_info: dict[str, Any],
) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "customer": "N/A",
        "project": "N/A",
        "projectName": (
            str(getattr(project, "projectName", "") or "").strip() or "N/A"
        ),
        "author": "N/A",
    }

    rows = project_info.get("projectInfo", []) if isinstance(project_info, dict) else []
    for row in rows:
        if not isinstance(row, list):
            continue
        for item in row:
            if not isinstance(item, dict):
                continue

            label = str(item.get("label") or "").strip()
            value = item.get("value")
            if value in (None, "", []):
                continue

            text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
            if label == "OEM":
                profile["customer"] = text
                profile["oem"] = text
            elif (
                label == "Project Leader"
                and profile.get("author") in {None, "", "N/A"}
            ):
                profile["author"] = text
            elif label == "Vehicle Type" and profile.get("project") in {
                None,
                "",
                "N/A",
            }:
                profile["project"] = text

    owner_item = project_info.get("owner") if isinstance(project_info, dict) else None
    if isinstance(owner_item, dict):
        owner_value = str(owner_item.get("value") or "").strip()
        if owner_value:
            profile["author"] = owner_value
    if profile.get("project") in {None, "", "N/A"}:
        profile["project"] = profile.get("projectName") or "N/A"

    return profile


async def _build_tcd09_profile(
    project_identifier: str,
    db: Session,
) -> dict[str, Any]:
    local_project_id = _to_int(project_identifier)
    local_project: Project | None = None
    local_project_info: dict[str, Any] = {}
    local_profile: dict[str, Any] = {}
    pms_uuid = ""

    if local_project_id is not None:
        local_project = (
            db.query(Project)
            .filter(Project.id == local_project_id)
            .first()
        )
        if local_project:
            local_project_info = _parse_project_info_json(local_project.projectInfo)
            local_profile = _build_local_fallback_profile(
                local_project,
                local_project_info,
            )
            pms_uuid = _extract_pms_uuid_from_project_info(local_project_info)

    profile: dict[str, Any] = {}
    if pms_uuid:
        fetched = await fetch_single_project_details(pms_uuid)
        if isinstance(fetched, dict):
            profile = fetched
        profile["uuid"] = pms_uuid

    # Always apply the locally saved front-end fields. This guarantees that
    # Inertial Sensor and Peripheral Sensor from EditPage are available even
    # when the remote PMS profile is empty or temporarily unavailable.
    if local_project_info:
        profile = apply_project_info_overrides(profile, local_project_info)

    if local_profile:
        for key, value in local_profile.items():
            if value not in (None, "", []):
                if key not in profile or profile.get(key) in (None, "", "N/A"):
                    profile[key] = value

    if not profile:
        profile = local_profile

    if local_project and str(local_project.projectName or "").strip():
        profile["projectName"] = str(local_project.projectName).strip()

    if (
        not str(profile.get("projectName") or "").strip()
        and str(profile.get("project") or "").strip()
    ):
        profile["projectName"] = str(profile.get("project")).strip()

    if (
        not str(profile.get("customer") or "").strip()
        and str(profile.get("oem") or "").strip()
    ):
        profile["customer"] = str(profile.get("oem")).strip()

    # TCD09 templates use this generated date instead of relying on a
    # front-end field that may be absent from the saved project profile.
    profile["report_date"] = datetime.now().strftime("%Y.%m.%d")

    return profile


async def _generate_tcd09_report(
    projectid: str,
    content: bytes,
    excel_content: bytes,
    db: Session,
):
    profile = await _build_tcd09_profile(str(projectid or "").strip(), db)
    filled_stream = insert_excel_section_images(io.BytesIO(content), excel_content)
    filled_stream = fill_tcd09_sensor_type_rows(profile, filled_stream)
    filled_stream = fill_docx_by_placeholders(
        profile,
        filled_stream,
        include_email_placeholders=False,
    )
    filled_stream = remove_unused_sensor_references(profile, filled_stream)
    filled_stream = remove_tcd09_template_instructions(filled_stream)

    # Word COM must run last. A later python-docx save may remove or alter
    # editable Office Shapes.
    return insert_tcd09_sensor_layout_shapes(profile, filled_stream)


def _tcd09_response(
    filled_stream: io.BytesIO,
    expected_filename: str,
    projectid: str,
):
    headers = {
        "Content-Disposition": f'attachment; filename="{expected_filename}"',
        "X-TCD09-Mode": "docx-images-sensor-overview-editable-layout",
        "X-TCD09-ProjectId": str(projectid or ""),
    }
    return StreamingResponse(
        filled_stream,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        headers=headers,
    )


@router.post("/fillTCD09Report")
async def fill_tcd09_report(
    projectid: str = Form(""),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Generate the current-stage TCD09 Word report.

    Processing order:
    1. Insert configured Excel images.
    2. Expand and fill Sensor Overview rows.
    3. Fill the remaining ordinary PMS text placeholders.
    4. Remove References entries for peripheral sensors not configured.
    5. Remove TCD09 template editing instructions.
    6. Add independent editable Word sensor-label Shapes and refresh the TOC.
    """

    selected_file, expected_filename = select_tcd09_template_file(files)
    selected_excel_file, _ = select_tcd09_ufs_excel_file(files)
    selected_name = selected_file.filename or expected_filename

    try:
        content = await selected_file.read()
        excel_content = await selected_excel_file.read()
    finally:
        for upload in files:
            try:
                await upload.close()
            except Exception:
                pass

    if not content:
        raise HTTPException(
            status_code=400,
            detail=f"Uploaded TCD09 template is empty: {selected_name}",
        )

    if not excel_content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded TCD09 UFS Excel is empty.",
        )

    filled_stream = await _generate_tcd09_report(
        projectid,
        content,
        excel_content,
        db,
    )
    return _tcd09_response(filled_stream, expected_filename, projectid)


@router.post("/fillTCD09ReportByPath")
async def fill_tcd09_report_by_path(
    request: TCD09PathReportRequest,
    db: Session = Depends(get_db),
):
    """Generate TCD09 from its fixed Word template and project Public Link Excel."""

    project_public_root = _get_tcd09_project_public_root(request.projectid, db)
    template_path, excel_path, expected_filename = select_tcd09_files_by_path(project_public_root)
    try:
        content = template_path.read_bytes()
        excel_content = excel_path.read_bytes()
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to read TCD09 files from public share: {exc}",
        ) from exc

    if not content:
        raise HTTPException(
            status_code=400,
            detail=f"TCD09 template is empty: {template_path}",
        )
    if not excel_content:
        raise HTTPException(
            status_code=400,
            detail=f"TCD09 UFS Excel is empty: {excel_path}",
        )

    filled_stream = await _generate_tcd09_report(
        request.projectid,
        content,
        excel_content,
        db,
    )
    return _tcd09_response(
        filled_stream,
        expected_filename,
        request.projectid,
    )
