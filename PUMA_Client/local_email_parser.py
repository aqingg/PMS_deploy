from __future__ import annotations

"""
Client-side local email parser for TCD08.

Purpose:
- Run inside PUMA_Client / local 7175 client.
- Read local Customer_Approval_Email directory.
- Parse .msg email files locally.
- Extract only the metadata needed by TCD08 placeholders.
- Return a small JSON-serializable email_summary dict.

This file intentionally does NOT upload or modify any email files.
It mirrors the current Server-side parser result shape so Server/datamerge
can reuse the same placeholder filling logic later.
"""

from contextlib import suppress
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Optional
import json
import logging
import re
import shutil
import tempfile
import zipfile

import extract_msg

logger = logging.getLogger(__name__)

# extract-msg may print harmless INFO logs when optional MAPI streams are missing
# inside a .msg file. They do not mean the email parsing failed. Keep those logs
# quiet for the local client CLI and Client.exe runtime.
logging.getLogger("extract_msg").setLevel(logging.WARNING)
logging.getLogger("extract_msg.msg_classes.msg").setLevel(logging.WARNING)
logging.getLogger("extract_msg.attachments").setLevel(logging.WARNING)


EMPTY_EMAIL_SUMMARY: dict[str, dict[str, Any]] = {
    "send": {
        "file": "N/A",
        "sender": "N/A",
        "sent_date": "N/A",
        "attachments": [],
        "zip": "N/A",
        "all_zip_entries": [],
        "excel_entries": [],
        "xlsx_entries": [],
        "standard_xlsx_files": [],
        "defect_xlsx_files": [],
        "specific_xlsx_files": [],
        "standard_xlsx_count": 0,
        "defect_xlsx_count": 0,
        "specific_xlsx_count": 0,
    },
    "approval": {
        "file": "N/A",
        "sender": "N/A",
        "sent_date": "N/A",
        "attachments": [],
        "zip": "N/A",
        "all_zip_entries": [],
        "excel_entries": [],
        "xlsx_entries": [],
        "standard_xlsx_files": [],
        "defect_xlsx_files": [],
        "specific_xlsx_files": [],
        "standard_xlsx_count": 0,
        "defect_xlsx_count": 0,
        "specific_xlsx_count": 0,
    },
}


def _empty_email_summary() -> dict[str, dict[str, Any]]:
    """Return a fresh empty result to avoid sharing mutable list instances."""
    return json.loads(json.dumps(EMPTY_EMAIL_SUMMARY, ensure_ascii=False))


def _clean_text(value: Any) -> str:
    """Convert MAPI/extract-msg values to clean printable text.

    Some .msg attachment names may contain a trailing NUL, for example
    "Results.zip\x00". That made the previous parser display the name in
    attachments, but fail `.endswith(".zip")`, so the `zip` field became N/A.
    """
    if value is None:
        return ""
    text = str(value)
    # Remove NUL and other control characters that should not be part of a file name.
    text = text.replace("\x00", "")
    text = re.sub(r"[\x01-\x1F\x7F]", "", text)
    return text.strip().strip('"').strip()


def _attachment_name(attachment: Any) -> str:
    return (
        _clean_text(getattr(attachment, "longFilename", None))
        or _clean_text(getattr(attachment, "shortFilename", None))
        or _clean_text(getattr(attachment, "filename", None))
    )


def _find_zip_attachment(msg: extract_msg.Message):
    for attachment in msg.attachments:
        filename = _attachment_name(attachment)
        if filename.lower().endswith(".zip"):
            return attachment, filename
    return None, None


def _write_attachment_data_to_temp(attachment: Any, suffix: str = ".zip") -> Optional[Path]:
    """Write attachment.data to a temp file when extract-msg exposes raw bytes."""
    data = getattr(attachment, "data", None)
    if data is None:
        return None
    if isinstance(data, str):
        data = data.encode("utf-8", errors="ignore")
    if not isinstance(data, (bytes, bytearray)) or not data:
        return None

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".zip") as temp_file:
        temp_file.write(data)
        return Path(temp_file.name)


def _save_zip_attachment_to_temp(attachment: Any, zip_name: str = "") -> Optional[Path]:
    """
    Save one zip attachment to a stable temp file and return its path.

    Prefer direct attachment.data to avoid filename problems caused by trailing
    NUL/control characters. Fall back to attachment.save() for compatibility
    with extract-msg versions where raw data is not exposed.
    """
    if attachment is None:
        return None

    suffix = Path(_clean_text(zip_name)).suffix or ".zip"

    data_path = _write_attachment_data_to_temp(attachment, suffix=suffix)
    if data_path and data_path.exists():
        return data_path

    with tempfile.TemporaryDirectory() as temp_dir:
        saved_result = attachment.save(customPath=temp_dir)

        # extract-msg usually returns (SaveType, path). Keep compatibility if
        # the library returns only a path in some versions.
        if isinstance(saved_result, tuple):
            saved_path = saved_result[-1]
        else:
            saved_path = saved_result

        candidates: list[Path] = []
        if saved_path:
            source_path = Path(str(saved_path))
            if source_path.is_file():
                candidates.append(source_path)
            elif source_path.is_dir():
                candidates.extend([p for p in source_path.rglob("*") if p.is_file()])

        if not candidates:
            candidates.extend([p for p in Path(temp_dir).rglob("*") if p.is_file()])
        if not candidates:
            return None

        # Prefer files that look like zip, otherwise use the largest saved file.
        candidates.sort(key=lambda p: (not _clean_text(p.name).lower().endswith(".zip"), -p.stat().st_size))
        source_path = candidates[0]

        with tempfile.NamedTemporaryFile(delete=False, suffix=source_path.suffix or suffix) as temp_file:
            target_path = Path(temp_file.name)
            with source_path.open("rb") as source_file:
                shutil.copyfileobj(source_file, temp_file)
            return target_path


def _normalize_zip_entry_name(entry_name: str) -> str:
    return Path(_clean_text(entry_name)).name


def _classify_excel_files(excel_names: list[str]) -> dict[str, Any]:
    """
    Classify Excel files using the same rules as the Server parser:
    - pps / idf / idp => specific
    - df / def => defect
    - others => standard
    """
    standard_files: list[str] = []
    defect_files: list[str] = []
    specific_files: list[str] = []

    for name in excel_names:
        base_name = _normalize_zip_entry_name(name)
        lower_name = base_name.lower()
        if not base_name or lower_name.startswith("~$"):
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


def _empty_zip_info(zip_name: str = "N/A") -> dict[str, Any]:
    return {
        "zip_name": _clean_text(zip_name) or "N/A",
        "all_zip_entries": [],
        "excel_entries": [],
        "xlsx_entries": [],
        **_classify_excel_files([]),
    }


def _extract_zip_xlsx_groups_from_msg(msg: extract_msg.Message) -> dict[str, Any]:
    """Read zip attachment names and Excel names from one .msg file."""
    zip_attachment, zip_attachment_name = _find_zip_attachment(msg)
    zip_attachment_name = _clean_text(zip_attachment_name)
    if zip_attachment is None:
        return _empty_zip_info()

    saved_zip_path = _save_zip_attachment_to_temp(zip_attachment, zip_attachment_name)
    if saved_zip_path is None or not saved_zip_path.exists():
        return _empty_zip_info(zip_attachment_name or "N/A")

    try:
        with zipfile.ZipFile(saved_zip_path, "r") as archive:
            all_entries = [_clean_text(name) for name in archive.namelist()]
    except zipfile.BadZipFile:
        logger.exception("Bad zip attachment: %s", zip_attachment_name)
        all_entries = []
    finally:
        with suppress(Exception):
            saved_zip_path.unlink(missing_ok=True)

    excel_entries = [
        name
        for name in all_entries
        if _clean_text(name).lower().endswith((".xlsx", ".xls", ".xlsm"))
        and not _normalize_zip_entry_name(name).lower().startswith("~$")
    ]
    xlsx_entries = [name for name in excel_entries if _clean_text(name).lower().endswith(".xlsx")]
    groups = _classify_excel_files(excel_entries)

    return {
        "zip_name": zip_attachment_name or "N/A",
        "all_zip_entries": all_entries,
        "excel_entries": excel_entries,
        "xlsx_entries": xlsx_entries,
        **groups,
    }


def _format_date(raw_date: Any) -> str:
    if not raw_date:
        return "N/A"
    try:
        if isinstance(raw_date, str):
            dt = parsedate_to_datetime(raw_date)
        else:
            dt = raw_date
        return dt.strftime("%Y.%m.%d")
    except Exception:
        try:
            return str(raw_date)
        except Exception:
            return "N/A"


def parse_msg_summary(msg_path: Path | str) -> Dict[str, Any]:
    """Parse one .msg and return the fields needed by TCD08 email placeholders."""
    msg_path = Path(msg_path)
    msg = extract_msg.Message(str(msg_path))
    try:
        sender = _clean_text(getattr(msg, "sender", None))
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
        with suppress(Exception):
            msg.close()


def _count_reply_markers(subject: str) -> int:
    """Count reply/approval markers except FW.

    These markers and FW markers are both used later in the same parity rule:
    odd count => approval/reply side; even count => send side.
    """
    text = _clean_text(subject)
    if not text:
        return 0
    chinese_count = text.count("答复")
    english_count = len(re.findall(r"\b(?:approval|approve|reply|response|re)\b", text, flags=re.IGNORECASE))
    return chinese_count + english_count


def _count_fw_markers(text: str) -> int:
    """Count Outlook forward markers such as FW:, FW_, FWD: and 转发."""
    text = _clean_text(text)
    if not text:
        return 0
    fw_count = len(re.findall(r"(?i)(?:^|[\s_\-\[\(])fwd?(?=\s*[:：_\-\]\)]|\s+)", text))
    chinese_forward_count = text.count("转发")
    return fw_count + chinese_forward_count


def _count_total_chain_markers(text: str) -> tuple[int, int, int]:
    """Return total/reply/FW marker counts for parity classification."""
    reply_count = _count_reply_markers(text)
    fw_count = _count_fw_markers(text)
    return reply_count + fw_count, reply_count, fw_count


def _subject_marker_counts(msg_path: Path) -> Optional[tuple[int, int, int]]:
    msg = extract_msg.Message(str(msg_path))
    try:
        subject = _clean_text(getattr(msg, "subject", None))
        # Also look at the saved .msg filename. Some exported Outlook files keep
        # FW only in the file name while the internal subject is normalized.
        combined = f"{subject} {msg_path.name}"
        return _count_total_chain_markers(combined)
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
    """
    Choose send and approval email.

    Preferred rule:
    - Count chain markers from both subject and file name.
    - Markers include 答复 / RE / reply / approval and FW / FWD / 转发.
    - Odd marker count => approval/reply side.
    - Even marker count => send side.
    - A zero-marker file can still be used as send when the other file is odd.
    - Fall back to filename keywords / sorted order when no marker is useful.
    """
    send = None
    approval = None

    scored: list[tuple[Path, int, int, int]] = []
    for path in msg_files:
        counts = _subject_marker_counts(path)
        if counts is not None:
            total_count, reply_count, fw_count = counts
            scored.append((path, total_count, reply_count, fw_count))

    # 1) Use the same odd/even parity rule for reply markers and FW markers.
    marked_scored = [item for item in scored if item[1] > 0]
    if marked_scored:
        even_candidates = sorted(
            [item for item in marked_scored if item[1] % 2 == 0],
            key=lambda item: (item[1], item[0].name.lower()),
        )
        odd_candidates = sorted(
            [item for item in marked_scored if item[1] % 2 == 1],
            key=lambda item: (item[1], item[0].name.lower()),
        )
        if even_candidates:
            send = even_candidates[0][0]
        if odd_candidates:
            approval = odd_candidates[0][0]

    # 2) Fill any missing side with remaining files. This preserves the common
    # case: original send has 0 markers, reply/approval has 1 marker.
    if send is None or approval is None:
        picked = {path for path in (send, approval) if path is not None}
        remaining = [path for path in msg_files if path not in picked]
        if send is None and remaining:
            send = remaining[0]
            remaining = remaining[1:]
        if approval is None and remaining:
            approval = remaining[0]

    if send is None or approval is None:
        fallback_send, fallback_approval = _fallback_choose_by_filename(msg_files)
        send = send or fallback_send
        approval = approval or fallback_approval

    return send, approval


def parse_email_pair(email_dir: Path | str) -> Dict[str, Dict[str, Any]]:
    """
    Parse the local Customer_Approval_Email directory.

    Returns a JSON-serializable dict with keys:
    - send
    - approval

    This result is intended to be sent as `email_summary` from 7175 to 8086.
    """
    email_dir = Path(email_dir)
    result = _empty_email_summary()

    if not email_dir.exists() or not email_dir.is_dir():
        logger.debug("Email dir does not exist: %s", email_dir)
        return result

    msg_files = sorted(email_dir.glob("*.msg"))
    if not msg_files:
        logger.debug("No .msg files found in email dir: %s", email_dir)
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


def parse_email_summary(email_dir: Path | str) -> Dict[str, Dict[str, Any]]:
    """Readable alias used by Client code in later steps."""
    return parse_email_pair(email_dir)


if __name__ == "__main__":
    """
    Manual test:
        python local_email_parser.py "C:\\...\\Customer_Approval_Email"
    """
    import argparse

    parser = argparse.ArgumentParser(description="Parse TCD08 local email directory and print email_summary JSON.")
    parser.add_argument("email_dir", help="Path to Customer_Approval_Email directory")
    args = parser.parse_args()

    # Keep our own warnings/errors, but suppress extract_msg's harmless INFO noise.
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")
    logging.getLogger("extract_msg").setLevel(logging.WARNING)
    logging.getLogger("extract_msg.msg_classes.msg").setLevel(logging.WARNING)

    summary = parse_email_summary(args.email_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))