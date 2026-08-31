"""Best-effort audit logging for successful report-generation operations."""

from __future__ import annotations

import csv
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from utils.path_config import LOGS_DIR

logger = logging.getLogger("uvicorn.error")

LOG_DIRECTORY_ENV = "PUMA_FILL_OPERATION_LOG_DIR"
DEFAULT_SHARED_LOG_DIR = Path(
    r"N:\Prj\PS\32_Application\EPD5-CN-Tools-Mgmt\14.App-PMS"
)
LOG_FILENAME = "fill_operations.csv"
LOCAL_FALLBACK_LOG_PATH = LOGS_DIR / LOG_FILENAME


@contextmanager
def _exclusive_lock(lock_path: Path) -> Iterator[None]:
    """Acquire an inter-process lock on a sidecar file before appending CSV."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()

        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + 10
            while True:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out acquiring log lock: {lock_path}")
                    time.sleep(0.05)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _append_row(log_path: Path, username: str, operation: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(log_path.with_suffix(f"{log_path.suffix}.lock")):
        is_new_file = not log_path.exists() or log_path.stat().st_size == 0
        with open(log_path, "a", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=("timestamp", "username", "operation", "status"),
            )
            if is_new_file:
                writer.writeheader()
            writer.writerow(
                {
                    "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "username": username or "Unknown",
                    "operation": operation,
                    "status": "success",
                }
            )


def log_successful_fill_operation(username: str | None, operation: str) -> None:
    """Append a successful operation without affecting the report response.

    The configured public-share directory is attempted first. Any failure is
    reported to the application log and then falls back to the Server-local CSV.
    """
    safe_username = str(username or "").strip() or "Unknown"
    configured_directory_text = os.getenv(LOG_DIRECTORY_ENV, "").strip()
    configured_directory = Path(configured_directory_text or DEFAULT_SHARED_LOG_DIR)

    if configured_directory:
        try:
            _append_row(configured_directory / LOG_FILENAME, safe_username, operation)
            return
        except Exception:
            logger.exception(
                "Failed to append fill-operation audit log to configured directory %s; "
                "falling back to %s.",
                configured_directory,
                LOCAL_FALLBACK_LOG_PATH,
            )

    try:
        _append_row(LOCAL_FALLBACK_LOG_PATH, safe_username, operation)
    except Exception:
        logger.exception(
            "Failed to append fallback fill-operation audit log to %s.",
            LOCAL_FALLBACK_LOG_PATH,
        )
