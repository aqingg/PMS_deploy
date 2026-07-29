from __future__ import annotations

import io
import gc
import json
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from services.tcd09.sensor_overview import build_sensor_layout_model


THIS_DIR = Path(__file__).resolve().parent
SERVER_ROOT = THIS_DIR.parents[1]
DEFAULT_LAYOUT_RULES_PATH = (
    SERVER_ROOT / "config" / "tcd09_sensor_layout_rules.json"
)

# Word / Office constants. Numeric constants avoid generated COM wrappers.
WD_ALERTS_NONE = 0
WD_DO_NOT_SAVE_CHANGES = 0
WD_FORMAT_DOCUMENT_DEFAULT = 16
WD_MAIN_TEXT_STORY = 1
WD_WRAP_FRONT = 3
MSO_SHAPE_RECTANGLE = 1
MSO_BRING_TO_FRONT = 0
MSO_ANCHOR_MIDDLE = 3
WD_ALIGN_PARAGRAPH_CENTER = 1
MSO_TRUE = -1
MSO_FALSE = 0
MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3

_WORD_COM_LOCK = threading.RLock()


def _load_rules(path: str | Path) -> dict[str, Any]:
    rules_path = Path(path)
    if not rules_path.is_file():
        raise HTTPException(
            status_code=500,
            detail=f"TCD09 sensor layout rules do not exist: {rules_path}",
        )
    try:
        data = json.loads(rules_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid TCD09 sensor layout rules: {rules_path}: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=500,
            detail="TCD09 sensor layout rules root must be a JSON object.",
        )
    if not isinstance(data.get("slots"), dict) or not data["slots"]:
        raise HTTPException(
            status_code=500,
            detail='TCD09 sensor layout rules must define non-empty "slots".',
        )
    return data


def _rgb(value: Any) -> int:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid RGB value in TCD09 sensor layout rules: {value!r}",
        )
    red, green, blue = [max(0, min(255, int(item))) for item in value]
    # Office/VBA RGB integer: R + G*256 + B*65536.
    return red | (green << 8) | (blue << 16)


def _stream_bytes(source: str | Path | io.BytesIO) -> bytes:
    if isinstance(source, io.BytesIO):
        source.seek(0)
        return source.read()

    path = Path(source)
    if not path.is_file():
        raise HTTPException(
            status_code=400,
            detail=f"TCD09 Word document does not exist: {path}",
        )
    return path.read_bytes()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _find_base_picture(document, alt_text: str):
    """Find the uniquely marked floating base picture in the main document."""

    floating_matches = []
    for shape in document.Shapes:
        if _safe_text(getattr(shape, "AlternativeText", "")) == alt_text:
            floating_matches.append(shape)

    if len(floating_matches) > 1:
        raise HTTPException(
            status_code=400,
            detail=(
                f'Multiple floating pictures use AlternativeText="{alt_text}". '
                "The TCD09 template must contain exactly one base picture."
            ),
        )
    if len(floating_matches) == 1:
        base = floating_matches[0]
        anchor = getattr(base, "Anchor", None)
        story_type = int(getattr(anchor, "StoryType", 0)) if anchor is not None else 0
        if story_type != WD_MAIN_TEXT_STORY:
            raise HTTPException(
                status_code=400,
                detail=(
                    "TCD09 sensor layout base picture is not in the main Word story. "
                    "Move it out of headers, footers, text boxes and other stories."
                ),
            )
        return base

    inline_matches = []
    for inline_shape in document.InlineShapes:
        if _safe_text(getattr(inline_shape, "AlternativeText", "")) == alt_text:
            inline_matches.append(inline_shape)

    if inline_matches:
        raise HTTPException(
            status_code=400,
            detail=(
                f'The picture marked "{alt_text}" is an inline picture. '
                "Set Wrap Text to Behind Text (or another floating layout), "
                "fix its page position, and run TCD09 again."
            ),
        )

    raise HTTPException(
        status_code=400,
        detail=(
            f'TCD09 base picture not found. Set the picture AlternativeText to '
            f'"{alt_text}" exactly.'
        ),
    )


def _delete_old_generated_shapes(document, prefix: str) -> int:
    deleted = 0
    for index in range(int(document.Shapes.Count), 0, -1):
        shape = document.Shapes(index)
        if _safe_text(getattr(shape, "Name", "")).startswith(prefix):
            shape.Delete()
            deleted += 1
    return deleted


def _apply_text_style(shape, text: str, rules: dict[str, Any]) -> None:
    font_rule = rules.get("font", {})
    default_rule = rules.get("default_shape", {})

    text_frame = shape.TextFrame
    text_frame.AutoSize = MSO_FALSE
    text_frame.WordWrap = MSO_TRUE
    margin = float(default_rule.get("text_margin_pt", 2.0))
    text_frame.MarginLeft = margin
    text_frame.MarginRight = margin
    text_frame.MarginTop = margin
    text_frame.MarginBottom = margin

    try:
        text_frame.VerticalAnchor = MSO_ANCHOR_MIDDLE
    except Exception:
        pass

    text_range = text_frame.TextRange
    text_range.Text = text
    text_range.ParagraphFormat.Alignment = WD_ALIGN_PARAGRAPH_CENTER
    text_range.Font.Name = str(font_rule.get("name") or "Arial")
    text_range.Font.Size = float(font_rule.get("size_pt", 8))
    text_range.Font.Bold = MSO_TRUE if bool(font_rule.get("bold", True)) else MSO_FALSE
    text_range.Font.Color = _rgb(font_rule.get("color_rgb", [0, 0, 0]))


def _create_label_shape(
    document,
    base,
    *,
    slot_name: str,
    text: str,
    slot_rule: dict[str, Any],
    rules: dict[str, Any],
):
    base_left = float(base.Left)
    base_top = float(base.Top)
    base_width = float(base.Width)
    base_height = float(base.Height)

    shape_width = base_width * float(slot_rule["width"])
    shape_height = base_height * float(slot_rule["height"])
    center_x = base_left + base_width * float(slot_rule["x"])
    center_y = base_top + base_height * float(slot_rule["y"])
    shape_left = center_x - shape_width / 2.0
    shape_top = center_y - shape_height / 2.0

    anchor = base.Anchor.Duplicate
    shape = document.Shapes.AddShape(
        MSO_SHAPE_RECTANGLE,
        0.0,
        0.0,
        shape_width,
        shape_height,
        anchor,
    )

    # Use exactly the same coordinate reference system as the base picture.
    shape.RelativeHorizontalPosition = base.RelativeHorizontalPosition
    shape.RelativeVerticalPosition = base.RelativeVerticalPosition
    shape.Left = shape_left
    shape.Top = shape_top

    prefix = str(rules.get("generated_shape_prefix") or "TCD09_SENSOR_")
    shape.Name = f"{prefix}{slot_name}_LABEL"
    shape.AlternativeText = f"TCD09 editable sensor label: {slot_name}"
    shape.LockAspectRatio = MSO_FALSE
    shape.LockAnchor = False
    shape.Visible = MSO_TRUE

    try:
        shape.LayoutInCell = base.LayoutInCell
    except Exception:
        pass

    default_rule = rules.get("default_shape", {})
    shape.Fill.Visible = MSO_TRUE
    shape.Fill.ForeColor.RGB = _rgb(slot_rule.get("fill_rgb", [220, 220, 220]))
    shape.Fill.Transparency = float(
        slot_rule.get(
            "fill_transparency",
            default_rule.get("fill_transparency", 0.0),
        )
    )
    shape.Line.Visible = MSO_TRUE
    shape.Line.ForeColor.RGB = _rgb(
        slot_rule.get(
            "line_rgb",
            default_rule.get("line_rgb", [0, 0, 0]),
        )
    )
    shape.Line.Weight = float(
        slot_rule.get(
            "line_weight_pt",
            default_rule.get("line_weight_pt", 1.0),
        )
    )

    shape.WrapFormat.Type = WD_WRAP_FRONT
    try:
        shape.WrapFormat.AllowOverlap = MSO_TRUE
    except Exception:
        pass

    _apply_text_style(shape, text, rules)

    shape.Rotation = float(slot_rule.get("rotation", 0.0))
    shape.ZOrder(MSO_BRING_TO_FRONT)
    return shape



def _normalized_rotation(slot_rule: dict[str, Any]) -> int:
    return int(round(float(slot_rule.get("rotation", 0.0)))) % 360


def _visual_label_box(
    base,
    slot_rule: dict[str, Any],
) -> tuple[float, float, float, float]:
    """Return the displayed label box after 90/270-degree rotation."""

    base_left = float(base.Left)
    base_top = float(base.Top)
    base_width = float(base.Width)
    base_height = float(base.Height)

    raw_width = base_width * float(slot_rule["width"])
    raw_height = base_height * float(slot_rule["height"])
    center_x = base_left + base_width * float(slot_rule["x"])
    center_y = base_top + base_height * float(slot_rule["y"])

    rotation = _normalized_rotation(slot_rule)
    if rotation in {90, 270}:
        visual_width, visual_height = raw_height, raw_width
    else:
        visual_width, visual_height = raw_width, raw_height

    return (
        center_x - visual_width / 2.0,
        center_y - visual_height / 2.0,
        visual_width,
        visual_height,
    )


def _resolve_marker_side(
    slot_rule: dict[str, Any],
    marker: dict[str, Any],
) -> str:
    marker_rule = slot_rule.get("marker")
    if not isinstance(marker_rule, dict):
        raise HTTPException(
            status_code=500,
            detail="TCD09 layout slot is missing marker configuration.",
        )

    expected_type = str(marker_rule.get("type") or "").strip().casefold()
    actual_type = str(marker.get("type") or "").strip().casefold()
    if expected_type and actual_type != expected_type:
        raise HTTPException(
            status_code=500,
            detail=(
                "TCD09 marker type mismatch: "
                f"expected {expected_type}, got {actual_type or 'empty'}."
            ),
        )

    fixed_side = str(marker_rule.get("fixed_side") or "").strip().casefold()
    if fixed_side:
        side = fixed_side
    else:
        state = str(marker.get("state") or "").strip().casefold()
        direction_sides = marker_rule.get("direction_sides")
        if not isinstance(direction_sides, dict):
            raise HTTPException(
                status_code=500,
                detail="TCD09 marker configuration has no direction_sides.",
            )
        side = str(direction_sides.get(state) or "").strip().casefold()

    if side not in {"left", "right", "top", "bottom"}:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid TCD09 marker side: {side!r}.",
        )
    return side


def _marker_geometry(
    base,
    slot_rule: dict[str, Any],
    marker_style: dict[str, Any],
    side: str,
) -> tuple[float, float, float, float]:
    """Attach the marker to one edge of the visible label box.

    This deliberately avoids one global dx/dy. Each slot declares which edge
    is physically outward, and the marker is calculated from that label's
    actual displayed width and height.
    """

    label_left, label_top, label_width, label_height = _visual_label_box(
        base,
        slot_rule,
    )

    length_ratio = float(marker_style.get("length_ratio", 0.45))
    thickness_ratio = float(marker_style.get("thickness_ratio", 0.12))
    gap_ratio = float(marker_style.get("gap_ratio", 0.0))

    if side in {"left", "right"}:
        marker_width = max(2.0, label_width * thickness_ratio)
        marker_height = max(4.0, label_height * length_ratio)
        gap = label_width * gap_ratio
        marker_top = label_top + (label_height - marker_height) / 2.0
        marker_left = (
            label_left - gap - marker_width
            if side == "left"
            else label_left + label_width + gap
        )
    else:
        marker_width = max(4.0, label_width * length_ratio)
        marker_height = max(2.0, label_height * thickness_ratio)
        gap = label_height * gap_ratio
        marker_left = label_left + (label_width - marker_width) / 2.0
        marker_top = (
            label_top - gap - marker_height
            if side == "top"
            else label_top + label_height + gap
        )

    return marker_left, marker_top, marker_width, marker_height


def _create_marker_shape(
    document,
    base,
    *,
    slot_name: str,
    marker: dict[str, Any],
    slot_rule: dict[str, Any],
    rules: dict[str, Any],
):
    marker_type = str(marker.get("type") or "").strip().casefold()
    marker_styles = rules.get("marker_styles")
    if not isinstance(marker_styles, dict):
        raise HTTPException(
            status_code=500,
            detail='TCD09 layout rules must define "marker_styles".',
        )

    marker_style = marker_styles.get(marker_type)
    if not isinstance(marker_style, dict):
        raise HTTPException(
            status_code=500,
            detail=f"Missing TCD09 marker style: {marker_type!r}.",
        )

    side = _resolve_marker_side(slot_rule, marker)
    left, top, width, height = _marker_geometry(
        base,
        slot_rule,
        marker_style,
        side,
    )

    anchor = base.Anchor.Duplicate
    shape = document.Shapes.AddShape(
        MSO_SHAPE_RECTANGLE,
        0.0,
        0.0,
        width,
        height,
        anchor,
    )
    shape.RelativeHorizontalPosition = base.RelativeHorizontalPosition
    shape.RelativeVerticalPosition = base.RelativeVerticalPosition
    shape.Left = left
    shape.Top = top

    prefix = str(rules.get("generated_shape_prefix") or "TCD09_SENSOR_")
    suffix = "CONNECTOR" if marker_type == "connector" else "LOCATOR"
    shape.Name = f"{prefix}{slot_name}_{suffix}"
    shape.AlternativeText = (
        f"TCD09 editable {marker_type} marker: {slot_name}; side={side}"
    )
    shape.LockAspectRatio = MSO_FALSE
    shape.LockAnchor = False
    shape.Visible = MSO_TRUE

    try:
        shape.LayoutInCell = base.LayoutInCell
    except Exception:
        pass

    shape.Fill.Visible = MSO_TRUE
    shape.Fill.ForeColor.RGB = _rgb(
        marker_style.get(
            "fill_rgb",
            [0, 176, 240] if marker_type == "connector" else [0, 0, 0],
        )
    )
    shape.Fill.Transparency = float(marker_style.get("fill_transparency", 0.0))

    line_weight = float(marker_style.get("line_weight_pt", 0.0))
    if line_weight <= 0:
        shape.Line.Visible = MSO_FALSE
    else:
        shape.Line.Visible = MSO_TRUE
        shape.Line.ForeColor.RGB = _rgb(
            marker_style.get("line_rgb", [0, 0, 0])
        )
        shape.Line.Weight = line_weight

    shape.WrapFormat.Type = WD_WRAP_FRONT
    try:
        shape.WrapFormat.AllowOverlap = MSO_TRUE
    except Exception:
        pass

    shape.ZOrder(MSO_BRING_TO_FRONT)
    return shape


def insert_tcd09_sensor_layout_shapes(
    profile: dict[str, Any],
    source: str | Path | io.BytesIO,
    *,
    rules_path: str | Path = DEFAULT_LAYOUT_RULES_PATH,
) -> io.BytesIO:
    """Add independent, editable Word Shapes over the marked car picture.

    This function must be the last Word-processing step because later
    python-docx saves can discard or alter Office drawing objects.
    """

    rules = _load_rules(rules_path)
    model = build_sensor_layout_model(profile)
    labels = model.get("labels", [])
    slots = rules["slots"]

    unknown_slots = [
        str(item.get("slot") or "")
        for item in labels
        if str(item.get("slot") or "") not in slots
    ]
    if unknown_slots:
        raise HTTPException(
            status_code=500,
            detail=(
                "TCD09 layout rules are missing sensor slots: "
                + ", ".join(sorted(set(unknown_slots)))
            ),
        )

    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "TCD09 editable sensor layout requires pywin32 on Windows. "
                "Install it with: python -m pip install pywin32"
            ),
        ) from exc

    content = _stream_bytes(source)

    with _WORD_COM_LOCK:
        temp_root = Path(tempfile.mkdtemp(prefix="puma_tcd09_layout_"))
        input_path = temp_root / "input.docx"
        output_path = temp_root / "output.docx"
        result: io.BytesIO | None = None
        base = None
        pythoncom.CoInitialize()
        word = None
        document = None
        try:
            input_path.write_bytes(content)

            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = WD_ALERTS_NONE
            word.ScreenUpdating = False
            try:
                word.AutomationSecurity = MSO_AUTOMATION_SECURITY_FORCE_DISABLE
            except Exception:
                pass

            document = word.Documents.Open(
                str(input_path.resolve()),
                ReadOnly=False,
                AddToRecentFiles=False,
                ConfirmConversions=False,
            )

            base = _find_base_picture(
                document,
                str(rules.get("base_image_alt_text") or "").strip(),
            )

            prefix = str(
                rules.get("generated_shape_prefix")
                or "TCD09_SENSOR_"
            )
            _delete_old_generated_shapes(document, prefix)

            for item in labels:
                slot_name = str(item["slot"])
                text = str(item.get("text") or "").strip()
                if not text:
                    continue

                slot_rule = slots[slot_name]
                _create_label_shape(
                    document,
                    base,
                    slot_name=slot_name,
                    text=text,
                    slot_rule=slot_rule,
                    rules=rules,
                )

                marker = item.get("marker")
                if isinstance(marker, dict):
                    _create_marker_shape(
                        document,
                        base,
                        slot_name=slot_name,
                        marker=marker,
                        slot_rule=slot_rule,
                        rules=rules,
                    )

            document.SaveAs2(
                str(output_path.resolve()),
                FileFormat=WD_FORMAT_DOCUMENT_DEFAULT,
                AddToRecentFiles=False,
            )

            result = io.BytesIO(output_path.read_bytes())
            result.seek(0)

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create editable TCD09 sensor labels: {exc}",
            ) from exc
        finally:
            # Release child COM proxies before closing their owner document.
            base = None
            if document is not None:
                try:
                    document.Close(SaveChanges=WD_DO_NOT_SAVE_CHANGES)
                except Exception:
                    pass
                document = None
            if word is not None:
                try:
                    word.Quit(SaveChanges=WD_DO_NOT_SAVE_CHANGES)
                except Exception:
                    pass
                word = None
            gc.collect()
            pythoncom.CoUninitialize()
            gc.collect()

            # Cleanup must never replace a successfully generated report with
            # WinError 32. Word can release its final file handle shortly after
            # Quit returns, especially when this runs inside the API process.
            shutil.rmtree(temp_root, ignore_errors=True)

        if result is None:
            raise HTTPException(
                status_code=500,
                detail="TCD09 sensor layout did not produce an output document.",
            )
        return result
