import getpass
import json
import logging
import re
import shutil
import tempfile
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.project import Project
from services.datamerge import (
    apply_project_info_overrides,
    fetch_single_project_details,
    fill_docx_by_placeholders,
)
from services.tcd08.rules import (
    red_paragraph_deletion_rules,
    red_paragraph_text_rewrite_rules,
    sections_to_delete_by_calibration_scope,
)
from services.word_sections import (
    remove_empty_email_simulation_blocks,
    replace_red_font_with_black,
    remove_template_instruction_text,
    remove_red_paragraph_groups,
    remove_red_paragraph_groups_batch,
    remove_word_sections,
    rewrite_red_paragraph_text,
    rewrite_red_paragraph_text_batch,
    update_tocs_with_word,
)
from utils.file_loader import load_folder_mapping

logger = logging.getLogger("uvicorn.error")


def _merge_red_paragraph_deletions(red_deletions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 section 合并 delete_groups，避免逐条删除造成组号重排。"""
    grouped_indexes: dict[str, set[int]] = defaultdict(set)
    grouped_rules: dict[str, list[str]] = defaultdict(list)

    for deletion in red_deletions:
        section = str(deletion.get("section", "")).strip()
        if not section:
            continue
        for group_index in deletion.get("delete_groups", []):
            try:
                grouped_indexes[section].add(int(group_index))
            except (TypeError, ValueError):
                continue
        description = str(deletion.get("description", "")).strip()
        if description:
            grouped_rules[section].append(description)

    merged: list[dict[str, Any]] = []
    for section, indexes in grouped_indexes.items():
        merged.append(
            {
                "section": section,
                "delete_groups": sorted(indexes),
                "matched_rules": grouped_rules.get(section, []),
            }
        )
    return merged


def _safe_filename_part(value: Any) -> str:
    """把 projectName 转成可安全用于 Windows 文件名的片段。"""
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._ ")
    return text or "TCD08_Report"


_MISSING_EMAIL_SIMULATION_VALUE_TEXTS = {
    "",
    "-",
    "—",
    "n/a",
    "na",
    "n.a",
    "n.a.",
    "none",
    "null",
}


def _normalize_optional_email_value(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\u00a0", " ")
    text = text.replace("，", ",")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text.strip(" .。:：\t\r\n")


def _optional_email_items(value: Any) -> list[str]:
    """Return meaningful file items from an email_summary field."""
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        return [
            str(item).strip()
            for item in value
            if _normalize_optional_email_value(item) not in _MISSING_EMAIL_SIMULATION_VALUE_TEXTS
        ]

    if isinstance(value, str):
        normalized = _normalize_optional_email_value(value)
        if normalized in _MISSING_EMAIL_SIMULATION_VALUE_TEXTS:
            return []
        if "\n" in value:
            return [
                item.strip()
                for item in value.splitlines()
                if _normalize_optional_email_value(item) not in _MISSING_EMAIL_SIMULATION_VALUE_TEXTS
            ]
        return [
            item.strip()
            for item in value.split(",")
            if _normalize_optional_email_value(item) not in _MISSING_EMAIL_SIMULATION_VALUE_TEXTS
        ]

    normalized = _normalize_optional_email_value(value)
    return [] if normalized in _MISSING_EMAIL_SIMULATION_VALUE_TEXTS else [str(value).strip()]


def _first_present_value(source: dict[str, Any], keys: list[str]) -> tuple[bool, Any]:
    for key in keys:
        if key in source:
            return True, source.get(key)
    return False, None


def _resolve_missing_email_simulation_keys(email_summary: Any) -> list[str]:
    """Decide which Email simulation optional blocks are truly empty.

    Important safety rule:
    If the expected field is not present in email_summary, do NOT guess it is
    empty. This prevents permanent deletion when the input JSON shape changes.
    """
    if not isinstance(email_summary, dict) or not email_summary:
        return []

    send = email_summary.get("send")
    if not isinstance(send, dict):
        return []

    field_candidates = {
        "standard": [
            "standard_xlsx_files",
            "standardXlsxFiles",
            "StandardXlsxFiles",
            "standard_files",
            "StandardFiles",
        ],
        "defect": [
            "defect_xlsx_files",
            "defectXlsxFiles",
            "DefectXlsxFiles",
            "defect_files",
            "DefectFiles",
        ],
        "specific": [
            "specific_xlsx_files",
            "specificXlsxFiles",
            "SpecificXlsxFiles",
            "specific_files",
            "SpecificFiles",
        ],
    }

    missing_keys: list[str] = []
    for block_key, candidates in field_candidates.items():
        found, value = _first_present_value(send, candidates)
        if found and not _optional_email_items(value):
            missing_keys.append(block_key)

    return missing_keys


# 固定收尾处理开关：
# 如需临时保留模板里的删除提示语/红色字体，把对应值改为 False 即可。
REMOVE_TEMPLATE_INSTRUCTIONS_ENABLED = True
REPLACE_RED_FONT_WITH_BLACK_ENABLED = True

# 红转黑白名单：这些章节保留红色，不执行红转黑。
# 示例：{"4.1"}
RED_TO_BLACK_SECTION_WHITELIST: set[str] = {"4.1"}

# 是否把整条文档处理链路放到本地临时目录执行：
# - True：先在服务器 temp 路径处理（含 TOC），最后统一复制到输出目录。
# - False：直接在输出目录原位置处理。
# 注意：当 copy_to_final_output=False 时，本函数会强制直接写 forced_output_dir，避免再复制到用户 C 盘。
PROCESS_ALL_STEPS_IN_LOCAL_TEMP = True


def _mapping_by_tag(tag_name: str) -> dict:
    """从 FolderLinkMapping.json 中找到指定 TagName 的配置项。"""
    for item in load_folder_mapping():
        if item.get("TagName") == tag_name:
            return item
    raise HTTPException(status_code=400, detail=f"No folder mapping found for {tag_name}")


def _mapping_base_path(item: dict, tag_name: str) -> Path:
    """读取某个 mapping 配置的 AbsolutePath，并确认路径存在。"""
    absolute_path = item.get("AbsolutePath") or ""
    if not absolute_path:
        raise HTTPException(status_code=400, detail=f"No AbsolutePath configured for {tag_name}")

    path = Path(absolute_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Configured path not found: {path}")
    return path


def _resolve_template_paths() -> list[Path]:
    """解析 TCD08 模板文件路径。模板仍来自服务器/公盘 AbsolutePath。"""
    item = _mapping_by_tag("ONETCD&TCD08_Template")
    base_path = _mapping_base_path(item, "ONETCD&TCD08_Template")
    file_keyword = (item.get("FileKeyWord") or "").strip()

    if file_keyword:
        if "/" in file_keyword or "\\" in file_keyword:
            raise HTTPException(
                status_code=400,
                detail="FileKeyWord must be a file name, not a path",
            )
        exact_file = base_path / file_keyword
        if not exact_file.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"TCD08 template file not found: {exact_file}",
            )
        return [exact_file]

    if not base_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"TCD08 template mapping must point to a folder when FileKeyWord is empty: {base_path}",
        )

    template_paths = [
        path
        for path in sorted(base_path.iterdir())
        if path.is_file() and path.suffix.lower() in {".docx", ".docm"}
    ]
    if not template_paths:
        raise HTTPException(status_code=404, detail=f"No Word templates found in {base_path}")
    return template_paths


def _resolve_output_dir() -> Path:
    """
    旧接口兜底输出目录。
    新架构下 7175 调用 8086 时，会传 forced_output_dir，通常不会走这里。
    """
    item = _mapping_by_tag("ONETCD&TCD08_Report")
    absolute_path = item.get("AbsolutePath") or ""
    if not absolute_path:
        raise HTTPException(
            status_code=400,
            detail="No AbsolutePath configured for ONETCD&TCD08_Report",
        )
    output_dir = Path(absolute_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _load_project_info_from_db(project_id: Optional[int], db: Session) -> dict:
    """当前端没有直接传 project_info 时，从本地 DB 读取 projectInfo。"""
    if not project_id:
        return {}
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    try:
        return json.loads(project.projectInfo)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"projectInfo JSON decode error: {exc}",
        ) from exc


def _load_project_name_from_db(project_id: Optional[int], db: Session) -> str:
    """从本地 projects 表读取 New Project 时输入的 projectName。"""
    if not project_id:
        return ""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return str(project.projectName or "").strip()


def _load_project_workflow_from_db(project_id: Optional[int], db: Session) -> dict[str, Any]:
    if not project_id:
        return {}
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    try:
        workflow = json.loads(project.projectWorkFlow or "{}")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"projectWorkFlow JSON decode error: {exc}",
        ) from exc
    return workflow if isinstance(workflow, dict) else {}


def _find_task_path(nodes: list[dict[str, Any]], target_task_id: str) -> list[dict[str, Any]] | None:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        current_path = [node]
        if node.get("id") == target_task_id:
            return current_path
        children = node.get("children") or []
        if isinstance(children, list) and children:
            child_path = _find_task_path(children, target_task_id)
            if child_path:
                return current_path + child_path
    return None


def _extract_calibration_parameter(task_name: str) -> str:
    clean_name = str(task_name or "").strip()
    if not clean_name:
        return ""
    if "_" in clean_name:
        suffix = clean_name.rsplit("_", 1)[-1].strip()
        if suffix:
            return suffix
    return clean_name


def _resolve_calibration_task_name_from_workflow(
    workflow: dict[str, Any],
    task_id: Optional[str],
) -> str:
    if not task_id:
        return ""
    task_tree = workflow.get("taskTree", [])
    if not isinstance(task_tree, list) or not task_tree:
        return ""
    path = _find_task_path(task_tree, task_id)
    if not path or len(path) < 2:
        return ""
    parent_task = path[-2]
    return str(parent_task.get("taskName") or "").strip()


def _resolve_calibration_parameter_from_workflow(
    workflow: dict[str, Any],
    task_id: Optional[str],
) -> str:
    parent_name = _resolve_calibration_task_name_from_workflow(workflow, task_id)
    return _extract_calibration_parameter(parent_name)


def _fill_docx_by_placeholders_with_optional_email_data(
    profile_dict: dict[str, Any],
    template_path: Path,
    uploaded_email_dir: str | None,
    email_summary: dict[str, Any] | None,
):
    """
    调用 datamerge.fill_docx_by_placeholders。

    第五步会同步修改 services/datamerge.py，使它正式支持 email_summary 参数：
    - 新方案：fill_docx_by_placeholders(profile, template, email_summary=..., email_dir=...)
    - 旧上传兜底：fill_docx_by_placeholders(profile, template, email_dir=...)
    - 最旧兜底：fill_docx_by_placeholders(profile, template)

    为了减少第四步覆盖后立刻因旧 datamerge 签名崩溃，这里做兼容降级。
    """
    if isinstance(email_summary, dict) and email_summary:
        try:
            return fill_docx_by_placeholders(
                profile_dict,
                template_path,
                email_dir=uploaded_email_dir,
                email_summary=email_summary,
            )
        except TypeError as exc:
            if "email_summary" not in str(exc):
                raise
            logger.warning(
                "[TCD08] services.datamerge.fill_docx_by_placeholders does not support "
                "email_summary yet. Fallback to email_dir/legacy call. Please complete step 5.",
                exc_info=True,
            )

    if uploaded_email_dir:
        try:
            return fill_docx_by_placeholders(
                profile_dict,
                template_path,
                email_dir=uploaded_email_dir,
            )
        except TypeError as exc:
            if "email_dir" not in str(exc):
                raise
            logger.warning(
                "[TCD08] services.datamerge.fill_docx_by_placeholders does not support "
                "email_dir yet. Fallback to legacy call without uploaded email_dir. Please complete step 5.",
                exc_info=True,
            )
    return fill_docx_by_placeholders(profile_dict, template_path)


async def generate_tcd08_report(
    *,
    uuid: str,
    project_id: Optional[int],
    task_id: Optional[str],
    project_info: dict[str, Any],
    author: str,
    report_date: str,
    customer_release_email: str,
    db: Session,
    uploaded_email_dir: str | None = None,
    email_summary: dict[str, Any] | None = None,
    forced_output_dir: str | None = None,
    copy_to_final_output: bool = True,
) -> dict:
    """
    TCD08 报告生成主流程。

    新架构职责边界：
    - 7175 Client 读取用户 C 盘 Customer_Approval_Email，并在本地解析 email/zip。
    - 7175 优先把 email_summary JSON 发给 8086，不再上传大 email 文件本体。
    - 兼容旧流程：若仍有 uploaded_email_dir，则 8086 可读取服务器临时 email 目录。
    - 8086 只把生成文件写到 forced_output_dir，即服务器临时输出目录。
    - 8086 不再复制或写入用户 C 盘。

    参数说明：
    - email_summary：7175 本地解析出的 email/zip 摘要，用于避免大文件上传触发 513。
    - uploaded_email_dir：旧上传流程中，api/report.py 保存上传 email 文件的服务器临时目录。
    - forced_output_dir：api/report.py 为本次请求创建的服务器临时输出目录。
    - copy_to_final_output：False 时禁止 shutil.copy2 到最终路径；直接在 forced_output_dir 生成，供 FileResponse 返回。
    """
    request_start = time.perf_counter()
    logger.info("[TCD08] Start generating report. uuid=%s", uuid)

    profile_dict = await fetch_single_project_details(uuid)
    if not profile_dict:
        raise HTTPException(
            status_code=404,
            detail=f"无法检索到项目UUID '{uuid}' 的详细信息。",
        )

    resolved_project_info = project_info or _load_project_info_from_db(project_id, db)
    if not isinstance(resolved_project_info, dict):
        resolved_project_info = {}

    project_name = _load_project_name_from_db(project_id, db)
    if project_name:
        profile_dict["projectName"] = project_name
        logger.info("[TCD08] Loaded projectName from DB. project_id=%s value=%s", project_id, project_name)

    # 兜底：若前端未传 Owner，但传了 author，则回填到 project_info。
    owner_item = resolved_project_info.get("owner")
    owner_value = ""
    if isinstance(owner_item, dict):
        owner_value = str(owner_item.get("value") or "").strip()
    if not owner_value and str(author).strip():
        resolved_project_info["owner"] = {"label": "Owner", "value": str(author).strip()}

    logger.info(
        "[TCD08] Project info loaded. source=%s project_id=%s",
        "request" if project_info else "database",
        project_id,
    )

    if resolved_project_info:
        profile_dict = apply_project_info_overrides(profile_dict, resolved_project_info)
        logger.info("[TCD08] Applied project info overrides to PMS profile.")

    workflow = _load_project_workflow_from_db(project_id, db)
    calibration_task_name = _resolve_calibration_task_name_from_workflow(workflow, task_id)
    calibration_parameter = _resolve_calibration_parameter_from_workflow(workflow, task_id)

    if calibration_task_name:
        logger.info(
            "[TCD08] Resolved calibration task name from workflow. task_id=%s value=%s",
            task_id,
            calibration_task_name,
        )
    if calibration_parameter:
        profile_dict["CalibrationParameter"] = calibration_parameter
        logger.info(
            "[TCD08] Resolved calibration parameter from workflow. task_id=%s value=%s",
            task_id,
            calibration_parameter,
        )
    else:
        logger.info("[TCD08] Calibration parameter not resolved from workflow. task_id=%s", task_id)

    profile_dict["author"] = (
        author
        or profile_dict.get("author")
        or profile_dict.get("project_leader")
        or getpass.getuser().upper()
    )
    profile_dict["report_date"] = report_date or datetime.now().strftime("%Y.%m.%d")
    profile_dict["customer_release_email"] = customer_release_email or "N/A"

    template_paths = _resolve_template_paths()

    if forced_output_dir:
        output_dir = Path(forced_output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info("[TCD08] Using forced server output dir: %s", output_dir)
    else:
        output_dir = _resolve_output_dir()
        logger.info("[TCD08] Using legacy output dir: %s", output_dir)

    if isinstance(email_summary, dict) and email_summary:
        send = email_summary.get("send") if isinstance(email_summary.get("send"), dict) else {}
        approval = email_summary.get("approval") if isinstance(email_summary.get("approval"), dict) else {}
        logger.info(
            "[TCD08] Using client parsed email_summary. send_file=%s approval_file=%s zip=%s",
            send.get("file") or send.get("msg_file") or "N/A",
            approval.get("file") or approval.get("msg_file") or "N/A",
            send.get("zip") or send.get("zip_file_name") or "N/A",
        )
    else:
        email_summary = None

    missing_email_simulation_keys = _resolve_missing_email_simulation_keys(email_summary)
    logger.info(
        "[TCD08] Empty Email simulation block cleanup plan. missing_keys=%s",
        missing_email_simulation_keys or "none",
    )

    if uploaded_email_dir:
        uploaded_email_path = Path(uploaded_email_dir)
        if uploaded_email_path.exists():
            logger.info("[TCD08] Using uploaded server email dir: %s", uploaded_email_path)
        else:
            logger.warning("[TCD08] uploaded_email_dir does not exist: %s", uploaded_email_path)
            uploaded_email_dir = None

    sections_to_delete = sections_to_delete_by_calibration_scope(resolved_project_info)
    red_paragraph_deletions = red_paragraph_deletion_rules(resolved_project_info, sections_to_delete)
    merged_red_paragraph_deletions = _merge_red_paragraph_deletions(red_paragraph_deletions)
    red_paragraph_text_rewrites = red_paragraph_text_rewrite_rules(resolved_project_info, sections_to_delete)

    logger.info(
        "[TCD08] Resolved %s template(s). output_dir=%s",
        len(template_paths),
        output_dir,
    )
    logger.info(
        "[TCD08] Section deletion plan from Calibration Scope: %s",
        sections_to_delete or "no sections to delete",
    )
    logger.info(
        "[TCD08] Red paragraph deletion plan: %s",
        merged_red_paragraph_deletions or "no red paragraph groups to delete",
    )
    logger.info(
        "[TCD08] Red paragraph text rewrite plan: %s",
        red_paragraph_text_rewrites or "no red paragraph text to rewrite",
    )

    saved_paths: list[str] = []
    generated_files: list[str] = []
    toc_update_paths: list[Path] = []
    section_delete_results: list[dict[str, Any]] = []
    red_paragraph_delete_results: list[dict[str, Any]] = []
    red_paragraph_text_rewrite_results: list[dict[str, Any]] = []
    instruction_removal_results: list[dict[str, Any]] = []
    color_replacement_results: list[dict[str, Any]] = []
    optional_block_removal_results: list[dict[str, Any]] = []
    toc_update_warning: str | None = None
    local_output_pairs: list[tuple[Path, Path]] = []

    # 新架构 copy_to_final_output=False 时，必须禁止最后 copy2 到用户 C 盘。
    # 直接把文件写在服务器 forced_output_dir，FileResponse 再返回给 7175。
    use_local_temp_workflow = PROCESS_ALL_STEPS_IN_LOCAL_TEMP and copy_to_final_output
    local_runtime_dir = (
        tempfile.TemporaryDirectory(prefix="puma_tcd08_report_")
        if use_local_temp_workflow
        else None
    )
    local_runtime_root = Path(local_runtime_dir.name) if local_runtime_dir else None

    if local_runtime_root is not None:
        logger.info("[TCD08] Local temp workflow enabled. temp_root=%s", local_runtime_root)
    else:
        logger.info(
            "[TCD08] Direct server output workflow enabled. copy_to_final_output=%s output_dir=%s",
            copy_to_final_output,
            output_dir,
        )

    try:
        for index, template_path in enumerate(template_paths, start=1):
            template_start = time.perf_counter()
            logger.info(
                "[TCD08] (%s/%s) Filling template: %s",
                index,
                len(template_paths),
                template_path,
            )

            step_start = time.perf_counter()
            filled_stream = _fill_docx_by_placeholders_with_optional_email_data(
                profile_dict,
                template_path,
                uploaded_email_dir,
                email_summary,
            )
            logger.info(
                "[TCD08] (%s/%s) Placeholder filling took %.2fs.",
                index,
                len(template_paths),
                time.perf_counter() - step_start,
            )

            date_stamp = datetime.now().strftime("%Y%m%d")
            safe_project_name = _safe_filename_part(profile_dict.get("projectName") or template_path.stem)
            output_name = f"{safe_project_name}_Calibration_Report_{date_stamp}{template_path.suffix}"
            output_path = output_dir / output_name

            working_path = output_path
            if local_runtime_root is not None:
                working_path = local_runtime_root / output_name
                local_output_pairs.append((working_path, output_path))

            step_start = time.perf_counter()
            with open(working_path, "wb") as output_file:
                output_file.write(filled_stream.read())
            logger.info(
                "[TCD08] (%s/%s) Filled document saved in %.2fs: %s",
                index,
                len(template_paths),
                time.perf_counter() - step_start,
                working_path,
            )

            optional_blocks_removed = 0
            if missing_email_simulation_keys:
                logger.info(
                    "[TCD08] (%s/%s) Removing empty Email simulation blocks. missing_keys=%s",
                    index,
                    len(template_paths),
                    missing_email_simulation_keys,
                )
                step_start = time.perf_counter()
                optional_block_summary = remove_empty_email_simulation_blocks(
                    working_path,
                    missing_keys=missing_email_simulation_keys,
                    use_local_temp=False,
                )
                optional_blocks_removed = optional_block_summary.removed_blocks
                optional_block_removal_results.append(
                    {
                        "file": str(output_path),
                        "requested_labels": optional_block_summary.requested_labels,
                        "removed_labels": optional_block_summary.removed_labels,
                        "skipped_labels": optional_block_summary.skipped_labels,
                        "removed_blocks": optional_block_summary.removed_blocks,
                        "removed_paragraphs": optional_block_summary.removed_paragraphs,
                    }
                )
                logger.info(
                    "[TCD08] (%s/%s) Removed empty Email simulation blocks in %.2fs. requested=%s removed=%s skipped=%s paragraphs=%s",
                    index,
                    len(template_paths),
                    time.perf_counter() - step_start,
                    optional_block_summary.requested_labels,
                    optional_block_summary.removed_labels,
                    optional_block_summary.skipped_labels,
                    optional_block_summary.removed_paragraphs,
                )

            if red_paragraph_text_rewrites:
                logger.info(
                    "[TCD08] (%s/%s) Batched red paragraph text rewrite for %s rule(s).",
                    index,
                    len(template_paths),
                    len(red_paragraph_text_rewrites),
                )
                step_start = time.perf_counter()
                rewrite_plans = [
                    {
                        "section": text_rewrite["section"],
                        "group": text_rewrite["group"],
                        "replacements": [
                            (replacement["from"], replacement["to"])
                            for replacement in text_rewrite["replacements"]
                        ],
                    }
                    for text_rewrite in red_paragraph_text_rewrites
                ]
                rewrite_summaries = rewrite_red_paragraph_text_batch(
                    working_path,
                    plans=rewrite_plans,
                    update_toc=False,
                    use_local_temp=False,
                )
                for text_rewrite, rewrite_summary in zip(red_paragraph_text_rewrites, rewrite_summaries):
                    red_paragraph_text_rewrite_results.append(
                        {
                            "file": str(output_path),
                            "section": rewrite_summary.section,
                            "group": rewrite_summary.group_index,
                            "rule": text_rewrite.get("description", ""),
                            "replacements_applied": rewrite_summary.replacements_applied,
                            "before": rewrite_summary.before_text,
                            "after": rewrite_summary.after_text,
                        }
                    )
                logger.info(
                    "[TCD08] (%s/%s) Batched red paragraph text rewrite took %.2fs.",
                    index,
                    len(template_paths),
                    time.perf_counter() - step_start,
                )

            if merged_red_paragraph_deletions:
                logger.info(
                    "[TCD08] (%s/%s) Batched red paragraph deletion for %s section(s).",
                    index,
                    len(template_paths),
                    len(merged_red_paragraph_deletions),
                )
                step_start = time.perf_counter()
                delete_plans = [
                    {
                        "section": red_deletion["section"],
                        "selected_indexes": red_deletion.get("delete_groups", []),
                    }
                    for red_deletion in merged_red_paragraph_deletions
                ]
                red_summaries = remove_red_paragraph_groups_batch(
                    working_path,
                    plans=delete_plans,
                    update_toc=False,
                    use_local_temp=False,
                )
                deletion_meta = {
                    str(item.get("section", "")).strip(): item
                    for item in merged_red_paragraph_deletions
                }
                for red_summary in red_summaries:
                    meta = deletion_meta.get(red_summary.section, {})
                    red_paragraph_delete_results.append(
                        {
                            "file": str(output_path),
                            "section": red_summary.section,
                            "requested_indexes": meta.get("delete_groups", []),
                            "matched_rules": meta.get("matched_rules", []),
                            "deleted_indexes": red_summary.deleted_indexes,
                            "remaining_red_groups": red_summary.remaining_red_groups,
                            "preview": red_summary.deleted_preview,
                        }
                    )
                logger.info(
                    "[TCD08] (%s/%s) Batched red paragraph deletion took %.2fs.",
                    index,
                    len(template_paths),
                    time.perf_counter() - step_start,
                )

            if sections_to_delete:
                logger.info(
                    "[TCD08] (%s/%s) Removing sections after red paragraph processing: %s",
                    index,
                    len(template_paths),
                    sections_to_delete,
                )
                step_start = time.perf_counter()
                deleted_sections = remove_word_sections(
                    working_path,
                    sections_to_delete,
                    update_toc=False,
                    use_local_temp=False,
                )
                section_delete_results.extend(
                    {
                        "file": str(output_path),
                        "section": result.removed_section,
                        "deleted_xml_nodes": result.deleted_xml_nodes,
                        "renumbered_paragraphs": result.typed_renumbered_paragraphs,
                        "preview": result.deleted_preview,
                    }
                    for result in deleted_sections
                )
                logger.info(
                    "[TCD08] (%s/%s) Removed %s section(s) in %.2fs.",
                    index,
                    len(template_paths),
                    len(deleted_sections),
                    time.perf_counter() - step_start,
                )

            instruction_replacements_applied = 0
            if REMOVE_TEMPLATE_INSTRUCTIONS_ENABLED:
                logger.info(
                    "[TCD08] (%s/%s) Removing template instruction text.",
                    index,
                    len(template_paths),
                )
                step_start = time.perf_counter()
                instruction_summary = remove_template_instruction_text(
                    working_path,
                    use_local_temp=False,
                )
                instruction_replacements_applied = instruction_summary.replacements_applied
                instruction_removal_results.append(
                    {
                        "file": str(output_path),
                        "instructions": instruction_summary.instructions,
                        "replacements_applied": instruction_summary.replacements_applied,
                        "changed_paragraphs": instruction_summary.changed_paragraphs,
                    }
                )
                logger.info(
                    "[TCD08] (%s/%s) Removed template instruction text in %.2fs. replacements=%s",
                    index,
                    len(template_paths),
                    time.perf_counter() - step_start,
                    instruction_summary.replacements_applied,
                )
            else:
                logger.info(
                    "[TCD08] (%s/%s) Template instruction removal disabled.",
                    index,
                    len(template_paths),
                )

            color_changed_runs = 0
            if REPLACE_RED_FONT_WITH_BLACK_ENABLED:
                logger.info(
                    "[TCD08] (%s/%s) Replacing remaining red font with black.",
                    index,
                    len(template_paths),
                )
                step_start = time.perf_counter()
                color_summary = replace_red_font_with_black(
                    working_path,
                    preserve_sections=RED_TO_BLACK_SECTION_WHITELIST,
                    use_local_temp=False,
                )
                color_changed_runs = color_summary.changed_runs
                color_replacement_results.append(
                    {
                        "file": str(output_path),
                        "source_colors": color_summary.source_colors,
                        "target_color": color_summary.target_color,
                        "changed_runs": color_summary.changed_runs,
                    }
                )
                logger.info(
                    "[TCD08] (%s/%s) Replaced red font with black in %.2fs. changed_runs=%s",
                    index,
                    len(template_paths),
                    time.perf_counter() - step_start,
                    color_summary.changed_runs,
                )
            else:
                logger.info(
                    "[TCD08] (%s/%s) Red-to-black font replacement disabled.",
                    index,
                    len(template_paths),
                )

            if (
                sections_to_delete
                or red_paragraph_deletions
                or red_paragraph_text_rewrites
                or instruction_replacements_applied
                or color_changed_runs
                or optional_blocks_removed
            ):
                logger.info(
                    "[TCD08] (%s/%s) Queued document for batched Word TOC update.",
                    index,
                    len(template_paths),
                )
                toc_update_paths.append(working_path)

            saved_paths.append(str(output_path))
            generated_files.append(str(output_path if local_runtime_root is None else working_path))
            logger.info(
                "[TCD08] (%s/%s) Template processing completed in %.2fs.",
                index,
                len(template_paths),
                time.perf_counter() - template_start,
            )

        if toc_update_paths:
            logger.info(
                "[TCD08] Updating Word TOC for %s document(s) in one Word session.",
                len(toc_update_paths),
            )
            step_start = time.perf_counter()
            try:
                update_tocs_with_word(toc_update_paths)
                logger.info(
                    "[TCD08] Batched Word TOC update took %.2fs.",
                    time.perf_counter() - step_start,
                )
            except Exception as exc:
                # TOC 更新失败不应影响文档生成主流程，降级为告警并继续返回成功。
                toc_update_warning = str(exc)
                logger.warning(
                    "[TCD08] Batched Word TOC update failed but report generation continues. error=%s",
                    exc,
                    exc_info=True,
                )

        if local_output_pairs and copy_to_final_output:
            step_start = time.perf_counter()
            copied_paths: list[str] = []
            for local_path, final_path in local_output_pairs:
                final_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(local_path, final_path)
                copied_paths.append(str(final_path))
            generated_files = copied_paths
            logger.info(
                "[TCD08] Copied %s local processed document(s) back to output_dir in %.2fs.",
                len(local_output_pairs),
                time.perf_counter() - step_start,
            )
        elif local_output_pairs and not copy_to_final_output:
            # 正常新架构不会进入这里，因为 copy_to_final_output=False 时已经禁用 local temp workflow。
            logger.warning(
                "[TCD08] local_output_pairs exists but copy_to_final_output=False. "
                "Skip copy2 to avoid writing user C drive."
            )
    finally:
        if local_runtime_dir is not None:
            local_runtime_dir.cleanup()

    logger.info(
        "[TCD08] Report generation completed in %.2fs. saved_paths=%s generated_files=%s",
        time.perf_counter() - request_start,
        saved_paths,
        generated_files,
    )

    return {
        "status": "success",
        "message": "TCD08报告已成功生成。",
        "template_paths": [str(path) for path in template_paths],
        "saved_paths": saved_paths,
        "generated_files": generated_files,
        "server_files": generated_files,
        "calibration_task_name": calibration_task_name,
        "calibration_parameter": calibration_parameter,
        "email_dir": str(uploaded_email_dir) if uploaded_email_dir else None,
        "email_summary_used": bool(email_summary),
        "output_dir": str(output_dir),
        "copy_to_final_output": copy_to_final_output,
        "section_deletions": section_delete_results,
        "red_paragraph_deletions": red_paragraph_delete_results,
        "red_paragraph_text_rewrites": red_paragraph_text_rewrite_results,
        "instruction_removals": instruction_removal_results,
        "color_replacements": color_replacement_results,
        "optional_block_removals": optional_block_removal_results,
        "toc_update_warning": toc_update_warning,
    }
