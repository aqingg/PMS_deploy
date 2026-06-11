"""Word 文档处理的兼容入口文件。

历史上，章节删除、红字删除、段落内改写、目录更新、宏保护，
全部都写在这个 word_sections.py 文件里，所以文件会非常长、非常难读。

现在真正的实现已经拆到 services.word 目录下：
- headings.py：负责识别 Word 标题和章节范围。
- sections.py：负责删除整个章节。
- red_paragraphs.py：负责扫描/删除红色段落组。
- text_rewrite.py：负责段落内部局部删词/改写。
- instructions.py：负责删除模板里的固定维护提示语。
- colors.py：负责把保留下来的红色字体转成黑色。
- package.py：负责 .docm zip 包写回和宏保护。
- toc.py：负责调用 Word COM 更新目录。
- xml_utils.py：负责 Word XML 的基础工具函数。

为什么还保留这个文件：
report.py 和已有测试脚本已经在使用
from services.word_sections import ...
如果直接删除这个文件，会导致旧代码全部改 import。

所以这里作为“转发层/兼容层”存在：
外部代码仍然从 word_sections.py 导入；
真正代码则放在更小、更容易阅读的小模块里。
"""

# 标题识别相关：
# 这些函数用于把 Word 自动编号标题或手打编号标题识别成 Heading 对象。
from services.word.colors import (
    ColorReplacementSummary,
    replace_font_colors_in_xml,
    replace_red_font_with_black,
)
from services.word.headings import (
    Heading,
    collect_headings,
    find_delete_span,
    find_section_span,
    is_toc_paragraph,
    paragraph_num_level,
    paragraph_style,
    section_level,
)
from services.word.instructions import (
    DEFAULT_TEMPLATE_INSTRUCTIONS,
    InstructionRemovalSummary,
    remove_template_instruction_text,
    remove_template_instruction_text_in_xml,
)
# .docm 包处理和宏保护相关：
# 这些函数负责安全地改写 zip 成员，并保证宏不丢。
from services.word.package import (
    MacroSupportMembers,
    ZipMember,
    clone_zip_info,
    patched_content_types_xml,
    patched_document_relationships_xml,
    read_macro_support_members,
    restore_zip_members,
    write_zip_with_replacement,
)
# 红色段落组相关：
# 这些函数负责找到某章节里的红字，并按“英文+中文”规则分组/删除。
from services.word.red_paragraphs import (
    RedParagraph,
    RedParagraphDeleteSummary,
    RedParagraphGroup,
    collect_red_paragraph_groups,
    collect_red_paragraphs,
    delete_red_paragraph_groups_in_xml,
    delete_red_paragraph_groups_batch_in_xml,
    has_cjk_text,
    normalize_color,
    parse_red_colors,
    red_text_in_paragraph,
    remove_red_paragraph_groups,
    remove_red_paragraph_groups_batch,
    run_text,
)
# 整个章节删除相关：
# 这些函数负责根据章节号删除一整段 XML 范围。
from services.word.sections import (
    SectionDeleteSummary,
    delete_section_in_xml,
    delete_sections_in_xml,
    remove_word_sections,
    renumber_typed_prefixes,
)
# 段落内部局部改写相关：
# 这些函数负责在不删除段落的情况下，只替换段落里的某些词句。
from services.word.text_rewrite import (
    RedParagraphTextRewriteSummary,
    paragraph_text_nodes,
    replace_text_in_paragraph,
    replace_text_span,
    rewrite_red_paragraph_text,
    rewrite_red_paragraph_text_batch,
    rewrite_red_paragraph_text_batch_in_xml,
    rewrite_red_paragraph_text_in_xml,
)
# Word COM 更新目录相关：
# XML 改完后，目录页和字段需要 Word 自己重新计算。
from services.word.toc import update_toc_with_word, update_tocs_with_word
# XML 基础工具：
# 命名空间、文本读取、属性读取等所有模块都会用到。
from services.word.xml_utils import (
    NAMESPACES,
    NS,
    WORD_NS,
    attr_val,
    clean_text,
    element_text,
    local_name,
    qn,
    set_paragraph_text,
)

# __all__ 明确声明这个兼容入口对外暴露哪些名字。
# 这样其他代码使用 from services.word_sections import * 时行为可控。
__all__ = [
    "Heading",
    "MacroSupportMembers",
    "NAMESPACES",
    "NS",
    "ColorReplacementSummary",
    "DEFAULT_TEMPLATE_INSTRUCTIONS",
    "InstructionRemovalSummary",
    "RedParagraph",
    "RedParagraphDeleteSummary",
    "RedParagraphGroup",
    "RedParagraphTextRewriteSummary",
    "SectionDeleteSummary",
    "WORD_NS",
    "ZipMember",
    "attr_val",
    "clean_text",
    "clone_zip_info",
    "collect_headings",
    "collect_red_paragraph_groups",
    "collect_red_paragraphs",
    "delete_red_paragraph_groups_in_xml",
    "delete_red_paragraph_groups_batch_in_xml",
    "delete_section_in_xml",
    "delete_sections_in_xml",
    "element_text",
    "find_delete_span",
    "find_section_span",
    "has_cjk_text",
    "is_toc_paragraph",
    "local_name",
    "normalize_color",
    "paragraph_num_level",
    "paragraph_style",
    "paragraph_text_nodes",
    "parse_red_colors",
    "patched_content_types_xml",
    "patched_document_relationships_xml",
    "qn",
    "read_macro_support_members",
    "red_text_in_paragraph",
    "replace_font_colors_in_xml",
    "replace_red_font_with_black",
    "remove_red_paragraph_groups",
    "remove_red_paragraph_groups_batch",
    "remove_template_instruction_text",
    "remove_template_instruction_text_in_xml",
    "remove_word_sections",
    "renumber_typed_prefixes",
    "replace_text_in_paragraph",
    "replace_text_span",
    "restore_zip_members",
    "rewrite_red_paragraph_text",
    "rewrite_red_paragraph_text_batch",
    "rewrite_red_paragraph_text_batch_in_xml",
    "rewrite_red_paragraph_text_in_xml",
    "run_text",
    "section_level",
    "set_paragraph_text",
    "update_toc_with_word",
    "update_tocs_with_word",
    "write_zip_with_replacement",
]
