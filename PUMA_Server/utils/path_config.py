from pathlib import Path

"""
Server runtime internal paths configuration.

All runtime assets (DB / data_source / templates / downloads)
are stored INSIDE the codebase, relative to main.py.

This mode is optimized for Docker / Linux runtime performance
and does NOT rely on bind mounts or host paths.
"""

# ==========================================================
# Project root directory
# utils/path_config.py -> utils -> project root
# ==========================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# PROJECT_ROOT = Path(r"N:\Prj\PS\32_Application\EPD5-AppPUMA-Templates")
# PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ==========================================================
# Runtime base directory (relative to project root)
# main.py
# ├─ DB/
# │  ├─ app.db
# │  ├─ data_source/
# │  ├─ templates/
# │  ├─ downloads/
# │  ├─ logs/
# │  └─ history/
# ==========================================================

BASE_RUNTIME_DIR = PROJECT_ROOT / "DB"
#BASE_RUNTIME_DIR = PROJECT_ROOT / "DB" / "local_mock_runtime"


# Ensure base runtime directory exists
BASE_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

# ==========================================================
# Derived paths
# ==========================================================
DB_PATH = BASE_RUNTIME_DIR / "app.db"

DATA_SOURCE_DIR = BASE_RUNTIME_DIR / "data_source"
CUSTOMER_LOGO_DIR = BASE_RUNTIME_DIR / "Customer_Logo"
TEMPLATES_DIR = BASE_RUNTIME_DIR / "templates"
DOWNLOADS_DIR = BASE_RUNTIME_DIR / "downloads"
LOGS_DIR = BASE_RUNTIME_DIR / "logs"
HISTORY_DIR = BASE_RUNTIME_DIR / "history"
EMAIL_DIR = BASE_RUNTIME_DIR / "Email"

# ==========================================================
# Ensure directory structure exists
# ==========================================================

for _dir in [
    DATA_SOURCE_DIR,
    CUSTOMER_LOGO_DIR,
    TEMPLATES_DIR,
    DOWNLOADS_DIR,
    LOGS_DIR,
    HISTORY_DIR,
    EMAIL_DIR,
]:
    _dir.mkdir(parents=True, exist_ok=True)
