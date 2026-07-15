class SensorMapError(RuntimeError):
    """Base exception for Sensor Map generation failures."""


class SensorMapConfigError(SensorMapError):
    """Raised when Sensor Map configuration is invalid."""


class SensorMapTemplateError(SensorMapError):
    """Raised when the Excel template cannot be found or opened."""


class SensorMapSectionError(SensorMapError):
    """Raised when worksheet sections cannot be resolved safely."""
