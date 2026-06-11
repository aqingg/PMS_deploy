from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree as ET  # type: ignore[reportMissingImports]

from services.word.xml_utils import NS, attr_val, element_text, local_name


@dataclass
class Heading:
    """表示从 word/document.xml 里识别出来的一个章节标题。

    字段含义：
    - index：这个标题在 <w:body> 子节点列表中的位置。
    - number：章节号，比如 "3.2.1"。
    - level：章节层级，比如 3.2.1 是 3 层。
    - text：标题段落的可见文本。
    - typed：是否是“手打章节号”识别出来的标题。

    注意：
    Word 里的标题不一定都把 "3.2.1" 写在文本里。
    有些标题是 Word 自动编号，需要从编号属性推算章节号。
    """

    index: int
    number: str
    level: int
    text: str
    typed: bool


def paragraph_style(paragraph: ET.Element) -> str:
    """读取段落样式 id。

    例子：
    - 目录里的段落通常是 TOC1、TOC2。
    - 普通正文/标题则可能是其他样式。

    这个函数主要用于判断一段是不是目录行。
    删除章节时不能把目录里的“3.2 标题文字”误认为正文标题。
    """
    ppr = paragraph.find("w:pPr", NS)
    if ppr is None:
        return ""
    return attr_val(ppr.find("w:pStyle", NS)) or ""


def paragraph_num_level(paragraph: ET.Element) -> int | None:
    """识别 Word 自动编号标题的层级。

    模板里的很多章节标题不是手打 "3.2"，而是 Word 自动编号。
    自动编号信息藏在段落属性 <w:pPr>/<w:numPr> 下面：
    - w:numId 表示使用哪一套编号规则。
    - w:ilvl 表示当前编号层级。

    当前模板的章节编号使用 numId == "25"。
    对应关系：
    - ilvl=0 表示一级标题
    - ilvl=1 表示二级标题
    - ilvl=2 表示三级标题

    如果不是模板章节编号，就返回 None。
    """
    ppr = paragraph.find("w:pPr", NS)
    if ppr is None:
        return None
    num_pr = ppr.find("w:numPr", NS)
    if num_pr is None:
        return None
    num_id = attr_val(num_pr.find("w:numId", NS))
    ilvl = attr_val(num_pr.find("w:ilvl", NS))
    if num_id != "25" or ilvl is None:
        return None
    return int(ilvl) + 1


def section_level(number: str) -> int:
    """根据章节号里的点号数量，计算章节层级。

    例子：
    - "3" 是 1 级
    - "3.2" 是 2 级
    - "3.2.1" 是 3 级
    """
    return len(number.split(".")) if number else 0


def is_toc_paragraph(paragraph: ET.Element) -> bool:
    """判断一个段落是不是目录里的段落。

    为什么要跳过目录：
    目录中也会出现 "3.2 xxx" 这样的文字。
    但它不是正文标题，只是目录项。
    如果不跳过，后续删除章节时会定位到错误位置。
    """
    return paragraph_style(paragraph).startswith("TOC")


def collect_headings(body_children: list[ET.Element]) -> list[Heading]:
    """扫描正文 XML，收集所有真实章节标题。

    这是章节删除功能的基础函数。
    它会从 <w:body> 的所有子节点中找出标题段落，并按文档顺序返回。

    支持两种标题：
    1. Word 自动编号标题：
       文本里可能没有 "3.2"，但 XML 编号属性里能推算出来。
    2. 手打编号标题：
       段落文字直接以 "3.3"、"3.7.1" 开头。

    返回的 Heading.index 非常关键：
    后面删除章节时，就是通过 index 判断从哪个 XML 节点删到哪个 XML 节点。
    """
    counters: list[int] = [0] * 9
    headings: list[Heading] = []

    for index, child in enumerate(body_children):
        if local_name(child.tag) != "p" or is_toc_paragraph(child):
            continue

        text = element_text(child)
        level = paragraph_num_level(child)
        if level is not None:
            counters[level - 1] += 1
            for reset_index in range(level, len(counters)):
                counters[reset_index] = 0

            number = ".".join(str(value) for value in counters[:level] if value > 0)
            headings.append(Heading(index=index, number=number, level=level, text=text, typed=False))
            continue

        # 有些模板标题不是 Word 自动编号，而是直接把章节号打在文本里。
        # 例如 "3.3 Rear algorithm"。
        # 这种情况用正则从段落开头提取章节号。
        match = re.match(r"^(\d+(?:\.\d+)*)\s+(?=[A-Z\u3400-\u9fff])", text)
        if match:
            number = match.group(1)
            headings.append(
                Heading(index=index, number=number, level=section_level(number), text=text, typed=True)
            )

    return headings


def find_delete_span(headings: list[Heading], target_number: str, body_len: int) -> tuple[Heading, int, int]:
    """根据章节号，找到这一节在 <w:body> 中占用的 XML 范围。

    删除章节的核心规则：
    - 从目标标题开始删。
    - 一直删到下一个“同级或更高级”的标题之前。

    例子：
    删除 3.2：
    - 会包含 3.2 标题本身。
    - 会包含 3.2.1、3.2.2 这些子章节。
    - 会在遇到 3.3 时停止，因为 3.3 和 3.2 同级。

    返回值：
    - target：目标标题对象。
    - start：删除起始 body index。
    - end：删除结束 body index，Python 切片语义，不包含 end 本身。
    """
    target = next((heading for heading in headings if heading.number == target_number), None)
    if target is None:
        raise RuntimeError(f"Could not find section heading {target_number}")

    delete_end = body_len
    for heading in headings:
        if heading.index <= target.index:
            continue
        if heading.level <= target.level:
            delete_end = heading.index
            break

    return target, target.index, delete_end


def find_section_span(headings: list[Heading], target_number: str, body_len: int) -> tuple[Heading, int, int]:
    """查找章节范围，但语义上用于“扫描章节”而不是“删除章节”。

    红色段落删除、段落内文字改写，都需要先定位某个章节范围。
    它们不会删除整个章节，只是在这个范围里继续找红字。
    所以保留这个别名，让调用方读起来更直观。
    """
    return find_delete_span(headings, target_number, body_len)
