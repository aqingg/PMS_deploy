from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from models.database import get_db
from services.tcd08.report import generate_tcd08_report
from services.sensormap_service import (
    SensorMapConfigError,
    SensorMapError,
    SensorMapSectionError,
    SensorMapTemplateError,
    generate_sensor_map,
    load_sensormap_config,
)

router = APIRouter(prefix="/report", tags=["Report"])


# ===============================================================
# 工具函数
# ===============================================================

def _resolve_sensor_map_calibration_scope(data: dict[str, Any]) -> str:
    """
    Read Calibration Scope sent by TaskDetailPage.

    Accepted names keep the API tolerant to frontend naming changes.
    """
    value = _get_first(
        data,
        "calibrationScope",
        "calibration_scope",
        "Calibration Scope",
        default="",
    )
    return str(value or "").strip()


def _cleanup_dir(path: str) -> None:
    """FileResponse 发送完成后清理本次请求临时目录。"""
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def _safe_filename(filename: str | None, fallback: str) -> str:
    """防止上传文件名里带路径。"""
    name = Path(filename or "").name.strip()
    return name or fallback


def _parse_project_info(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            data = json.loads(value)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _parse_email_summary(value: Any) -> Optional[dict[str, Any]]:
    """
    解析 7175 Client 本地解析 email 后传来的摘要。

    新方案中，Client 不再上传 .msg / zip 文件本体，而是发送 email_summary JSON。
    为了兼容 multipart/form-data 或旧调用，这里同时支持 dict 和 JSON 字符串。
    """
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            data = json.loads(value)
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None


def _to_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _get_first(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


def _collect_generated_files(result: Any) -> list[Path]:
    """
    兼容 service 层不同返回字段。
    """
    if not isinstance(result, dict):
        return []

    candidates: list[Any] = []
    for key in ("generated_files", "server_files", "saved_paths", "files"):
        value = result.get(key)
        if isinstance(value, list):
            candidates.extend(value)

    for key in ("generated_file", "server_file", "saved_path", "download_path"):
        value = result.get(key)
        if value:
            candidates.append(value)

    files: list[Path] = []
    for item in candidates:
        if isinstance(item, dict):
            path_value = (
                item.get("path")
                or item.get("server_file")
                or item.get("saved_path")
                or item.get("download_path")
            )
        else:
            path_value = item

        if not path_value:
            continue

        path = Path(str(path_value))
        if path.is_file():
            files.append(path)

    # 去重，保持顺序
    unique: list[Path] = []
    seen: set[str] = set()
    for path in files:
        key = str(path.resolve())
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def _media_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix == ".docm":
        return "application/vnd.ms-word.document.macroEnabled.12"
    if suffix == ".zip":
        return "application/zip"
    return "application/octet-stream"


def _zip_files(files: list[Path], zip_path: Path) -> Path:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        used_names: set[str] = set()
        for index, file_path in enumerate(files, start=1):
            arcname = file_path.name
            if arcname in used_names:
                arcname = f"{file_path.stem}_{index}{file_path.suffix}"
            used_names.add(arcname)
            zf.write(file_path, arcname=arcname)
    return zip_path


# ===============================================================
# POST /report/fillTCD08Report
# ===============================================================

@router.post("/fillTCD08Report")
async def fill_tcd08_report(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    TCD08 服务器端生成接口。

    兼容两种输入：
    - 新方案：7175 Client 本地解析 email，发送 email_summary JSON，避免大文件经过 nginx/gate。
    - 旧方案：7175 Client 使用 multipart/form-data 上传 email 文件本体，Server 保存到临时目录后解析。

    本接口不读取用户 C 盘，不写入用户 C 盘。
    """
    content_type = (request.headers.get("content-type") or "").lower()

    request_temp_dir = Path(tempfile.mkdtemp(prefix="puma_tcd08_request_"))
    uploaded_email_dir = request_temp_dir / "uploaded_email"
    server_output_dir = request_temp_dir / "generated_report"
    uploaded_email_dir.mkdir(parents=True, exist_ok=True)
    server_output_dir.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {}

    try:
        # ===========================================================
        # 1. 旧方案 / fallback：multipart/form-data 上传 email 文件
        # ===========================================================
        if "multipart/form-data" in content_type:
            form = await request.form()
            upload_index = 0
            for key, value in form.multi_items():
                if isinstance(value, UploadFile):
                    upload_index += 1
                    filename = _safe_filename(value.filename, f"email_file_{upload_index}")
                    target = uploaded_email_dir / filename
                    with open(target, "wb") as out:
                        while True:
                            chunk = await value.read(1024 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                    await value.close()
                else:
                    data[key] = value

        # ===========================================================
        # 2. 新方案：application/json，包含 email_summary
        # ===========================================================
        elif "application/json" in content_type:
            try:
                payload = await request.json()
                if isinstance(payload, dict):
                    data.update(payload)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc

        else:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported content-type: {content_type}",
            )

        uuid = str(_get_first(data, "uuid", "projectid", default="")).strip()
        project_id = _to_int(_get_first(data, "projectId", "projectid", "project_id"))
        task_id = _get_first(data, "taskId", "task_id", default=None)
        project_info = _parse_project_info(
            _get_first(data, "project_info", "projectInfo", default=None)
        )
        email_summary = _parse_email_summary(
            _get_first(data, "email_summary", "emailSummary", default=None)
        )
        author = str(_get_first(data, "author", default="") or "")
        report_date = str(_get_first(data, "report_date", "reportDate", default="") or "")
        customer_release_email = str(
            _get_first(
                data,
                "customer_release_email",
                "customerReleaseEmail",
                default="",
            )
            or ""
        )

        if not uuid:
            shutil.rmtree(request_temp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail="uuid is required")

        # multipart 但没有上传文件，也可以继续让 service 自己决定是否报错。
        has_uploaded_files = any(uploaded_email_dir.iterdir())
        email_dir_for_service = str(uploaded_email_dir) if has_uploaded_files else None

        # ===========================================================
        # 3. 调用 service 层
        #
        # 第四步需要同步修改 services/tcd08/report.py，
        # 让 generate_tcd08_report 支持 email_summary 参数。
        # ===========================================================
        result = await generate_tcd08_report(
            uuid=uuid,
            project_id=project_id,
            task_id=task_id,
            project_info=project_info,
            author=author,
            report_date=report_date,
            customer_release_email=customer_release_email,
            db=db,
            uploaded_email_dir=email_dir_for_service,
            email_summary=email_summary,
            forced_output_dir=str(server_output_dir),
            copy_to_final_output=False,
        )

        generated_files = _collect_generated_files(result)
        if not generated_files:
            # 没有生成文件时，返回 JSON，同时清理临时目录
            response_payload = {
                "status": "success",
                "message": "TCD08 report generated, but no downloadable file was returned by service.",
                "result": result,
            }
            shutil.rmtree(request_temp_dir, ignore_errors=True)
            return JSONResponse(response_payload)

        background = BackgroundTask(_cleanup_dir, str(request_temp_dir))

        # ===========================================================
        # 4. 单文件：直接返回 Word
        # ===========================================================
        if len(generated_files) == 1:
            file_path = generated_files[0]
            return FileResponse(
                path=str(file_path),
                filename=file_path.name,
                media_type=_media_type_for(file_path),
                background=background,
            )

        # ===========================================================
        # 5. 多文件：打包 zip 返回
        # ===========================================================
        zip_path = request_temp_dir / "TCD08_Report_Result.zip"
        _zip_files(generated_files, zip_path)
        return FileResponse(
            path=str(zip_path),
            filename=zip_path.name,
            media_type="application/zip",
            background=background,
        )

    except HTTPException:
        shutil.rmtree(request_temp_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(request_temp_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail=f"TCD08 report server generation failed: {exc}",
        ) from exc


def _sensor_map_get_first(
    data: dict[str, Any],
    *keys: str,
    default: Any = None,
) -> Any:
    """Return the first non-empty value for the supplied keys."""
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


def _sensor_map_find_nested_value(
    data: Any,
    candidate_keys: set[str],
) -> Any:
    """
    Recursively search dictionaries/lists for a matching key.

    This allows the existing workflow executor to send project data in
    different wrappers, for example:
        {"projectInfo": {"Peripheral Sensor": "..."}}
        {"project_info": {"peripheralSensor": "..."}}
        {"data": {"project": {"peripheral_sensor_scope": "..."}}}
    """
    normalized_candidates = {
        key.casefold().replace("_", "").replace(" ", "")
        for key in candidate_keys
    }

    if isinstance(data, dict):
        label = data.get("label")
        value = data.get("value")
        normalized_label = (
            str(label).casefold().replace("_", "").replace(" ", "")
        )
        if normalized_label in normalized_candidates and value not in (
            None,
            "",
        ):
            return value

        for key, value in data.items():
            normalized_key = (
                str(key).casefold().replace("_", "").replace(" ", "")
            )
            if normalized_key in normalized_candidates and value not in (
                None,
                "",
            ):
                return value

        for value in data.values():
            found = _sensor_map_find_nested_value(
                value,
                candidate_keys,
            )
            if found not in (None, ""):
                return found

    elif isinstance(data, list):
        for item in data:
            found = _sensor_map_find_nested_value(
                item,
                candidate_keys,
            )
            if found not in (None, ""):
                return found

    return None


async def _read_sensor_map_request_data(
    request: Request,
) -> dict[str, Any]:
    """
    Read an optional JSON or form request body.

    The workflow button may submit an empty body. In that case this function
    returns an empty dictionary instead of failing.
    """
    content_type = (
        request.headers.get("content-type") or ""
    ).lower()

    if "application/json" in content_type:
        raw_body = await request.body()
        if not raw_body:
            return {}

        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid JSON body: {exc}",
            ) from exc

        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400,
                detail="Sensor Map request body must be a JSON object.",
            )
        return payload

    if (
        "multipart/form-data" in content_type
        or "application/x-www-form-urlencoded" in content_type
    ):
        form = await request.form()
        return {
            key: value
            for key, value in form.multi_items()
            if not hasattr(value, "filename")
        }

    # Empty body or a caller that does not set Content-Type.
    raw_body = await request.body()
    if not raw_body:
        return {}

    raise HTTPException(
        status_code=415,
        detail=f"Unsupported content-type: {content_type or 'unknown'}",
    )


def _resolve_sensor_map_scope(data: dict[str, Any]) -> str:
    """
    Resolve Peripheral Sensor Scope from workflow/project context.

    The endpoint accepts multiple naming conventions so the existing generic
    workflow caller does not need Sensor Map-specific frontend code.
    """
    direct_value = _sensor_map_get_first(
        data,
        "peripheralSensorScope",
        "peripheral_sensor_scope",
        "peripheralSensor",
        "peripheral_sensor",
        "Peripheral Sensor Scope",
        "Peripheral Sensor",
    )

    if direct_value not in (None, ""):
        return str(direct_value).strip()

    nested_value = _sensor_map_find_nested_value(
        data,
        {
            "peripheralSensorScope",
            "peripheral_sensor_scope",
            "peripheralSensor",
            "peripheral_sensor",
            "Peripheral Sensor Scope",
            "Peripheral Sensor",
        },
    )

    return str(nested_value or "").strip()


def _resolve_sensor_map_output_directory(
    data: dict[str, Any],
    config: dict[str, Any],
) -> Path:
    """
    Resolve the final Sensor Map output directory.

    Supported workflow context:
    1. An explicit output directory:
       outputDirectory / output_directory / sensorMapOutputDirectory
    2. A project Public Link root:
       publicLink / public_link / publicPath / public_path

    When a Public Link root is supplied, the configured
    `output_relative_path` is appended.
    """
    explicit_output = _sensor_map_get_first(
        data,
        "outputDirectory",
        "output_directory",
        "sensorMapOutputDirectory",
        "sensor_map_output_directory",
    )

    if explicit_output in (None, ""):
        explicit_output = _sensor_map_find_nested_value(
            data,
            {
                "outputDirectory",
                "output_directory",
                "sensorMapOutputDirectory",
                "sensor_map_output_directory",
            },
        )

    if explicit_output not in (None, ""):
        return Path(str(explicit_output).strip())

    public_link = _sensor_map_get_first(
        data,
        "publicLink",
        "public_link",
        "publicPath",
        "public_path",
        "projectPublicLink",
        "project_public_link",
    )

    if public_link in (None, ""):
        public_link = _sensor_map_find_nested_value(
            data,
            {
                "publicLink",
                "public_link",
                "publicPath",
                "public_path",
                "projectPublicLink",
                "project_public_link",
            },
        )

    if public_link in (None, ""):
        raise HTTPException(
            status_code=400,
            detail=(
                "Sensor Map output path could not be resolved. "
                "The workflow context must contain an output directory "
                "or the current project's Public Link."
            ),
        )

    relative_path = str(
        config.get(
            "output_relative_path",
            "40.Application/A.Vehicle_integration/03_Sensor_map",
        )
    ).strip()

    if not relative_path:
        raise HTTPException(
            status_code=500,
            detail=(
                '"output_relative_path" is missing from '
                "sensormap_sections.json."
            ),
        )

    # Convert JSON slash notation safely on Windows or Linux.
    path_parts = [
        part
        for part in relative_path.replace("\\", "/").split("/")
        if part
    ]
    return Path(str(public_link).strip()).joinpath(*path_parts)


def _resolve_sensor_map_project_name(
    data: dict[str, Any],
) -> str | None:
    """Resolve an optional project name for the generated filename."""
    value = _sensor_map_get_first(
        data,
        "projectName",
        "project_name",
        "name",
    )

    if value in (None, ""):
        value = _sensor_map_find_nested_value(
            data,
            {
                "projectName",
                "project_name",
            },
        )

    text = str(value or "").strip()
    return text or None



# ===============================================================
# POST /report/generateSensorMap
# ===============================================================
@router.post("/generateSensorMap")
async def generate_sensor_map_report(request: Request):
    """
    Generate a Sensor Map Excel file.

    The existing workflow mechanism may call this endpoint without
    Sensor Map-specific frontend code. The endpoint searches the standard
    request/project context for:
    - Peripheral Sensor Scope;
    - project Public Link or explicit output directory;
    - optional project name.

    The Excel template path and section-title mappings come from:
        PUMA_Server/config/sensormap_sections.json
    """
    try:
        data = await _read_sensor_map_request_data(request)
        config = load_sensormap_config()

        peripheral_sensor_scope = _resolve_sensor_map_scope(data)
        calibration_scope = _resolve_sensor_map_calibration_scope(data)

        if not calibration_scope:
            raise HTTPException(
             status_code=400,
             detail=(
                "Calibration Scope could not be resolved from "
                "the workflow/project context."
                ),
            )
        if not peripheral_sensor_scope:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Peripheral Sensor Scope could not be resolved from "
                    "the workflow/project context."
                ),
            )

        output_directory = _resolve_sensor_map_output_directory(
            data,
            config,
        )
        project_name = _resolve_sensor_map_project_name(data)

        result = generate_sensor_map(
        peripheral_sensor_scope=peripheral_sensor_scope,
        calibration_scope=calibration_scope,
        output_directory=output_directory,
        project_name=project_name,
        overwrite=True,
)

        return {
            "status": "success",
            "message": result.get(
                "message",
                "Sensor Map generated successfully.",
            ),
            "result": result,
        }

    except HTTPException:
        raise
    except SensorMapConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except SensorMapTemplateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except SensorMapSectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SensorMapError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Sensor Map generation failed: {exc}",
        ) from exc


