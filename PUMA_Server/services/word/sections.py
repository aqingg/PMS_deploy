from __future__ import annotations

import logging
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree as ET  # type: ignore[reportMissingImports]

from services.word.headings import (
    collect_headings,
    find_delete_span,
    is_toc_paragraph,
    paragraph_num_level,
    section_level,
)
from services.word.package import write_zip_with_replacement
from services.word.toc import update_toc_with_word
from services.word.xml_utils import NS, clean_text, element_text, local_name, set_paragraph_text


logger = logging.getLogger("uvicorn.error")


def _same_file(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


@dataclass
class SectionDeleteSummary:
    """记录一次章节删除的结果，方便 API 返回和服务端日志排查。

    字段含义：
    - removed_section：被删除的章节号。
    - deleted_preview：被删除内容的前一小段预览。
    - deleted_xml_nodes：实际删除了多少个 XML 节点。
    - typed_renumbered_paragraphs：有多少个“手打章节号”段落被重编号。
    """

    removed_section: str
    deleted_preview: str
    deleted_xml_nodes: int
    typed_renumbered_paragraphs: int


def renumber_typed_prefixes(
    body_children: list[ET.Element], deleted_section_number: str, start_index: int
) -> int:
    """删除某个章节后，修正后续“手打章节号”的编号。

    为什么需要：
    有些章节标题是 Word 自动编号，删掉前面的章节后 Word 会自动重新编号。
    但有些标题是普通文本，比如 "3.4.2 xxx"。
    这种文本不会自动变，所以要手动把后续编号减 1。

    例子：
    - 删除 3.4.1。
    - 后面的 "3.4.2 xxx" 应该变成 "3.4.1 xxx"。

    返回值：
    - 实际修改了多少个手打编号段落。
    """
    parts = deleted_section_number.split(".")
    if len(parts) < 2:
        # 一级章节没有父级前缀，不处理重编号。
        return 0

    parent_prefix = ".".join(parts[:-1])
    parent_level = len(parts) - 1
    deleted_ordinal = int(parts[-1])
    # 只匹配同一个父章节下、排在被删除章节后面的手打编号。
    pattern = re.compile(rf"^\s*{re.escape(parent_prefix)}\.(\d+)((?:\.\d+)*)\b")
    changed = 0

    for child in body_children[start_index:]:
        # 只处理段落，目录行跳过。
        if local_name(child.tag) != "p" or is_toc_paragraph(child):
            continue

        level = paragraph_num_level(child)
        if level is not None and level <= parent_level:
            # 遇到同级或更高级 Word 自动编号标题，说明已经离开当前父章节范围。
            break

        text = element_text(child)
        explicit_heading = re.match(r"^(\d+(?:\.\d+)*)\b", text)
        if explicit_heading and section_level(explicit_heading.group(1)) <= parent_level:
            # 遇到同级或更高级的手打标题，也停止处理。
            break

        match = pattern.match(text)
        if not match:
            continue

        ordinal = int(match.group(1))
        if ordinal <= deleted_ordinal:
            continue

        old_prefix = f"{parent_prefix}.{ordinal}{match.group(2)}"
        new_prefix = f"{parent_prefix}.{ordinal - 1}{match.group(2)}"
        new_text = re.sub(rf"^\s*{re.escape(old_prefix)}", new_prefix, text, count=1)
        set_paragraph_text(child, new_text)
        changed += 1

    return changed


def delete_section_in_xml(input_docm: Path, output_docm: Path, target_number: str) -> SectionDeleteSummary:
    """删除单个章节，并写出新的 .docm 文件。

    这个函数是底层 XML 操作：
    - 打开 .docm zip 包。
    - 读取 word/document.xml。
    - 找到目标章节所在的 body 节点范围。
    - 从 XML 树里移除这些节点。
    - 把新的 document.xml 写回 zip 包。

    通常生产路径会调用 delete_sections_in_xml，因为它能一次删除多个章节更快。
    """
    with zipfile.ZipFile(input_docm, "r") as archive:
        document_xml = archive.read("word/document.xml")

    root = ET.fromstring(document_xml)
    body = root.find("w:body", NS)
    if body is None:
        raise RuntimeError("word/document.xml does not contain w:body")

    body_children = list(body)
    # 先扫描所有标题，才能知道目标章节从哪里开始、到哪里结束。
    headings = collect_headings(body_children)
    target, delete_start, delete_end = find_delete_span(headings, target_number, len(body_children))

    deleted_nodes = body_children[delete_start:delete_end]
    # 预览文本只用于日志/API 返回，不参与 Word 写回。
    deleted_preview = clean_text(" ".join(element_text(node) for node in deleted_nodes))
    if len(deleted_preview) > 160:
        deleted_preview = deleted_preview[:160] + "..."

    for node in deleted_nodes:
        # 从 XML 树中移除目标范围内的每个节点。
        body.remove(node)

    remaining_children = list(body)
    # 删除后如果存在手打编号标题，需要顺手修正。
    typed_count = renumber_typed_prefixes(remaining_children, target.number, delete_start)

    updated_document_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    write_zip_with_replacement(input_docm, output_docm, {"word/document.xml": updated_document_xml})
    return SectionDeleteSummary(target_number, deleted_preview, len(deleted_nodes), typed_count)


def delete_sections_in_xml(
    input_docm: Path,
    output_docm: Path,
    section_numbers: list[str],
) -> list[SectionDeleteSummary]:
    """一次性删除多个章节，只读写 document.xml 一次。

    性能优化点：
    以前如果每删一个章节就读写一次 .docm，会很慢。
    现在先把 document.xml 读到内存里，然后在内存中连续删除多个章节，
    最后只写回一次 zip 包。

    注意：
    删除顺序必须从后往前。
    如果先删前面的章节，后面章节的编号/位置可能会变化，导致定位不稳定。
    """
    with zipfile.ZipFile(input_docm, "r") as archive:
        document_xml = archive.read("word/document.xml")

    root = ET.fromstring(document_xml)
    body = root.find("w:body", NS)
    if body is None:
        raise RuntimeError("word/document.xml does not contain w:body")

    summaries: list[SectionDeleteSummary] = []
    # 按章节号倒序删除，例如 3.9、3.8、3.7。
    # 这样前面章节的 XML 位置不会因为后面章节删除而被影响。
    ordered_sections = sorted(
        section_numbers,
        key=lambda value: tuple(int(part) for part in value.split(".")),
        reverse=True,
    )

    # 每删一个章节后重新收集 headings。
    # 因为 XML 树已经变了，标题列表也要基于最新正文重新计算。
    for section_number in ordered_sections:
        body_children = list(body)
        headings = collect_headings(body_children)
        target, delete_start, delete_end = find_delete_span(headings, section_number, len(body_children))

        deleted_nodes = body_children[delete_start:delete_end]
        deleted_preview = clean_text(" ".join(element_text(node) for node in deleted_nodes))
        if len(deleted_preview) > 160:
            deleted_preview = deleted_preview[:160] + "..."

        for node in deleted_nodes:
            body.remove(node)

        remaining_children = list(body)
        typed_count = renumber_typed_prefixes(remaining_children, target.number, delete_start)
        summaries.append(SectionDeleteSummary(section_number, deleted_preview, len(deleted_nodes), typed_count))

    updated_document_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    write_zip_with_replacement(input_docm, output_docm, {"word/document.xml": updated_document_xml})
    return summaries


def remove_word_sections(
    document_path: Path,
    section_numbers: list[str],
    update_toc: bool = True,
    use_local_temp: bool = True,
) -> list[SectionDeleteSummary]:
    """对外入口：删除指定章节。

    这个函数比 delete_sections_in_xml 多做三件事：
    1. 把文档先复制到本机临时目录，避免公盘/网络盘 PermissionError。
    2. 调用底层 XML 删除逻辑。
    3. 根据 update_toc 决定是否立刻调用 Word COM 更新目录。

    report.py 里通常传 update_toc=False，
    因为章节删除、红字删除、文字改写完成后，只需要最后统一更新一次目录。
    """
    if not section_numbers:
        return []

    if not use_local_temp:
        summaries = delete_sections_in_xml(document_path, document_path, section_numbers)
        if update_toc:
            update_toc_with_word(document_path)
        return summaries

    with tempfile.TemporaryDirectory(prefix="puma_tcd08_", ignore_cleanup_errors=True) as temp_dir:
        temp_root = Path(temp_dir)
        # working_path 是本机 temp 里的工作副本。
        # next_path 是底层函数写出的中间成品。
        working_path = temp_root / f"working{document_path.suffix}"
        next_path = temp_root / f"sections_removed{document_path.suffix}"
        shutil.copy2(document_path, working_path)
        logger.info("[TCD08] Using local temp directory for section removal: %s", temp_root)

        summaries = delete_sections_in_xml(working_path, next_path, section_numbers)
        # 把中间成品替换成新的工作副本，后续 TOC 更新基于它执行。
        next_path.replace(working_path)

        if update_toc:
            update_toc_with_word(working_path)
        if not _same_file(working_path, document_path):
            shutil.copy2(working_path, document_path)

    return summaries
