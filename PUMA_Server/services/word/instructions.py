from __future__ import annotations

import logging
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree as ET  # type: ignore[reportMissingImports]

from services.word.package import write_zip_with_replacement
from services.word.text_rewrite import paragraph_text_nodes, replace_text_span
from services.word.xml_utils import NS, clean_text, element_text


logger = logging.getLogger("uvicorn.error")


def _same_file(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()

DEFAULT_TEMPLATE_INSTRUCTIONS = [
    "(delete sentences if not applicable)",
    "(delete sentence if not applicable)",
    "(delete chapter if not applicable)",
    "(delete not configured sensor)",
    "（如不需要删除这段）",
    "(如不需要删除这段)",
    "(删掉不需要的sensor)",
    "(如不需要删除这段）",
    "(delete this sentence if this sensor configuration is not applicable)",
    "(adapt sentence if not applicable)",
    "（如不适用修改这段）",
    "(如果标定在越南完成，删除这段)",
    "(delete this paragraph if calibration in Vietnam)",
    "(delete this paragraph if calibration in China)",
    "(如果标定在中国完成，删除这段)",
    "The red text identifies template-text and hints and should be adapted for customer specific report. Not changed text should be color changed (if values and text are applicable) or removed (if not necessary or not applicable) ",
    "The blue text identifies hints for the use of a report in Acquisition-Phase and should be adapted for customer specific reports. Not changed text should be color changed (if values and text are applicable) or removed (if not necessary or not applicable)"
    "(modify chapter if not applicable) ",
    "(如不适用修改该段) "
]

# 这两条长句删除后若只清空文本会留下整页空白，所以按“整段删除”处理。
FULL_PARAGRAPH_TEMPLATE_INSTRUCTIONS = [
    "The red text identifies template-text and hints and should be adapted for customer specific report. Not changed text should be color changed (if values and text are applicable) or removed (if not necessary or not applicable)",
    "The blue text identifies hints for the use of a report in Acquisition-Phase and should be adapted for customer specific reports. Not changed text should be color changed (if values and text are applicable) or removed (if not necessary or not applicable)",
]

INSTRUCTION_SIDE_SPACE_CHARS = " \t\r\n\xa0\u3000"
INSTRUCTION_TRAILING_PUNCT_CHARS = ".\u3002\uff0e,\uff0c\u3001;\uff1b:\uff1a!?\uff01\uff1f"


@dataclass
class InstructionRemovalSummary:
    """记录模板提示语删除结果。"""

    instructions: list[str]
    replacements_applied: int
    changed_paragraphs: int


def instruction_removal_patterns(instructions: list[str]) -> list[re.Pattern[str]]:
    side_spaces = f"[{re.escape(INSTRUCTION_SIDE_SPACE_CHARS)}]*"
    trailing_punct = f"[{re.escape(INSTRUCTION_TRAILING_PUNCT_CHARS)}]"
    return [
        re.compile(
            f"{side_spaces}{re.escape(instruction)}{side_spaces}(?:{trailing_punct}{side_spaces})?"
        )
        for instruction in instructions
        if instruction
    ]


def normalize_instruction_text(text: str) -> str:
    return clean_text(text).strip().lower()


def full_paragraph_instruction_set(instructions: list[str]) -> set[str]:
    full_paragraph_norm = {
        normalize_instruction_text(value) for value in FULL_PARAGRAPH_TEMPLATE_INSTRUCTIONS if value
    }
    return {
        normalize_instruction_text(value)
        for value in instructions
        if value and normalize_instruction_text(value) in full_paragraph_norm
    }


def paragraph_matches_full_instruction(paragraph: ET.Element, full_instruction_set: set[str]) -> bool:
    if not full_instruction_set:
        return False
    paragraph_text = normalize_instruction_text(element_text(paragraph))
    return paragraph_text in full_instruction_set


def remove_instruction_patterns_in_paragraph(
    paragraph: ET.Element,
    patterns: list[re.Pattern[str]],
) -> int:
    applied = 0
    text_nodes = paragraph_text_nodes(paragraph)
    if not text_nodes:
        return applied

    for pattern in patterns:
        search_from = 0
        while True:
            combined_text = "".join(node.text or "" for node in text_nodes)
            match = pattern.search(combined_text, search_from)
            if match is None:
                break

            start, end = match.span()
            replace_text_span(text_nodes, start, end, "")
            applied += 1
            search_from = start

    return applied


def remove_template_instruction_text_in_xml(
    input_docm: Path,
    output_docm: Path,
    instructions: list[str] | None = None,
) -> InstructionRemovalSummary:
    """从正文 document.xml 中删除固定模板提示语。

    这里删除的是固定短语本身，不按黄色高亮判断，避免误删业务正文里的
    黄色强调内容。
    """
    target_instructions = instructions or DEFAULT_TEMPLATE_INSTRUCTIONS
    patterns = instruction_removal_patterns(target_instructions)
    full_instruction_set = full_paragraph_instruction_set(target_instructions)

    with zipfile.ZipFile(input_docm, "r") as archive:
        document_xml = archive.read("word/document.xml")

    root = ET.fromstring(document_xml)
    replacements_applied = 0
    changed_paragraphs = 0
    for paragraph in root.findall(".//w:p", NS):
        if paragraph_matches_full_instruction(paragraph, full_instruction_set):
            parent = paragraph.getparent()
            if parent is not None:
                parent.remove(paragraph)
                replacements_applied += 1
                changed_paragraphs += 1
                continue

        applied = remove_instruction_patterns_in_paragraph(paragraph, patterns)
        if applied:
            replacements_applied += applied
            changed_paragraphs += 1

    if replacements_applied == 0:
        if not _same_file(input_docm, output_docm):
            shutil.copy2(input_docm, output_docm)
    else:
        updated_document_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        write_zip_with_replacement(input_docm, output_docm, {"word/document.xml": updated_document_xml})

    return InstructionRemovalSummary(
        instructions=list(target_instructions),
        replacements_applied=replacements_applied,
        changed_paragraphs=changed_paragraphs,
    )


def remove_template_instruction_text(
    document_path: Path,
    instructions: list[str] | None = None,
    use_local_temp: bool = True,
) -> InstructionRemovalSummary:
    """删除报告正文中残留的模板维护提示语。

    作为固定收尾步骤使用：先完成规则删除和章节删除，再清理这些
    "(delete ... if not applicable)" / "（如不需要删除这段）" 提示。
    """
    if not use_local_temp:
        summary = remove_template_instruction_text_in_xml(
            document_path,
            document_path,
            instructions=instructions,
        )
        logger.info(
            "[TCD08] Removed template instruction text. replacements=%s paragraphs=%s",
            summary.replacements_applied,
            summary.changed_paragraphs,
        )
        return summary

    with tempfile.TemporaryDirectory(prefix="puma_word_instruction_") as temp_dir:
        temp_path = Path(temp_dir) / document_path.name
        shutil.copy2(document_path, temp_path)

        output_path = Path(temp_dir) / f"{document_path.stem}_instructions{document_path.suffix}"
        summary = remove_template_instruction_text_in_xml(
            temp_path,
            output_path,
            instructions=instructions,
        )
        if not _same_file(output_path, document_path):
            shutil.copy2(output_path, document_path)

    logger.info(
        "[TCD08] Removed template instruction text. replacements=%s paragraphs=%s",
        summary.replacements_applied,
        summary.changed_paragraphs,
    )
    return summary
