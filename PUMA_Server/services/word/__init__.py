"""TCD08 报告 Word 文档处理包。

这个目录是从原来的 services/word_sections.py 拆出来的。
拆分目标是：一个文件只负责一类事情，方便以后查问题、改规则、加功能。

各文件职责：
- xml_utils.py：最底层 XML 工具，处理命名空间、文本读取、段落文字替换。
- headings.py：识别 Word 标题，计算某章节从哪里开始、到哪里结束。
- package.py：把修改后的 document.xml 写回 .docm，并保护宏。
- sections.py：删除整个章节，比如删除 3.4、3.5.1。
- red_paragraphs.py：扫描红色字体段落，并按英文/中文组合成组后删除。
- text_rewrite.py：不删除段落，只在段落内部做局部文字替换。
- instructions.py：删除模板里的固定维护提示语。
- colors.py：把保留下来的红色字体转成黑色正式文本。
- toc.py：调用 Word COM 更新目录、页码和域。

注意：
对外业务代码多数仍然通过 services.word_sections 导入。
这里的 __init__.py 只暴露最常用的几个入口。
"""

# 常用数据结构：标题、删除结果、红字组、宏信息等。
from services.word.headings import Heading
from services.word.colors import ColorReplacementSummary, replace_red_font_with_black
from services.word.instructions import InstructionRemovalSummary, remove_template_instruction_text
from services.word.package import MacroSupportMembers, ZipMember
from services.word.red_paragraphs import (
    RedParagraph,
    RedParagraphDeleteSummary,
    RedParagraphGroup,
    remove_red_paragraph_groups,
)
from services.word.sections import SectionDeleteSummary, remove_word_sections
from services.word.text_rewrite import RedParagraphTextRewriteSummary, rewrite_red_paragraph_text
from services.word.toc import update_toc_with_word, update_tocs_with_word

# 控制 from services.word import * 时可以导出的名字。
# 这里不导出所有底层工具，是为了让包入口保持简洁。
__all__ = [
    "Heading",
    "ColorReplacementSummary",
    "InstructionRemovalSummary",
    "MacroSupportMembers",
    "RedParagraph",
    "RedParagraphDeleteSummary",
    "RedParagraphGroup",
    "RedParagraphTextRewriteSummary",
    "SectionDeleteSummary",
    "ZipMember",
    "remove_red_paragraph_groups",
    "remove_template_instruction_text",
    "remove_word_sections",
    "replace_red_font_with_black",
    "rewrite_red_paragraph_text",
    "update_toc_with_word",
    "update_tocs_with_word",
]
