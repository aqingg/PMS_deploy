from __future__ import annotations

import logging
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree as ET  # type: ignore[reportMissingImports]

from services.word.headings import collect_headings, find_section_span
from services.word.package import write_zip_with_replacement
from services.word.toc import update_toc_with_word
from services.word.xml_utils import NS, clean_text, element_text, local_name, qn


logger = logging.getLogger("uvicorn.error")


def _same_file(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


@dataclass
class RedParagraph:
    """表示某个章节内“含红色文字”的一个段落。

    字段含义：
    - body_index：这个段落在 <w:body> 子节点里的全局位置。
    - section_index：这个段落在当前章节正文里的顺序。
    - text：整段可见文字。
    - red_text：只提取红色 run 后得到的文字。
    """

    body_index: int
    section_index: int
    text: str
    red_text: str


@dataclass
class RedParagraphGroup:
    """表示一个业务意义上的“红色段落组”。

    模板中经常是：
    - 英文红字段落
    - 紧跟一个中文红字段落

    用户在业务上会把这两段看成一组说明。
    所以这里把“英文 + 中文”合并为一个 group。

    JSON 规则里的 delete_groups: [1, 2] 指的就是这里的 red_index。
    """

    red_index: int
    paragraphs: list[RedParagraph]
    text: str
    red_text: str


@dataclass
class RedParagraphDeleteSummary:
    """记录一次红色段落组删除的结果。

    这个对象会返回给 report.py，用于日志和 API response：
    - section：在哪个章节里删。
    - deleted_indexes：实际删掉了哪些红色段落组。
    - deleted_preview：删掉内容的短预览。
    - remaining_red_groups：删除后还剩几个红色段落组。
    """

    section: str
    deleted_indexes: list[int]
    deleted_preview: list[str]
    remaining_red_groups: int


def normalize_color(value: str | None) -> str:
    """统一颜色值格式。

    Word XML 里的颜色可能写成：
    - FF0000
    - #FF0000
    - 小写 ff0000

    为了判断是不是红色，统一去掉 # 并转成大写。
    """
    if not value:
        return ""
    return value.strip().lstrip("#").upper()


def parse_red_colors(value: str) -> set[str]:
    """把配置里的红色列表解析成集合。

    当前默认值是 "FF0000,C00000"。
    因为不同模板或 Word 版本里，红色可能不是完全相同的色值。
    用集合判断可以同时支持多个红色。
    """
    colors = {normalize_color(part) for part in value.split(",")}
    return {color for color in colors if color}


def run_text(run: ET.Element) -> str:
    """读取一个 Word run 里的可见文字。

    Word 中 <w:r> 代表一段拥有相同格式的文字 run。
    一个 run 里面可能有一个或多个 <w:t>。
    这里把它们拼起来，并做空白清洗。
    """
    return clean_text("".join(node.text or "" for node in run.findall(".//w:t", NS)))


def red_text_in_paragraph(paragraph: ET.Element, red_colors: set[str]) -> str:
    """只提取一个段落中“红色字体 run”的文字。

    判断方式：
    - 扫描段落下所有 <w:r>。
    - 读取 run 的 <w:rPr>/<w:color>。
    - 如果颜色在 red_colors 里，就收集这个 run 的文字。

    如果一个段落里只有部分文字是红色，这里只返回红色那部分。
    """
    red_parts: list[str] = []
    for run in paragraph.findall(".//w:r", NS):
        # 字体颜色不是段落属性，而是在每个 run 的 rPr 里。
        color = run.find("w:rPr/w:color", NS)
        if color is None or normalize_color(color.get(qn("val"))) not in red_colors:
            continue

        text = run_text(run)
        if text:
            red_parts.append(text)

    return clean_text(" ".join(red_parts))


def has_cjk_text(text: str) -> bool:
    """判断文本里是否包含中日韩字符。

    这里主要用于判断“下一段是不是中文翻译”。
    如果当前红字段落是英文，下一段含中文，就把两段合成同一个红色段落组。
    """
    return bool(re.search(r"[\u3400-\u9fff]", text))


def collect_red_paragraphs(
    body_children: list[ET.Element],
    section_start: int,
    section_end: int,
    red_colors: set[str],
) -> list[RedParagraph]:
    """在某个章节范围内，收集所有含红字的段落。

    输入的 section_start / section_end 是正文 <w:body> 的节点范围。
    函数只在这个范围内扫描，不会跨到其他章节。

    返回值是按文档顺序排列的 RedParagraph 列表。
    """
    red_paragraphs: list[RedParagraph] = []
    section_index = 0
    for body_index in range(section_start + 1, section_end):
        child = body_children[body_index]
        if local_name(child.tag) != "p":
            # 只处理段落节点，表格等其他节点跳过。
            continue

        text = element_text(child)
        if not text:
            # 空段落没有业务意义，也不会作为红字组。
            continue

        section_index += 1
        red_text = red_text_in_paragraph(child, red_colors)
        if red_text:
            # 只有真正含有红色 run 的段落才加入候选。
            red_paragraphs.append(
                RedParagraph(
                    body_index=body_index,
                    section_index=section_index,
                    text=text,
                    red_text=red_text,
                )
            )

    return red_paragraphs


def collect_red_paragraph_groups(
    body_children: list[ET.Element],
    section_start: int,
    section_end: int,
    red_colors: set[str],
) -> list[RedParagraphGroup]:
    """把红字段落按业务阅读顺序分组。

        分组规则：
        - 默认每个红字段落自己是一组。
        - 如果一个英文红字段落后面紧跟中文红字段落，就把两段合并成一组。
        - 如果模板里只有中文翻译是红字，而英文说明是前一段普通黑字，
            也要把这两段并成同一组，保证删除时中英一起删除。

    这样前端/JSON 只需要说删除第 1、2、3 组，
    不需要关心英文和中文到底是几个 XML 段落。
    """
    red_paragraphs = collect_red_paragraphs(body_children, section_start, section_end, red_colors)
    groups: list[RedParagraphGroup] = []
    index = 0

    while index < len(red_paragraphs):
        paragraph = red_paragraphs[index]
        grouped = [paragraph]

        # 某些模板里只有中文翻译是红字，英文说明段保持黑字，
        # 但业务上这两段仍然应当视为同一组并一起删除。
        if has_cjk_text(paragraph.text) and paragraph.body_index - 1 > section_start:
            previous_body_child = body_children[paragraph.body_index - 1]
            previous_text = ""
            if local_name(previous_body_child.tag) == "p":
                previous_text = element_text(previous_body_child)

            if previous_text and not has_cjk_text(previous_text):
                grouped = [
                    RedParagraph(
                        body_index=paragraph.body_index - 1,
                        section_index=max(paragraph.section_index - 1, 1),
                        text=previous_text,
                        red_text="",
                    ),
                    paragraph,
                ]

        next_index = index + 1
        # 英文段落 + 中文段落，合并成一个业务组。
        if (
            next_index < len(red_paragraphs)
            and not has_cjk_text(paragraph.text)
            and has_cjk_text(red_paragraphs[next_index].text)
        ):
            grouped.append(red_paragraphs[next_index])
            index += 1

        groups.append(
            RedParagraphGroup(
                red_index=len(groups) + 1,
                paragraphs=grouped,
                text=clean_text(" ".join(item.text for item in grouped)),
                red_text=clean_text(" ".join(item.red_text for item in grouped)),
            )
        )
        index += 1

    return groups


def delete_red_paragraph_groups_in_xml(
    input_docm: Path,
    output_docm: Path,
    section: str,
    selected_indexes: list[int],
    red_colors: set[str],
) -> RedParagraphDeleteSummary:
    """从指定章节中删除指定编号的红色段落组。

    这是底层 XML 删除函数：
    1. 读取 document.xml。
    2. 定位章节范围。
    3. 扫描并分组红色段落。
    4. 根据 selected_indexes 删除对应组里的所有段落节点。
    5. 写回新的 document.xml。
    """
    with zipfile.ZipFile(input_docm, "r") as archive:
        document_xml = archive.read("word/document.xml")

    root = ET.fromstring(document_xml)
    body = root.find("w:body", NS)
    if body is None:
        raise RuntimeError("word/document.xml does not contain w:body")

    body_children = list(body)
    # 先找到目标章节范围，避免误删其他章节里的红字。
    headings = collect_headings(body_children)
    _, section_start, section_end = find_section_span(headings, section, len(body_children))

    candidates = collect_red_paragraph_groups(body_children, section_start, section_end, red_colors)
    wanted = set(selected_indexes)
    # selected_indexes 来自 JSON 规则，比如 [1, 2, 3, 4]。
    deleted = [group for group in candidates if group.red_index in wanted]
    if not deleted:
        logger.info(
            "[TCD08] No matching red paragraph groups found in section %s. requested=%s detected=%s",
            section,
            selected_indexes,
            len(candidates),
        )
        if not _same_file(input_docm, output_docm):
            shutil.copy2(input_docm, output_docm)
        return RedParagraphDeleteSummary(section, [], [], len(candidates))

    body_indexes = {
        paragraph.body_index
        for group in deleted
        for paragraph in group.paragraphs
    }
    # 必须倒序删除。
    # 如果正序删除，前面的节点删掉后，后面节点的 index 会变化。
    for body_index in sorted(body_indexes, reverse=True):
        body.remove(body_children[body_index])

    # 删除后重新扫描一次，统计剩余红色段落组数量。
    remaining_children = list(body)
    headings_after = collect_headings(remaining_children)
    _, remaining_start, remaining_end = find_section_span(headings_after, section, len(remaining_children))
    remaining_red_count = len(
        collect_red_paragraph_groups(remaining_children, remaining_start, remaining_end, red_colors)
    )

    updated_document_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    write_zip_with_replacement(input_docm, output_docm, {"word/document.xml": updated_document_xml})
    return RedParagraphDeleteSummary(
        section=section,
        deleted_indexes=[group.red_index for group in deleted],
        deleted_preview=[
            group.text[:160] + "..." if len(group.text) > 160 else group.text
            for group in deleted
        ],
        remaining_red_groups=remaining_red_count,
    )


def delete_red_paragraph_groups_batch_in_xml(
    input_docm: Path,
    output_docm: Path,
    plans: list[dict[str, object]],
    red_colors: set[str],
) -> list[RedParagraphDeleteSummary]:
    """批量删除多个章节的红色段落组，只读写 document.xml 一次。"""
    if not plans:
        return []

    with zipfile.ZipFile(input_docm, "r") as archive:
        document_xml = archive.read("word/document.xml")

    root = ET.fromstring(document_xml)
    body = root.find("w:body", NS)
    if body is None:
        raise RuntimeError("word/document.xml does not contain w:body")

    summaries: list[RedParagraphDeleteSummary] = []
    deleted_any = False

    for plan in plans:
        section = str(plan.get("section", "")).strip()
        selected_indexes = [int(value) for value in plan.get("selected_indexes", [])]  # type: ignore[misc]

        body_children = list(body)
        headings = collect_headings(body_children)
        _, section_start, section_end = find_section_span(headings, section, len(body_children))
        candidates = collect_red_paragraph_groups(body_children, section_start, section_end, red_colors)

        wanted = set(selected_indexes)
        deleted = [group for group in candidates if group.red_index in wanted]
        if not deleted:
            summaries.append(
                RedParagraphDeleteSummary(
                    section=section,
                    deleted_indexes=[],
                    deleted_preview=[],
                    remaining_red_groups=len(candidates),
                )
            )
            continue

        body_indexes = {
            paragraph.body_index
            for group in deleted
            for paragraph in group.paragraphs
        }
        for body_index in sorted(body_indexes, reverse=True):
            body.remove(body_children[body_index])

        deleted_any = True

        remaining_children = list(body)
        headings_after = collect_headings(remaining_children)
        _, remaining_start, remaining_end = find_section_span(headings_after, section, len(remaining_children))
        remaining_red_count = len(
            collect_red_paragraph_groups(remaining_children, remaining_start, remaining_end, red_colors)
        )

        summaries.append(
            RedParagraphDeleteSummary(
                section=section,
                deleted_indexes=[group.red_index for group in deleted],
                deleted_preview=[
                    group.text[:160] + "..." if len(group.text) > 160 else group.text
                    for group in deleted
                ],
                remaining_red_groups=remaining_red_count,
            )
        )

    if deleted_any:
        updated_document_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        write_zip_with_replacement(input_docm, output_docm, {"word/document.xml": updated_document_xml})
    elif not _same_file(input_docm, output_docm):
        shutil.copy2(input_docm, output_docm)

    return summaries


def remove_red_paragraph_groups(
    document_path: Path,
    section: str,
    selected_indexes: list[int],
    red_colors: set[str] | None = None,
    update_toc: bool = True,
    use_local_temp: bool = True,
) -> RedParagraphDeleteSummary:
    """对外入口：删除红色段落组。

    比 delete_red_paragraph_groups_in_xml 多做：
    - 复制到本机临时目录，避免网络盘权限问题。
    - 设置默认红色值。
    - 根据 update_toc 决定是否更新目录。
    - 最后把结果复制回原文档路径。
    """
    colors = red_colors or parse_red_colors("FF0000,C00000")

    if not use_local_temp:
        summary = delete_red_paragraph_groups_in_xml(
            input_docm=document_path,
            output_docm=document_path,
            section=section,
            selected_indexes=selected_indexes,
            red_colors=colors,
        )
        if update_toc:
            update_toc_with_word(document_path)
        return summary

    with tempfile.TemporaryDirectory(prefix="puma_tcd08_red_", ignore_cleanup_errors=True) as temp_dir:
        temp_root = Path(temp_dir)
        # 所有 XML 修改都在 working_path 上进行，原文件只在最后被覆盖。
        working_path = temp_root / f"working{document_path.suffix}"
        next_path = temp_root / f"red_paragraphs_removed{document_path.suffix}"
        shutil.copy2(document_path, working_path)
        logger.info("[TCD08] Using local temp directory for red paragraph removal: %s", temp_root)

        summary = delete_red_paragraph_groups_in_xml(
            input_docm=working_path,
            output_docm=next_path,
            section=section,
            selected_indexes=selected_indexes,
            red_colors=colors,
        )
        next_path.replace(working_path)
        if update_toc:
            update_toc_with_word(working_path)
        if not _same_file(working_path, document_path):
            shutil.copy2(working_path, document_path)

    return summary


def remove_red_paragraph_groups_batch(
    document_path: Path,
    plans: list[dict[str, object]],
    red_colors: set[str] | None = None,
    update_toc: bool = True,
    use_local_temp: bool = True,
) -> list[RedParagraphDeleteSummary]:
    """对外入口：批量删除红色段落组，尽量减少 zip 重写次数。"""
    colors = red_colors or parse_red_colors("FF0000,C00000")

    if not plans:
        return []

    if not use_local_temp:
        summaries = delete_red_paragraph_groups_batch_in_xml(
            input_docm=document_path,
            output_docm=document_path,
            plans=plans,
            red_colors=colors,
        )
        if update_toc:
            update_toc_with_word(document_path)
        return summaries

    with tempfile.TemporaryDirectory(prefix="puma_tcd08_red_", ignore_cleanup_errors=True) as temp_dir:
        temp_root = Path(temp_dir)
        working_path = temp_root / f"working{document_path.suffix}"
        next_path = temp_root / f"red_paragraphs_removed{document_path.suffix}"
        shutil.copy2(document_path, working_path)
        logger.info("[TCD08] Using local temp directory for batched red paragraph removal: %s", temp_root)

        summaries = delete_red_paragraph_groups_batch_in_xml(
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
