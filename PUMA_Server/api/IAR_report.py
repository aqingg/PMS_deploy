from __future__ import annotations

import io
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

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
# IAR Public Link placeholders
# -----------------------------------------------------------------------------

PUBLIC_LINK_PLACEHOLDER_SPECS: dict[str, list[str]] = {
    "link_mcls": [
        "Mounting&Function Checklist Mail",
    ],
    "link_sensor_assessment": [
        "Mounting Assessment Excel (PS)",
        "Mounting Assessment Report (CS)",
        "Mounting Assessment Report (PS)",
        "Mounting Assessment Mail (CS)",
        "Mounting Picture From Customer",
    ],
    "link_ecu_assessment": [
        "Mounting Assessment Excel (PS)",
        "Mounting Assessment Report (CS)",
        "Mounting Assessment Report (PS)",
        "Mounting Assessment Mail (CS)",
        "Mounting Picture From Customer",
    ],
    "link_mounting_guideline": [
        "Mounting Guidelines (Template)",
    ],
    "link_hammer_test": [
        "Hammer Test Report",
    ],
    "link_sensor_map": [
        "Sensor Map",
        "Sensor Map Mail",
    ],
    "link_mounting_assessment": [
        "Mounting Assessment Excel (PS)",
        "Mounting Assessment Report (CS)",
        "Mounting Assessment Report (PS)",
        "Mounting Assessment Mail (CS)",
        "Mounting Picture From Customer",
    ],
    "link_mounting_function_checklist": [
        "Mounting&Function Checklist Mail",
    ],
    "link_onetcd_tcd09": [
        "Output",
        "Input",
        "ONETCD&TCD09",
        "ONETCD&TCD09_Report",
    ],
}

PUBLIC_LINK_ALIASES: dict[str, str] = {
    "public_link_hammer_test": "link_hammer_test",
    "public_link_sensor_map": "link_sensor_map",
    "public_link_mounting_assessment": "link_mounting_assessment",
    "public_link_mounting_function_checklist": "link_mounting_function_checklist",
    "public_link_onetcd_tcd09": "link_onetcd_tcd09",
    "link_mounting_checklist": "link_mounting_function_checklist",
    "link_function_checklist": "link_mounting_function_checklist",
    "link_qstl0461": "link_mounting_function_checklist",
}


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


def _sanitize_filename_part(value: Any, fallback: str) -> str:
    """
    Make a value safe for Windows file names.

    Windows forbidden characters:
        < > : " / \\ | ? *
    """
    text = str(value or "").strip()
    if not text or text.upper() in {"N/A", "NA", "NONE", "NULL"}:
        text = fallback

    forbidden = '<>:"/\\|?*'
    for ch in forbidden:
        text = text.replace(ch, "_")

    text = text.replace("\n", "_").replace("\r", "_").replace("\t", "_")
    text = "_".join(part for part in text.split(" ") if part)
    text = text.strip("._ ")

    return text or fallback


def _output_filename(profile_dict: dict[str, Any]) -> str:
    """
    Output file name format:

        OEM_projectName_Installation_Assessment_Review_Date.xlsx

    Rule:
        OEM         = <PMS.customer>    -> profile_dict["customer"]
        projectName = <PMS.projectName> -> profile_dict["projectName"]

    Fallback:
        projectName falls back to profile_dict["project"] when projectName is missing.
    """
    oem = _sanitize_filename_part(profile_dict.get("customer"), "OEM")
    project_name = _sanitize_filename_part(
        profile_dict.get("projectName") or profile_dict.get("project"),
        "projectName",
    )
    date_str = datetime.now().strftime("%Y%m%d")

    return f"{oem}_{project_name}_Installation_Assessment_Review_{date_str}.xlsx"


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

    for key in ("owner", "proxies", "uuid"):
        item = project_info.get(key)
        if isinstance(item, dict):
            label = item.get("label") or key
            _add_value(values, str(label), item.get("value"))
            _add_value(values, key, item.get("value"))
        else:
            _add_value(values, key, item)

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
        "projectName": "N/A",
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

    form_to_profile = {
        "Customer": "customer",
        "OEM": "oem",
        "Project": "project",
        "Project Name": "projectName",
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

    if not _is_meaningful(profile.get("projectName")) and _is_meaningful(profile.get("project")):
        profile["projectName"] = profile["project"]

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

    if not _is_meaningful(merged.get("projectName")) and _is_meaningful(merged.get("project")):
        merged["projectName"] = merged["project"]

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


# -----------------------------------------------------------------------------
# Public Link helpers
# -----------------------------------------------------------------------------

def _extract_project_root(project_info: dict[str, Any], root_label: str) -> str:
    """Extract Local Link/Public Link/SharePoint from flattened projectInfo."""
    flat = _flatten_local_project_info(project_info)
    candidates = (
        root_label,
        root_label.replace(" ", ""),
        root_label.lower(),
        root_label.upper(),
    )
    for key in candidates:
        value = flat.get(key)
        if _is_meaningful(value):
            return str(value).strip()
    return ""


def _normalize_relative_path(relative_path: Any) -> str:
    text = str(relative_path or "").strip()
    if not text:
        return ""
    text = text.replace("/", "\\")
    while text.startswith("\\"):
        text = text[1:]
    return text


def _is_url(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _join_root_and_relative(root: str, relative_path: str) -> str:
    """
    Join a Public Link root and a FolderLinkMapping RelativePath.

    Supports both Windows/UNC style roots and browser URL roots.
    """
    root_text = str(root or "").strip()
    rel_text = _normalize_relative_path(relative_path)
    if not root_text:
        return "N/A"
    if not rel_text:
        return root_text

    if _is_url(root_text):
        root_url = root_text.rstrip("/")
        parts = [quote(part) for part in rel_text.replace("\\", "/").split("/") if part]
        return root_url + "/" + "/".join(parts)

    return str(Path(root_text) / Path(rel_text))


def _mapping_by_tag_name() -> dict[str, dict[str, Any]]:
    try:
        mappings = load_folder_mapping()
    except Exception as exc:
        logger.warning("[IAR] Failed to load FolderLinkMapping for public links. error=%s", exc)
        return {}

    result: dict[str, dict[str, Any]] = {}
    if not isinstance(mappings, list):
        return result

    for item in mappings:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("TagName") or "").strip()
        if tag:
            result[tag] = item
    return result


def _resolve_public_link_by_tag_candidates(
    *,
    public_root: str,
    tag_candidates: list[str],
    mapping_lookup: dict[str, dict[str, Any]],
) -> str:
    for tag_name in tag_candidates:
        item = mapping_lookup.get(tag_name)
        if not item:
            continue

        absolute_path = str(item.get("AbsolutePath") or "").strip()
        relative_path = str(item.get("RelativePath") or "").strip()

        if _is_meaningful(relative_path):
            return _join_root_and_relative(public_root, relative_path)

        if _is_meaningful(absolute_path):
            return absolute_path

    return "N/A"


def _build_iar_public_link_profile(project_info: dict[str, Any]) -> dict[str, Any]:
    """
    Build Public Link placeholder values for IAR Excel.

    The Excel template can use placeholders such as:
        <PMS.link_hammer_test>
        <PMS.link_sensor_map>
        <PMS.link_mounting_assessment>
        <PMS.link_mounting_function_checklist>
        <PMS.link_onetcd_tcd09>

    Values are calculated from Project.projectInfo 'Public Link' plus
    FolderLinkMapping.json RelativePath.
    """
    public_root = _extract_project_root(project_info, "Public Link")
    profile: dict[str, Any] = {
        "public_link_root": public_root or "N/A",
    }

    if not public_root:
        logger.warning("[IAR] Public Link is empty. IAR public-link placeholders will be N/A.")
        for key in PUBLIC_LINK_PLACEHOLDER_SPECS:
            profile[key] = "N/A"
        for alias, source_key in PUBLIC_LINK_ALIASES.items():
            profile[alias] = profile.get(source_key, "N/A")
        return profile

    mapping_lookup = _mapping_by_tag_name()
    for key, tag_candidates in PUBLIC_LINK_PLACEHOLDER_SPECS.items():
        profile[key] = _resolve_public_link_by_tag_candidates(
            public_root=public_root,
            tag_candidates=tag_candidates,
            mapping_lookup=mapping_lookup,
        )

    for alias, source_key in PUBLIC_LINK_ALIASES.items():
        profile[alias] = profile.get(source_key, "N/A")

    logger.info(
        "[IAR] Public link preview: hammer=%s sensor_map=%s checklist=%s onetcd_tcd09=%s",
        profile.get("link_hammer_test"),
        profile.get("link_sensor_map"),
        profile.get("link_mounting_function_checklist"),
        profile.get("link_onetcd_tcd09"),
    )
    return profile


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
        5. Add IAR Public Link path fields from Project.projectInfo['Public Link'].
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

    remote_candidates: list[str] = []
    if _is_meaningful(explicit_uuid):
        remote_candidates.append(str(explicit_uuid).strip())
    if _is_meaningful(pms_uuid_from_local):
        remote_candidates.append(pms_uuid_from_local)
    if _is_meaningful(project_identifier) and _to_int(project_identifier) is None:
        remote_candidates.append(str(project_identifier).strip())

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

    if not _is_meaningful(profile.get("projectName")) and _is_meaningful(profile.get("project")):
        profile["projectName"] = profile["project"]

    public_link_profile = _build_iar_public_link_profile(local_project_info)
    profile.update(public_link_profile)

    logger.info(
        "[IAR] Profile preview: customer=%s project=%s projectName=%s model=%s sop=%s region=%s oem=%s public_link_root=%s",
        profile.get("customer"),
        profile.get("project"),
        profile.get("projectName"),
        profile.get("model"),
        profile.get("sop"),
        profile.get("region"),
        profile.get("oem"),
        profile.get("public_link_root"),
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
    Fill the QSCL0415 IAR Excel template and return a single .xlsx file.

    Important behavior:
        - It reads the expected template file name from FolderLinkMapping.json FileKeyWord.
        - It only processes that exact uploaded file and ignores other uploaded Office files.
        - It resolves local projectid -> Project.projectInfo.uuid -> PMS profile first.
        - It adds Public Link path placeholders from Project.projectInfo['Public Link'].
        - It returns the filled Excel workbook directly, not a zip package.
        - Output file name:
              OEM_projectName_Installation_Assessment_Review_Date.xlsx
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
    output_name = _output_filename(profile_dict)

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