from __future__ import annotations

import io
import logging
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree as ET  # type: ignore[reportMissingImports]

from services.tcd09.sensor_parser import merge_sensor_entries
from services.word.package import write_zip_with_replacement
from services.word.xml_utils import NS, clean_text, element_text, qn

logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class SensorReferenceRule:
    """Map one peripheral sensor family to its References list item."""

    anchors: tuple[str, ...]
    continuations: tuple[str, ...] = ()


# Only sensor-specific mounting-guideline entries are conditional.
# AB-ECU, eSense, Vehicle Tests and Wiring Harness are intentionally retained.
SENSOR_REFERENCE_RULES: dict[str, SensorReferenceRule] = {
    "PAS": SensorReferenceRule(
        anchors=("Mounting Guideline PAS",),
        continuations=("外围加速度传感器的安装指南",),
    ),
    "UFS": SensorReferenceRule(
        anchors=("Mounting Guideline UFS",),
        continuations=("前碰传感器的安装指南",),
    ),
    "RCS": SensorReferenceRule(
        anchors=("Mounting Guideline RCS",),
        continuations=("后碰传感器的安装指南",),
    ),
    "PPS": SensorReferenceRule(
        anchors=("Mounting Guideline PPS",),
        continuations=("外围压力传感器的安装指南",),
    ),
    "PCS": SensorReferenceRule(
        anchors=("Mounting Guideline PCS",),
        continuations=("行人碰撞加速度传感器的安装指南",),
    ),
    "PTS": SensorReferenceRule(
        anchors=("Mounting Guideline PTS",),
        continuations=("行人碰撞压力管传感器的安装指南",),
    ),
}


def _normalize(value: Any) -> str:
    return clean_text(value).casefold()


def _present_peripheral_families(profile: dict[str, Any]) -> set[str]:
    entries = merge_sensor_entries(
        profile.get("peripheral_sensor_configuration"),
        force_inertial=False,
    )
    return {
        str(entry.family or "").strip().upper()
        for entry in entries
        if str(entry.family or "").strip()
    }


def _contains_any(text: str, candidates: tuple[str, ...]) -> bool:
    normalized = _normalize(text)
    return any(_normalize(candidate) in normalized for candidate in candidates if candidate)


def _clear_paragraph(paragraph: ET.Element) -> None:
    """Keep a valid empty paragraph when a table cell cannot lose its last block."""

    paragraph_properties = paragraph.find("w:pPr", NS)
    for child in list(paragraph):
        if child is paragraph_properties:
            continue
        paragraph.remove(child)

    if paragraph_properties is not None:
        numbering = paragraph_properties.find("w:numPr", NS)
        if numbering is not None:
            paragraph_properties.remove(numbering)


def _remove_paragraph_safely(paragraph: ET.Element) -> bool:
    """Delete a paragraph, preserving the minimum valid structure of table cells."""

    parent = paragraph.getparent()
    if parent is None:
        return False

    if parent.tag == qn("tc"):
        remaining_blocks = [
            child
            for child in parent
            if child is not paragraph and child.tag in {qn("p"), qn("tbl")}
        ]
        if not remaining_blocks:
            _clear_paragraph(paragraph)
            return True

    parent.remove(paragraph)
    return True


def _paragraph_deletion_plan(
    document_root: ET.Element,
    missing_families: set[str],
) -> dict[ET.Element, str]:
    paragraphs = list(document_root.findall(".//w:p", NS))
    texts = [element_text(paragraph) for paragraph in paragraphs]
    normalized_texts = [_normalize(text) for text in texts]
    planned: dict[ET.Element, str] = {}

    for index, paragraph in enumerate(paragraphs):
        paragraph_text = normalized_texts[index]
        if not paragraph_text:
            continue

        for family in sorted(missing_families):
            rule = SENSOR_REFERENCE_RULES[family]
            if not any(_normalize(anchor) in paragraph_text for anchor in rule.anchors):
                continue

            planned[paragraph] = family

            # In the normal template the English and Chinese text are in one
            # bullet paragraph separated by a line break. This fallback also
            # supports templates where the Chinese explanation is a separate,
            # immediately following paragraph.
            continuation_in_same_paragraph = any(
                _normalize(continuation) in paragraph_text
                for continuation in rule.continuations
            )
            if not continuation_in_same_paragraph and rule.continuations:
                for next_index in range(index + 1, min(index + 3, len(paragraphs))):
                    candidate = paragraphs[next_index]
                    candidate_text = normalized_texts[next_index]
                    if not candidate_text:
                        continue
                    if _contains_any(candidate_text, rule.continuations):
                        planned[candidate] = family
                    break
            break

    return planned


def remove_unused_sensor_references(
    profile: dict[str, Any],
    source: io.BytesIO,
) -> io.BytesIO:
    """Remove References bullets for peripheral families absent from the profile.

    Examples:
    - ``2*PTS`` and ``2*PTS1`` both preserve the PTS guideline.
    - An empty peripheral configuration removes PAS/UFS/RCS/PPS/PCS/PTS
      guideline bullets, while generic references remain unchanged.
    """

    source.seek(0)
    content = source.read()
    if not content:
        raise ValueError("TCD09 Word stream is empty.")

    present_families = _present_peripheral_families(profile)
    managed_families = set(SENSOR_REFERENCE_RULES)
    missing_families = managed_families - present_families

    if not missing_families:
        return io.BytesIO(content)

    with tempfile.TemporaryDirectory(prefix="puma_tcd09_references_") as temp_root:
        input_path = Path(temp_root) / "input.docx"
        output_path = Path(temp_root) / "output.docx"
        input_path.write_bytes(content)

        with zipfile.ZipFile(input_path, "r") as archive:
            try:
                document_xml = archive.read("word/document.xml")
            except KeyError as exc:
                raise ValueError(
                    "TCD09 Word package does not contain word/document.xml."
                ) from exc

        document_root = ET.fromstring(document_xml)
        deletion_plan = _paragraph_deletion_plan(
            document_root,
            missing_families,
        )

        removed_by_family: dict[str, int] = {}
        for paragraph, family in deletion_plan.items():
            if _remove_paragraph_safely(paragraph):
                removed_by_family[family] = removed_by_family.get(family, 0) + 1

        if not removed_by_family:
            logger.info(
                "[TCD09] No unused sensor References entries matched. "
                "present=%s missing=%s",
                sorted(present_families),
                sorted(missing_families),
            )
            return io.BytesIO(content)

        updated_document_xml = ET.tostring(
            document_root,
            encoding="utf-8",
            xml_declaration=True,
        )
        write_zip_with_replacement(
            input_path,
            output_path,
            {"word/document.xml": updated_document_xml},
        )

        logger.info(
            "[TCD09] Removed unused sensor References entries. "
            "present=%s removed=%s",
            sorted(present_families),
            removed_by_family,
        )
        return io.BytesIO(output_path.read_bytes())
