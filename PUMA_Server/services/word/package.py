from __future__ import annotations

import os
import logging
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree as ET  # type: ignore[reportMissingImports]


logger = logging.getLogger("uvicorn.error")


def _unlink_with_retry(path: Path, *, raise_on_final_error: bool = False) -> None:
    """Best-effort file deletion with retry for transient Windows/DFS locks.

    Why this exists:
    - On Windows network shares, antivirus/indexing/SMB delays can keep a just-used
      temp file locked for a short period.
    - Cleanup failures must not hide the real upstream exception unless explicitly requested.
    """
    retry_delays = [0.1, 0.2, 0.4, 0.8, 1.2]
    max_attempts = len(retry_delays) + 1

    for attempt in range(1, max_attempts + 1):
        try:
            path.unlink(missing_ok=True)
            return
        except FileNotFoundError:
            return
        except (PermissionError, OSError) as exc:
            winerror = getattr(exc, "winerror", None)
            is_lock_error = isinstance(exc, PermissionError) or winerror in {5, 32}
            if (not is_lock_error) or attempt == max_attempts:
                if raise_on_final_error:
                    raise
                logger.warning(
                    "[TCD08] Temp cleanup skipped after %d attempts for %s: %s",
                    attempt,
                    path,
                    exc,
                )
                return
            time.sleep(retry_delays[attempt - 1])


def _replace_with_retry(source: Path, target: Path) -> None:
    """Replace target with source and retry on transient file locks.

    Uses os.replace for atomic same-filesystem replacement.
    """
    retry_delays = [0.1, 0.2, 0.4, 0.8, 1.2]
    max_attempts = len(retry_delays) + 1

    for attempt in range(1, max_attempts + 1):
        try:
            os.replace(source, target)
            return
        except (PermissionError, OSError) as exc:
            winerror = getattr(exc, "winerror", None)
            is_lock_error = isinstance(exc, PermissionError) or winerror in {5, 32}
            if (not is_lock_error) or attempt == max_attempts:
                raise
            logger.warning(
                "[TCD08] Zip replace retry %d/%d due to file lock: %s",
                attempt,
                max_attempts,
                exc,
            )
            time.sleep(retry_delays[attempt - 1])


# .docx/.docm 文件本质是 zip 包。
# ZipMember 表示 zip 包里的一个成员：
# - ZipInfo：文件名、压缩方式、时间戳等元信息。
# - bytes：这个成员真实的二进制内容。
ZipMember = tuple[zipfile.ZipInfo, bytes]


@dataclass
class MacroSupportMembers:
    """保存 .docm 里“宏相关”的 zip 成员和关系信息。

    背景：
    .docm 是带宏的 Word 文件，本质仍然是 zip 包。
    宏不只是一份 word/vbaProject.bin，还需要：
    - [Content_Types].xml 里的宏类型声明。
    - word/_rels/document.xml.rels 里的宏关系。

    Word COM 保存文件时，可能会清理或改变这些包成员。
    所以更新目录前先保存这些宏相关信息，更新后再合并回去。
    """

    parts: dict[str, ZipMember]
    content_type_overrides: dict[str, str]
    document_relationships: list[dict[str, str]]


def clone_zip_info(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    """复制 zip 成员的元信息。

    只复制文件内容还不够，zip 里的每个成员还有：
    - 文件名
    - 修改时间
    - 压缩方式
    - 外部属性
    - comment / extra 等信息

    重写 .docm 时尽量保留这些元信息，可以降低 Word 认为文档结构异常的概率。
    """
    cloned = zipfile.ZipInfo(info.filename, info.date_time)
    cloned.compress_type = info.compress_type
    cloned.comment = info.comment
    cloned.extra = info.extra
    cloned.internal_attr = info.internal_attr
    cloned.external_attr = info.external_attr
    cloned.create_system = info.create_system
    return cloned


def write_zip_with_replacement(source: Path, output: Path, replacements: dict[str, bytes]) -> None:
    """重写 Word zip 包，同时替换指定成员。

    最常见的用途：
    - 读出原始 .docm。
    - 修改 word/document.xml。
    - 把新的 document.xml 放回 zip 包。
    - 其他成员原样复制。

    这样可以做到“只动正文 XML，不碰宏、图片、页眉页脚、样式等其他部分”。

    参数说明：
    - source：原文档路径。
    - output：写出的新文档路径。
    - replacements：要替换的 zip 成员，key 通常是 "word/document.xml"。
    """
    with zipfile.ZipFile(source, "r") as zin:
        # 先一次性读出所有成员，后面写新 zip 时逐个复制。
        infos = zin.infolist()
        original = {info.filename: zin.read(info.filename) for info in infos}
        source_has_vba = "word/vbaProject.bin" in original

    # 在 output 所在目录创建临时文件。
    # 注意：上层 wrapper 已经把文档复制到本地 temp，所以这里通常不是公盘路径。
    fd, temp_name = tempfile.mkstemp(suffix=output.suffix, dir=str(output.parent))
    os.close(fd)
    _unlink_with_retry(Path(temp_name), raise_on_final_error=True)

    try:
        with zipfile.ZipFile(temp_name, "w") as zout:
            for info in infos:
                # 如果 replacements 指定了这个成员，就写新内容。
                # 否则就写回原始内容。
                data = replacements.get(info.filename, original[info.filename])
                zout.writestr(clone_zip_info(info), data)

        with zipfile.ZipFile(temp_name, "r") as test_zip:
            # testzip 会检查 zip 成员 CRC，能提前发现写坏的包。
            bad_member = test_zip.testzip()
            if bad_member:
                raise RuntimeError(f"Bad zip member after writing: {bad_member}")
            # 如果输入本来是带宏 .docm，输出也必须继续有 vbaProject.bin。
            # 这是最基本的宏完整性保护。
            if (
                output.suffix.lower() == ".docm"
                and source_has_vba
                and "word/vbaProject.bin" not in test_zip.namelist()
            ):
                raise RuntimeError("Macro project missing after writing.")

        _replace_with_retry(Path(temp_name), output)
    finally:
        # 正常情况下 temp_name 已经被 move 走。
        # 如果中途异常，finally 会尽量清理临时文件。
        # 注意：清理失败不能覆盖主异常，否则会丢失真实故障点。
        _unlink_with_retry(Path(temp_name), raise_on_final_error=False)


def read_macro_support_members(package_path: Path) -> MacroSupportMembers:
    """在 Word COM 更新目录前，读取并保存宏相关包成员。

    为什么只保存“宏相关”：
    之前如果把旧的 [Content_Types].xml 和 document.xml.rels 整体覆盖回去，
    Word 可能已经删除了无用页眉/页脚关系，再覆盖旧关系会造成坏引用，
    最终打开文档时提示“无法读取内容”。

    所以这里不保存全部关系，只保存 vba 相关部分：
    - 所有文件名中包含 vba 的 zip 成员。
    - [Content_Types].xml 中指向 vba 成员的 Override。
    - document.xml.rels 中指向 vba 的 Relationship。
    """
    with zipfile.ZipFile(package_path, "r") as archive:
        infos = archive.infolist()
        names = {info.filename for info in infos}
        if "word/vbaProject.bin" not in names:
            # 普通 docx 或没有宏的 docm，不需要做宏恢复。
            return MacroSupportMembers({}, {}, [])

        # 不只保存 word/vbaProject.bin，也保存其他名字里包含 vba 的辅助成员。
        vba_part_names = {name for name in names if "vba" in name.lower()}
        parts = {
            info.filename: (clone_zip_info(info), archive.read(info.filename))
            for info in infos
            if info.filename in vba_part_names
        }

        content_type_overrides: dict[str, str] = {}
        content_types_root = ET.fromstring(archive.read("[Content_Types].xml"))
        content_types_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
        for override in content_types_root.findall(f"{{{content_types_ns}}}Override"):
            # Content Types 负责告诉 Word：某个 Part 是 VBA 项目。
            part_name = override.get("PartName", "")
            content_type = override.get("ContentType", "")
            if part_name.lstrip("/") in vba_part_names and content_type:
                content_type_overrides[part_name] = content_type

        document_relationships: list[dict[str, str]] = []
        relationships_root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        relationships_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        for relationship in relationships_root.findall(f"{{{relationships_ns}}}Relationship"):
            # Relationship 负责告诉 Word：主文档和 VBA 项目之间有关系。
            rel_type = relationship.get("Type", "")
            target = relationship.get("Target", "")
            if "vba" in rel_type.lower() or "vba" in target.lower():
                document_relationships.append(dict(relationship.attrib))

        return MacroSupportMembers(parts, content_type_overrides, document_relationships)


def patched_content_types_xml(content_types_xml: bytes, macro_members: MacroSupportMembers) -> bytes:
    """把缺失的 VBA ContentType 声明合并回 [Content_Types].xml。

    注意是“合并”，不是“覆盖”：
    - 覆盖会把 Word 保存时产生的合法变化回滚掉。
    - 合并只补回宏需要的声明，更安全。
    """
    content_types_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    root = ET.fromstring(content_types_xml)
    existing = {
        override.get("PartName")
        for override in root.findall(f"{{{content_types_ns}}}Override")
    }
    for part_name, content_type in macro_members.content_type_overrides.items():
        if part_name in existing:
            continue
        # Word 保存后如果 VBA Override 丢了，这里补回来。
        override = ET.SubElement(root, f"{{{content_types_ns}}}Override")
        override.set("PartName", part_name)
        override.set("ContentType", content_type)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def patched_document_relationships_xml(
    relationships_xml: bytes,
    macro_members: MacroSupportMembers,
) -> bytes:
    """把缺失的 VBA Relationship 合并回 document.xml.rels。

    这里专门避免恢复非 VBA 关系。
    因为 Word 更新目录/保存文件时，可能会清理无用的页眉页脚、图片或其他关系。
    如果把旧 rels 整体覆盖回去，就可能引用已经不存在的文件，导致文档损坏。
    """
    relationships_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    root = ET.fromstring(relationships_xml)
    relationships = root.findall(f"{{{relationships_ns}}}Relationship")
    existing_targets = {
        relationship.get("Target", "")
        for relationship in relationships
    }
    used_ids = {
        relationship.get("Id", "")
        for relationship in relationships
    }

    for preserved_relationship in macro_members.document_relationships:
        target = preserved_relationship.get("Target", "")
        if not target or target in existing_targets:
            continue

        # 只有目标不存在时才新增，避免重复关系。
        relationship = ET.SubElement(root, f"{{{relationships_ns}}}Relationship")
        for key, value in preserved_relationship.items():
            relationship.set(key, value)

        rel_id = relationship.get("Id", "")
        if rel_id in used_ids:
            # 如果原来的 rId 已经被 Word 用掉，就生成一个新的 rId。
            next_index = 1
            while f"rId{next_index}" in used_ids:
                next_index += 1
            relationship.set("Id", f"rId{next_index}")
        used_ids.add(relationship.get("Id", ""))
        existing_targets.add(target)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def restore_zip_members(package_path: Path, preserved_members: MacroSupportMembers) -> None:
    """Word COM 保存后，把前面保存的宏相关内容合并回文档。

    这个函数的目标不是“恢复整个旧文档包”，而是：
    - 保留 Word COM 更新目录后的合法结果。
    - 只补回宏需要的文件、ContentType 和 Relationship。

    这样既能更新目录，又能避免 .docm 宏丢失。
    """
    if not preserved_members.parts:
        return

    with zipfile.ZipFile(package_path, "r") as zin:
        # 读取 Word 保存后的当前包结构。
        current_infos = zin.infolist()
        current = {info.filename: zin.read(info.filename) for info in current_infos}

    if "[Content_Types].xml" in current:
        # 合并 VBA ContentType，不能用旧 XML 整体覆盖。
        current["[Content_Types].xml"] = patched_content_types_xml(
            current["[Content_Types].xml"],
            preserved_members,
        )
    if "word/_rels/document.xml.rels" in current:
        # 合并 VBA Relationship，不能恢复旧的非 VBA 关系。
        current["word/_rels/document.xml.rels"] = patched_document_relationships_xml(
            current["word/_rels/document.xml.rels"],
            preserved_members,
        )

    # 先在本机临时目录构建恢复后的包。
    # 这样可以减少公盘/网络盘上的临时文件权限问题。
    # 最后只把成品 copy 回目标路径。
    with tempfile.TemporaryDirectory(prefix="puma_tcd08_macro_", ignore_cleanup_errors=True) as temp_dir:
        temp_path = Path(temp_dir) / f"macro_restored{package_path.suffix}"
        written_names: set[str] = set()
        with zipfile.ZipFile(temp_path, "w") as zout:
            for info in current_infos:
                if info.filename in preserved_members.parts:
                    # 如果这个成员是 VBA 相关成员，用之前保存的版本。
                    preserved_info, data = preserved_members.parts[info.filename]
                    zout.writestr(clone_zip_info(preserved_info), data)
                else:
                    # 其他成员保留 Word COM 保存后的版本。
                    zout.writestr(clone_zip_info(info), current[info.filename])
                written_names.add(info.filename)

            for name, (info, data) in preserved_members.parts.items():
                if name not in written_names:
                    # 如果 Word 保存后直接删掉了某个 VBA 成员，这里重新补进去。
                    zout.writestr(clone_zip_info(info), data)

        with zipfile.ZipFile(temp_path, "r") as test_zip:
            # 最后再检查一次 zip 完整性和宏存在性。
            bad_member = test_zip.testzip()
            if bad_member:
                raise RuntimeError(f"Bad zip member after restoring macro parts: {bad_member}")
            if "word/vbaProject.bin" in preserved_members.parts and "word/vbaProject.bin" not in test_zip.namelist():
                raise RuntimeError("Macro project missing after Word TOC update.")

        retry_delays = [0.1, 0.2, 0.4, 0.8, 1.2]
        max_attempts = len(retry_delays) + 1
        for attempt in range(1, max_attempts + 1):
            try:
                shutil.copy2(temp_path, package_path)
                break
            except (PermissionError, OSError) as exc:
                winerror = getattr(exc, "winerror", None)
                is_lock_error = isinstance(exc, PermissionError) or winerror == 32
                if (not is_lock_error) or attempt == max_attempts:
                    raise
                logger.warning(
                    "[TCD08] Macro restore copy retry %d/%d due to file lock: %s",
                    attempt,
                    max_attempts,
                    exc,
                )
                time.sleep(retry_delays[attempt - 1])
