from __future__ import annotations

import gc
import logging
from pathlib import Path
from typing import Iterable

from services.word.package import MacroSupportMembers, read_macro_support_members, restore_zip_members


logger = logging.getLogger("uvicorn.error")


try:
    import win32com.client  # type: ignore[reportMissingImports]
except ImportError:  # pragma: no cover - depends on Windows server setup.
    # 没有安装 pywin32 或当前环境不是 Windows Word 环境时，TOC 更新会自动跳过。
    # 服务器正式环境通常需要 Word COM，所以这里不让 import 失败直接影响模块加载。
    win32com = None  # type: ignore[assignment]


def create_word_application():
    """创建一个后台 Word.Application 实例。

    DispatchEx 会启动独立 Word 进程，避免影响用户正在操作的 Word。
    批量处理多个文档时复用这个实例，可以省掉反复启动 Word 的时间。
    """
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    word.AutomationSecurity = 3
    try:
        # 关闭屏幕刷新对后台任务也有帮助，某些 Word 版本可能不支持该属性。
        word.ScreenUpdating = False
    except Exception:
        pass
    return word


def update_document_toc_with_application(
    word,
    docm_path: Path,
    mode: str = "toc_only",
) -> MacroSupportMembers:
    """用已经创建好的 Word.Application 更新单个文档。

    mode:
    - toc_only：快速模式，只更新目录对象。适合当前流程：XML 已经完成删除/改写，
      主要需要目录条目和页码刷新。
    - full：兼容旧逻辑，显式重新分页并更新所有 Fields，然后更新目录。
    """
    preserved_macro_members = read_macro_support_members(docm_path)
    document = None
    try:
        # 参数含义大致是：文件名、确认转换、只读、添加到最近文件等。
        # 这里用可写方式打开，因为后面需要 Save。
        document = word.Documents.Open(str(docm_path), False, False, False)

        if mode == "full":
            document.Repaginate()
            for field in document.Fields:
                field.Update()
        elif mode != "toc_only":
            raise ValueError(f"Unsupported Word TOC update mode: {mode}")

        # TOC.Update 会重建目录条目并刷新页码，比额外遍历所有 Fields 更轻。
        for toc in document.TablesOfContents:
            toc.Update()

        document.Save()
    finally:
        if document is not None:
            try:
                document.Close(False)
            except Exception as exc:
                # Word COM 在某些环境会在 Close 阶段断连，记录并继续，避免影响主流程。
                logger.warning("[TCD08] Failed to close Word document: %s", exc)

    return preserved_macro_members


def update_toc_with_word(docm_path: Path, mode: str = "toc_only") -> None:
    """用 Word COM 打开一个文档并刷新目录。

    保留这个单文档入口，是为了兼容 sections/red_paragraphs/text_rewrite 中的旧调用。
    TCD08 主流程会优先使用 update_tocs_with_word 批量入口。
    """
    if win32com is None:
        return

    word = None
    preserved_macro_members = None
    processing_error: BaseException | None = None
    try:
        word = create_word_application()
        preserved_macro_members = update_document_toc_with_application(word, docm_path, mode=mode)
    except BaseException as exc:
        processing_error = exc
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception as exc:
                logger.warning("[TCD08] Failed to quit Word application: %s", exc)
        gc.collect()

    if preserved_macro_members is not None:
        restore_zip_members(docm_path, preserved_macro_members)

    if processing_error is not None:
        raise processing_error.with_traceback(processing_error.__traceback__)


def update_tocs_with_word(docm_paths: Iterable[Path], mode: str = "toc_only") -> None:
    """批量刷新多个文档的目录，并复用同一个 Word 进程。

    这里的加速点主要有两个：
    1. 多个模板输出时只启动一次 Word。
    2. 默认 toc_only，不再显式 Repaginate + 遍历所有 Fields。
    """
    paths = [Path(path) for path in docm_paths]
    if win32com is None or not paths:
        return

    word = None
    preserved_macro_members_list: list[tuple[Path, MacroSupportMembers]] = []
    processing_error: BaseException | None = None
    try:
        word = create_word_application()
        for docm_path in paths:
            preserved_macro_members = update_document_toc_with_application(word, docm_path, mode=mode)
            preserved_macro_members_list.append((docm_path, preserved_macro_members))
    except BaseException as exc:
        processing_error = exc
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception as exc:
                logger.warning("[TCD08] Failed to quit Word application: %s", exc)
        gc.collect()

    for docm_path, preserved_macro_members in preserved_macro_members_list:
        restore_zip_members(docm_path, preserved_macro_members)

    if processing_error is not None:
        raise processing_error.with_traceback(processing_error.__traceback__)
