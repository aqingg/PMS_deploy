from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException, UploadFile

from services.path_resolver import get_mapping_entry

TCD09_TEMPLATE_TAG_NAME = "TCD09_Word_Template"
DEFAULT_TCD09_FILENAME = "QSTL0461_Instruction_Airbag-ECU_and_Sensor_installation_V1.4.docx"
SUPPORTED_TCD09_SUFFIXES = {".docx", ".docm"}
SUPPORTED_TCD09_EXCEL_SUFFIXES = {".xlsx", ".xlsm"}


def _safe_upload_filename(filename: str | None) -> str:
    name = str(filename or "").replace("\\", "/").split("/")[-1].strip()
    return name or DEFAULT_TCD09_FILENAME


def _get_mapping_keyword(tag_name: str, fallback: str) -> str:
    try:
        mapping = get_mapping_entry(tag_name)
    except Exception:
        return fallback

    keyword = str(mapping.get("FileKeyWord") or "").strip()
    return keyword or fallback


def get_tcd09_expected_filename() -> str:
    return _get_mapping_keyword(TCD09_TEMPLATE_TAG_NAME, DEFAULT_TCD09_FILENAME)


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
    candidates: list[tuple[UploadFile, str]] = []
    for upload in files:
        upload_name = _safe_upload_filename(upload.filename)
        if upload_name.startswith("~$"):
            continue
        if Path(upload_name).suffix.lower() in SUPPORTED_TCD09_EXCEL_SUFFIXES:
            candidates.append((upload, upload_name))

    if not candidates:
        raise HTTPException(
            status_code=404,
            detail="No .xlsm or .xlsx TCD09 Excel file was uploaded.",
        )
    if len(candidates) > 1:
        names = [name for _, name in candidates]
        raise HTTPException(
            status_code=409,
            detail=(
                "Multiple TCD09 Excel files were uploaded. Upload exactly one "
                f".xlsm or .xlsx file. Found={names}"
            ),
        )
    return candidates[0]


def _path_is_within(path: Path, allowed_root: Path) -> bool:
    try:
        path_key = os.path.normcase(os.path.abspath(str(path)))
        root_key = os.path.normcase(os.path.abspath(str(allowed_root)))
        return os.path.commonpath([path_key, root_key]) == root_key
    except ValueError:
        return False


def _validate_readable_file(
    path: Path,
    *,
    allowed_root: Path,
    allowed_suffixes: set[str],
    description: str,
) -> Path:
    if not _path_is_within(path, allowed_root):
        raise HTTPException(
            status_code=403,
            detail=f"{description} path is outside its configured directory: {path}",
        )
    if path.suffix.lower() not in allowed_suffixes:
        raise HTTPException(
            status_code=400,
            detail=f"{description} must be one of {sorted(allowed_suffixes)}: {path.name}",
        )
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{description} file does not exist: {path}")
    if not os.access(path, os.R_OK):
        raise HTTPException(status_code=403, detail=f"{description} file is not readable: {path}")
    return path


def _get_fixed_tcd09_template_path(template_root_value: str) -> tuple[Path, str]:
    template_root_value = str(template_root_value or "").strip()
    if not template_root_value:
        raise HTTPException(
            status_code=500,
            detail=(
                "FolderLinkMapping.json must configure AbsolutePath for "
                f"{TCD09_TEMPLATE_TAG_NAME}."
            ),
        )
    template_root = Path(template_root_value)

    expected_filename = get_tcd09_expected_filename()
    template_path = template_root / expected_filename
    return (
        _validate_readable_file(
            template_path,
            allowed_root=template_root,
            allowed_suffixes=SUPPORTED_TCD09_SUFFIXES,
            description="TCD09 template",
        ),
        expected_filename,
    )


def _select_single_tcd09_excel(input_directory: Path, public_root: Path) -> Path:
    if not _path_is_within(input_directory, public_root):
        raise HTTPException(
            status_code=403,
            detail=f"TCD09 input directory is outside the project Public Link: {input_directory}",
        )
    if not input_directory.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"TCD09 input directory does not exist: {input_directory}",
        )

    try:
        candidates = [
            path
            for path in input_directory.iterdir()
            if (
                path.is_file()
                and not path.name.startswith("~$")
                and path.suffix.lower() in SUPPORTED_TCD09_EXCEL_SUFFIXES
                and os.access(path, os.R_OK)
            )
        ]
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to inspect TCD09 input directory: {exc}",
        ) from exc

    if not candidates:
        raise HTTPException(
            status_code=404,
            detail=(
                "No readable .xlsm or .xlsx TCD09 Excel file was found in "
                f"{input_directory}."
            ),
        )
    if len(candidates) == 1:
        return candidates[0]

    picture_candidates = [
        path
        for path in candidates
        if "图片收集" in path.name or "图片" in path.name
    ]
    if len(picture_candidates) == 1:
        return picture_candidates[0]

    names = sorted(path.name for path in candidates)
    picture_names = sorted(path.name for path in picture_candidates)
    if picture_candidates:
        raise HTTPException(
            status_code=409,
            detail=(
                "Multiple Excel files with '图片' were found. Keep exactly one "
                f"TCD09 picture Excel in {input_directory}. Found={picture_names}"
            ),
        )
    raise HTTPException(
        status_code=409,
        detail=(
            "Multiple Excel files were found, but none has '图片收集' or '图片' "
            f"in its file name. Found={names}"
        ),
    )


def select_tcd09_files_by_path(
    template_root: str,
    input_directory: str,
    public_root: str,
) -> tuple[Path, Path, str]:
    """Select TCD09 files from directories already resolved by Path Resolver."""

    public_root_path = Path(str(public_root or "").strip())
    if not str(public_root_path):
        raise HTTPException(status_code=400, detail="Project Public Link must not be empty.")

    template_path, expected_filename = _get_fixed_tcd09_template_path(template_root)
    input_directory_path = Path(str(input_directory or "").strip())
    if not str(input_directory_path):
        raise HTTPException(status_code=400, detail="TCD09 input directory must not be empty.")

    excel_path = _select_single_tcd09_excel(input_directory_path, public_root_path)
    return template_path, excel_path, expected_filename