from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, UploadFile

from utils.file_loader import load_folder_mapping

TCD09_TEMPLATE_TAG_NAME = "TCD09_Input"
TCD09_UFS_EXCEL_TAG_NAME = "TCD09_UFS_Excel"
DEFAULT_TCD09_FILENAME = "QSTL0461_Instruction_Airbag-ECU_and_Sensor_installation_V1.4.docx"
DEFAULT_TCD09_UFS_EXCEL_FILENAME = "VW316_9_CS ECU及传感器安装评估图片收集 V3.0 1.xlsm"
SUPPORTED_TCD09_SUFFIXES = {".docx", ".docm"}
SUPPORTED_TCD09_EXCEL_SUFFIXES = {".xlsx", ".xlsm"}


def _safe_upload_filename(filename: str | None) -> str:
    name = str(filename or "").replace("\\", "/").split("/")[-1].strip()
    return name or DEFAULT_TCD09_FILENAME


def _get_mapping_keyword(tag_name: str, fallback: str) -> str:
    try:
        mappings = load_folder_mapping()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load FolderLinkMapping.json: {exc}",
        ) from exc

    if not isinstance(mappings, list):
        return fallback

    for item in mappings:
        if not isinstance(item, dict):
            continue
        if item.get("TagName") == tag_name:
            keyword = str(item.get("FileKeyWord") or "").strip()
            return keyword or fallback

    return fallback


def get_tcd09_expected_filename() -> str:
    return _get_mapping_keyword(TCD09_TEMPLATE_TAG_NAME, DEFAULT_TCD09_FILENAME)


def get_tcd09_ufs_excel_expected_filename() -> str:
    return _get_mapping_keyword(TCD09_UFS_EXCEL_TAG_NAME, DEFAULT_TCD09_UFS_EXCEL_FILENAME)


def _select_upload_file(
    files: list[UploadFile],
    *,
    expected_filename: str,
    allowed_suffixes: set[str],
    missing_detail_prefix: str,
) -> tuple[UploadFile, str]:
    if not files:
        raise HTTPException(status_code=400, detail="No uploaded files were provided.")

    expected_lower = expected_filename.casefold()
    uploaded_names: list[str] = []

    for upload in files:
        upload_name = _safe_upload_filename(upload.filename)
        uploaded_names.append(upload_name)
        if upload_name.casefold() == expected_lower:
            suffix = Path(upload_name).suffix.lower()
            if suffix not in allowed_suffixes:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{missing_detail_prefix} must be one of {sorted(allowed_suffixes)}. "
                        f"Got: {upload_name}"
                    ),
                )
            return upload, expected_filename

    raise HTTPException(
        status_code=404,
        detail=(
            f"{missing_detail_prefix} file not found in uploaded files. "
            f"Expected FileKeyWord='{expected_filename}'. Uploaded={uploaded_names}"
        ),
    )


def select_tcd09_template_file(files: list[UploadFile]) -> tuple[UploadFile, str]:
    return _select_upload_file(
        files,
        expected_filename=get_tcd09_expected_filename(),
        allowed_suffixes=SUPPORTED_TCD09_SUFFIXES,
        missing_detail_prefix="TCD09 template",
    )


def select_tcd09_ufs_excel_file(files: list[UploadFile]) -> tuple[UploadFile, str]:
    return _select_upload_file(
        files,
        expected_filename=get_tcd09_ufs_excel_expected_filename(),
        allowed_suffixes=SUPPORTED_TCD09_EXCEL_SUFFIXES,
        missing_detail_prefix="TCD09 UFS Excel",
    )


def select_tcd09_template_file(files: list[UploadFile]) -> tuple[UploadFile, str]:
    if not files:
        raise HTTPException(status_code=400, detail="No uploaded files were provided.")

    expected_filename = get_tcd09_expected_filename()
    expected_lower = expected_filename.casefold()
    uploaded_names: list[str] = []

    for upload in files:
        upload_name = _safe_upload_filename(upload.filename)
        uploaded_names.append(upload_name)
        if upload_name.casefold() == expected_lower:
            suffix = Path(upload_name).suffix.lower()
            if suffix not in SUPPORTED_TCD09_SUFFIXES:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"TCD09 template must be one of {sorted(SUPPORTED_TCD09_SUFFIXES)}. "
                        f"Got: {upload_name}"
                    ),
                )
            return upload, expected_filename

    raise HTTPException(
        status_code=404,
        detail=(
            "TCD09 template file not found in uploaded files. "
            f"Expected FileKeyWord='{expected_filename}'. Uploaded={uploaded_names}"
        ),
    )