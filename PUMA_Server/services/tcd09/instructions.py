from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path

from services.word.instructions import remove_template_instruction_text_in_xml

logger = logging.getLogger("uvicorn.error")

# TCD09 模板中用于人工维护传感器条目的提示语。
# 仅维护已在 TCD09 规则中确认的精确文本，避免误删正常业务正文。
TCD09_TEMPLATE_INSTRUCTIONS = [
    "Text highlighted in red indicates default template text and hints and needs to be adapted project specifically. Text that has not been adapted, must be changed from red to black color (if values and text are applicable) or removed (if not necessary or not applicable).",
    "Remark: Include ECU and peripheral sensors. Mind the physical direction indicated by locator pin and connector: Right click on vehicle (embedded object ->open), include sensors and ECU, then save image created. Polarity is no longer needed. ",
    "NEW: Please provide the schematics for RHD (if applicable). LHD and RHD schematics are necessary for the setup and execution of the SDT (sensing direction test).",
    "Remark: Include all internal as well as external sensors for the specific vehicle in the table. Remove empty cells.",
    "(Remove this hint before creating customer version).",
    "[Include CAD images or photographs here that show the mounting position and important surroundings. Please also include the driving direction.]",
    "Remove Documentation of Changes for the template and start a new Documentation for customer specific document."


]

# 当上述提示独占一个 Word 段落时，删除整个段落并清理紧邻的空白残留段落。
TCD09_FULL_PARAGRAPH_INSTRUCTIONS = TCD09_TEMPLATE_INSTRUCTIONS[:]


def remove_tcd09_template_instructions(source: io.BytesIO) -> io.BytesIO:
    """Remove TCD09 template editing prompts from the main Word document XML."""

    source.seek(0)
    content = source.read()
    with tempfile.TemporaryDirectory(prefix="puma_tcd09_instructions_") as temp_root:
        input_path = Path(temp_root) / "input.docx"
        output_path = Path(temp_root) / "output.docx"
        input_path.write_bytes(content)

        summary = remove_template_instruction_text_in_xml(
            input_path,
            output_path,
            instructions=TCD09_TEMPLATE_INSTRUCTIONS,
            full_paragraph_instructions=TCD09_FULL_PARAGRAPH_INSTRUCTIONS,
        )
        logger.info(
            "[TCD09] Removed template instruction text. replacements=%s paragraphs=%s",
            summary.replacements_applied,
            summary.changed_paragraphs,
        )
        return io.BytesIO(output_path.read_bytes())
