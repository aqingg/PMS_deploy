from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional
import logging
import re
import tempfile
import zipfile
from contextlib import suppress

from email.utils import parsedate_to_datetime

import extract_msg


logger = logging.getLogger(__name__)


def _attachment_name(attachment) -> str:
    return (
        (getattr(attachment, "longFilename", None) or "").strip()
        or (getattr(attachment, "shortFilename", None) or "").strip()
        or (getattr(attachment, "filename", None) or "").strip()
    )


def _find_zip_attachment(msg: extract_msg.Message):
    for attachment in msg.attachments:
        filename = _attachment_name(attachment)
        if filename.lower().endswith(".zip"):
            return attachment, filename
    return None, None


def _save_zip_attachment_to_temp(attachment) -> Optional[Path]:
    if attachment is None:
        return None

    with tempfile.TemporaryDirectory() as temp_dir:
        _, saved_path = attachment.save(customPath=temp_dir)
        # Copy the extracted zip to a stable temp file because the temporary
        # directory is removed when this helper exits.
        source_path = Path(saved_path)
        if not source_path.exists():
            return None

        with tempfile.NamedTemporaryFile(delete=False, suffix=source_path.suffix) as temp_file:
            target_path = Path(temp_file.name)
            with source_path.open("rb") as source_file:
                temp_file.write(source_file.read())
        return target_path


def _normalize_zip_entry_name(entry_name: str) -> str:
    return Path(entry_name).name


def _classify_excel_files(excel_names: list[str]) -> dict[str, list[str]]:
    standard_files: list[str] = []
    defect_files: list[str] = []
    specific_files: list[str] = []

    for name in excel_names:
        base_name = _normalize_zip_entry_name(name)
        lower_name = base_name.lower()
        if lower_name.startswith("~$"):
            continue
        if any(token in lower_name for token in ("pps", "idf", "idp")):
            specific_files.append(base_name)
        elif any(token in lower_name for token in ("df", "def")):
            defect_files.append(base_name)
        else:
            standard_files.append(base_name)

    standard_files.sort()
    defect_files.sort()
    specific_files.sort()
    return {
        "standard_xlsx_files": standard_files,
        "defect_xlsx_files": defect_files,
        "specific_xlsx_files": specific_files,
        "standard_xlsx_count": len(standard_files),
        "defect_xlsx_count": len(defect_files),
        "specific_xlsx_count": len(specific_files),
    }


def _extract_zip_xlsx_groups_from_msg(msg: extract_msg.Message) -> dict[str, object]:
    zip_attachment, zip_attachment_name = _find_zip_attachment(msg)
    if zip_attachment is None:
        return {
            "zip_name": "N/A",
            "all_zip_entries": [],
            "excel_entries": [],
            "xlsx_entries": [],
            **_classify_excel_files([]),
        }

    saved_zip_path = _save_zip_attachment_to_temp(zip_attachment)
    if saved_zip_path is None or not saved_zip_path.exists():
        return {
            "zip_name": zip_attachment_name or "N/A",
            "all_zip_entries": [],
            "excel_entries": [],
            "xlsx_entries": [],
            **_classify_excel_files([]),
        }

    try:
        with zipfile.ZipFile(saved_zip_path, "r") as archive:
            all_entries = archive.namelist()
    except zipfile.BadZipFile:
        all_entries = []
    finally:
        with suppress(Exception):
            saved_zip_path.unlink(missing_ok=True)

    excel_entries = [
        name
        for name in all_entries
        if name.lower().endswith((".xlsx", ".xls", ".xlsm"))
        and not _normalize_zip_entry_name(name).lower().startswith("~$")
    ]
    xlsx_entries = [name for name in excel_entries if name.lower().endswith(".xlsx")]
    groups = _classify_excel_files(excel_entries)
    return {
        "zip_name": zip_attachment_name or "N/A",
        "all_zip_entries": all_entries,
        "excel_entries": excel_entries,
        "xlsx_entries": xlsx_entries,
        **groups,
    }


def _format_date(raw_date) -> str:
    if not raw_date:
        return "N/A"
    try:
        if isinstance(raw_date, str):
            dt = parsedate_to_datetime(raw_date)
        else:
            dt = raw_date
        # Some parsedate_to_datetime results are naive or aware; format date only
        return dt.strftime("%Y.%m.%d")
    except Exception:
        try:
            return str(raw_date)
        except Exception:
            return "N/A"


def parse_msg_summary(msg_path: Path) -> Dict[str, Optional[str]]:
    msg = extract_msg.Message(str(msg_path))
    try:
        sender = (getattr(msg, "sender", None) or "").strip()
        sent_date_raw = getattr(msg, "date", None)
        sent_date = _format_date(sent_date_raw)
        attachments = [_attachment_name(att) for att in msg.attachments]
        attachments = [name for name in attachments if name]
        zip_info = _extract_zip_xlsx_groups_from_msg(msg)
        return {
            "file": msg_path.name,
            "sender": sender or "N/A",
            "sent_date": sent_date or "N/A",
            "sent_date_raw": str(sent_date_raw) if sent_date_raw is not None else "",
            "attachments": attachments,
            "zip": zip_info.get("zip_name", "N/A"),
            "all_zip_entries": zip_info.get("all_zip_entries", []),
            "excel_entries": zip_info.get("excel_entries", []),
            "xlsx_entries": zip_info.get("xlsx_entries", []),
            "standard_xlsx_files": zip_info.get("standard_xlsx_files", []),
            "defect_xlsx_files": zip_info.get("defect_xlsx_files", []),
            "specific_xlsx_files": zip_info.get("specific_xlsx_files", []),
            "standard_xlsx_count": zip_info.get("standard_xlsx_count", 0),
            "defect_xlsx_count": zip_info.get("defect_xlsx_count", 0),
            "specific_xlsx_count": zip_info.get("specific_xlsx_count", 0),
        }
    finally:
        msg.close()


def _count_reply_markers(subject: str) -> int:
    text = (subject or "").strip()
    if not text:
        return 0
    chinese_count = text.count("答复")
    english_count = len(re.findall(r"\bapproval\b", text, flags=re.IGNORECASE))
    return chinese_count + english_count


def _subject_reply_marker_count(msg_path: Path) -> Optional[int]:
    msg = extract_msg.Message(str(msg_path))
    try:
        subject = (getattr(msg, "subject", None) or "").strip()
        return _count_reply_markers(subject)
    except Exception:
        logger.exception("Failed to read subject for msg: %s", msg_path)
        return None
    finally:
        with suppress(Exception):
            msg.close()


def _fallback_choose_by_filename(msg_files: list[Path]) -> tuple[Optional[Path], Optional[Path]]:
    send = None
    approval = None
    lower_names = [(p, p.name.lower()) for p in msg_files]
    for p, name in lower_names:
        if "send" in name:
            send = p
        if any(k in name for k in ("approval", "appoval", "approve", "reply", "response", "ack")):
            approval = p

    if not send or not approval:
        if len(msg_files) == 2:
            p0, p1 = msg_files[0], msg_files[1]
            n0, n1 = p0.name.lower(), p1.name.lower()
            if any(k in n0 for k in ("approval", "appoval", "reply", "response", "ack")) and "send" in n1:
                approval, send = p0, p1
            elif any(k in n1 for k in ("approval", "appoval", "reply", "response", "ack")) and "send" in n0:
                approval, send = p1, p0
            else:
                send, approval = p0, p1

    return send, approval


def _choose_send_and_approval(msg_files: list[Path]) -> tuple[Optional[Path], Optional[Path]]:
    send = None
    approval = None

    # Preferred rule: determine role by subject marker count parity.
    # odd count (1/3/5/...) -> approval, even count (0/2/4/...) -> send
    scored: list[tuple[Path, int]] = []
    for path in msg_files:
        marker_count = _subject_reply_marker_count(path)
        if marker_count is not None:
            scored.append((path, marker_count))

    even_candidates = sorted(
        [item for item in scored if item[1] % 2 == 0],
        key=lambda item: (item[1], item[0].name.lower()),
    )
    odd_candidates = sorted(
        [item for item in scored if item[1] % 2 == 1],
        key=lambda item: (item[1], item[0].name.lower()),
    )

    if even_candidates:
        send = even_candidates[0][0]
    if odd_candidates:
        approval = odd_candidates[0][0]

    # If one side is still missing, use the remaining file as the other side.
    if send is None or approval is None:
        picked = {path for path in (send, approval) if path is not None}
        remaining = [path for path in msg_files if path not in picked]
        if send is None and remaining:
            send = remaining[0]
            remaining = remaining[1:]
        if approval is None and remaining:
            approval = remaining[0]

    # Fallback to historical filename-based heuristic when needed.
    if send is None or approval is None:
        fallback_send, fallback_approval = _fallback_choose_by_filename(msg_files)
        send = send or fallback_send
        approval = approval or fallback_approval

    return send, approval


def parse_email_pair(email_dir: Path) -> Dict[str, Dict[str, Optional[str]]]:
    email_dir = Path(email_dir)
    result = {
        "send": {"file": "N/A", "sender": "N/A", "sent_date": "N/A", "attachments": [], "zip": "N/A"},
        "approval": {"file": "N/A", "sender": "N/A", "sent_date": "N/A", "attachments": [], "zip": "N/A"},
    }

    if not email_dir.exists() or not email_dir.is_dir():
        logger.debug("Email dir does not exist: %s", email_dir)
        return result

    msg_files = sorted(email_dir.glob("*.msg"))
    if not msg_files:
        return result

    send_path, approval_path = _choose_send_and_approval(msg_files)

    if send_path:
        try:
            result["send"] = parse_msg_summary(send_path)
        except Exception:
            logger.exception("Failed to parse send msg: %s", send_path)

    if approval_path:
        try:
            result["approval"] = parse_msg_summary(approval_path)
        except Exception:
            logger.exception("Failed to parse approval msg: %s", approval_path)

    return result
