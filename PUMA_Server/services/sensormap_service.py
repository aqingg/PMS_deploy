"""
公盘原始模板.xls
        ↓ 复制
公盘输出目录中的临时文件.xls
        ↓ Excel COM 打开
删除未选中的 Sensor 行区块
        ↓
删除未选中的 Calibration Scope 测试列
        ↓ Excel COM 保存
公盘临时文件.xls
        ↓ 同目录重命名
最终结果.xls

Sensor Map Excel generation service based on Microsoft Excel COM.

Why COM
-------
The original Sensor Map template is a legacy .xls workbook. Using the native
Excel COM object model allows Excel itself to delete worksheet rows and save
the workbook in its original format, which better preserves legacy formatting,
formulas, charts, names, VBA projects and other Excel-specific features.

Public API compatibility
------------------------
This module intentionally keeps the same public names used by api/report.py:

- SensorMapConfigError
- SensorMapError
- SensorMapSectionError
- SensorMapTemplateError
- load_sensormap_config(...)
- generate_sensor_map(...)

Therefore api/report.py and the frontend do not need to change.
"""

from __future__ import annotations

import gc
import json
import logging
import os
import re
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "sensormap_sections.json"
)

SUPPORTED_EXCEL_SUFFIXES = {".xls", ".xlsx", ".xlsm", ".xlsb"}

# Excel COM automation is not reliably thread-safe. Serializing requests also
# reduces the risk of leaving multiple orphaned EXCEL.EXE processes.
_EXCEL_COM_LOCK = threading.Lock()

# Excel constants used without importing generated COM type libraries.
XL_SHIFT_UP = -4162
MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3


class SensorMapError(RuntimeError):
    """Base exception for Sensor Map generation failures."""


class SensorMapConfigError(SensorMapError):
    """Raised when the Sensor Map JSON configuration is invalid."""


class SensorMapTemplateError(SensorMapError):
    """Raised when the Excel template cannot be found or opened."""


class SensorMapSectionError(SensorMapError):
    """Raised when configured Sensor sections cannot be resolved safely."""


@dataclass(frozen=True)
class SectionLocation:
    """A Sensor section located in a worksheet."""

    sensor_code: str
    start_row: int
    end_row: int
    title: str


def _normalize_text(value: Any) -> str:
    """
    Normalize text for reliable comparisons.

    Normalization includes:
    - conversion to string;
    - replacement of common full-width punctuation;
    - trimming;
    - collapsing repeated whitespace;
    - case-insensitive comparison.
    """
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\u3000", " ")
    text = text.replace("：", ":")
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def load_sensormap_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    """Load and validate the Sensor Map JSON configuration."""
    path = Path(config_path)

    if not path.is_file():
        raise SensorMapConfigError(
            f"Sensor Map config file does not exist: {path}"
        )

    try:
        with path.open("r", encoding="utf-8-sig") as file:
            config = json.load(file)
    except json.JSONDecodeError as exc:
        raise SensorMapConfigError(
            f"Sensor Map config is not valid JSON: {path}. "
            f"Line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise SensorMapConfigError(
            f"Unable to read Sensor Map config: {path}"
        ) from exc

    if not isinstance(config, dict):
        raise SensorMapConfigError(
            "Sensor Map config root must be a JSON object."
        )

    template_path = config.get("template_path")
    if not isinstance(template_path, str) or not template_path.strip():
        raise SensorMapConfigError(
            '"template_path" must be a non-empty string.'
        )

    sensor_sections = config.get("sensor_sections")
    if not isinstance(sensor_sections, dict) or not sensor_sections:
        raise SensorMapConfigError(
            '"sensor_sections" must be a non-empty JSON object.'
        )

    for code, rule in sensor_sections.items():
        if not isinstance(rule, dict):
            raise SensorMapConfigError(
                f'Sensor rule "{code}" must be a JSON object.'
            )

        aliases = rule.get("aliases")
        titles = rule.get("titles")

        if not isinstance(aliases, list) or not any(
            isinstance(item, str) and item.strip() for item in aliases
        ):
            raise SensorMapConfigError(
                f'Sensor rule "{code}" must contain a non-empty '
                '"aliases" string list.'
            )

        if not isinstance(titles, list) or not any(
            isinstance(item, str) and item.strip() for item in titles
        ):
            raise SensorMapConfigError(
                f'Sensor rule "{code}" must contain a non-empty '
                '"titles" string list.'
            )

    calibration_columns = config.get("calibration_columns", {})
    if not isinstance(calibration_columns, dict):
        raise SensorMapConfigError(
            '"calibration_columns" must be a JSON object.'
        )

    for code, rule in calibration_columns.items():
        if not isinstance(rule, dict):
            raise SensorMapConfigError(
                f'Calibration column rule "{code}" must be a JSON object.'
            )

        scope_aliases = rule.get("scope_aliases")
        column_titles = rule.get("column_titles")

        if not isinstance(scope_aliases, list) or not any(
            isinstance(item, str) and item.strip()
            for item in scope_aliases
        ):
            raise SensorMapConfigError(
                f'Calibration column rule "{code}" must contain a non-empty '
                '"scope_aliases" string list.'
            )

        if not isinstance(column_titles, list) or not any(
            isinstance(item, str) and item.strip()
            for item in column_titles
        ):
            raise SensorMapConfigError(
                f'Calibration column rule "{code}" must contain a non-empty '
                '"column_titles" string list.'
            )

    return config


def parse_peripheral_sensor_scope(
    scope: str | None,
    sensor_sections: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    """
    Convert a Peripheral Sensor string to configured Sensor codes.

    Examples:
        "2*UFS6s+2*PAS6s+2*PPS3" -> {"UFS", "PAS", "PPS"}
        "PCS + RCS"               -> {"PCS", "RCS"}

    Aliases may touch digits but are not matched inside a longer alphabetic
    word. For example, UFS matches UFS6s but not MUFSTEST.
    """
    normalized_scope = _normalize_text(scope)
    if not normalized_scope:
        return set()

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



def parse_calibration_scope(
    scope: str | None,
    calibration_columns: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    """
    Convert Calibration Scope text to configured calibration-column keys.

    Example:
        "FSR+Rose1+Offzone"
        -> {"ROLL_OVER", "OFFZONE"}

    The actual mapping is defined in sensormap_sections.json, for example:
        Rose1 / Rose1+ -> roll over crash test
        PitchOver      -> pitchover
        Offzone        -> offzone
        EPP            -> pedestrian protection test
    """
    normalized_scope = _normalize_text(scope)
    if not normalized_scope:
        return set()

    detected: set[str] = set()

    for raw_code, rule in calibration_columns.items():
        code = str(raw_code).upper().strip()

        for alias in rule.get("scope_aliases", []):
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
    """
    Resolve the configured template.

    To support replacing the committed test.xlsx with the original test.xls
    without changing another source file, a same-directory, same-stem .xls
    file is preferred when it exists.

    Resolution order:
    1. same-stem .xls;
    2. exact configured path;
    3. same-stem .xlsx/.xlsm/.xlsb fallback.
    """
    configured_path = Path(str(configured_value or "").strip()).expanduser()

    candidates: list[Path] = []

    # The requested migration explicitly prefers the original legacy workbook.
    legacy_candidate = configured_path.with_suffix(".xls")
    candidates.append(legacy_candidate)
    candidates.append(configured_path)

    for suffix in (".xlsx", ".xlsm", ".xlsb"):
        candidates.append(configured_path.with_suffix(suffix))

    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(str(candidate)))
        if key in seen:
            continue
        seen.add(key)

        if candidate.is_file():
            suffix = candidate.suffix.lower()
            if suffix not in SUPPORTED_EXCEL_SUFFIXES:
                raise SensorMapTemplateError(
                    "Unsupported Sensor Map Excel format: "
                    f"{candidate.suffix}. Supported formats: "
                    f"{sorted(SUPPORTED_EXCEL_SUFFIXES)}"
                )
            return candidate

    attempted = ", ".join(str(path) for path in candidates)
    raise SensorMapTemplateError(
        "Sensor Map template does not exist. Attempted: "
        f"{attempted}"
    )


def _resolve_output_filename(
    template_path: Path,
    output_filename: str | None,
    project_name: str | None,
) -> str:
    """Build a safe output filename while preserving the template suffix."""
    suffix = template_path.suffix.lower()
    requested = str(output_filename or "").strip()

    if requested:
        candidate = Path(requested).name
        candidate_path = Path(candidate)

        if candidate_path.suffix.lower() in SUPPORTED_EXCEL_SUFFIXES:
            candidate = candidate_path.with_suffix(suffix).name
        elif not candidate.lower().endswith(suffix):
            candidate += suffix

        return candidate

    safe_project = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]+',
        "_",
        str(project_name or "Sensor_Map"),
    ).strip(" ._")

    if not safe_project:
        safe_project = "Sensor_Map"

    date_text = datetime.now().strftime("%Y%m%d")
    return f"{safe_project}_Sensor_Map_{date_text}{suffix}"


def _import_excel_com() -> tuple[Any, Any, Any]:
    """Import Windows COM modules lazily and return clear setup errors."""
    if os.name != "nt":
        raise SensorMapTemplateError(
            "Excel COM automation requires Windows. "
            f"Current operating system: {os.name}"
        )

    try:
        import pythoncom
        import pywintypes
        import win32com.client
    except ImportError as exc:
        raise SensorMapTemplateError(
            "pywin32 is required for Excel COM automation. "
            "Install it in the PUMA_Server Python environment with: "
            "python -m pip install pywin32"
        ) from exc

    return pythoncom, pywintypes, win32com.client


def _coerce_used_range_values(
    values: Any,
    row_count: int,
    column_count: int,
) -> tuple[tuple[Any, ...], ...]:
    """Convert Excel UsedRange.Value2 to a predictable 2D tuple."""
    if row_count <= 0 or column_count <= 0:
        return tuple()

    if row_count == 1 and column_count == 1:
        return ((values,),)

    if isinstance(values, tuple):
        # Normal multi-cell COM result: tuple[tuple[Any, ...], ...]
        if values and isinstance(values[0], tuple):
            return tuple(tuple(row) for row in values)

        if row_count == 1:
            return (tuple(values),)

        if column_count == 1:
            return tuple((value,) for value in values)

    # Defensive fallback. This should rarely be needed.
    return ((values,),)


def _iter_non_empty_cells(
    worksheet: Any,
) -> Iterable[tuple[int, int, str]]:
    """
    Yield absolute row, column and normalized value from Excel UsedRange.

    Reading Value2 once avoids thousands of slow cell-by-cell COM calls.
    """
    used_range = worksheet.UsedRange

    try:
        first_row = int(used_range.Row)
        first_column = int(used_range.Column)
        row_count = int(used_range.Rows.Count)
        column_count = int(used_range.Columns.Count)
        values = _coerce_used_range_values(
            used_range.Value2,
            row_count,
            column_count,
        )

        for row_offset, row_values in enumerate(values):
            for column_offset, raw_value in enumerate(row_values):
                normalized = _normalize_text(raw_value)
                if normalized:
                    yield (
                        first_row + row_offset,
                        first_column + column_offset,
                        normalized,
                    )
    finally:
        used_range = None


def _find_title_rows(
    worksheet: Any,
    sensor_sections: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[int, str]]:
    """
    Locate every configured Sensor title.

    Each Sensor title must resolve to exactly one worksheet row. Multiple
    matching cells on the same row are accepted; matches on different rows are
    rejected because the deletion range would be ambiguous.
    """
    title_lookup: dict[str, list[tuple[str, str]]] = {}

    for raw_code, rule in sensor_sections.items():
        code = str(raw_code).upper().strip()

        for title in rule.get("titles", []):
            normalized = _normalize_text(title)
            if normalized:
                title_lookup.setdefault(normalized, []).append((code, title))

    matches: dict[str, list[tuple[int, int, str]]] = {
        str(code).upper().strip(): []
        for code in sensor_sections
    }

    for row, column, cell_text in _iter_non_empty_cells(worksheet):
        for code, configured_title in title_lookup.get(cell_text, []):
            matches[code].append((row, column, configured_title))

    result: dict[str, tuple[int, str]] = {}
    errors: list[str] = []

    for raw_code, locations in matches.items():
        code = str(raw_code).upper().strip()

        if not locations:
            expected = sensor_sections[raw_code].get("titles", [])
            errors.append(
                f'{code}: title not found; expected one of {expected}'
            )
            continue

        unique_rows = sorted({row for row, _, _ in locations})
        if len(unique_rows) > 1:
            errors.append(
                f"{code}: title found on multiple rows {unique_rows}"
            )
            continue

        result[code] = (locations[0][0], locations[0][2])

    if errors:
        raise SensorMapSectionError(
            "Unable to locate Sensor sections safely: "
            + "; ".join(errors)
        )

    return result


def _find_end_marker_row(
    worksheet: Any,
    configured_markers: Sequence[str],
    after_row: int,
) -> int | None:
    """Find the first configured end marker below the final Sensor title."""
    markers = {
        _normalize_text(marker)
        for marker in configured_markers
        if isinstance(marker, str) and marker.strip()
    }

    if not markers:
        return None

    rows = [
        row
        for row, _, cell_text in _iter_non_empty_cells(worksheet)
        if row > after_row and cell_text in markers
    ]

    return min(rows) if rows else None


def find_sensor_sections(
    worksheet: Any,
    config: Mapping[str, Any],
) -> dict[str, SectionLocation]:
    """
    Calculate Sensor section row ranges dynamically.

    A section begins on its configured title row and ends immediately before
    the next Sensor title. The final section ends before the first configured
    non-Sensor end marker.
    """
    sensor_sections = config["sensor_sections"]
    title_rows = _find_title_rows(worksheet, sensor_sections)

    ordered = sorted(
        (row, code, title)
        for code, (row, title) in title_rows.items()
    )

    if not ordered:
        raise SensorMapSectionError(
            "No Sensor section titles were found."
        )

    if len({row for row, _, _ in ordered}) != len(ordered):
        raise SensorMapSectionError(
            "Two configured Sensor sections resolve to the same row."
        )

    final_sensor_start = ordered[-1][0]
    end_marker_row = _find_end_marker_row(
        worksheet,
        config.get("section_end_markers", []),
        after_row=final_sensor_start,
    )

    if end_marker_row is None:
        raise SensorMapSectionError(
            "No configured section end marker was found after the final "
            "Sensor section. Check section_end_markers in "
            "sensormap_sections.json."
        )

    result: dict[str, SectionLocation] = {}

    for index, (start_row, code, title) in enumerate(ordered):
        if index + 1 < len(ordered):
            end_row = ordered[index + 1][0] - 1
        else:
            end_row = end_marker_row - 1

        if end_row < start_row:
            raise SensorMapSectionError(
                f"Invalid calculated range for {code}: "
                f"{start_row}-{end_row}"
            )

        result[code] = SectionLocation(
            sensor_code=code,
            start_row=start_row,
            end_row=end_row,
            title=title,
        )

    return result


def delete_unused_sensor_sections(
    worksheet: Any,
    sections: Mapping[str, SectionLocation],
    sensors_to_keep: set[str],
) -> list[str]:
    """
    Delete unused Sensor section rows using native Excel row deletion.

    Deletion is performed from bottom to top so the original row coordinates
    remain valid for sections above the current deletion.
    """
    unsupported = sorted(sensors_to_keep - set(sections))
    if unsupported:
        raise SensorMapSectionError(
            "Scope contains configured Sensor codes that were not found "
            f"in the worksheet: {unsupported}"
        )

    sections_to_remove = [
        section
        for code, section in sections.items()
        if code not in sensors_to_keep
    ]

    for section in sorted(
        sections_to_remove,
        key=lambda item: item.start_row,
        reverse=True,
    ):
        row_range = worksheet.Rows(
            f"{section.start_row}:{section.end_row}"
        )
        try:
            row_range.EntireRow.Delete(Shift=XL_SHIFT_UP)
        finally:
            row_range = None

    return sorted(
        section.sensor_code
        for section in sections_to_remove
    )



def find_calibration_columns(
    worksheet: Any,
    calibration_columns: Mapping[str, Mapping[str, Any]],
) -> dict[str, int]:
    """
    Locate each configured Calibration Scope column by its Excel title.

    The title may appear on any row, but each configured rule must resolve to
    exactly one worksheet column. The actual column letter/number is not stored
    in JSON, so inserting columns in the template does not break the rule.
    """
    title_lookup: dict[str, list[str]] = {}

    for raw_code, rule in calibration_columns.items():
        code = str(raw_code).upper().strip()

        for title in rule.get("column_titles", []):
            normalized = _normalize_text(title)
            if normalized:
                title_lookup.setdefault(normalized, []).append(code)

    matches: dict[str, set[int]] = {
        str(code).upper().strip(): set()
        for code in calibration_columns
    }

    for _, column, cell_text in _iter_non_empty_cells(worksheet):
        for code in title_lookup.get(cell_text, []):
            matches[code].add(column)

    result: dict[str, int] = {}
    errors: list[str] = []

    for raw_code, columns in matches.items():
        code = str(raw_code).upper().strip()

        if not columns:
            expected = calibration_columns[raw_code].get(
                "column_titles",
                [],
            )
            errors.append(
                f"{code}: column title not found; expected one of {expected}"
            )
            continue

        if len(columns) > 1:
            errors.append(
                f"{code}: column title found in multiple columns "
                f"{sorted(columns)}"
            )
            continue

        result[code] = next(iter(columns))

    if errors:
        raise SensorMapSectionError(
            "Unable to locate Calibration Scope columns safely: "
            + "; ".join(errors)
        )

    return result


def delete_unused_calibration_columns(
    worksheet: Any,
    located_columns: Mapping[str, int],
    calibration_columns_to_keep: set[str],
) -> list[str]:
    """
    Delete unselected Calibration Scope columns using native Excel COM.

    Deletion is performed from right to left so the original column indexes
    remain valid for columns to the left.
    """
    unsupported = sorted(
        calibration_columns_to_keep - set(located_columns)
    )
    if unsupported:
        raise SensorMapSectionError(
            "Calibration Scope contains configured column rules that were not "
            f"found in the worksheet: {unsupported}"
        )

    columns_to_remove = [
        (code, column_index)
        for code, column_index in located_columns.items()
        if code not in calibration_columns_to_keep
    ]

    for _, column_index in sorted(
        columns_to_remove,
        key=lambda item: item[1],
        reverse=True,
    ):
        column_range = worksheet.Columns(column_index)
        try:
            column_range.EntireColumn.Delete()
        finally:
            column_range = None

    return sorted(code for code, _ in columns_to_remove)


def _verify_calibration_column_result(
    worksheet: Any,
    config: Mapping[str, Any],
    calibration_columns_to_keep: set[str],
    removed_calibration_columns: Sequence[str],
) -> None:
    """
    Verify that kept calibration titles remain and removed titles disappear.
    """
    current_values = {
        cell_text
        for _, _, cell_text in _iter_non_empty_cells(worksheet)
    }

    failures: list[str] = []
    calibration_columns = config.get("calibration_columns", {})

    for raw_code, rule in calibration_columns.items():
        code = str(raw_code).upper().strip()
        normalized_titles = {
            _normalize_text(title)
            for title in rule.get("column_titles", [])
            if _normalize_text(title)
        }
        title_exists = bool(current_values & normalized_titles)

        if code in calibration_columns_to_keep and not title_exists:
            failures.append(
                f"{code}: expected column to remain, but its title is missing"
            )

        if code in removed_calibration_columns and title_exists:
            failures.append(
                f"{code}: expected column to be removed, "
                "but its title still exists"
            )

    if failures:
        raise SensorMapSectionError(
            "Calibration column verification failed: "
            + "; ".join(failures)
        )


def _select_worksheet(
    workbook: Any,
    worksheet_name: str | None,
) -> Any:
    """Select the configured worksheet, or the active worksheet when blank."""
    requested = str(worksheet_name or "").strip()

    available = [
        str(workbook.Worksheets.Item(index).Name)
        for index in range(1, int(workbook.Worksheets.Count) + 1)
    ]

    if requested:
        if requested not in available:
            raise SensorMapTemplateError(
                f'Worksheet "{requested}" does not exist. '
                f"Available worksheets: {available}"
            )
        return workbook.Worksheets.Item(requested)

    active_sheet = workbook.ActiveSheet
    try:
        # Chart sheets do not expose UsedRange.
        _ = active_sheet.UsedRange
        return active_sheet
    except Exception:
        active_sheet = None

    if not available:
        raise SensorMapTemplateError(
            "The Sensor Map workbook contains no worksheets."
        )

    return workbook.Worksheets.Item(1)


def _verify_section_result(
    worksheet: Any,
    config: Mapping[str, Any],
    sensors_to_keep: set[str],
    removed_sections: Sequence[str],
) -> None:
    """Verify kept titles still exist and removed titles no longer exist."""
    current_values = {
        cell_text
        for _, _, cell_text in _iter_non_empty_cells(worksheet)
    }

    failures: list[str] = []
    sensor_sections = config["sensor_sections"]

    for raw_code, rule in sensor_sections.items():
        code = str(raw_code).upper().strip()
        normalized_titles = {
            _normalize_text(title)
            for title in rule.get("titles", [])
            if _normalize_text(title)
        }
        title_exists = bool(current_values & normalized_titles)

        if code in sensors_to_keep and not title_exists:
            failures.append(
                f"{code}: expected to remain, but its title is missing"
            )

        if code in removed_sections and title_exists:
            failures.append(
                f"{code}: expected to be removed, but its title still exists"
            )

    if failures:
        raise SensorMapSectionError(
            "Sensor Map verification failed: " + "; ".join(failures)
        )


def _safe_close_workbook(workbook: Any) -> None:
    """Close a COM workbook without raising during cleanup."""
    if workbook is None:
        return

    try:
        workbook.Close(SaveChanges=False)
    except Exception:
        LOGGER.exception(
            "Failed to close the Sensor Map workbook cleanly."
        )


def _safe_quit_excel(excel: Any) -> None:
    """Quit a dedicated Excel COM instance without masking the main error."""
    if excel is None:
        return

    try:
        excel.DisplayAlerts = False
    except Exception:
        pass

    try:
        excel.Quit()
    except Exception:
        LOGGER.exception(
            "Failed to quit the Excel COM instance cleanly."
        )


def _edit_workbook_with_excel_com(
    temporary_path: Path,
    config: Mapping[str, Any],
    sensors_to_keep: set[str],
    calibration_columns_to_keep: set[str],
) -> tuple[str, list[str], list[str]]:
    """
    Open the copied workbook in an isolated Excel instance, delete sections,
    verify the result and save it in the original format.
    """
    pythoncom, pywintypes, win32_client = _import_excel_com()

    excel = None
    workbook = None
    worksheet = None
    com_initialized = False

    try:
        pythoncom.CoInitialize()
        com_initialized = True

        # DispatchEx starts a separate Excel instance instead of attaching to
        # a user's already-open interactive workbook.
        excel = win32_client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.ScreenUpdating = False
        excel.EnableEvents = False
        excel.AskToUpdateLinks = False
        excel.AutomationSecurity = MSO_AUTOMATION_SECURITY_FORCE_DISABLE

        workbook = excel.Workbooks.Open(
            Filename=str(temporary_path.resolve()),
            UpdateLinks=0,
            ReadOnly=False,
            IgnoreReadOnlyRecommended=True,
            AddToMru=False,
            Local=True,
        )

        if bool(workbook.ReadOnly):
            raise SensorMapTemplateError(
                "Excel opened the temporary Sensor Map workbook as read-only: "
                f"{temporary_path}"
            )

        worksheet = _select_worksheet(
            workbook,
            config.get("worksheet_name"),
        )
        worksheet_name = str(worksheet.Name)

        if bool(worksheet.ProtectContents):
            raise SensorMapTemplateError(
                f'Worksheet "{worksheet_name}" is protected. '
                "Excel cannot delete Sensor section rows without the "
                "worksheet password."
            )

        detected_sections = find_sensor_sections(
            worksheet,
            config,
        )
        removed_sections = delete_unused_sensor_sections(
            worksheet,
            detected_sections,
            sensors_to_keep,
        )

        _verify_section_result(
            worksheet,
            config,
            sensors_to_keep,
            removed_sections,
        )

        # After row filtering, locate the Calibration Scope test columns in
        # the current worksheet and delete unselected columns from right to
        # left using native Excel COM.
        calibration_rules = config.get("calibration_columns", {})
        located_calibration_columns = find_calibration_columns(
            worksheet,
            calibration_rules,
        )
        removed_calibration_columns = (
            delete_unused_calibration_columns(
                worksheet,
                located_calibration_columns,
                calibration_columns_to_keep,
            )
        )

        _verify_calibration_column_result(
            worksheet,
            config,
            calibration_columns_to_keep,
            removed_calibration_columns,
        )

        # Save() preserves the copied workbook's original file type, including
        # legacy .xls. No conversion through SaveAs is performed.
        workbook.Save()
        workbook.Close(SaveChanges=False)
        workbook = None

        return (
            worksheet_name,
            removed_sections,
            removed_calibration_columns,
        )

    except SensorMapError:
        raise
    except pywintypes.com_error as exc:
        hresult = getattr(exc, "hresult", None)
        message = getattr(exc, "strerror", None) or str(exc)
        raise SensorMapTemplateError(
            "Microsoft Excel COM operation failed"
            f"{f' (HRESULT {hresult})' if hresult is not None else ''}: "
            f"{message}. Confirm that desktop Microsoft Excel is installed, "
            "the workbook is not locked, and the PUMA_Server account can "
            "access the template and output directory."
        ) from exc
    except Exception as exc:
        LOGGER.exception(
            "Unexpected Excel COM Sensor Map editing failure."
        )
        raise SensorMapError(
            f"Unexpected Excel COM Sensor Map editing failure: {exc}"
        ) from exc
    finally:
        worksheet = None
        _safe_close_workbook(workbook)
        workbook = None
        _safe_quit_excel(excel)
        excel = None

        gc.collect()

        if com_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                LOGGER.exception(
                    "Failed to uninitialize COM cleanly."
                )


def generate_sensor_map(
    peripheral_sensor_scope: str | None,
    output_directory: str | Path,
    *,
    calibration_scope: str | None = None,
    project_name: str | None = None,
    output_filename: str | None = None,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    overwrite: bool = True,
) -> dict[str, Any]:
    """
    Generate a project-specific Sensor Map workbook using Excel COM.

    The function signature and return structure intentionally remain compatible
    with the existing /report/generateSensorMap endpoint.
    """
    config = load_sensormap_config(config_path)
    template_path = _resolve_template_path(config["template_path"])

    output_dir = Path(output_directory).expanduser()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SensorMapTemplateError(
            f"Unable to create Sensor Map output directory: {output_dir}"
        ) from exc

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

    sensor_sections = config["sensor_sections"]
    sensors_to_keep = parse_peripheral_sensor_scope(
        peripheral_sensor_scope,
        sensor_sections,
    )

    calibration_columns = config.get("calibration_columns", {})
    calibration_columns_to_keep = parse_calibration_scope(
        calibration_scope,
        calibration_columns,
    )

    # Safety guard: never interpret an unrecognized non-empty scope as
    # "delete every Sensor section".
    if not sensors_to_keep:
        supported = sorted(
            str(code).upper().strip()
            for code in sensor_sections
        )
        raise SensorMapSectionError(
            "No supported Peripheral Sensor was recognized from: "
            f"{peripheral_sensor_scope!r}. Supported codes: {supported}. "
            "Generation was stopped to prevent deleting every Sensor section."
        )

    # An empty Calibration Scope is also treated as unsafe when column rules
    # exist, because otherwise all configured test columns would be deleted.
    if calibration_columns and not calibration_columns_to_keep:
        supported_calibration = sorted(
            str(code).upper().strip()
            for code in calibration_columns
        )
        raise SensorMapSectionError(
            "No supported Calibration Scope was recognized from: "
            f"{calibration_scope!r}. Supported column rules: "
            f"{supported_calibration}. Generation was stopped to prevent "
            "deleting every configured Calibration Scope column."
        )

    delete_rule = (
        config.get("matching", {})
        .get("delete_rule", "delete_if_not_present")
    )
    if delete_rule != "delete_if_not_present":
        raise SensorMapConfigError(
            'Only "delete_if_not_present" is currently supported as '
            '"matching.delete_rule".'
        )

    temporary_path = output_path.with_name(
        f"__puma_sensormap_{uuid.uuid4().hex}{template_path.suffix.lower()}"
    )

    worksheet_name = ""
    removed_sections: list[str] = []
    removed_calibration_columns: list[str] = []

    try:
        shutil.copy2(template_path, temporary_path)

        with _EXCEL_COM_LOCK:
            (
                worksheet_name,
                removed_sections,
                removed_calibration_columns,
            ) = _edit_workbook_with_excel_com(
                temporary_path,
                config,
                sensors_to_keep,
                calibration_columns_to_keep,
            )

        # Replace only after Excel saved and closed the temporary file.
        # os.replace keeps the previous output intact if replacement fails.
        temporary_path.replace(output_path)

    except PermissionError as exc:
        raise SensorMapTemplateError(
            "Permission denied while reading or writing the Sensor Map file. "
            "Confirm that the template/output file is not open in Excel and "
            "that the PUMA_Server account can write to the Public Link."
        ) from exc
    except SensorMapError:
        raise
    except OSError as exc:
        LOGGER.exception(
            "Sensor Map file-system operation failed."
        )
        raise SensorMapTemplateError(
            f"Sensor Map file-system operation failed: {exc}"
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

    configured_codes = {
        str(code).upper().strip()
        for code in sensor_sections
    }

    return {
        "success": True,
        "message": "Sensor Map generated successfully by Microsoft Excel.",
        "template_path": str(template_path),
        "output_path": str(output_path),
        "worksheet": worksheet_name or (
            config.get("worksheet_name") or "active"
        ),
        "scope": peripheral_sensor_scope or "",
        "calibration_scope": calibration_scope or "",
        "kept_sections": sorted(sensors_to_keep),
        "removed_sections": removed_sections,
        "kept_calibration_columns": sorted(
            calibration_columns_to_keep
        ),
        "removed_calibration_columns": removed_calibration_columns,
        "configured_sections": sorted(configured_codes),
        "engine": "Microsoft Excel COM",
        "file_format": template_path.suffix.lower(),
    }


if __name__ == "__main__":
    """
    Minimal local smoke test.

    Before running:
    1. Confirm desktop Microsoft Excel is installed.
    2. Confirm sensormap_sections.json points to the intended template, or put
       a same-stem .xls beside the configured .xlsx.
    3. Edit the values below.

    Run:
        python PUMA_Server/services/sensormap_service.py
    """
    TEST_SCOPE = "UFS+PAS+PPS+PTS"
    TEST_CALIBRATION_SCOPE = "FSR+Rose1+Offzone"
    TEST_OUTPUT_DIRECTORY = Path.cwd() / "sensormap_test_output"
    TEST_PROJECT_NAME = "Demo_Project"

    try:
        result = generate_sensor_map(
            peripheral_sensor_scope=TEST_SCOPE,
            calibration_scope=TEST_CALIBRATION_SCOPE,
            output_directory=TEST_OUTPUT_DIRECTORY,
            project_name=TEST_PROJECT_NAME,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except SensorMapError as error:
        print(f"Sensor Map test failed: {error}")