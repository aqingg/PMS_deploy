from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from models.database import get_db
from models.project import Project
from services.IAR_fill import fill_excel_by_placeholders
from services.datamerge import apply_project_info_overrides, fetch_single_project_details
from utils.file_loader import load_folder_mapping

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/report", tags=["Report"])

DEFAULT_IAR_FILE_KEYWORD = "QSCL0415_Installation_Assessment_Review_v3.2.1.xlsx"
IAR_TEMPLATE_TAG_NAME = "IAR_Template"
SUPPORTED_IAR_SUFFIXES = {".xlsx", ".xlsm"}


# -----------------------------------------------------------------------------
# File selection helpers
# -----------------------------------------------------------------------------

def _safe_upload_filename(filename: str | None) -> str:
    """Return a safe basename for UploadFile.filename, supporting Windows paths."""
    name = str(filename or "").replace("\\", "/").split("/")[-1].strip()
    return name or "uploaded_iar_template.xlsx"


def _get_iar_file_keyword_from_mapping() -> str:
    """
    Read the expected IAR Excel file name from FolderLinkMapping.json.

    Preferred mapping:
        {"TagName": "IAR_Template", "FileKeyWord": "QSCL0415_...xlsx"}
    """
    try:
        mappings = load_folder_mapping()
    except Exception as exc:
        logger.warning(
            "[IAR] Failed to load FolderLinkMapping.json. Fallback to default keyword. error=%s",
            exc,
        )
        return DEFAULT_IAR_FILE_KEYWORD

    if not isinstance(mappings, list):
        return DEFAULT_IAR_FILE_KEYWORD

    for item in mappings:
        if not isinstance(item, dict):
            continue
        if item.get("TagName") == IAR_TEMPLATE_TAG_NAME:
            keyword = str(item.get("FileKeyWord") or "").strip()
            return keyword or DEFAULT_IAR_FILE_KEYWORD

    for item in mappings:
        if not isinstance(item, dict):
            continue
        keyword = str(item.get("FileKeyWord") or "").strip()
        if keyword.casefold() == DEFAULT_IAR_FILE_KEYWORD.casefold():
            return keyword

    return DEFAULT_IAR_FILE_KEYWORD


def _select_iar_upload_file(files: list[UploadFile], expected_filename: str) -> UploadFile:
    """Only accept/read the IAR template file configured by FileKeyWord."""
    if not files:
        raise HTTPException(status_code=400, detail="No uploaded files were provided.")

    expected = expected_filename.casefold()
    uploaded_names: list[str] = []

    for upload in files:
        upload_name = _safe_upload_filename(upload.filename)
        uploaded_names.append(upload_name)
        if upload_name.casefold() == expected:
            return upload

    raise HTTPException(
        status_code=404,
        detail=(
            f"IAR template file not found in uploaded files. "
            f"Expected FileKeyWord='{expected_filename}'. "
            f"Uploaded={uploaded_names}"
        ),
    )


def _output_filename(template_filename: str) -> str:
    """Return a clear Excel result name instead of the old zip result name."""
    path = Path(template_filename)
    suffix = path.suffix or ".xlsx"
    stem = path.stem or "IAR_Result"
    return f"{stem}_filled{suffix}"


def _media_type_for_excel(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".xlsm":
        return "application/vnd.ms-excel.sheet.macroEnabled.12"
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# -----------------------------------------------------------------------------
# Project/profile helpers
# -----------------------------------------------------------------------------

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


def _is_meaningful(value: Any) -> bool:
    if value is None or value == "" or value == []:
        return False
    text = str(value).strip()
    if not text:
        return False
    return text.upper() not in {"N/A", "NA", "NULL", "NONE"}


def _add_value(target: dict[str, Any], key: str, value: Any) -> None:
    if not _is_meaningful(value):
        return
    if isinstance(value, list):
        target[key] = ", ".join(str(item) for item in value if str(item).strip())
    else:
        target[key] = str(value)


def _flatten_local_project_info(project_info: dict[str, Any]) -> dict[str, Any]:
    """Flatten local projectInfo form data as a fallback profile source."""
    values: dict[str, Any] = {}

    # Top-level metadata, normally including uuid: {label: "uuid", value: "..."}
    for key in ("owner", "proxies", "uuid"):
        item = project_info.get(key)
        if isinstance(item, dict):
            label = item.get("label") or key
            _add_value(values, str(label), item.get("value"))
            _add_value(values, key, item.get("value"))
        else:
            _add_value(values, key, item)

    # Main project form rows.
    for row in project_info.get("projectInfo", []) or []:
        if not isinstance(row, list):
            continue
        for item in row:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            if label:
                _add_value(values, label, item.get("value"))

    return values


def _extract_pms_uuid_from_project_info(project_info: dict[str, Any]) -> str:
    """
    Extract the real PMS uuid stored in local Project.projectInfo.

    Current PMS project model stores it as:
        projectInfo["uuid"] = {"label": "uuid", "value": "..."}

    This helper also supports several defensive variants so the interface can
    keep working if the form label is changed later.
    """
    candidates: list[Any] = []

    top_level_keys = (
        "uuid",
        "UUID",
        "pms_uuid",
        "PMS_UUID",
        "pmsUuid",
        "PMS UUID",
        "Project UUID",
    )
    for key in top_level_keys:
        item = project_info.get(key)
        if isinstance(item, dict):
            candidates.append(item.get("value"))
        else:
            candidates.append(item)

    flat = _flatten_local_project_info(project_info)
    for key in top_level_keys:
        candidates.append(flat.get(key))

    for value in candidates:
        if _is_meaningful(value):
            return str(value).strip()
    return ""


def _build_profile_from_local_project(project: Project | None) -> dict[str, Any]:
    """
    Fallback profile when remote PMS project details are unavailable.

    This is only a fallback. The correct source for IAR fields such as
    customer/model/region/sensors should be PMS data fetched by PMS uuid.
    """
    profile: dict[str, Any] = {
        "customer": "N/A",
        "project": "N/A",
        "model": "N/A",
        "ab_generation": "N/A",
        "vehicle_variant": "N/A",
        "sop": "N/A",
        "plattform": "N/A",
        "type": "N/A",
        "region": "N/A",
        "oem": "N/A",
        "project_leader": "N/A",
        "vint_responsible": "N/A",
        "peripheral_sensor_configuration": "N/A",
        "internal_sensor_configuration": "N/A",
        "MCR_No": "N/A",
        "role_summary": "N/A",
        "role_email_summary": "N/A",
    }

    if not project:
        return profile

    project_name = str(project.projectName or "").strip()
    if project_name:
        profile["project"] = project_name
        profile["projectName"] = project_name
        profile["model"] = project_name
        profile["vehicle_variant"] = project_name

    project_info = _parse_project_info_json(project.projectInfo)
    flat = _flatten_local_project_info(project_info)

    # Local-form fallback labels. This is intentionally conservative and does
    # not include a special plattform/platform fix per current request.
    form_to_profile = {
        "Customer": "customer",
        "OEM": "oem",
        "Project": "project",
        "Project Name": "project",
        "Model": "model",
        "Vehicle Model": "model",
        "Vehicle Variant": "vehicle_variant",
        "Product Category": "ab_generation",
        "AB Generation": "ab_generation",
        "SOP Date": "sop",
        "SOP": "sop",
        "Vehicle Type": "type",
        "Region": "region",
        "Market": "TargetMarket",
        "Project Leader": "project_leader",
        "VINT Responsible": "vint_responsible",
        "MCR No.": "MCR_No",
        "MCR No": "MCR_No",
        "Peripheral Sensor": "peripheral_sensor_configuration",
        "Inertial Sensor": "internal_sensor_configuration",
        "Internal Sensor": "internal_sensor_configuration",
        "Owner": "author",
    }

    for form_label, profile_key in form_to_profile.items():
        if _is_meaningful(flat.get(form_label)):
            profile[profile_key] = flat[form_label]

    pms_uuid = _extract_pms_uuid_from_project_info(project_info)
    if pms_uuid:
        profile["uuid"] = pms_uuid

    if _is_meaningful(flat.get("owner")):
        profile.setdefault("author", flat["owner"])

    return profile


def _fill_missing_values(base: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Use fallback values only when the base profile is missing/N/A."""
    merged = dict(base or {})
    for key, value in (fallback or {}).items():
        if not _is_meaningful(merged.get(key)) and _is_meaningful(value):
            merged[key] = value
    return merged


async def _try_fetch_pms_profile(identifier: str) -> dict[str, Any]:
    """Fetch PMS profile and return {} if the remote result is unavailable."""
    if not _is_meaningful(identifier):
        return {}

    try:
        remote_profile = await fetch_single_project_details(identifier)
    except Exception as exc:
        logger.warning(
            "[IAR] Failed to fetch PMS profile by uuid=%s. error=%s",
            identifier,
            exc,
        )
        return {}

    if isinstance(remote_profile, dict) and remote_profile:
        logger.info("[IAR] Loaded PMS profile by uuid=%s", identifier)
        return remote_profile

    return {}


async def _build_iar_profile(
    *,
    project_identifier: str,
    explicit_uuid: str,
    local_project_id: Optional[int],
    db: Session,
) -> dict[str, Any]:
    """
    Build the placeholder profile for IAR.

    Correct priority:
        1. If form-data contains uuid, use it directly.
        2. If form-data contains local projectid, read Project.projectInfo.uuid,
           then use that PMS uuid to fetch full PMS profile.
        3. If project_identifier is non-numeric, treat it as a possible PMS uuid.
        4. Use local projectInfo only as fallback/override.
    """
    local_project: Project | None = None
    local_profile: dict[str, Any] = {}
    local_project_info: dict[str, Any] = {}
    pms_uuid_from_local = ""

    if local_project_id is not None:
        local_project = db.query(Project).filter(Project.id == local_project_id).first()
        if local_project:
            local_project_info = _parse_project_info_json(local_project.projectInfo)
            local_profile = _build_profile_from_local_project(local_project)
            pms_uuid_from_local = _extract_pms_uuid_from_project_info(local_project_info)
            logger.info(
                "[IAR] Resolved local project. projectid=%s projectName=%s pms_uuid=%s",
                local_project_id,
                getattr(local_project, "projectName", ""),
                pms_uuid_from_local or "<empty>",
            )
        else:
            logger.warning("[IAR] Local project not found by projectid=%s", local_project_id)

    # Do not directly treat a numeric local DB id as PMS uuid. That was the
    # reason many placeholders became N/A.
    remote_candidates: list[str] = []
    if _is_meaningful(explicit_uuid):
        remote_candidates.append(str(explicit_uuid).strip())
    if _is_meaningful(pms_uuid_from_local):
        remote_candidates.append(pms_uuid_from_local)
    if _is_meaningful(project_identifier) and _to_int(project_identifier) is None:
        remote_candidates.append(str(project_identifier).strip())

    # De-duplicate while preserving order.
    seen: set[str] = set()
    remote_candidates = [
        item for item in remote_candidates
        if not (item in seen or seen.add(item))
    ]

    profile: dict[str, Any] = {}
    for candidate in remote_candidates:
        profile = await _try_fetch_pms_profile(candidate)
        if profile:
            profile["uuid"] = candidate
            break

    # Local Project.projectInfo can still override manually maintained fields,
    # matching existing datamerge/TCD08 behavior.
    if profile and local_project_info:
        try:
            profile = apply_project_info_overrides(profile, local_project_info)
        except Exception as exc:
            logger.warning("[IAR] apply_project_info_overrides failed: %s", exc)

    if profile:
        profile = _fill_missing_values(profile, local_profile)
    elif local_profile:
        logger.warning(
            "[IAR] PMS profile unavailable. Using local projectInfo fallback only. "
            "Some placeholders may still be N/A. projectid=%s pms_uuid=%s",
            local_project_id,
            pms_uuid_from_local or "<empty>",
        )
        profile = local_profile
    else:
        logger.warning(
            "[IAR] No PMS profile and no local project fallback. identifier=%s projectid=%s",
            project_identifier,
            local_project_id,
        )
        profile = _build_profile_from_local_project(None)

    logger.info(
        "[IAR] Profile preview: customer=%s project=%s model=%s sop=%s region=%s oem=%s",
        profile.get("customer"),
        profile.get("project"),
        profile.get("model"),
        profile.get("sop"),
        profile.get("region"),
        profile.get("oem"),
    )
    return profile


# -----------------------------------------------------------------------------
# API
# -----------------------------------------------------------------------------

@router.post("/fillIARDocuments")
async def fill_iar_documents(
    projectid: str = Form(""),
    uuid: str = Form(""),
    projectId: str = Form(""),
    project_id: str = Form(""),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """
    Fill the QSCL0415 IAR Excel template and return a single .xlsx/.xlsm file.

    Important behavior:
        - It reads the expected template file name from FolderLinkMapping.json FileKeyWord.
        - It only processes that exact uploaded file and ignores other uploaded Office files.
        - It resolves local projectid -> Project.projectInfo.uuid -> PMS profile first.
        - It returns the filled Excel workbook directly, not a zip package.
    """
    expected_filename = _get_iar_file_keyword_from_mapping()
    selected_file = _select_iar_upload_file(files, expected_filename)
    selected_name = _safe_upload_filename(selected_file.filename)
    selected_suffix = Path(selected_name).suffix.lower()

    if selected_suffix not in SUPPORTED_IAR_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"IAR template must be an Excel file {sorted(SUPPORTED_IAR_SUFFIXES)}. "
                f"Got: {selected_name}"
            ),
        )

    try:
        content = await selected_file.read()
    finally:
        for upload in files:
            try:
                await upload.close()
            except Exception:
                pass

    if not content:
        raise HTTPException(status_code=400, detail=f"Uploaded IAR template is empty: {selected_name}")

    # 7175 currently sends form-data projectid. In this workflow, projectid is
    # normally the local DB project id. The real PMS uuid is stored in
    # Project.projectInfo.uuid and must be resolved before fetching PMS details.
    project_identifier = (projectid or projectId or project_id or uuid or "").strip()
    explicit_uuid = (uuid or "").strip()
    local_project_id = _to_int(projectId) or _to_int(project_id) or _to_int(projectid)

    profile_dict = await _build_iar_profile(
        project_identifier=project_identifier,
        explicit_uuid=explicit_uuid,
        local_project_id=local_project_id,
        db=db,
    )

    logger.info(
        "[IAR] Filling template. expected=%s selected=%s project_identifier=%s explicit_uuid=%s local_project_id=%s",
        expected_filename,
        selected_name,
        project_identifier,
        explicit_uuid or "<empty>",
        local_project_id,
    )

    filled_stream = fill_excel_by_placeholders(profile_dict, io.BytesIO(content))
    output_name = _output_filename(expected_filename)

    # The current 7175 /saveReport parses filename=... from this header and saves response.content.
    headers = {
        "Content-Disposition": f'attachment; filename="{output_name}"',
        "X-IAR-Template-File": expected_filename,
        "X-IAR-Output-Mode": "single-excel",
    }

    return StreamingResponse(
        filled_stream,
        media_type=_media_type_for_excel(output_name),
        headers=headers,
    )