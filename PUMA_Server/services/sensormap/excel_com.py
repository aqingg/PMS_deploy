from __future__ import annotations

import gc
import os
from pathlib import Path
from typing import Any, Iterable

from .errors import SensorMapTemplateError

MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3
XL_SHIFT_UP = -4162


def import_excel_com() -> tuple[Any, Any, Any]:
    if os.name != "nt":
        raise SensorMapTemplateError(
            "Excel COM automation requires Windows."
        )

    try:
        import pythoncom
        import pywintypes
        import win32com.client
    except ImportError as exc:
        raise SensorMapTemplateError(
            "pywin32 is required. Install it with: "
            "python -m pip install pywin32"
        ) from exc

    return pythoncom, pywintypes, win32com.client


def coerce_used_range_values(
    values: Any,
    row_count: int,
    column_count: int,
) -> tuple[tuple[Any, ...], ...]:
    if row_count <= 0 or column_count <= 0:
        return tuple()

    if row_count == 1 and column_count == 1:
        return ((values,),)

    if isinstance(values, tuple):
        if values and isinstance(values[0], tuple):
            return tuple(tuple(row) for row in values)
        if row_count == 1:
            return (tuple(values),)
        if column_count == 1:
            return tuple((value,) for value in values)

    return ((values,),)


class ExcelSession:
    """Context manager around an isolated Excel COM instance."""

    def __init__(self, workbook_path: str | Path):
        self.workbook_path = Path(workbook_path).resolve()
        self.pythoncom = None
        self.pywintypes = None
        self.excel = None
        self.workbook = None

    def __enter__(self) -> "ExcelSession":
        (
            self.pythoncom,
            self.pywintypes,
            win32_client,
        ) = import_excel_com()

        self.pythoncom.CoInitialize()
        self.excel = win32_client.DispatchEx("Excel.Application")
        self.excel.Visible = False
        self.excel.DisplayAlerts = False
        self.excel.ScreenUpdating = False
        self.excel.EnableEvents = False
        self.excel.AskToUpdateLinks = False
        self.excel.AutomationSecurity = (
            MSO_AUTOMATION_SECURITY_FORCE_DISABLE
        )

        self.workbook = self.excel.Workbooks.Open(
            Filename=str(self.workbook_path),
            UpdateLinks=0,
            ReadOnly=False,
            IgnoreReadOnlyRecommended=True,
            AddToMru=False,
            Local=True,
        )

        if bool(self.workbook.ReadOnly):
            raise SensorMapTemplateError(
                f"Workbook opened read-only: {self.workbook_path}"
            )

        return self

    def select_worksheet(self, worksheet_name: str | None) -> Any:
        requested = str(worksheet_name or "").strip()
        available = [
            str(self.workbook.Worksheets.Item(index).Name)
            for index in range(
                1,
                int(self.workbook.Worksheets.Count) + 1,
            )
        ]

        if requested:
            if requested not in available:
                raise SensorMapTemplateError(
                    f'Worksheet "{requested}" does not exist. '
                    f"Available worksheets: {available}"
                )
            return self.workbook.Worksheets.Item(requested)

        active = self.workbook.ActiveSheet
        try:
            _ = active.UsedRange
            return active
        except Exception:
            if not available:
                raise SensorMapTemplateError(
                    "Workbook contains no worksheets."
                )
            return self.workbook.Worksheets.Item(1)

    def save(self) -> None:
        self.workbook.Save()

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self.workbook is not None:
                self.workbook.Close(SaveChanges=False)
        finally:
            self.workbook = None
            if self.excel is not None:
                try:
                    self.excel.Quit()
                except Exception:
                    pass
            self.excel = None
            gc.collect()
            if self.pythoncom is not None:
                try:
                    self.pythoncom.CoUninitialize()
                except Exception:
                    pass
