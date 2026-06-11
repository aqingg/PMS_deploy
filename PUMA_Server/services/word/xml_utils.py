from __future__ import annotations

import re

from lxml import etree as ET  # type: ignore[reportMissingImports]


# Word 文档本质上是一个 zip 包，正文内容在 word/document.xml 里。
# document.xml 不是普通 HTML，而是 WordprocessingML。
# 段落、文字 run、真实文本节点几乎都带有下面这个命名空间。
# 所以这里统一定义 WORD_NS，后面的模块都从这里引用，避免到处手写长字符串。
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": WORD_NS}


# 注册模板文档中可能出现的命名空间。
#
# 为什么要注册：
# 1. lxml 修改 XML 后会重新序列化 document.xml。
# 2. 如果不提前注册命名空间，lxml 可能把原来的 w:、r:、wp: 等前缀改成 ns0、ns1。
# 3. Word 大多数时候也能识别，但为了最大程度保持原模板结构稳定，这里主动注册。
#
# 这些命名空间不一定每个函数都会用到，但它们可能存在于模板的图片、形状、公式、
# 兼容标记、页眉页脚引用里。保留它们可以减少 Word 打开后的“修复文档”风险。
NAMESPACES = {
    "wpc": "http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas",
    "cx": "http://schemas.microsoft.com/office/drawing/2014/chartex",
    "cx1": "http://schemas.microsoft.com/office/drawing/2015/9/8/chartex",
    "cx2": "http://schemas.microsoft.com/office/drawing/2015/10/21/chartex",
    "cx3": "http://schemas.microsoft.com/office/drawing/2016/5/9/chartex",
    "cx4": "http://schemas.microsoft.com/office/drawing/2016/5/10/chartex",
    "cx5": "http://schemas.microsoft.com/office/drawing/2016/5/11/chartex",
    "cx6": "http://schemas.microsoft.com/office/drawing/2016/5/12/chartex",
    "cx7": "http://schemas.microsoft.com/office/drawing/2016/5/13/chartex",
    "cx8": "http://schemas.microsoft.com/office/drawing/2016/5/14/chartex",
    "w": WORD_NS,
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "v": "urn:schemas-microsoft-com:vml",
    "o": "urn:schemas-microsoft-com:office:office",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "wp14": "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "a14": "http://schemas.microsoft.com/office/drawing/2010/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "w10": "urn:schemas-microsoft-com:office:word",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "w15": "http://schemas.microsoft.com/office/word/2012/wordml",
    "w16": "http://schemas.microsoft.com/office/word/2018/wordml",
    "w16cex": "http://schemas.microsoft.com/office/word/2018/wordml/cex",
    "w16cid": "http://schemas.microsoft.com/office/word/2016/wordml/cid",
    "w16du": "http://schemas.microsoft.com/office/word/2023/wordml/word16du",
    "w16sdtdh": "http://schemas.microsoft.com/office/word/2020/wordml/sdtdatahash",
    "w16sdtfl": "http://schemas.microsoft.com/office/word/2024/wordml/sdtformatlock",
    "w16se": "http://schemas.microsoft.com/office/word/2015/wordml/symex",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "wpi": "http://schemas.microsoft.com/office/word/2010/wordprocessingInk",
    "wne": "http://schemas.microsoft.com/office/word/2006/wordml",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
}

for prefix, uri in NAMESPACES.items():
    ET.register_namespace(prefix, uri)


def qn(name: str) -> str:
    """把简短标签名转换成带 Word 命名空间的完整标签名。

    在 lxml 里查找/创建 Word 元素时，不能只写 "p" 或 "t"。
    真正的标签名是 "{命名空间}p" 这种格式。

    例子：
    - qn("p") 代表 Word 段落 <w:p>
    - qn("r") 代表 Word run <w:r>
    - qn("t") 代表真正的文本节点 <w:t>
    """
    return f"{{{WORD_NS}}}{name}"


def local_name(tag: str) -> str:
    """取出 XML 标签的本地名称，也就是去掉命名空间后的名字。

    lxml 读到的标签通常长这样："{http://.../wordprocessingml}p"。
    人眼和业务判断只关心最后的 "p"、"r"、"t"。
    这个函数就是把完整标签简化成可读的本地名称。
    """
    return tag.rsplit("}", 1)[-1]


def clean_text(text: object) -> str:
    """清洗 Word 文本，方便匹配规则和打印日志。

    Word 文本里可能包含：
    - 连续空格
    - 换行
    - 不换行空格 \xa0

    如果直接拿这些文本做字符串匹配，很容易因为空白字符不同而失败。
    所以这里统一压缩成普通空格，并去掉首尾空白。
    """
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text).replace("\xa0", " ")).strip()


def element_text(element: ET.Element) -> str:
    """读取一个 Word XML 元素下面所有“人能看见的文字”。

    重点理解：
    - Word 里一个视觉段落，不一定只有一个文本节点。
    - 一个句子可能被拆成很多 <w:r> run。
    - 每个 run 里面才有真正存文字的 <w:t>。

    所以这个函数会递归扫描整个元素：
    - 遇到 <w:t> 就收集文字
    - 遇到 <w:tab> 就当作制表符
    - 遇到换行标签就当作换行

    最终返回一段适合阅读、匹配、写日志的普通字符串。
    """
    parts: list[str] = []
    for node in element.iter():
        name = local_name(node.tag)
        if name == "t":
            parts.append(node.text or "")
        elif name == "tab":
            parts.append("\t")
        elif name in {"br", "cr"}:
            parts.append("\n")
    return clean_text("".join(parts))


def attr_val(element: ET.Element | None) -> str | None:
    """读取 Word XML 元素上的 w:val 属性。

    很多 Word 配置都不是写在文本里，而是写在属性里：
    - 段落样式：<w:pStyle w:val="TOC1">
    - 编号 id：<w:numId w:val="25">
    - 编号层级：<w:ilvl w:val="0">

    如果元素不存在就返回 None，避免调用方反复写空判断。
    """
    if element is None:
        return None
    return element.get(qn("val"))


def set_paragraph_text(paragraph: ET.Element, text: str) -> None:
    """替换一个段落的可见文字，但不删除段落本身。

    当前主要用于“手打章节号”的重编号：
    比如删除 3.4.1 后，后面的 "3.4.2 xxx" 需要变成 "3.4.1 xxx"。

    处理方式：
    1. 找到段落里所有 <w:t> 文本节点。
    2. 把新文本写入第一个文本节点。
    3. 其他文本节点清空。

    为什么不重建整个段落：
    - 重建段落容易丢样式、缩进、字体、编号信息。
    - 保留原 <w:p> 和 <w:r> 结构更稳。
    - 这里只改章节号文字，格式不是重点。
    """
    text_nodes = [node for node in paragraph.iter() if local_name(node.tag) == "t"]
    if text_nodes:
        text_nodes[0].text = text
        for node in text_nodes[1:]:
            node.text = ""
        return

    run = ET.SubElement(paragraph, qn("r"))
    text_node = ET.SubElement(run, qn("t"))
    text_node.text = text
