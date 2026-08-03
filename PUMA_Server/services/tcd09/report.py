from __future__ import annotations

import os
from pathlib import Path
from typing import Any

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
    mapping = _get_mapping_entry(tag_name)
    if not mapping:
        return fallback

    keyword = str(mapping.get("FileKeyWord") or "").strip()
    return keyword or fallback


def _get_mapping_entry(tag_name: str) -> dict[str, Any] | None:
    try:
        mappings = load_folder_mapping()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load FolderLinkMapping.json: {exc}",
        ) from exc

    if not isinstance(mappings, list):
        return None

    for item in mappings:
        if not isinstance(item, dict):
            continue
        if item.get("TagName") == tag_name:
            return item

    return None


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


def _path_is_within(path: Path, allowed_root: Path) -> bool:
    try:
        path_key = os.path.normcase(os.path.abspath(str(path)))
        root_key = os.path.normcase(os.path.abspath(str(allowed_root)))
        return os.path.commonpath([path_key, root_key]) == root_key
    except ValueError:
        return False


def _get_tcd09_allowed_roots() -> list[Path]:
    roots: list[Path] = []
    for tag_name in (TCD09_TEMPLATE_TAG_NAME, TCD09_UFS_EXCEL_TAG_NAME):
        mapping = _get_mapping_entry(tag_name)
        absolute_path = str((mapping or {}).get("AbsolutePath") or "").strip()
        if not absolute_path:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"FolderLinkMapping.json must configure AbsolutePath for {tag_name} "
                    "when using the TCD09 path-based report API."
                ),
            )

        root = Path(absolute_path)
        if not any(os.path.normcase(str(root)) == os.path.normcase(str(item)) for item in roots):
            roots.append(root)
    return roots


def _select_tcd09_path_file(
    template_paths: list[str],
    *,
    expected_filename: str,
    allowed_suffixes: set[str],
    missing_detail_prefix: str,
    allowed_roots: list[Path],
) -> tuple[Path, str]:
    if not template_paths:
        raise HTTPException(status_code=400, detail="template_paths must not be empty.")

    expected_lower = expected_filename.casefold()
    supplied_names: list[str] = []
    for raw_path in template_paths:
        value = str(raw_path or "").strip()
        if not value:
            continue

        path = Path(value)
        supplied_names.append(path.name)
        if path.name.startswith("~$"):
            continue
        if path.name.casefold() != expected_lower:
            continue
        if path.suffix.lower() not in allowed_suffixes:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{missing_detail_prefix} must be one of {sorted(allowed_suffixes)}. "
                    f"Got: {path.name}"
                ),
            )
        if not any(_path_is_within(path, root) for root in allowed_roots):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"{missing_detail_prefix} path is outside the configured TCD09 public "
                    f"share: {path}"
                ),
            )
        if not path.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"{missing_detail_prefix} file does not exist: {path}",
            )
        if not os.access(path, os.R_OK):
            raise HTTPException(
                status_code=403,
                detail=f"{missing_detail_prefix} file is not readable: {path}",
            )
        return path, expected_filename

    raise HTTPException(
        status_code=404,
        detail=(
            f"{missing_detail_prefix} file not found in template_paths. "
            f"Expected FileKeyWord='{expected_filename}'. Supplied={supplied_names}"
        ),
    )


def select_tcd09_files_by_path(template_paths: list[str]) -> tuple[Path, Path, str]:
    """Select validated TCD09 inputs directly from configured public shares."""

    allowed_roots = _get_tcd09_allowed_roots()
    template_path, expected_filename = _select_tcd09_path_file(
        template_paths,
        expected_filename=get_tcd09_expected_filename(),
        allowed_suffixes=SUPPORTED_TCD09_SUFFIXES,
        missing_detail_prefix="TCD09 template",
        allowed_roots=allowed_roots,
    )
    excel_path, _ = _select_tcd09_path_file(
        template_paths,
        expected_filename=get_tcd09_ufs_excel_expected_filename(),
        allowed_suffixes=SUPPORTED_TCD09_EXCEL_SUFFIXES,
        missing_detail_prefix="TCD09 UFS Excel",
        allowed_roots=allowed_roots,
    )
    return template_path, excel_path, expected_filename