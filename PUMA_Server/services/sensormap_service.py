"""
Compatibility wrapper for the refactored Sensor Map package.

Existing imports such as:
    from services.sensormap_service import generate_sensor_map

continue to work without changing api/report.py.
"""

from sensormap import (
    SensorMapConfigError,
    SensorMapError,
    SensorMapSectionError,
    SensorMapTemplateError,
    generate_sensor_map,
    load_sensormap_config,
)

__all__ = [
    "SensorMapConfigError",
    "SensorMapError",
    "SensorMapSectionError",
    "SensorMapTemplateError",
    "generate_sensor_map",
    "load_sensormap_config",
]


if __name__ == "__main__":
    from pathlib import Path
    import json

    TEST_SCOPE = "3*PCSXY+UFSXY+3*RCS"
    TEST_CALIBRATION_SCOPE = "FSR"
    TEST_OUTPUT_DIRECTORY = Path.cwd() / "sensormap_test_output"
    TEST_PROJECT_NAME = "Demo_Project"

    try:
        result = generate_sensor_map(
            peripheral_sensor_scope=TEST_SCOPE,
            calibration_scope=TEST_CALIBRATION_SCOPE,
            output_directory=TEST_OUTPUT_DIRECTORY,
            project_name=TEST_PROJECT_NAME,
        )
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )
    except SensorMapError as error:
        print(f"Sensor Map test failed: {error}")
