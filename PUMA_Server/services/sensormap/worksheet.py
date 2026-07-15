from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from .errors import SensorMapSectionError
from .excel_com import XL_SHIFT_UP, coerce_used_range_values
from .models import SectionLocation, SensorRow, SensorSelection


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\u3000", " ")
    text = text.replace("：", ":")
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def iter_non_empty_cells(
    worksheet: Any,
) -> Iterable[tuple[int, int, str]]:
    used_range = worksheet.UsedRange
    try:
        first_row = int(used_range.Row)
        first_column = int(used_range.Column)
        row_count = int(used_range.Rows.Count)
        column_count = int(used_range.Columns.Count)
        values = coerce_used_range_values(
            used_range.Value2,
            row_count,
            column_count,
        )

        for row_offset, row_values in enumerate(values):
            for column_offset, raw_value in enumerate(row_values):
                normalized = normalize_text(raw_value)
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
    title_lookup: dict[str, list[tuple[str, str]]] = {}
    for raw_code, rule in sensor_sections.items():
        code = str(raw_code).upper().strip()
        for title in rule.get("titles", []):
            normalized = normalize_text(title)
            if normalized:
                title_lookup.setdefault(normalized, []).append(
                    (code, title)
                )

    matches: dict[str, list[tuple[int, str]]] = {
        str(code).upper().strip(): []
        for code in sensor_sections
    }

    for row, _, cell_text in iter_non_empty_cells(worksheet):
        for code, configured_title in title_lookup.get(cell_text, []):
            matches[code].append((row, configured_title))

    result: dict[str, tuple[int, str]] = {}
    errors: list[str] = []

    for raw_code, locations in matches.items():
        code = str(raw_code).upper().strip()
        if not locations:
            errors.append(f"{code}: title not found")
            continue

        rows = sorted({row for row, _ in locations})
        if len(rows) != 1:
            errors.append(f"{code}: title found on rows {rows}")
            continue

        result[code] = (rows[0], locations[0][1])

    if errors:
        raise SensorMapSectionError(
            "Unable to locate Sensor sections safely: "
            + "; ".join(errors)
        )

    return result


def find_sensor_sections(
    worksheet: Any,
    config: Mapping[str, Any],
) -> dict[str, SectionLocation]:
    title_rows = _find_title_rows(
        worksheet,
        config["sensor_sections"],
    )

    ordered = sorted(
        (row, code, title)
        for code, (row, title) in title_rows.items()
    )

    markers = {
        normalize_text(marker)
        for marker in config.get("section_end_markers", [])
        if str(marker).strip()
    }

    final_start = ordered[-1][0]
    marker_rows = [
        row
        for row, _, cell_text in iter_non_empty_cells(worksheet)
        if row > final_start and cell_text in markers
    ]

    if not marker_rows:
        raise SensorMapSectionError(
            "No configured Sensor section end marker was found."
        )

    end_marker_row = min(marker_rows)
    result: dict[str, SectionLocation] = {}

    for index, (start_row, code, title) in enumerate(ordered):
        if index + 1 < len(ordered):
            end_row = ordered[index + 1][0] - 1
        else:
            end_row = end_marker_row - 1

        result[code] = SectionLocation(
            sensor_code=code,
            start_row=start_row,
            end_row=end_row,
            title=title,
        )

    return result


def merge_row_ranges(
    ranges: Sequence[tuple[int, int]],
) -> list[tuple[int, int]]:
    if not ranges:
        return []

    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1] + 1:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)

    return [(start, end) for start, end in merged]


def delete_row_ranges(
    worksheet: Any,
    ranges: Sequence[tuple[int, int]],
) -> None:
    for start_row, end_row in sorted(
        ranges,
        key=lambda item: item[0],
        reverse=True,
    ):
        row_range = worksheet.Rows(
            f"{start_row}:{end_row}"
        )
        try:
            row_range.EntireRow.Delete(Shift=XL_SHIFT_UP)
        finally:
            row_range = None


def row_texts_in_range(
    worksheet: Any,
    start_row: int,
    end_row: int,
) -> dict[int, str]:
    row_parts: dict[int, list[str]] = {}
    for row, _, cell_text in iter_non_empty_cells(worksheet):
        if start_row <= row <= end_row:
            row_parts.setdefault(row, []).append(cell_text)

    return {
        row: " | ".join(parts)
        for row, parts in row_parts.items()
    }


def _first_matching_key(
    text: str,
    mapping: Mapping[str, Sequence[str]],
) -> str | None:
    for key, patterns in mapping.items():
        if any(
            normalize_text(pattern) in text
            for pattern in patterns
            if normalize_text(pattern)
        ):
            return str(key).upper()
    return None


def classify_sensor_rows(
    worksheet: Any,
    section: SectionLocation,
    sensor_code: str,
    sensor_rule: Mapping[str, Any],
) -> list[SensorRow]:
    row_rules = sensor_rule.get("row_rules", {})
    position_rules = row_rules.get("positions", {})
    axis_rules = row_rules.get("axes", {})

    rows: list[SensorRow] = []
    for row_number, row_text in row_texts_in_range(
        worksheet,
        section.start_row,
        section.end_row,
    ).items():
        if row_number == section.start_row:
            continue

        normalized = normalize_text(row_text)
        position = _first_matching_key(
            normalized,
            position_rules,
        )
        axis = _first_matching_key(
            normalized,
            axis_rules,
        )

        if position is not None and axis is not None:
            rows.append(
                SensorRow(
                    row_number=row_number,
                    sensor=sensor_code,
                    position=position,
                    axis=axis,
                    text=row_text,
                )
            )

    return rows


def build_sensor_detail_delete_ranges(
    worksheet: Any,
    sections: Mapping[str, SectionLocation],
    selections: Mapping[str, SensorSelection],
    sensor_rules: Mapping[str, Mapping[str, Any]],
) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    ranges: list[tuple[int, int]] = []
    details: dict[str, Any] = {}

    for code, selection in selections.items():
        section = sections.get(code)
        if section is None:
            raise SensorMapSectionError(
                f"{code}: worksheet section not found."
            )

        rows = classify_sensor_rows(
            worksheet,
            section,
            code,
            sensor_rules[code],
        )

        deleted: list[dict[str, Any]] = []
        for sensor_row in rows:
            if (
                sensor_row.position not in selection.positions
                or sensor_row.axis not in selection.axes
            ):
                ranges.append(
                    (sensor_row.row_number, sensor_row.row_number)
                )
                deleted.append({
                    "row": sensor_row.row_number,
                    "position": sensor_row.position,
                    "axis": sensor_row.axis,
                    "text": sensor_row.text,
                })

        details[code] = {
            "selection": selection.as_dict(),
            "deleted_rows": deleted,
        }

    return merge_row_ranges(ranges), details


def parse_calibration_scope(
    scope: str | None,
    calibration_columns: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    normalized_scope = normalize_text(scope)
    detected: set[str] = set()

    for raw_code, rule in calibration_columns.items():
        code = str(raw_code).upper().strip()
        for alias in rule.get("scope_aliases", []):
            normalized_alias = normalize_text(alias)
            if normalized_alias and re.search(
                rf"(?<![a-z]){re.escape(normalized_alias)}(?![a-z])",
                normalized_scope,
            ):
                detected.add(code)
                break

    return detected


def find_calibration_columns(
    worksheet: Any,
    calibration_columns: Mapping[str, Mapping[str, Any]],
) -> dict[str, int]:
    title_lookup: dict[str, list[str]] = {}
    for raw_code, rule in calibration_columns.items():
        code = str(raw_code).upper().strip()
        for title in rule.get("column_titles", []):
            normalized = normalize_text(title)
            if normalized:
                title_lookup.setdefault(normalized, []).append(code)

    matches: dict[str, set[int]] = {
        str(code).upper().strip(): set()
        for code in calibration_columns
    }

    for _, column, cell_text in iter_non_empty_cells(worksheet):
        for code in title_lookup.get(cell_text, []):
            matches[code].add(column)

    result: dict[str, int] = {}
    errors: list[str] = []

    for code, columns in matches.items():
        if not columns:
            errors.append(f"{code}: column title not found")
        elif len(columns) > 1:
            errors.append(
                f"{code}: column found in multiple columns "
                f"{sorted(columns)}"
            )
        else:
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
    calibration_to_keep: set[str],
) -> list[str]:
    columns_to_remove = [
        (code, column_index)
        for code, column_index in located_columns.items()
        if code not in calibration_to_keep
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


def _all_main_section_titles(
    config: Mapping[str, Any],
) -> set[str]:
    titles: set[str] = set()

    for rule in config.get("fixed_sections", {}).values():
        title = rule.get("title")
        if title:
            titles.add(normalize_text(title))

    for rule in config.get("sensor_sections", {}).values():
        for title in rule.get("titles", []):
            titles.add(normalize_text(title))

    for rule in config.get("non_sensor_sections", {}).values():
        title = rule.get("title")
        if title:
            titles.add(normalize_text(title))

    return {title for title in titles if title}


def find_section_range_by_title(
    worksheet: Any,
    config: Mapping[str, Any],
    section_title: str,
) -> tuple[int, int]:
    normalized_title = normalize_text(section_title)
    cells = list(iter_non_empty_cells(worksheet))

    start_rows = sorted({
        row
        for row, _, text in cells
        if text == normalized_title
    })

    if len(start_rows) != 1:
        raise SensorMapSectionError(
            f'{section_title}: expected one title row, found {start_rows}'
        )

    start_row = start_rows[0]
    main_titles = _all_main_section_titles(config)
    next_rows = sorted({
        row
        for row, _, text in cells
        if row > start_row and text in main_titles
    })

    if not next_rows:
        raise SensorMapSectionError(
            f'Unable to determine the end of section "{section_title}".'
        )

    return start_row, next_rows[0] - 1


def build_calibration_row_delete_ranges(
    worksheet: Any,
    config: Mapping[str, Any],
    calibration_to_keep: set[str],
) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    """
    Supports both:
    1) the preferred shared-condition schema:
       calibration_row_rules.NO_ROLLOVER_OR_PITCHOVER
    2) the older angular_rate_section / central_acceleration_keyword_rows schema.
    """
    rules = config.get("calibration_row_rules", {})
    ranges: list[tuple[int, int]] = []
    details = {
        "deleted_sections": [],
        "deleted_keyword_rows": [],
    }

    shared_rule = rules.get("NO_ROLLOVER_OR_PITCHOVER")
    if isinstance(shared_rule, dict):
        keep_if_any = {
            str(code).upper()
            for code in shared_rule.get(
                "keep_if_any_calibration",
                [],
            )
        }
        if not (calibration_to_keep & keep_if_any):
            for item in shared_rule.get("delete_sections", []):
                title = str(item.get("title") or "").strip()
                if not title:
                    continue
                start, end = find_section_range_by_title(
                    worksheet,
                    config,
                    title,
                )
                ranges.append((start, end))
                details["deleted_sections"].append({
                    "title": title,
                    "start_row": start,
                    "end_row": end,
                })

            for item in shared_rule.get("delete_keyword_rows", []):
                title = str(
                    item.get("section_title") or ""
                ).strip()
                keywords = [
                    normalize_text(keyword)
                    for keyword in item.get("keywords", [])
                    if str(keyword).strip()
                ]
                if not title or not keywords:
                    continue

                start, end = find_section_range_by_title(
                    worksheet,
                    config,
                    title,
                )

                matched_rows = sorted({
                    row
                    for row, _, text in iter_non_empty_cells(worksheet)
                    if start <= row <= end
                    and any(keyword in text for keyword in keywords)
                })

                for row in matched_rows:
                    ranges.append((row, row))
                    details["deleted_keyword_rows"].append({
                        "row": row,
                        "section_title": title,
                        "keywords": keywords,
                    })

        return merge_row_ranges(ranges), details

    # Backward-compatible schema.
    angular_rule = rules.get("angular_rate_section", {})
    keep_if_any = {
        str(code).upper()
        for code in angular_rule.get(
            "keep_if_any_calibration",
            [],
        )
    }
    title = str(
        angular_rule.get("section_title") or ""
    ).strip()

    condition_triggered = bool(
        title and not (calibration_to_keep & keep_if_any)
    )

    if condition_triggered:
        start, end = find_section_range_by_title(
            worksheet,
            config,
            title,
        )
        ranges.append((start, end))
        details["deleted_sections"].append({
            "title": title,
            "start_row": start,
            "end_row": end,
        })

        keyword_rule = rules.get(
            "central_acceleration_keyword_rows",
            {},
        )
        section_title = str(
            keyword_rule.get("section_title") or ""
        ).strip()
        keywords = [
            normalize_text(keyword)
            for keyword in keyword_rule.get(
                "delete_if_contains",
                [],
            )
            if str(keyword).strip()
        ]

        if section_title and keywords:
            start, end = find_section_range_by_title(
                worksheet,
                config,
                section_title,
            )
            matched_rows = sorted({
                row
                for row, _, text in iter_non_empty_cells(worksheet)
                if start <= row <= end
                and any(keyword in text for keyword in keywords)
            })

            for row in matched_rows:
                ranges.append((row, row))
                details["deleted_keyword_rows"].append({
                    "row": row,
                    "section_title": section_title,
                    "keywords": keywords,
                })

    return merge_row_ranges(ranges), details
