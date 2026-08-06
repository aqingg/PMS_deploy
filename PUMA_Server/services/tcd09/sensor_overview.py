from __future__ import annotations

# 本文件负责生成 Sensor Overview 的四列数据，并填写 Word 表格模板行。
# 不处理汽车底图 Shape 的位置或方向逻辑。

import io
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from fastapi import HTTPException

from services.datamerge import docx
from services.tcd09.sensor_models import POSITION_ORDER, SensorEntry
from services.tcd09.sensor_parser import (
    default_count,
    merge_sensor_entries,
    normalize_pps_position,
    pas_positions_from_count,
    pps_positions_from_count,
    three_position_set_from_count,
)


SENSOR_TYPE_ROWS_PLACEHOLDER = "<TCD09_SENSOR_TYPE_ROWS>"
SENSOR_LOCATION_ROWS_PLACEHOLDER = "<TCD09_SENSOR_LOCATION_ROWS>"
SENSOR_DIRECTION_ROWS_PLACEHOLDER = "<TCD09_SENSOR_DIRECTION_ROWS>"
SENSOR_MEASUREMENT_ROWS_PLACEHOLDER = "<TCD09_SENSOR_MEASUREMENT_ROWS>"

THIS_DIR = Path(__file__).resolve().parent
SERVER_ROOT = THIS_DIR.parents[1]
DEFAULT_SENSORMAP_RULES_PATH = SERVER_ROOT / "config" / "sensormap_sensor_rules.json"
DEFAULT_SENSOR_OVERVIEW_RULES_PATH = (
    SERVER_ROOT / "config" / "tcd09_sensor_overview_rules.json"
)


@dataclass(frozen=True)
class SensorOverviewEntry:
    sensor_type: str
    sensor_location: str
    channel_rows: tuple[tuple[str, str], ...]


def _load_sensormap_rules(
    rules_path: str | Path = DEFAULT_SENSORMAP_RULES_PATH,
) -> dict[str, Any]:
    path = Path(rules_path)
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _format_three_positions(positions: set[str], location_name: str) -> str:
    phrases = {
        frozenset({"L"}): f"Left {location_name}",
        frozenset({"C"}): f"Center {location_name}",
        frozenset({"R"}): f"Right {location_name}",
        frozenset({"L", "R"}): f"Left and Right {location_name}",
        frozenset({"L", "C"}): f"Left and Center {location_name}",
        frozenset({"C", "R"}): f"Center and Right {location_name}",
        frozenset({"L", "C", "R"}): f"Left, Center and Right {location_name}",
    }
    normalized = set(positions)
    return phrases.get(frozenset(normalized), f"{', '.join(sorted(normalized))} {location_name}")


def _format_pas_positions(positions: set[str]) -> str:
    normalized = set(positions)
    if normalized == {"BL", "BR"}:
        return "Left and Right B-pillar"
    if normalized == {"CL", "CR"}:
        return "Left and Right C-pillar"
    if normalized == {"BL", "BR", "CL", "CR"}:
        return "Left and Right B-pillar; Left and Right C-pillar"
    names = {
        "BL": "Left B-pillar", "BR": "Right B-pillar",
        "CL": "Left C-pillar", "CR": "Right C-pillar",
    }
    return "; ".join(names[position] for position in POSITION_ORDER["PAS"] if position in normalized) or "N/A"


def _format_pps_positions(positions: set[str]) -> str:
    normalized = {normalize_pps_position(position) for position in positions if str(position or "").strip()}
    if normalized == {"FL", "FR"}:
        return "Left and Right Front door"
    if normalized == {"RL", "RR"}:
        return "Left and Right Rear door"
    if normalized == {"FL", "FR", "RL", "RR"}:
        return "Left and Right Front and Rear door"
    names = {
        "FL": "Left Front door", "FR": "Right Front door",
        "RL": "Left Rear door", "RR": "Right Rear door",
    }
    return "; ".join(names[position] for position in POSITION_ORDER["PPS"] if position in normalized) or "N/A"


def _sensor_location(entry: SensorEntry, rules: dict[str, Any]) -> str:
    if entry.is_inertial:
        return "ECU on tunnel"
    family = entry.family
    if family == "UFS":
        positions = entry.positions or three_position_set_from_count(default_count(entry, rules, fallback=2))
        return _format_three_positions(positions, "(longitudinal beam)")
    if family == "RCS":
        positions = entry.positions or three_position_set_from_count(default_count(entry, rules, fallback=2))
        return _format_three_positions(positions, "(rear trunk)")
    if family == "PAS":
        positions = entry.positions or pas_positions_from_count(default_count(entry, rules, fallback=2), rules)
        return _format_pas_positions(positions)
    if family == "PCS":
        positions = entry.positions or three_position_set_from_count(default_count(entry, rules, fallback=1))
        return _format_three_positions(positions, "(front bumper)")
    if family == "PPS":
        positions = {normalize_pps_position(position) for position in entry.positions}
        if not positions:
            positions = pps_positions_from_count(default_count(entry, rules, fallback=2))
        return _format_pps_positions(positions)
    if family == "PTS":
        return "(front bumper)"
    return "N/A"


def _load_sensor_overview_rules(
    rules_path: str | Path = DEFAULT_SENSOR_OVERVIEW_RULES_PATH,
) -> dict[str, Any]:
    path = Path(rules_path)
    if not path.is_file():
        raise HTTPException(status_code=500, detail=f"TCD09 Sensor Overview rules do not exist: {path}")
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Invalid TCD09 Sensor Overview rules: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=500,
            detail="TCD09 Sensor Overview rules must be a JSON object.",
        )
    if not isinstance(data.get("sensing_direction"), dict):
        raise HTTPException(
            status_code=500,
            detail='TCD09 Sensor Overview rules must define "sensing_direction".',
        )
    if not isinstance(data.get("measurement"), dict):
        raise HTTPException(
            status_code=500,
            detail='TCD09 Sensor Overview rules must define "measurement".',
        )
    if "channel_rows" in data and not isinstance(data.get("channel_rows"), dict):
        raise HTTPException(
            status_code=500,
            detail='"channel_rows" must be a JSON object when configured.',
        )
    return data


def _as_rule_lines(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    elif isinstance(value, (list, tuple)):
        values = [str(item) for item in value]
    else:
        values = []
    return [str(line).strip() for line in values if str(line).strip()]


def _lookup_rule_config(
    entry: SensorEntry,
    rules: dict[str, Any],
) -> Any:
    exact_models = rules.get("exact_models", {})
    sensor_families = rules.get("sensor_families", {})

    exact_lookup = (
        {
            str(key).strip().casefold(): value
            for key, value in exact_models.items()
            if str(key).strip()
        }
        if isinstance(exact_models, dict)
        else {}
    )
    family_lookup = (
        {
            str(key).strip().upper(): value
            for key, value in sensor_families.items()
            if str(key).strip()
        }
        if isinstance(sensor_families, dict)
        else {}
    )

    configured = exact_lookup.get(entry.display_name.casefold())
    if configured is None:
        configured = family_lookup.get(entry.family.upper())
    if configured is None:
        configured = rules.get("default")
    return configured


def _overview_rule_lines(
    entry: SensorEntry,
    overview_rules: dict[str, Any],
    rule_name: str,
) -> list[str]:
    rules = overview_rules.get(rule_name, {})
    if not isinstance(rules, dict):
        return ["N/A"]
    configured = _lookup_rule_config(entry, rules)
    return _as_rule_lines(configured) or ["N/A"]


def _overview_rule_value(
    entry: SensorEntry,
    overview_rules: dict[str, Any],
    rule_name: str,
) -> str:
    """Backward-compatible joined-string helper."""

    return "\n".join(
        _overview_rule_lines(entry, overview_rules, rule_name)
    )


def _parse_channel_rows(value: Any) -> list[tuple[str, str]]:
    if not isinstance(value, (list, tuple)):
        return []

    rows: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        direction = str(item.get("direction") or "").strip()
        measurement = str(item.get("measurement") or "").strip()
        if not direction and not measurement:
            continue
        rows.append((direction, measurement))
    return rows


def _legacy_channel_rows(
    entry: SensorEntry,
    overview_rules: dict[str, Any],
) -> list[tuple[str, str]]:
    directions = _overview_rule_lines(
        entry, overview_rules, "sensing_direction"
    )
    measurements = _overview_rule_lines(
        entry, overview_rules, "measurement"
    )

    if len(directions) == len(measurements):
        return list(zip(directions, measurements))

    if len(measurements) == 1:
        return [(direction, measurements[0]) for direction in directions]

    if len(directions) == 1:
        return [
            (directions[0] if index == 0 else "", measurement)
            for index, measurement in enumerate(measurements)
        ]

    raise HTTPException(
        status_code=500,
        detail=(
            "TCD09 Sensor Overview direction/measurement counts do not match "
            f"for {entry.display_name}: "
            f"{len(directions)} direction values and "
            f"{len(measurements)} measurement values. "
            'Add an explicit entry under "channel_rows".'
        ),
    )


def _overview_channel_rows(
    entry: SensorEntry,
    overview_rules: dict[str, Any],
) -> list[tuple[str, str]]:
    channel_rules = overview_rules.get("channel_rows", {})
    if isinstance(channel_rules, dict):
        configured = _lookup_rule_config(entry, channel_rules)
        parsed_rows = _parse_channel_rows(configured)
        if parsed_rows:
            return parsed_rows

    return _legacy_channel_rows(entry, overview_rules)


def _build_sensor_overview_entries(
    profile: dict[str, Any],
    *,
    sensormap_rules_path: str | Path = DEFAULT_SENSORMAP_RULES_PATH,
    overview_rules_path: str | Path = DEFAULT_SENSOR_OVERVIEW_RULES_PATH,
) -> list[SensorOverviewEntry]:
    sensor_map_rules = _load_sensormap_rules(sensormap_rules_path)
    overview_rules = _load_sensor_overview_rules(overview_rules_path)
    parsed_entries = [
        *merge_sensor_entries(
            profile.get("internal_sensor_configuration"),
            force_inertial=True,
        ),
        *merge_sensor_entries(
            profile.get("peripheral_sensor_configuration"),
            force_inertial=False,
        ),
    ]

    entries: list[SensorOverviewEntry] = []
    seen: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()

    for entry in parsed_entries:
        channel_rows = tuple(
            _overview_channel_rows(entry, overview_rules)
            or [("N/A", "N/A")]
        )
        overview_entry = SensorOverviewEntry(
            sensor_type=entry.display_name,
            sensor_location=_sensor_location(entry, sensor_map_rules),
            channel_rows=channel_rows,
        )
        key = (
            overview_entry.sensor_type.casefold(),
            overview_entry.sensor_location.casefold(),
            tuple(
                (direction.casefold(), measurement.casefold())
                for direction, measurement in overview_entry.channel_rows
            ),
        )
        if key not in seen:
            seen.add(key)
            entries.append(overview_entry)

    return entries


def build_sensor_overview_rows(
    profile: dict[str, Any],
    *,
    sensormap_rules_path: str | Path = DEFAULT_SENSORMAP_RULES_PATH,
    overview_rules_path: str | Path = DEFAULT_SENSOR_OVERVIEW_RULES_PATH,
) -> list[tuple[str, str, str, str]]:
    """Build backward-compatible four-value rows.

    The Word writer uses structured channel rows internally. This helper
    keeps the previous joined-string return format for existing callers.
    """

    rows: list[tuple[str, str, str, str]] = []
    for entry in _build_sensor_overview_entries(
        profile,
        sensormap_rules_path=sensormap_rules_path,
        overview_rules_path=overview_rules_path,
    ):
        rows.append(
            (
                entry.sensor_type,
                entry.sensor_location,
                "\n".join(
                    direction for direction, _ in entry.channel_rows
                ),
                "\n".join(
                    measurement for _, measurement in entry.channel_rows
                ),
            )
        )
    return rows


def parse_sensor_types(value: Any) -> list[str]:
    """Backward-compatible first-column parser."""
    return [entry.display_name for entry in merge_sensor_entries(value, force_inertial=False)]


def build_sensor_type_rows(profile: dict[str, Any]) -> list[str]:
    """Backward-compatible Sensor Type-only helper."""

    return [
        entry.sensor_type
        for entry in _build_sensor_overview_entries(profile)
    ]


def _iter_tables(container) -> Iterator[Any]:
    for table in container.tables:
        yield table
        for row in table.rows:
            for cell in row.cells:
                yield from _iter_tables(cell)


def _cell_xml(row_xml, cell_index: int):
    cells = [child for child in row_xml if str(getattr(child, "tag", "")).endswith("}tc")]
    return cells[cell_index] if 0 <= cell_index < len(cells) else None


def _replace_placeholder_in_cell_xml(row_xml, *, cell_index: int, placeholder: str, replacement: str) -> None:
    cell_xml = _cell_xml(row_xml, cell_index)
    if cell_xml is None:
        raise HTTPException(status_code=500, detail=f"TCD09 Sensor Overview template row does not contain column #{cell_index + 1}.")
    text_nodes = [node for node in cell_xml.iter() if str(getattr(node, "tag", "")).endswith("}t")]
    if not text_nodes:
        raise HTTPException(status_code=500, detail=f"TCD09 Sensor Overview template cell has no text node: {placeholder}")
    full_text = "".join(str(node.text or "") for node in text_nodes)
    if placeholder not in full_text:
        raise HTTPException(status_code=500, detail=f"TCD09 Sensor Overview placeholder is split or missing: {placeholder}")

    lines = full_text.replace(placeholder, replacement, 1).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    first_text_node = text_nodes[0]
    first_text_node.text = lines[0]
    for node in text_nodes[1:]:
        node.text = ""
    if len(lines) <= 1:
        return
    parent_run = first_text_node.getparent()
    if parent_run is None:
        raise HTTPException(status_code=500, detail=f"TCD09 Sensor Overview template text node has no run: {placeholder}")
    namespace = str(first_text_node.tag).split("}")[0].lstrip("{")
    insert_index = parent_run.index(first_text_node) + 1
    for line in lines[1:]:
        break_node = first_text_node.makeelement(f"{{{namespace}}}br")
        line_node = first_text_node.makeelement(f"{{{namespace}}}t")
        line_node.text = line
        parent_run.insert(insert_index, break_node)
        parent_run.insert(insert_index + 1, line_node)
        insert_index += 2


def _find_sensor_template_rows(document) -> list[tuple[Any, Any]]:
    matches: list[tuple[Any, Any]] = []
    placeholders = (
        SENSOR_TYPE_ROWS_PLACEHOLDER,
        SENSOR_LOCATION_ROWS_PLACEHOLDER,
        SENSOR_DIRECTION_ROWS_PLACEHOLDER,
        SENSOR_MEASUREMENT_ROWS_PLACEHOLDER,
    )
    for table in _iter_tables(document):
        for row in list(table.rows):
            if len(row.cells) >= 4 and all(placeholder in str(row.cells[index].text or "") for index, placeholder in enumerate(placeholders)):
                matches.append((table, row))
    return matches


def _word_namespace(element) -> str:
    tag = str(getattr(element, "tag", ""))
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    raise HTTPException(
        status_code=500,
        detail="Unable to determine Word XML namespace.",
    )


def _remove_fixed_row_height(row_xml) -> None:
    """Let every channel use a compact automatic Word row height."""

    row_properties = next(
        (
            child
            for child in row_xml
            if str(getattr(child, "tag", "")).endswith("}trPr")
        ),
        None,
    )
    if row_properties is None:
        return

    for child in list(row_properties):
        if str(getattr(child, "tag", "")).endswith("}trHeight"):
            row_properties.remove(child)


def _set_vertical_merge(
    row_xml,
    *,
    cell_index: int,
    restart: bool,
) -> None:
    cell_xml = _cell_xml(row_xml, cell_index)
    if cell_xml is None:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to vertically merge Sensor Overview "
                f"column #{cell_index + 1}."
            ),
        )

    namespace = _word_namespace(cell_xml)
    cell_properties = next(
        (
            child
            for child in cell_xml
            if str(getattr(child, "tag", "")).endswith("}tcPr")
        ),
        None,
    )
    if cell_properties is None:
        cell_properties = cell_xml.makeelement(
            f"{{{namespace}}}tcPr"
        )
        cell_xml.insert(0, cell_properties)

    for child in list(cell_properties):
        if str(getattr(child, "tag", "")).endswith("}vMerge"):
            cell_properties.remove(child)

    vertical_merge = cell_properties.makeelement(
        f"{{{namespace}}}vMerge"
    )
    if restart:
        vertical_merge.set(f"{{{namespace}}}val", "restart")
    cell_properties.append(vertical_merge)


def _expand_template_row(
    table,
    template_row,
    entries: list[SensorOverviewEntry],
) -> int:
    template_xml = template_row._tr
    values = entries or [
        SensorOverviewEntry(
            sensor_type="N/A",
            sensor_location="N/A",
            channel_rows=(("N/A", "N/A"),),
        )
    ]
    placeholders = (
        SENSOR_TYPE_ROWS_PLACEHOLDER,
        SENSOR_LOCATION_ROWS_PLACEHOLDER,
        SENSOR_DIRECTION_ROWS_PLACEHOLDER,
        SENSOR_MEASUREMENT_ROWS_PLACEHOLDER,
    )

    generated_row_count = 0
    for entry in values:
        generated_rows = []
        channel_rows = entry.channel_rows or (("N/A", "N/A"),)

        for channel_index, (direction, measurement) in enumerate(channel_rows):
            copied_row_xml = deepcopy(template_xml)
            _remove_fixed_row_height(copied_row_xml)
            row_values = (
                entry.sensor_type if channel_index == 0 else "",
                entry.sensor_location if channel_index == 0 else "",
                direction,
                measurement,
            )

            for cell_index, (placeholder, value) in enumerate(
                zip(placeholders, row_values)
            ):
                _replace_placeholder_in_cell_xml(
                    copied_row_xml,
                    cell_index=cell_index,
                    placeholder=placeholder,
                    replacement=value,
                )

            template_xml.addprevious(copied_row_xml)
            generated_rows.append(copied_row_xml)
            generated_row_count += 1

        if len(generated_rows) > 1:
            for row_index, generated_row in enumerate(generated_rows):
                _set_vertical_merge(
                    generated_row,
                    cell_index=0,
                    restart=row_index == 0,
                )
                _set_vertical_merge(
                    generated_row,
                    cell_index=1,
                    restart=row_index == 0,
                )

    table._tbl.remove(template_xml)
    return generated_row_count


def fill_tcd09_sensor_type_rows(profile: dict[str, Any], source: str | Path | io.BytesIO) -> io.BytesIO:
    """Expand the four-column Sensor Overview template row in a Word document."""
    try:
        document = docx.Document(source)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to open TCD09 Word template for Sensor Overview: {exc}") from exc
    template_rows = _find_sensor_template_rows(document)
    if not template_rows:
        raise HTTPException(
            status_code=400,
            detail=(
                "TCD09 Sensor Overview template row was not found. "
                "Place <TCD09_SENSOR_TYPE_ROWS> in column 1, "
                "<TCD09_SENSOR_LOCATION_ROWS> in column 2, "
                "<TCD09_SENSOR_DIRECTION_ROWS> in column 3 and "
                "<TCD09_SENSOR_MEASUREMENT_ROWS> in column 4 of the same row."
            ),
        )
    overview_entries = _build_sensor_overview_entries(profile)
    for table, template_row in template_rows:
        _expand_template_row(table, template_row, overview_entries)
    output = io.BytesIO()
    document.save(output)
    output.seek(0)
    return output
