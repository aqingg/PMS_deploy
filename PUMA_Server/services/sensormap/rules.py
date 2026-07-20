from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import SensorMapConfigError

PACKAGE_DIR = Path(__file__).resolve().parent
PUMA_SERVER_DIR = PACKAGE_DIR.parents[1]

DEFAULT_SECTION_CONFIG_PATH = (
    PUMA_SERVER_DIR / "config" / "sensormap_sections.json"
)
DEFAULT_SENSOR_RULES_PATH = (
    PUMA_SERVER_DIR / "config" / "sensormap_sensor_rules.json"
)


def _load_json(path: str | Path, label: str) -> dict[str, Any]:
    json_path = Path(path)
    if not json_path.is_file():
        raise SensorMapConfigError(f"{label} does not exist: {json_path}")

    try:
        with json_path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise SensorMapConfigError(
            f"{label} is invalid JSON: {json_path}. "
            f"Line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise SensorMapConfigError(
            f"Unable to read {label}: {json_path}"
        ) from exc

    if not isinstance(data, dict):
        raise SensorMapConfigError(f"{label} root must be a JSON object.")
    return data


def load_sensormap_config(
    config_path: str | Path = DEFAULT_SECTION_CONFIG_PATH,
) -> dict[str, Any]:
    config = _load_json(config_path, "Sensor Map section config")

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

    calibration_columns = config.get("calibration_columns", {})
    if not isinstance(calibration_columns, dict):
        raise SensorMapConfigError(
            '"calibration_columns" must be a JSON object.'
        )

    calibration_row_rules = config.get("calibration_row_rules", {})
    if not isinstance(calibration_row_rules, dict):
        raise SensorMapConfigError(
            '"calibration_row_rules" must be a JSON object.'
        )

    return config


def load_sensor_rules(
    rules_path: str | Path = DEFAULT_SENSOR_RULES_PATH,
) -> dict[str, Any]:
    rules = _load_json(rules_path, "Sensor topology rules")
    if not rules:
        raise SensorMapConfigError(
            "Sensor topology rules must not be empty."
        )

    for raw_code, rule in rules.items():
        code = str(raw_code).upper().strip()
        if not isinstance(rule, dict):
            raise SensorMapConfigError(
                f'Sensor rule "{code}" must be a JSON object.'
            )

        topology = rule.get("topology")
        if topology not in {
            "three_position",
            "symmetric_levels",
            "pillar_pairs",
            "fixed_positions",
        }:
            raise SensorMapConfigError(
                f'Sensor rule "{code}" has unsupported topology: {topology}'
            )

        axes = rule.get("supported_axes")
        if not isinstance(axes, list) or not axes:
            raise SensorMapConfigError(
                f'Sensor rule "{code}" must define supported_axes.'
            )

        row_rules = rule.get("row_rules")
        if not isinstance(row_rules, dict):
            raise SensorMapConfigError(
                f'Sensor rule "{code}" must define row_rules.'
            )

    return rules
