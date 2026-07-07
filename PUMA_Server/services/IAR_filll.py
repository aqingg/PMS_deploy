from __future__ import annotations

import io
import re
import zipfile
from typing import Any
from xml.sax.saxutils import escape as xml_escape


PLACEHOLDER_PATTERN_XML_ESCAPED = re.compile(r"&lt;PMS\.([^&<>]+?)&gt;")
PLACEHOLDER_PATTERN_RAW = re.compile(r"<PMS\.([^<>]+?)>")


# -----------------------------------------------------------------------------
# Basic value helpers
# -----------------------------------------------------------------------------

def _is_meaningful(value: Any) -> bool:
    if value is None or value == "" or value == []:
        return False
    text = str(value).strip()
    if not text:
        return False
    return text.upper() not in {"N/A", "NA", "NULL", "NONE"}


def _stringify_value(value: Any) -> str:
    if value is None:
        return "N/A"

    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(parts) if parts else "N/A"

    if isinstance(value, dict):
        # Keep dict fallback readable, but avoid crashing on unexpected values.
        parts = []
        for key, val in value.items():
            if _is_meaningful(val):
                parts.append(f"{key}: {val}")
        return "; ".join(parts) if parts else "N/A"

    text = str(value).strip()
    return text if text else "N/A"


def _normalize_role_name(role: str) -> str:
    """
    Normalize common PMS role names into placeholder-friendly keys.

    Examples:
        PjM      -> PJM
        TPM      -> TPM
        SW PCM   -> SW_PCM
        SW-PCM   -> SW_PCM
        TestM    -> TestM
    """
    text = str(role or "").strip()
    if not text:
        return ""

    compact = (
        text.replace("-", "_")
            .replace(" ", "_")
            .replace("/", "_")
            .replace("\\", "_")
            .replace(".", "_")
    )

    aliases = {
        "PjM": "PJM",
        "PJM": "PJM",
        "TPM": "TPM",
        "SW_PCM": "SW_PCM",
        "SWPCM": "SW_PCM",
        "SW_PCM": "SW_PCM",
        "FSM": "FSM",
        "TestM": "TestM",
        "TESTM": "TestM",
        "Test_Manager": "TestM",
        "Test_Manager_": "TestM",
    }

    return aliases.get(compact, aliases.get(text, compact))


def _parse_role_summary(role_summary: Any) -> dict[str, str]:
    """
    Parse simple role summary strings.

    Supported examples:
        "PjM: Zhang San; TPM: Li Si"
        "PJM：Zhang San；TPM：Li Si"
        "PjM=Zhang San, TPM=Li Si"
    """
    if not _is_meaningful(role_summary):
        return {}

    text = str(role_summary)
    result: dict[str, str] = {}

    # Split by common separators.
    chunks = re.split(r"[;\n\r；]+", text)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        if ":" in chunk:
            role, value = chunk.split(":", 1)
        elif "：" in chunk:
            role, value = chunk.split("：", 1)
        elif "=" in chunk:
            role, value = chunk.split("=", 1)
        else:
            continue

        role_key = _normalize_role_name(role)
        value_text = value.strip()
        if role_key and value_text:
            result[role_key] = value_text

    return result


def _parse_role_email_summary(role_email_summary: Any) -> dict[str, str]:
    """
    Parse role email summary strings.

    Supported examples:
        "PjMEmail: Zhang San_zhang.san@example.com; TPMEmail: Li Si_li.si@example.com"
        "PJMEmail: Zhang San <zhang.san@example.com>"
    """
    if not _is_meaningful(role_email_summary):
        return {}

    text = str(role_email_summary)
    result: dict[str, str] = {}

    chunks = re.split(r"[;\n\r；]+", text)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        if ":" in chunk:
            role, value = chunk.split(":", 1)
        elif "：" in chunk:
            role, value = chunk.split("：", 1)
        elif "=" in chunk:
            role, value = chunk.split("=", 1)
        else:
            continue

        role = role.strip()
        value_text = value.strip()
        if not role or not value_text:
            continue

        # Normalize PjMEmail / PJMEmail / TPMEmail.
        role_no_email = re.sub(r"email$", "", role, flags=re.IGNORECASE).strip()
        role_key = _normalize_role_name(role_no_email)
        if role_key:
            result[f"{role_key}Email"] = value_text

    return result


def _prepare_profile_for_filling(profile_dict: dict[str, Any]) -> dict[str, str]:
    """
    Prepare all values that can be used by <PMS.xxx> placeholders.

    Rules:
        1. Direct profile key:
              <PMS.customer> -> profile["customer"]
        2. Role summary:
              role_summary = "PjM: Zhang San"
              <PMS.PJM> -> "Zhang San"
        3. Role email summary:
              <PMS.PJMEmail> -> "Zhang San_zhang.san@example.com"
        4. Missing key:
              -> "N/A"
    """
    prepared: dict[str, str] = {}

    for key, value in (profile_dict or {}).items():
        prepared[str(key)] = _stringify_value(value)

    # Add role placeholders from role_summary.
    role_values = _parse_role_summary(profile_dict.get("role_summary"))
    for key, value in role_values.items():
        prepared[key] = _stringify_value(value)

    # Add role email placeholders from role_email_summary.
    role_email_values = _parse_role_email_summary(profile_dict.get("role_email_summary"))
    for key, value in role_email_values.items():
        prepared[key] = _stringify_value(value)

    # Useful fallback: projectName falls back to project.
    if not _is_meaningful(prepared.get("projectName")) and _is_meaningful(prepared.get("project")):
        prepared["projectName"] = prepared["project"]

    return prepared


def _resolve_placeholder_value(key: str, prepared_profile: dict[str, str]) -> str:
    """
    Resolve placeholder key.

    Supports:
        <PMS.customer>
        <PMS.customer-project>
    """
    key = str(key or "").strip()
    if not key:
        return "N/A"

    # Composite placeholder, same style as old datamerge:
    # <PMS.customer-project> -> customer_project
    if "-" in key:
        parts = [part.strip() for part in key.split("-") if part.strip()]
        values = []
        for part in parts:
            value = prepared_profile.get(part)
            values.append(value if _is_meaningful(value) else "N/A")
        return "_".join(values) if values else "N/A"

    value = prepared_profile.get(key)
    if _is_meaningful(value):
        return value

    # Small defensive fallback for case-insensitive lookup.
    key_lower = key.lower()
    for profile_key, profile_value in prepared_profile.items():
        if str(profile_key).lower() == key_lower and _is_meaningful(profile_value):
            return profile_value

    return "N/A"


# -----------------------------------------------------------------------------
# XML replacement helpers
# -----------------------------------------------------------------------------

def _replace_placeholders_in_xml_text(xml_text: str, prepared_profile: dict[str, str]) -> str:
    """
    Replace placeholders inside XML text while keeping XML valid.

    In xlsx XML, cell text like <PMS.customer> is normally stored as:
        &lt;PMS.customer&gt;

    Therefore, replacement values must be XML-escaped before insertion.
    """

    def replace_xml_escaped(match: re.Match[str]) -> str:
        key = match.group(1)
        value = _resolve_placeholder_value(key, prepared_profile)
        return xml_escape(value)

    def replace_raw(match: re.Match[str]) -> str:
        key = match.group(1)
        value = _resolve_placeholder_value(key, prepared_profile)
        return xml_escape(value)

    xml_text = PLACEHOLDER_PATTERN_XML_ESCAPED.sub(replace_xml_escaped, xml_text)
    xml_text = PLACEHOLDER_PATTERN_RAW.sub(replace_raw, xml_text)
    return xml_text


def _should_try_replace(zip_name: str) -> bool:
    """
    Only modify XML text files that may contain cell/shared string text.

    All media files, drawing binaries, WMF/PNG/images are copied byte-for-byte.
    """
    name = zip_name.replace("\\", "/")

    if not name.endswith(".xml"):
        return False

    # These files are safe textual XML and may contain placeholders.
    if name == "xl/sharedStrings.xml":
        return True

    if name.startswith("xl/worksheets/") and name.endswith(".xml"):
        return True

    # Some Excel templates may store text boxes/comments in drawing XML.
    # Replacing only textual placeholders here is safe; media files remain untouched.
    if name.startswith("xl/drawings/") and name.endswith(".xml"):
        return True

    if name.startswith("xl/comments") and name.endswith(".xml"):
        return True

    return False


def _decode_xml(data: bytes) -> str | None:
    """
    Most xlsx XML files are UTF-8. If a file cannot be decoded, leave it unchanged.
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None


# -----------------------------------------------------------------------------
# Public API used by IAR_report.py
# -----------------------------------------------------------------------------

def fill_excel_by_placeholders(profile_dict: dict[str, Any], source: io.BytesIO | bytes) -> io.BytesIO:
    """
    Fill <PMS.xxx> placeholders in an xlsx/xlsm file without using openpyxl.

    Why this implementation:
        xlsx is a zip package. Images, WMF, drawings, headers and media are stored
        as separate files inside the package. openpyxl may drop unsupported media
        when saving. This function avoids that by copying the whole package and
        only replacing placeholder text inside XML files.

    Input:
        profile_dict:
            dictionary containing PMS fields and generated public link fields.
        source:
            BytesIO or bytes of the original Excel template.

    Output:
        BytesIO of the filled Excel workbook.

    Important:
        This preserves xl/media/* and drawing relationships byte-for-byte.
    """
    prepared_profile = _prepare_profile_for_filling(profile_dict)

    if isinstance(source, bytes):
        source_stream = io.BytesIO(source)
    else:
        source.seek(0)
        source_stream = source

    output_stream = io.BytesIO()

    with zipfile.ZipFile(source_stream, "r") as zin:
        with zipfile.ZipFile(output_stream, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                original_data = zin.read(item.filename)
                new_data = original_data

                if _should_try_replace(item.filename):
                    xml_text = _decode_xml(original_data)
                    if xml_text is not None and ("PMS." in xml_text or "&lt;PMS." in xml_text):
                        replaced_xml = _replace_placeholders_in_xml_text(xml_text, prepared_profile)
                        new_data = replaced_xml.encode("utf-8")

                # Preserve zip metadata as much as possible.
                new_info = zipfile.ZipInfo(filename=item.filename, date_time=item.date_time)
                new_info.comment = item.comment
                new_info.extra = item.extra
                new_info.internal_attr = item.internal_attr
                new_info.external_attr = item.external_attr
                new_info.create_system = item.create_system
                new_info.compress_type = item.compress_type

                zout.writestr(new_info, new_data)

    output_stream.seek(0)
    return output_stream


def build_demo_iar_profile() -> dict[str, Any]:
    """
    Small demo profile for local manual testing.
    """
    return {
        "customer": "Geely",
        "project": "BX11",
        "projectName": "BX11",
        "model": "BX11 HEV",
        "sop": "2027-08-01",
        "region": "CN",
        "oem": "Geely",
        "project_leader": "Zhang San",
        "vint_responsible": "Li Si",
        "peripheral_sensor_configuration": "UFS+PAS+PPS",
        "internal_sensor_configuration": "IMS",
        "MCR_No": "MCR-2026-001",
        "role_summary": "PjM: Zhang San; TPM: Li Si; SW_PCM: Wang Wu",
        "role_email_summary": "PjMEmail: Zhang San_zhang.san@example.com; TPMEmail: Li Si_li.si@example.com",
        "link_hammer_test": r"N:\Project\40.Application\A.Vehicle_integration\Hammer_Test",
        "link_sensor_map": r"N:\Project\40.Application\A.Vehicle_integration\Sensor_Map",
    }