from __future__ import annotations

import logging
import shutil
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree as ET  # type: ignore[reportMissingImports]

from services.word.headings import collect_headings, find_section_span
from services.word.package import write_zip_with_replacement
from services.word.red_paragraphs import collect_red_paragraph_groups, parse_red_colors
from services.word.toc import update_toc_with_word
from services.word.xml_utils import NS, clean_text, element_text, local_name, qn


logger = logging.getLogger("uvicorn.error")


def _same_file(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


def normalize_color(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lstrip("#").upper()


def text_node_run_color(text_node: ET.Element) -> str:
    """读取 <w:t> 所属 run 的颜色值（标准化后）。"""
    current: ET.Element | None = text_node
    while current is not None and local_name(current.tag) != "r":
        current = current.getparent()

    if current is None:
        return ""

    color_node = current.find("w:rPr/w:color", NS)
    if color_node is None:
        return ""
    return normalize_color(color_node.get(qn("val")))


def choose_replacement_anchor_index(
    text_nodes: list[ET.Element],
    first_index: int,
    last_index: int,
    preferred_colors: set[str] | None,
) -> int:
    """选择替换文本写入的锚点节点。

    默认写入 first_index；若跨 run 且存在红色 run，则优先把新文本写入红色 run，
    避免替换后文字继承到黑色样式。
    """
    if not preferred_colors:
        return first_index

    normalized_colors = {normalize_color(color) for color in preferred_colors if normalize_color(color)}
    if not normalized_colors:
        return first_index

    for index in range(first_index, last_index + 1):
        if text_node_run_color(text_nodes[index]) in normalized_colors:
            return index

    return first_index


def normalize_loose_text(text: str) -> str:
    """归一化文本：去掉空白和所有标点，便于宽松匹配。"""
    if not text:
        return ""

    return "".join(
        char
        for char in text
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


def build_loose_index_map(text: str) -> tuple[str, list[int]]:
    """构建宽松匹配索引。

    返回：
    - normalized_text: 去掉空白/标点后的文本
    - original_indexes: normalized_text 每个字符在原文本中的索引
    """
    normalized_chars: list[str] = []
    original_indexes: list[int] = []

    for index, char in enumerate(text):
        if char.isspace() or unicodedata.category(char).startswith("P"):
            continue
        normalized_chars.append(char)
        original_indexes.append(index)

    return "".join(normalized_chars), original_indexes


@dataclass
class RedParagraphTextRewriteSummary:
    """记录一次红色段落组内“局部改写”的结果。

    字段含义：
    - section：在哪个章节改写。
    - group_index：改写第几个红色段落组。
    - before_text：改写前这一组的可见文本。
    - after_text：改写后这一组的可见文本。
    - replacements_applied：实际替换成功了几处文本。
    """

    section: str
    group_index: int
    before_text: str
    after_text: str
    replacements_applied: int


def rewrite_red_paragraph_text_batch_in_xml(
    input_docm: Path,
    output_docm: Path,
    plans: list[dict[str, object]],
    red_colors: set[str],
) -> list[RedParagraphTextRewriteSummary]:
    """批量执行红色段落组内的局部文字改写，只读写 document.xml 一次。"""
    if not plans:
        return []

    with zipfile.ZipFile(input_docm, "r") as archive:
        document_xml = archive.read("word/document.xml")

    root = ET.fromstring(document_xml)
    body = root.find("w:body", NS)
    if body is None:
        raise RuntimeError("word/document.xml does not contain w:body")

    summaries: list[RedParagraphTextRewriteSummary] = []
    total_replacements_applied = 0

    for plan in plans:
        section = str(plan.get("section", "")).strip()
        group_index = int(plan.get("group", 0))
        replacements = plan.get("replacements", [])
        typed_replacements: list[tuple[str, str]] = [
            (str(old_text), str(new_text)) for old_text, new_text in replacements  # type: ignore[misc]
        ]

        body_children = list(body)
        headings = collect_headings(body_children)
        _, section_start, section_end = find_section_span(headings, section, len(body_children))
        groups = collect_red_paragraph_groups(body_children, section_start, section_end, red_colors)
        target_group = next((group for group in groups if group.red_index == group_index), None)
        if target_group is None:
            raise RuntimeError(f"Could not find red paragraph group {group_index} in section {section}")

        before_text = target_group.text
        replacements_applied = 0
        for red_paragraph in target_group.paragraphs:
            paragraph = body_children[red_paragraph.body_index]
            replacements_applied += replace_text_in_paragraph(
                paragraph,
                typed_replacements,
                preferred_colors=red_colors,
            )

        after_text = clean_text(
            " ".join(
                element_text(body_children[red_paragraph.body_index])
                for red_paragraph in target_group.paragraphs
            )
        )

        total_replacements_applied += replacements_applied
        summaries.append(
            RedParagraphTextRewriteSummary(
                section=section,
                group_index=group_index,
                before_text=before_text,
                after_text=after_text,
                replacements_applied=replacements_applied,
            )
        )

    if total_replacements_applied == 0:
        if not _same_file(input_docm, output_docm):
            shutil.copy2(input_docm, output_docm)
    else:
        updated_document_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        write_zip_with_replacement(input_docm, output_docm, {"word/document.xml": updated_document_xml})

    return summaries


def paragraph_text_nodes(paragraph: ET.Element) -> list[ET.Element]:
    """返回一个段落里所有真正存放文字的 <w:t> 节点。

    Word 段落结构大致是：
    <w:p>
      <w:r>
        <w:t>文字</w:t>
      </w:r>
    </w:p>

    一个段落可能有很多 run，因此也可能有很多 <w:t>。
    局部改写时必须跨这些节点处理。
    """
    return [node for node in paragraph.iter() if local_name(node.tag) == "t"]


def replace_text_span(
    text_nodes: list[ET.Element],
    start: int,
    end: int,
    replacement: str,
    preferred_colors: set[str] | None = None,
) -> None:
    """替换一段跨文本节点的字符范围。

    难点：
    用户看到的是一句连续的话，但 Word 可能把它拆成多个 <w:t>。

    例子：
    - 第一个 <w:t> 是 "UFS and "
    - 第二个 <w:t> 是 "RCS are used"
    - 视觉上是一句 "UFS and RCS are used"

    如果要替换整句，就必须知道 start/end 落在哪些 <w:t> 里。
    这个函数先建立每个文本节点在“合并字符串”里的区间，再把 replacement 写回对应节点。
    """
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for node in text_nodes:
        text = node.text or ""
        # offsets 记录每个 <w:t> 在合并文本中的起止位置。
        offsets.append((cursor, cursor + len(text)))
        cursor += len(text)

    # 找到替换范围起点所在的文本节点。
    first_index = next(
        index for index, (_, node_end) in enumerate(offsets) if node_end > start
    )
    # 找到替换范围终点所在的文本节点。
    last_index = next(
        index for index, (_, node_end) in enumerate(offsets) if node_end >= end
    )
    first_start, _ = offsets[first_index]
    last_start, _ = offsets[last_index]
    first_text = text_nodes[first_index].text or ""
    last_text = text_nodes[last_index].text or ""
    prefix = first_text[: start - first_start]
    suffix = last_text[end - last_start :]
    anchor_index = choose_replacement_anchor_index(
        text_nodes,
        first_index,
        last_index,
        preferred_colors,
    )

    if first_index == last_index:
        # 替换内容完全落在同一个 <w:t> 里，直接字符串拼接即可。
        text_nodes[first_index].text = prefix + replacement + suffix
        return

    # 替换范围跨多个 <w:t>：
    # - 先清空命中区间。
    # - 第一个节点保留前缀。
    # - 最后一个节点保留后缀。
    # - replacement 写到锚点节点（优先红色 run）。
    for index in range(first_index, last_index + 1):
        text_nodes[index].text = ""

    text_nodes[first_index].text = prefix
    if anchor_index == first_index:
        text_nodes[first_index].text = prefix + replacement
    else:
        text_nodes[anchor_index].text = replacement

    if anchor_index == last_index:
        text_nodes[last_index].text = (text_nodes[last_index].text or "") + suffix
    else:
        text_nodes[last_index].text = suffix


def replace_text_in_paragraph(
    paragraph: ET.Element,
    replacements: list[tuple[str, str]],
    preferred_colors: set[str] | None = None,
) -> int:
    """在一个段落内部执行多个“普通字符串替换”。

    为什么不能直接 paragraph.text.replace：
    Word 的文字散落在多个 <w:t> 节点里，段落本身没有一个可直接写的 text 字段。

    处理方式：
    1. 收集段落所有 <w:t>。
    2. 拼成一个完整字符串用于查找 old_text。
    3. 找到后调用 replace_text_span，把修改写回原 XML 节点。

    返回值：
    - 实际替换了多少处。
    """
    applied = 0
    text_nodes = paragraph_text_nodes(paragraph)
    if not text_nodes:
        return applied

    for old_text, new_text in replacements:
        if not old_text:
            continue

        exact_applied_for_current = 0
        search_from = 0
        while True:
            # 每次替换后重新合并文本，因为前一次替换可能改变长度。
            combined_text = "".join(node.text or "" for node in text_nodes)
            start = combined_text.find(old_text, search_from)
            if start == -1:
                break

            end = start + len(old_text)
            replace_text_span(
                text_nodes,
                start,
                end,
                new_text,
                preferred_colors=preferred_colors,
            )
            applied += 1
            exact_applied_for_current += 1
            search_from = start + len(new_text)

        # 精确匹配未命中时，回退到“忽略空白/标点”的宽松匹配。
        if exact_applied_for_current > 0:
            continue

        normalized_old_text = normalize_loose_text(old_text)
        if not normalized_old_text:
            continue

        loose_search_from = 0
        while True:
            combined_text = "".join(node.text or "" for node in text_nodes)
            normalized_combined, original_indexes = build_loose_index_map(combined_text)

            loose_start = normalized_combined.find(normalized_old_text, loose_search_from)
            if loose_start == -1:
                break

            loose_end = loose_start + len(normalized_old_text)
            original_start = original_indexes[loose_start]
            original_end = original_indexes[loose_end - 1] + 1

            replace_text_span(
                text_nodes,
                original_start,
                original_end,
                new_text,
                preferred_colors=preferred_colors,
            )
            applied += 1

            normalized_new_text = normalize_loose_text(new_text)
            loose_search_from = loose_start + max(len(normalized_new_text), 1)

    return applied


def rewrite_red_paragraph_text_in_xml(
    input_docm: Path,
    output_docm: Path,
    section: str,
    group_index: int,
    replacements: list[tuple[str, str]],
    red_colors: set[str],
) -> RedParagraphTextRewriteSummary:
    """在指定红色段落组内部做局部文字改写。

    和“删除红色段落组”的区别：
    - 删除：把整个段落节点从 document.xml 移除。
    - 改写：保留段落和格式，只替换段落里的某些词/句子。

    当前 3.3 的 UFS/RCS 需求就是用这个函数：
    - 如果只保留 UFS，就把 "UFS and RCS are used" 改成 "UFS is used"。
    - 如果只保留 RCS，就改成 "RCS is used"。
    """
    with zipfile.ZipFile(input_docm, "r") as archive:
        document_xml = archive.read("word/document.xml")

    root = ET.fromstring(document_xml)
    body = root.find("w:body", NS)
    if body is None:
        raise RuntimeError("word/document.xml does not contain w:body")

    body_children = list(body)
    # 先定位章节，再在章节内部定位第几个红色段落组。
    headings = collect_headings(body_children)
    _, section_start, section_end = find_section_span(headings, section, len(body_children))
    groups = collect_red_paragraph_groups(body_children, section_start, section_end, red_colors)
    target_group = next((group for group in groups if group.red_index == group_index), None)
    if target_group is None:
        raise RuntimeError(f"Could not find red paragraph group {group_index} in section {section}")

    before_text = target_group.text
    replacements_applied = 0
    for red_paragraph in target_group.paragraphs:
        # 一个 group 可能包含英文段落和中文段落，所以需要逐段改写。
        paragraph = body_children[red_paragraph.body_index]
        replacements_applied += replace_text_in_paragraph(
            paragraph,
            replacements,
            preferred_colors=red_colors,
        )

    after_text = clean_text(
        " ".join(
            element_text(body_children[red_paragraph.body_index])
            for red_paragraph in target_group.paragraphs
        )
    )

    if replacements_applied == 0:
        # 没有命中任何文本时，不强行写 XML。
        # 直接复制原文件作为 output，保持调用链一致。
        logger.info(
            "[TCD08] No text replacements applied in section %s red group %s. replacements=%s",
            section,
            group_index,
            replacements,
        )
        if not _same_file(input_docm, output_docm):
            shutil.copy2(input_docm, output_docm)
    else:
        updated_document_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        write_zip_with_replacement(input_docm, output_docm, {"word/document.xml": updated_document_xml})

    return RedParagraphTextRewriteSummary(
        section=section,
        group_index=group_index,
        before_text=before_text,
        after_text=after_text,
        replacements_applied=replacements_applied,
    )


def rewrite_red_paragraph_text(
    document_path: Path,
    section: str,
    group_index: int,
    replacements: list[tuple[str, str]],
    red_colors: set[str] | None = None,
    update_toc: bool = True,
    use_local_temp: bool = True,
) -> RedParagraphTextRewriteSummary:
    """对外入口：执行红色段落组内的局部文字改写。

    比 rewrite_red_paragraph_text_in_xml 多做：
    - 复制到本机临时目录，规避网络盘权限问题。
    - 设置默认红色值。
    - 根据 update_toc 决定是否更新目录。
    - 最后把结果复制回原文档路径。
    """
    colors = red_colors or parse_red_colors("FF0000,C00000")

    if not use_local_temp:
        summary = rewrite_red_paragraph_text_in_xml(
            input_docm=document_path,
            output_docm=document_path,
            section=section,
            group_index=group_index,
            replacements=replacements,
            red_colors=colors,
        )
        if update_toc:
            update_toc_with_word(document_path)
        return summary

    with tempfile.TemporaryDirectory(prefix="puma_tcd08_text_", ignore_cleanup_errors=True) as temp_dir:
        temp_root = Path(temp_dir)
        # working_path 是临时工作副本，next_path 是底层 XML 函数写出的中间成品。
        working_path = temp_root / f"working{document_path.suffix}"
        next_path = temp_root / f"red_text_rewritten{document_path.suffix}"
        shutil.copy2(document_path, working_path)
        logger.info("[TCD08] Using local temp directory for red text rewrite: %s", temp_root)

        summary = rewrite_red_paragraph_text_in_xml(
            input_docm=working_path,
            output_docm=next_path,
            section=section,
            group_index=group_index,
            replacements=replacements,
            red_colors=colors,
        )
        next_path.replace(working_path)
        if update_toc:
            update_toc_with_word(working_path)
        if not _same_file(working_path, document_path):
            shutil.copy2(working_path, document_path)

    return summary


def rewrite_red_paragraph_text_batch(
    document_path: Path,
    plans: list[dict[str, object]],
    red_colors: set[str] | None = None,
    update_toc: bool = True,
    use_local_temp: bool = True,
) -> list[RedParagraphTextRewriteSummary]:
    """对外入口：批量执行红色段落组改写，尽量减少 zip 重写次数。"""
    colors = red_colors or parse_red_colors("FF0000,C00000")

    if not plans:
        return []

    if not use_local_temp:
        summaries = rewrite_red_paragraph_text_batch_in_xml(
            input_docm=document_path,
            output_docm=document_path,
            plans=plans,
            red_colors=colors,
        )
        if update_toc:
            update_toc_with_word(document_path)
        return summaries

    with tempfile.TemporaryDirectory(prefix="puma_tcd08_text_", ignore_cleanup_errors=True) as temp_dir:
        temp_root = Path(temp_dir)
        working_path = temp_root / f"working{document_path.suffix}"
        next_path = temp_root / f"red_text_rewritten{document_path.suffix}"
        shutil.copy2(document_path, working_path)
        logger.info("[TCD08] Using local temp directory for batched red text rewrite: %s", temp_root)

        summaries = rewrite_red_paragraph_text_batch_in_xml(
            input_docm=working_path,
            output_docm=next_path,
            plans=plans,
            red_colors=colors,
        )
        next_path.replace(working_path)
        if update_toc:
            update_toc_with_word(working_path)
        if not _same_file(working_path, document_path):
            shutil.copy2(working_path, document_path)

    return summaries
