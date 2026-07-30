from __future__ import annotations

# 本文件负责生成 Sensor Overview 的四列数据，并填写 Word 表格模板行。
# 不处理汽车底图 Shape 的位置或方向逻辑。

import io
import json
from copy import deepcopy
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
        return _format_three_positions(positions, "longitudinal beam")
    if family == "RCS":
        positions = entry.positions or three_position_set_from_count(default_count(entry, rules, fallback=2))
        return _format_three_positions(positions, "rear trunk")
    if family == "PAS":
        positions = entry.positions or pas_positions_from_count(default_count(entry, rules, fallback=2), rules)
        return _format_pas_positions(positions)
    if family == "PCS":
        positions = entry.positions or three_position_set_from_count(default_count(entry, rules, fallback=1))
        return _format_three_positions(positions, "front bumper")
    if family == "PPS":
        positions = {normalize_pps_position(position) for position in entry.positions}
        if not positions:
            positions = pps_positions_from_count(default_count(entry, rules, fallback=2))
        return _format_pps_positions(positions)
    if family == "PTS":
        return "Front bumper"
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
    if not isinstance(data, dict) or not isinstance(data.get("sensing_direction"), dict):
        raise HTTPException(status_code=500, detail='TCD09 Sensor Overview rules must define "sensing_direction".')
    return data


def _as_rule_lines(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    elif isinstance(value, (list, tuple)):
        values = [str(item) for item in value]
    else:
        values = []
    return [str(line).strip() for line in values if str(line).strip()]


def _overview_rule_value(entry: SensorEntry, overview_rules: dict[str, Any], rule_name: str) -> str:
    rules = overview_rules.get(rule_name, {})
    exact_models = rules.get("exact_models", {})
    sensor_families = rules.get("sensor_families", {})
    exact_lookup = {str(key).strip().casefold(): value for key, value in exact_models.items() if str(key).strip()} if isinstance(exact_models, dict) else {}
    family_lookup = {str(key).strip().upper(): value for key, value in sensor_families.items() if str(key).strip()} if isinstance(sensor_families, dict) else {}
    configured = exact_lookup.get(entry.display_name.casefold())
    if configured is None:
        configured = family_lookup.get(entry.family.upper())
    if configured is None:
        configured = rules.get("default", ["N/A"])
    return "\n".join(_as_rule_lines(configured) or ["N/A"])


def build_sensor_overview_rows(
    profile: dict[str, Any],
    *,
    sensormap_rules_path: str | Path = DEFAULT_SENSORMAP_RULES_PATH,
    overview_rules_path: str | Path = DEFAULT_SENSOR_OVERVIEW_RULES_PATH,
) -> list[tuple[str, str, str, str]]:
    """Build the four Sensor Overview table values for each parsed sensor."""

    sensor_map_rules = _load_sensormap_rules(sensormap_rules_path)
    overview_rules = _load_sensor_overview_rules(overview_rules_path)
    entries = [
        *merge_sensor_entries(profile.get("internal_sensor_configuration"), force_inertial=True),
        *merge_sensor_entries(profile.get("peripheral_sensor_configuration"), force_inertial=False),
    ]
    rows: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for entry in entries:
        row = (
            entry.display_name,
            _sensor_location(entry, sensor_map_rules),
            _overview_rule_value(entry, overview_rules, "sensing_direction"),
            _overview_rule_value(entry, overview_rules, "measurement"),
        )
        key = tuple(value.casefold() for value in row)
        if key not in seen:
            seen.add(key)
            rows.append(row)
    return rows


def parse_sensor_types(value: Any) -> list[str]:
    """Backward-compatible first-column parser."""
    return [entry.display_name for entry in merge_sensor_entries(value, force_inertial=False)]


def build_sensor_type_rows(profile: dict[str, Any]) -> list[str]:
    """Backward-compatible Sensor Type-only helper."""
    return [row[0] for row in build_sensor_overview_rows(profile)]


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


def _expand_template_row(table, template_row, rows: list[tuple[str, str, str, str]]) -> int:
    template_xml = template_row._tr
    values = rows or [("N/A", "N/A", "N/A", "N/A")]
    placeholders = (
        SENSOR_TYPE_ROWS_PLACEHOLDER,
        SENSOR_LOCATION_ROWS_PLACEHOLDER,
        SENSOR_DIRECTION_ROWS_PLACEHOLDER,
        SENSOR_MEASUREMENT_ROWS_PLACEHOLDER,
    )
    for values_for_row in values:
        copied_row_xml = deepcopy(template_xml)
        for cell_index, (placeholder, value) in enumerate(zip(placeholders, values_for_row)):
            _replace_placeholder_in_cell_xml(copied_row_xml, cell_index=cell_index, placeholder=placeholder, replacement=value)
        template_xml.addprevious(copied_row_xml)
    table._tbl.remove(template_xml)
    return len(values)


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
    overview_rows = build_sensor_overview_rows(profile)
    for table, template_row in template_rows:
        _expand_template_row(table, template_row, overview_rows)
    output = io.BytesIO()
    document.save(output)
    output.seek(0)
    return output
