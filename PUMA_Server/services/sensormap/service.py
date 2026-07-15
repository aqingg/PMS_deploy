from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .errors import (
    SensorMapConfigError,
    SensorMapError,
    SensorMapSectionError,
    SensorMapTemplateError,
)
from .excel_com import ExcelSession
from .parser import parse_sensor_requests
from .rules import (
    DEFAULT_SECTION_CONFIG_PATH,
    DEFAULT_SENSOR_RULES_PATH,
    load_sensor_rules,
    load_sensormap_config,
)
from .topology import resolve_sensor_selections
from .worksheet import (
    build_calibration_row_delete_ranges,
    build_sensor_detail_delete_ranges,
    delete_row_ranges,
    delete_unused_calibration_columns,
    find_calibration_columns,
    find_sensor_sections,
    merge_row_ranges,
    parse_calibration_scope,
)

LOGGER = logging.getLogger(__name__)

SUPPORTED_EXCEL_SUFFIXES = {".xls", ".xlsx", ".xlsm", ".xlsb"}
_EXCEL_COM_LOCK = threading.Lock()


def _normalize_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def parse_peripheral_sensor_scope(
    scope: str | None,
    sensor_sections: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    """Legacy section-level detection retained for non-detailed sensors."""
    normalized_scope = _normalize_text(scope)
    detected: set[str] = set()

    for raw_code, rule in sensor_sections.items():
        code = str(raw_code).upper().strip()
        for alias in rule.get("aliases", []):
            normalized_alias = _normalize_text(alias)
            if not normalized_alias:
                continue

            pattern = (
                rf"(?<![a-z])"
                rf"{re.escape(normalized_alias)}"
                rf"(?![a-z])"
            )
            if re.search(pattern, normalized_scope):
                detected.add(code)
                break

    return detected


def _resolve_template_path(configured_value: Any) -> Path:
    configured_path = Path(
        str(configured_value or "").strip()
    ).expanduser()

    candidates = [
        configured_path.with_suffix(".xls"),
        configured_path,
        configured_path.with_suffix(".xlsx"),
        configured_path.with_suffix(".xlsm"),
        configured_path.with_suffix(".xlsb"),
    ]

    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(
            os.path.abspath(str(candidate))
        )
        if key in seen:
            continue
        seen.add(key)

        if candidate.is_file():
            if candidate.suffix.lower() not in SUPPORTED_EXCEL_SUFFIXES:
                raise SensorMapTemplateError(
                    f"Unsupported Excel format: {candidate.suffix}"
                )
            return candidate

    raise SensorMapTemplateError(
        "Sensor Map template does not exist. Attempted: "
        + ", ".join(str(path) for path in candidates)
    )


def _resolve_output_filename(
    template_path: Path,
    output_filename: str | None,
    project_name: str | None,
) -> str:
    suffix = template_path.suffix.lower()
    requested = str(output_filename or "").strip()

    if requested:
        candidate = Path(requested).name
        candidate_path = Path(candidate)
        if candidate_path.suffix.lower() in SUPPORTED_EXCEL_SUFFIXES:
            return candidate_path.with_suffix(suffix).name
        return candidate + suffix

    safe_project = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]+',
        "_",
        str(project_name or "Sensor_Map"),
    ).strip(" ._") or "Sensor_Map"

    return (
        f"{safe_project}_Sensor_Map_"
        f"{datetime.now().strftime('%Y%m%d')}{suffix}"
    )


def _verify_kept_and_removed_sections(
    worksheet: Any,
    config: Mapping[str, Any],
    sensors_to_keep: set[str],
    removed_sections: list[str],
) -> None:
    from .worksheet import iter_non_empty_cells, normalize_text

    current_values = {
        text
        for _, _, text in iter_non_empty_cells(worksheet)
    }

    failures: list[str] = []
    for raw_code, rule in config["sensor_sections"].items():
        code = str(raw_code).upper().strip()
        titles = {
            normalize_text(title)
            for title in rule.get("titles", [])
            if normalize_text(title)
        }
        exists = bool(current_values & titles)

        if code in sensors_to_keep and not exists:
            failures.append(
                f"{code}: expected section to remain."
            )
        if code in removed_sections and exists:
            failures.append(
                f"{code}: expected section to be removed."
            )

    if failures:
        raise SensorMapSectionError(
            "Sensor section verification failed: "
            + "; ".join(failures)
        )


def _edit_workbook(
    temporary_path: Path,
    config: Mapping[str, Any],
    sensor_rules: Mapping[str, Any],
    sensors_to_keep: set[str],
    selections: Mapping[str, Any],
    calibration_to_keep: set[str],
) -> tuple[str, list[str], list[str], dict[str, Any], dict[str, Any]]:
    with ExcelSession(temporary_path) as excel:
        worksheet = excel.select_worksheet(
            config.get("worksheet_name")
        )
        worksheet_name = str(worksheet.Name)

        if bool(worksheet.ProtectContents):
            raise SensorMapTemplateError(
                f'Worksheet "{worksheet_name}" is protected.'
            )

        sections = find_sensor_sections(
            worksheet,
            config,
        )

        sections_to_remove = [
            section
            for code, section in sections.items()
            if code not in sensors_to_keep
        ]

        removed_sections = sorted(
            section.sensor_code
            for section in sections_to_remove
        )

        peripheral_ranges = [
            (section.start_row, section.end_row)
            for section in sections_to_remove
        ]

        calibration_row_ranges, calibration_row_details = (
            build_calibration_row_delete_ranges(
                worksheet,
                config,
                calibration_to_keep,
            )
        )

        sensor_detail_ranges, sensor_detail_details = (
            build_sensor_detail_delete_ranges(
                worksheet,
                sections,
                selections,
                sensor_rules,
            )
        )

        delete_row_ranges(
            worksheet,
            merge_row_ranges(
                [
                    *peripheral_ranges,
                    *calibration_row_ranges,
                    *sensor_detail_ranges,
                ]
            ),
        )

        _verify_kept_and_removed_sections(
            worksheet,
            config,
            sensors_to_keep,
            removed_sections,
        )

        located_columns = find_calibration_columns(
            worksheet,
            config.get("calibration_columns", {}),
        )

        removed_calibration_columns = (
            delete_unused_calibration_columns(
                worksheet,
                located_columns,
                calibration_to_keep,
            )
        )

        excel.save()

        return (
            worksheet_name,
            removed_sections,
            removed_calibration_columns,
            calibration_row_details,
            sensor_detail_details,
        )


def generate_sensor_map(
    peripheral_sensor_scope: str | None,
    output_directory: str | Path,
    *,
    calibration_scope: str | None = None,
    project_name: str | None = None,
    output_filename: str | None = None,
    config_path: str | Path = DEFAULT_SECTION_CONFIG_PATH,
    sensor_rules_path: str | Path = DEFAULT_SENSOR_RULES_PATH,
    overwrite: bool = True,
) -> dict[str, Any]:
    config = load_sensormap_config(config_path)
    sensor_rules = load_sensor_rules(sensor_rules_path)

    template_path = _resolve_template_path(
        config["template_path"]
    )

    output_dir = Path(output_directory).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = _resolve_output_filename(
        template_path,
        output_filename,
        project_name,
    )
    output_path = output_dir / filename

    if output_path.exists() and not overwrite:
        raise SensorMapTemplateError(
            f"Output file already exists: {output_path}"
        )

    # 1) Legacy section-level detection keeps simple sensors such as PPS/PTS
    #    working even before they receive detailed topology rules.
    sensors_to_keep = parse_peripheral_sensor_scope(
        peripheral_sensor_scope,
        config["sensor_sections"],
    )

    # 2) Semantic parser + topology engine handles detailed sensors.
    requests = parse_sensor_requests(
        peripheral_sensor_scope,
        sensor_rules,
    )
    selections = resolve_sensor_selections(
        requests,
        sensor_rules,
    )
    sensors_to_keep.update(selections.keys())

    if not sensors_to_keep:
        raise SensorMapSectionError(
            "No supported Peripheral Sensor was recognized from: "
            f"{peripheral_sensor_scope!r}. Generation was stopped to prevent "
            "deleting every Sensor section."
        )

    calibration_to_keep = parse_calibration_scope(
        calibration_scope,
        config.get("calibration_columns", {}),
    )

    temporary_path = output_path.with_name(
        f"__puma_sensormap_{uuid.uuid4().hex}"
        f"{template_path.suffix.lower()}"
    )

    try:
        shutil.copy2(template_path, temporary_path)

        with _EXCEL_COM_LOCK:
            (
                worksheet_name,
                removed_sections,
                removed_calibration_columns,
                calibration_row_details,
                sensor_detail_details,
            ) = _edit_workbook(
                temporary_path,
                config,
                sensor_rules,
                sensors_to_keep,
                selections,
                calibration_to_keep,
            )

        temporary_path.replace(output_path)

    except SensorMapError:
        raise
    except PermissionError as exc:
        raise SensorMapTemplateError(
            "Permission denied. Confirm that the template/output file is not "
            "open in Excel and that the account can write to the directory."
        ) from exc
    except Exception as exc:
        LOGGER.exception(
            "Unexpected Sensor Map generation failure."
        )
        raise SensorMapError(
            f"Unexpected Sensor Map generation failure: {exc}"
        ) from exc
    finally:
        if temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                LOGGER.warning(
                    "Unable to remove temporary Sensor Map file: %s",
                    temporary_path,
                )

    return {
        "success": True,
        "message": "Sensor Map generated successfully by Microsoft Excel.",
        "template_path": str(template_path),
        "output_path": str(output_path),
        "worksheet": worksheet_name,
        "scope": peripheral_sensor_scope or "",
        "calibration_scope": calibration_scope or "",
        "kept_sections": sorted(sensors_to_keep),
        "removed_sections": removed_sections,
        "kept_calibration_columns": sorted(calibration_to_keep),
        "removed_calibration_columns": removed_calibration_columns,
        "calibration_row_rules": calibration_row_details,
        "sensor_selections": {
            code: selection.as_dict()
            for code, selection in selections.items()
        },
        "sensor_detail_filters": sensor_detail_details,
        "sensor_parse_warnings": {
            code: list(selection.warnings)
            for code, selection in selections.items()
            if selection.warnings
        },
        "engine": "Microsoft Excel COM",
        "file_format": template_path.suffix.lower(),
    }
