"""Safe optional Word block cleanup helpers for TCD08 reports.

This module is deliberately conservative:
- report.py must explicitly tell it which Email simulation blocks are empty.
- it never deletes a label just because it sees an arbitrary N/A elsewhere.
- even for an explicitly requested empty block, it verifies that the label is
  followed by an actual missing value (N/A / empty placeholder) before deletion.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from lxml import etree as ET  # type: ignore[reportMissingImports]

from services.word.package import write_zip_with_replacement
from services.word.xml_utils import NS, clean_text, element_text

logger = logging.getLogger("uvicorn.error")

DOCUMENT_XML = "word/document.xml"

EMAIL_SIMULATION_BLOCKS: dict[str, dict[str, Any]] = {
    "standard": {
        "label": "Standard simulation",
        "placeholders": [
            "<PMS.Email.Send.StandardXlsxFiles>",
            "<PMS. Email.Send.StandardXlsxFiles>",
        ],
    },
    "defect": {
        "label": "UFS Defect simulation",
        "placeholders": [
            "<PMS.Email.Send.DefectXlsxFiles>",
            "<PMS. Email.Send.DefectXlsxFiles>",
        ],
    },
    "specific": {
        "label": "Customer specific simulation",
        "placeholders": [
            "<PMS.Email.Send.SpecificXlsxFiles>",
            "<PMS. Email.Send.SpecificXlsxFiles>",
        ],
    },
}

_MISSING_VALUE_TEXTS = {
    "",
    "-",
    "—",
    "n/a",
    "na",
    "n.a",
    "n.a.",
    "none",
    "null",
}


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except FileNotFoundError:
        return False


@dataclass
class OptionalBlockRemovalSummary:
    """Summary returned after optional block removal."""

    document_path: str
    requested_labels: list[str] = field(default_factory=list)
    removed_labels: list[str] = field(default_factory=list)
    skipped_labels: list[str] = field(default_factory=list)
    removed_paragraphs: int = 0
    changed: bool = False

    @property
    def removed_blocks(self) -> int:
        return len(self.removed_labels)

    @property
    def matched_labels(self) -> list[str]:
        """Backward-compatible alias for earlier report.py logging."""
        return self.removed_labels

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_path": self.document_path,
            "requested_labels": self.requested_labels,
            "removed_labels": self.removed_labels,
            "skipped_labels": self.skipped_labels,
            "matched_labels": self.matched_labels,
            "removed_blocks": self.removed_blocks,
            "removed_paragraphs": self.removed_paragraphs,
            "changed": self.changed,
        }


def _normalize_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\u00a0", " ")
    text = text.replace("：", ":")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _normalize_label(value: Any) -> str:
    return _normalize_text(value).rstrip(":").strip()


def _paragraph_text(paragraph: ET.Element) -> str:
    return clean_text(element_text(paragraph)).strip()


def _is_empty_value_text(value: Any, placeholders: Iterable[str] = ()) -> bool:
    normalized = _normalize_text(value).strip(" .。:：\t\r\n")
    if normalized in _MISSING_VALUE_TEXTS:
        return True

    for placeholder in placeholders:
        if normalized == _normalize_text(placeholder).strip(" .。:：\t\r\n"):
            return True

    return False


def _is_label_paragraph(paragraph: ET.Element, label: str) -> bool:
    text = _normalize_text(_paragraph_text(paragraph))
    label_norm = _normalize_label(label)
    return text == label_norm or text == f"{label_norm}:" or text.startswith(f"{label_norm}: ")


def _matching_any_label(paragraph: ET.Element) -> str | None:
    for rule in EMAIL_SIMULATION_BLOCKS.values():
        label = str(rule["label"])
        if _is_label_paragraph(paragraph, label):
            return label
    return None


def _resolve_requested_rules(
    *,
    missing_labels: Iterable[str] | None = None,
    missing_keys: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Resolve caller-supplied keys/labels into canonical block rules."""
    resolved: list[dict[str, Any]] = []
    seen_labels: set[str] = set()

    for key in missing_keys or []:
        normalized_key = _normalize_label(key).replace(" ", "_").replace("-", "_")
        rule = EMAIL_SIMULATION_BLOCKS.get(normalized_key)
        if rule and str(rule["label"]) not in seen_labels:
            resolved.append(rule)
            seen_labels.add(str(rule["label"]))

    label_lookup = {
        _normalize_label(str(rule["label"])): rule
        for rule in EMAIL_SIMULATION_BLOCKS.values()
    }
    key_lookup = {
        _normalize_label(key): rule
        for key, rule in EMAIL_SIMULATION_BLOCKS.items()
    }

    for label in missing_labels or []:
        normalized_label = _normalize_label(label)
        rule = label_lookup.get(normalized_label) or key_lookup.get(normalized_label)
        if rule and str(rule["label"]) not in seen_labels:
            resolved.append(rule)
            seen_labels.add(str(rule["label"]))

    return resolved


def _collect_requested_empty_block(
    paragraphs: list[ET.Element],
    start_index: int,
    rule: dict[str, Any],
) -> list[ET.Element]:
    """Collect paragraphs for one explicitly requested empty block.

    A block is removed only when this exact label is followed by a missing value.
    This prevents the earlier failure mode where labels were deleted permanently
    even when their placeholder had a real value.
    """
    label = str(rule["label"])
    placeholders = [str(item) for item in rule.get("placeholders", [])]
    label_paragraph = paragraphs[start_index]

    if not _is_label_paragraph(label_paragraph, label):
        return []

    label_text = _paragraph_text(label_paragraph)
    label_norm = _normalize_label(label)
    normalized_label_text = _normalize_text(label_text)

    # Same paragraph: "UFS Defect simulation: N/A".
    if normalized_label_text.startswith(f"{label_norm}:"):
        suffix = normalized_label_text[len(label_norm) + 1 :].strip()
        if suffix and _is_empty_value_text(suffix, placeholders):
            return [label_paragraph]
        if suffix:
            return []

    # Separate paragraph:
    #   UFS Defect simulation:
    #   N/A
    # Allow blank paragraphs between label and value. Stop at next label or any
    # meaningful non-missing value.
    block: list[ET.Element] = [label_paragraph]
    found_missing_value = False

    for candidate in paragraphs[start_index + 1 :]:
        if _matching_any_label(candidate):
            break

        candidate_text = _paragraph_text(candidate)
        normalized_candidate = _normalize_text(candidate_text).strip(" .。:：\t\r\n")

        if normalized_candidate == "":
            block.append(candidate)
            continue

        if _is_empty_value_text(candidate_text, placeholders):
            block.append(candidate)
            found_missing_value = True
            # Remove following blank paragraph(s) that are visually part of the block.
            continue

        # A real file name/value means this block must be kept.
        break

    if not found_missing_value:
        return []

    # Include blank paragraphs immediately after the missing value, but stop at
    # next label or any real content.
    selected_ids = {id(item) for item in block}
    last_selected_index = max(
        index for index, paragraph in enumerate(paragraphs) if id(paragraph) in selected_ids
    )
    for candidate in paragraphs[last_selected_index + 1 :]:
        if _matching_any_label(candidate):
            break
        if _normalize_text(_paragraph_text(candidate)).strip(" .。:：\t\r\n") == "":
            block.append(candidate)
            continue
        break

    return block


def _remove_paragraphs(paragraphs: list[ET.Element]) -> int:
    removed = 0
    for paragraph in paragraphs:
        parent = paragraph.getparent()
        if parent is None:
            continue
        parent.remove(paragraph)
        removed += 1
    return removed


def remove_empty_email_simulation_blocks_in_xml(
    input_docm: Path,
    output_docm: Path,
    *,
    missing_labels: Iterable[str] | None = None,
    missing_keys: Iterable[str] | None = None,
) -> OptionalBlockRemovalSummary:
    """Remove explicitly requested empty Email simulation blocks from a Word file."""
    requested_rules = _resolve_requested_rules(missing_labels=missing_labels, missing_keys=missing_keys)
    requested_labels = [str(rule["label"]) for rule in requested_rules]

    if not requested_rules:
        if not _same_file(input_docm, output_docm):
            shutil.copy2(input_docm, output_docm)
        return OptionalBlockRemovalSummary(document_path=str(output_docm), requested_labels=[])

    with zipfile.ZipFile(input_docm, "r") as archive:
        document_xml = archive.read(DOCUMENT_XML)

    root = ET.fromstring(document_xml)
    paragraphs = root.findall(".//w:p", NS)

    paragraphs_to_remove: list[ET.Element] = []
    removed_ids: set[int] = set()
    removed_labels: list[str] = []
    skipped_labels: list[str] = []

    for rule in requested_rules:
        label = str(rule["label"])
        removed_this_label = False

        for index, paragraph in enumerate(paragraphs):
            if id(paragraph) in removed_ids:
                continue
            if not _is_label_paragraph(paragraph, label):
                continue

            block = _collect_requested_empty_block(paragraphs, index, rule)
            if not block:
                continue

            for item in block:
                if id(item) not in removed_ids:
                    paragraphs_to_remove.append(item)
                    removed_ids.add(id(item))

            removed_labels.append(label)
            removed_this_label = True
            break

        if not removed_this_label:
            skipped_labels.append(label)

    if not paragraphs_to_remove:
        if not _same_file(input_docm, output_docm):
            shutil.copy2(input_docm, output_docm)
        return OptionalBlockRemovalSummary(
            document_path=str(output_docm),
            requested_labels=requested_labels,
            skipped_labels=skipped_labels or requested_labels,
        )

    removed_paragraphs = _remove_paragraphs(paragraphs_to_remove)
    updated_document_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    write_zip_with_replacement(input_docm, output_docm, {DOCUMENT_XML: updated_document_xml})

    return OptionalBlockRemovalSummary(
        document_path=str(output_docm),
        requested_labels=requested_labels,
        removed_labels=removed_labels,
        skipped_labels=skipped_labels,
        removed_paragraphs=removed_paragraphs,
        changed=removed_paragraphs > 0,
    )


def remove_empty_email_simulation_blocks(
    document_path: Path,
    *,
    missing_labels: Iterable[str] | None = None,
    missing_keys: Iterable[str] | None = None,
    use_local_temp: bool = True,
) -> OptionalBlockRemovalSummary:
    """Delete requested Email simulation blocks only when their value is N/A/empty."""
    if not use_local_temp:
        summary = remove_empty_email_simulation_blocks_in_xml(
            document_path,
            document_path,
            missing_labels=missing_labels,
            missing_keys=missing_keys,
        )
        logger.info(
            "[TCD08] Removed empty email simulation blocks. requested=%s removed=%s skipped=%s paragraphs=%s",
            summary.requested_labels,
            summary.removed_labels,
            summary.skipped_labels,
            summary.removed_paragraphs,
        )
        return summary

    with tempfile.TemporaryDirectory(prefix="puma_word_optional_blocks_") as temp_dir:
        temp_path = Path(temp_dir) / document_path.name
        shutil.copy2(document_path, temp_path)

        output_path = Path(temp_dir) / f"{document_path.stem}_optional_blocks{document_path.suffix}"
        summary = remove_empty_email_simulation_blocks_in_xml(
            temp_path,
            output_path,
            missing_labels=missing_labels,
            missing_keys=missing_keys,
        )

        if not _same_file(output_path, document_path):
            shutil.copy2(output_path, document_path)

    logger.info(
        "[TCD08] Removed empty email simulation blocks. requested=%s removed=%s skipped=%s paragraphs=%s",
        summary.requested_labels,
        summary.removed_labels,
        summary.skipped_labels,
        summary.removed_paragraphs,
    )
    return summary
