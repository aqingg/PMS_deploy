"""Generate TCD08 rule JSON from easier-to-maintain sources.

The runtime rule engine still consumes the same JSON shape as
``services.tcd08.rules``. This module only helps maintain that JSON from an
Excel workbook or a small line-oriented text format.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


SHEET_ALIASES = {
    "calibration_scope": {"calibration_scope", "章节删除", "section_delete"},
    "condition_refs": {"condition_refs", "条件定义", "conditions"},
    "red_paragraph_rules": {"red_paragraph_rules", "段落删除", "red_delete"},
    "red_paragraph_text_rules": {"red_paragraph_text_rules", "文本改写", "text_rewrite"},
}

OPERATOR_NAMES = {
    "contains",
    "not_contains",
    "only_contains",
    "not_only_contains",
    "only_matches",
    "not_only_matches",
    "matches_any",
    "not_matches_any",
    "matches_all",
}

SENSOR_PATTERN_SUFFIX = "[A-Z0-9]*"
SECTION_RE = re.compile(r"^\d+(?:\.\d+)*$")


class RuleGenerationError(ValueError):
    """Raised when source rules cannot be converted into runtime JSON."""


@dataclass
class RuleValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_invalid(self) -> None:
        if self.errors:
            raise RuleGenerationError("\n".join(self.errors))


def read_rules_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as rules_file:
        data = json.load(rules_file)
    if not isinstance(data, dict):
        raise RuleGenerationError(f"Rule JSON root must be an object: {path}")
    return data


def write_rules_json(rules: dict[str, Any], output_path: Path, *, backup: bool = True) -> Path | None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    if output_path.exists() and backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = output_path.with_suffix(f"{output_path.suffix}.{timestamp}.bak")
        shutil.copy2(output_path, backup_path)

    with open(output_path, "w", encoding="utf-8") as rules_file:
        json.dump(rules, rules_file, ensure_ascii=False, indent=2)
        rules_file.write("\n")
    return backup_path


def canonical_sheet_name(sheet_name: str) -> str | None:
    normalized = sheet_name.strip().lower()
    for canonical_name, aliases in SHEET_ALIASES.items():
        if normalized in {alias.lower() for alias in aliases}:
            return canonical_name
    return None


def split_list(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    separator = "|" if "|" in text else r"[,，、;；]"
    if separator == "|":
        parts = text.split("|")
    else:
        parts = re.split(separator, text)
    return [part.strip() for part in parts if part.strip()]


def parse_int_list(value: Any, *, label: str) -> list[int]:
    values: list[int] = []
    for item in split_list(value):
        try:
            values.append(int(item))
        except ValueError as exc:
            raise RuleGenerationError(f"{label} must contain integers only: {value}") from exc
    return values


def parse_json_object(value: Any, *, label: str) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuleGenerationError(f"{label} must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuleGenerationError(f"{label} must be a JSON object")
    return parsed


def parse_operator_value(operator: str, value: Any, value_type: str = "") -> str | list[str]:
    if operator == "matches_all" or value_type.strip().lower() == "list":
        return split_list(value)
    return str(value or "").strip()


def normalize_row(row: dict[str, Any]) -> dict[str, str]:
    return {str(key).strip(): str(value or "").strip() for key, value in row.items()}


def get_first(row: dict[str, str], *names: str) -> str:
    lowered = {key.lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return value
    return ""


def when_ref_value(raw_value: str) -> str | list[str] | None:
    values = split_list(raw_value)
    if not values:
        return None
    return values[0] if len(values) == 1 else values


def add_condition_from_row(rule: dict[str, Any], row: dict[str, str], *, row_label: str) -> None:
    when_json = get_first(row, "when_json", "when")
    inline_when = parse_json_object(when_json, label=f"{row_label} when_json")
    if when_json.strip():
        rule["when"] = inline_when

    field_label = get_first(row, "field_label", "field")
    operator = get_first(row, "operator")
    value = get_first(row, "value")
    if field_label or operator or value:
        if not field_label or not operator or not value:
            raise RuleGenerationError(
                f"{row_label} inline condition requires field_label, operator and value"
            )
        if operator not in OPERATOR_NAMES:
            raise RuleGenerationError(f"{row_label} has unsupported operator: {operator}")
        rule.setdefault("when", {}).setdefault(field_label, {})[operator] = parse_operator_value(
            operator,
            value,
            get_first(row, "value_type"),
        )


def rows_to_rules(sheets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rules: dict[str, Any] = {}

    calibration_rows = [normalize_row(row) for row in sheets.get("calibration_scope", [])]
    if calibration_rows:
        field_label = get_first(calibration_rows[0], "field_label", "field") or "Calibration Scope"
        delete_when_missing = []
        for index, row in enumerate(calibration_rows, start=2):
            if not any(row.values()):
                continue
            row_field_label = get_first(row, "field_label", "field")
            if row_field_label and row_field_label != field_label:
                raise RuleGenerationError(
                    "calibration_scope supports one field_label per workbook; "
                    f"got {field_label!r} and {row_field_label!r}"
                )
            delete_when_missing.append(
                {
                    "required_any": split_list(get_first(row, "required_any", "required_scopes")),
                    "sections": split_list(get_first(row, "sections", "section")),
                    "description": get_first(row, "description", "说明"),
                }
            )
            if not delete_when_missing[-1]["required_any"] or not delete_when_missing[-1]["sections"]:
                raise RuleGenerationError(
                    f"calibration_scope row {index} requires required_any and sections"
                )
        rules["calibration_scope"] = {
            "field_label": field_label,
            "delete_when_missing": delete_when_missing,
        }

    condition_rows = [normalize_row(row) for row in sheets.get("condition_refs", [])]
    if condition_rows:
        condition_refs: dict[str, dict[str, dict[str, str | list[str]]]] = {}
        for index, row in enumerate(condition_rows, start=2):
            if not any(row.values()):
                continue
            ref_name = get_first(row, "ref_name", "name", "condition_ref")
            field_label = get_first(row, "field_label", "field")
            operator = get_first(row, "operator")
            value = get_first(row, "value")
            if not ref_name or not field_label or not operator or not value:
                raise RuleGenerationError(
                    f"condition_refs row {index} requires ref_name, field_label, operator and value"
                )
            if operator not in OPERATOR_NAMES:
                raise RuleGenerationError(f"condition_refs row {index} has unsupported operator: {operator}")
            field_conditions = condition_refs.setdefault(ref_name, {}).setdefault(field_label, {})
            if operator in field_conditions:
                raise RuleGenerationError(
                    f"condition_refs row {index} duplicates {ref_name}.{field_label}.{operator}"
                )
            field_conditions[operator] = parse_operator_value(operator, value, get_first(row, "value_type"))
        rules["condition_refs"] = condition_refs

    red_rows = [normalize_row(row) for row in sheets.get("red_paragraph_rules", [])]
    if red_rows:
        red_rules = []
        for index, row in enumerate(red_rows, start=2):
            if not any(row.values()):
                continue
            rule: dict[str, Any] = {
                "description": get_first(row, "description", "说明"),
                "section": get_first(row, "section", "章节"),
                "delete_groups": parse_int_list(
                    get_first(row, "delete_groups", "groups", "删除组"),
                    label=f"red_paragraph_rules row {index} delete_groups",
                ),
            }
            ref_value = when_ref_value(get_first(row, "when_ref", "condition_ref"))
            if ref_value:
                rule["when_ref"] = ref_value
            add_condition_from_row(rule, row, row_label=f"red_paragraph_rules row {index}")
            red_rules.append(rule)
        rules["red_paragraph_rules"] = red_rules

    rewrite_rows = [normalize_row(row) for row in sheets.get("red_paragraph_text_rules", [])]
    if rewrite_rows:
        grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
        for index, row in enumerate(rewrite_rows, start=2):
            if not any(row.values()):
                continue
            section = get_first(row, "section", "章节")
            group = get_first(row, "group", "组")
            description = get_first(row, "description", "说明")
            ref_text = get_first(row, "when_ref", "condition_ref")
            when_json = get_first(row, "when_json", "when")
            rule_id = get_first(row, "rule_id", "id")
            key = (
                rule_id
                or section,
                group,
                description,
                ref_text,
                when_json,
                get_first(row, "field_label", "field"),
                get_first(row, "operator"),
                get_first(row, "value"),
            )
            if key not in grouped:
                try:
                    group_index = int(group)
                except ValueError as exc:
                    raise RuleGenerationError(
                        f"red_paragraph_text_rules row {index} group must be an integer: {group}"
                    ) from exc
                rule = {
                    "description": description,
                    "section": section,
                    "group": group_index,
                    "replacements": [],
                }
                ref_value = when_ref_value(ref_text)
                if ref_value:
                    rule["when_ref"] = ref_value
                add_condition_from_row(rule, row, row_label=f"red_paragraph_text_rules row {index}")
                grouped[key] = rule

            from_text = get_first(row, "from", "from_text", "原文")
            if not from_text:
                raise RuleGenerationError(f"red_paragraph_text_rules row {index} requires from text")
            grouped[key]["replacements"].append(
                {
                    "from": from_text,
                    "to": get_first(row, "to", "to_text", "目标文本"),
                }
            )
        rules["red_paragraph_text_rules"] = list(grouped.values())

    return rules


def rules_to_rows(rules: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    sheets: dict[str, list[dict[str, Any]]] = {
        "calibration_scope": [],
        "condition_refs": [],
        "red_paragraph_rules": [],
        "red_paragraph_text_rules": [],
    }

    calibration_scope = rules.get("calibration_scope", {})
    field_label = calibration_scope.get("field_label", "Calibration Scope")
    for item in calibration_scope.get("delete_when_missing", []):
        sheets["calibration_scope"].append(
            {
                "field_label": field_label,
                "required_any": "|".join(str(value) for value in item.get("required_any", [])),
                "sections": "|".join(str(value) for value in item.get("sections", [])),
                "description": item.get("description", ""),
            }
        )

    for ref_name, condition in rules.get("condition_refs", {}).items():
        for field_label, field_condition in condition.items():
            for operator, value in field_condition.items():
                sheets["condition_refs"].append(
                    {
                        "ref_name": ref_name,
                        "field_label": field_label,
                        "operator": operator,
                        "value": "|".join(str(item) for item in value) if isinstance(value, list) else value,
                        "value_type": "list" if isinstance(value, list) else "",
                        "description": "",
                    }
                )

    for rule in rules.get("red_paragraph_rules", []):
        sheets["red_paragraph_rules"].append(
            {
                "description": rule.get("description", ""),
                "section": rule.get("section", ""),
                "when_ref": encode_when_ref(rule.get("when_ref")),
                "when_json": json.dumps(rule.get("when", {}), ensure_ascii=False) if "when" in rule else "",
                "delete_groups": "|".join(str(item) for item in rule.get("delete_groups", [])),
            }
        )

    for rule_index, rule in enumerate(rules.get("red_paragraph_text_rules", []), start=1):
        for replacement in rule.get("replacements", []):
            sheets["red_paragraph_text_rules"].append(
                {
                    "rule_id": f"rewrite_{rule_index}",
                    "description": rule.get("description", ""),
                    "section": rule.get("section", ""),
                    "group": rule.get("group", ""),
                    "when_ref": encode_when_ref(rule.get("when_ref")),
                    "when_json": json.dumps(rule.get("when", {}), ensure_ascii=False) if "when" in rule else "",
                    "from": replacement.get("from", ""),
                    "to": replacement.get("to", ""),
                }
            )

    return sheets


def encode_when_ref(value: Any) -> str:
    if isinstance(value, list):
        return "|".join(str(item) for item in value)
    return str(value or "")


def validate_rules(rules: dict[str, Any]) -> RuleValidationResult:
    result = RuleValidationResult()
    condition_refs = rules.get("condition_refs", {})
    if condition_refs is not None and not isinstance(condition_refs, dict):
        result.errors.append("condition_refs must be an object")
        condition_refs = {}

    calibration_scope = rules.get("calibration_scope", {})
    if calibration_scope:
        if not isinstance(calibration_scope, dict):
            result.errors.append("calibration_scope must be an object")
        else:
            if not calibration_scope.get("field_label"):
                result.errors.append("calibration_scope.field_label is required")
            for index, rule in enumerate(calibration_scope.get("delete_when_missing", []), start=1):
                validate_section_list(rule.get("sections"), result, f"calibration_scope[{index}].sections")
                if not rule.get("required_any"):
                    result.errors.append(f"calibration_scope[{index}].required_any is required")

    validate_condition_refs(condition_refs, result)

    for index, rule in enumerate(rules.get("red_paragraph_rules", []), start=1):
        validate_section(rule.get("section"), result, f"red_paragraph_rules[{index}].section")
        if not rule.get("delete_groups"):
            result.errors.append(f"red_paragraph_rules[{index}].delete_groups is required")
        for group in rule.get("delete_groups", []):
            if not isinstance(group, int):
                result.errors.append(f"red_paragraph_rules[{index}].delete_groups must contain integers")
        validate_rule_condition(rule, condition_refs, result, f"red_paragraph_rules[{index}]")

    for index, rule in enumerate(rules.get("red_paragraph_text_rules", []), start=1):
        validate_section(rule.get("section"), result, f"red_paragraph_text_rules[{index}].section")
        if not isinstance(rule.get("group"), int):
            result.errors.append(f"red_paragraph_text_rules[{index}].group must be an integer")
        replacements = rule.get("replacements")
        if not isinstance(replacements, list) or not replacements:
            result.errors.append(f"red_paragraph_text_rules[{index}].replacements is required")
        else:
            for replacement_index, replacement in enumerate(replacements, start=1):
                if not isinstance(replacement, dict) or not replacement.get("from"):
                    result.errors.append(
                        f"red_paragraph_text_rules[{index}].replacements[{replacement_index}].from is required"
                    )
        validate_rule_condition(rule, condition_refs, result, f"red_paragraph_text_rules[{index}]")

    return result


def validate_condition_refs(condition_refs: dict[str, Any], result: RuleValidationResult) -> None:
    for ref_name, condition in condition_refs.items():
        if not isinstance(condition, dict):
            result.errors.append(f"condition_refs.{ref_name} must be an object")
            continue
        validate_condition_object(condition, result, f"condition_refs.{ref_name}")


def validate_rule_condition(
    rule: dict[str, Any],
    condition_refs: dict[str, Any],
    result: RuleValidationResult,
    label: str,
) -> None:
    for ref_name in rule_ref_names(rule.get("when_ref")):
        if ref_name not in condition_refs:
            result.errors.append(f"{label}.when_ref references missing condition: {ref_name}")
    if "when" in rule:
        validate_condition_object(rule.get("when"), result, f"{label}.when")


def validate_condition_object(condition: Any, result: RuleValidationResult, label: str) -> None:
    if not isinstance(condition, dict):
        result.errors.append(f"{label} must be an object")
        return
    for field_label, field_condition in condition.items():
        if not isinstance(field_condition, dict):
            result.errors.append(f"{label}.{field_label} must be an object")
            continue
        for operator, value in field_condition.items():
            if operator not in OPERATOR_NAMES:
                result.errors.append(f"{label}.{field_label} has unsupported operator: {operator}")
            if operator == "matches_all" and not isinstance(value, list):
                result.errors.append(f"{label}.{field_label}.matches_all must be a list")
            if operator != "matches_all" and not isinstance(value, str):
                result.errors.append(f"{label}.{field_label}.{operator} must be a string")


def rule_ref_names(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def validate_section_list(value: Any, result: RuleValidationResult, label: str) -> None:
    if not isinstance(value, list) or not value:
        result.errors.append(f"{label} must be a non-empty list")
        return
    for item in value:
        validate_section(item, result, label)


def validate_section(value: Any, result: RuleValidationResult, label: str) -> None:
    if not isinstance(value, str) or not SECTION_RE.fullmatch(value.strip()):
        result.errors.append(f"{label} must look like a section number, got: {value!r}")


def summarize_rules(rules: dict[str, Any], old_rules: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = {
        "calibration_scope_rules": len(
            rules.get("calibration_scope", {}).get("delete_when_missing", [])
        ),
        "condition_refs": len(rules.get("condition_refs", {})),
        "red_paragraph_rules": len(rules.get("red_paragraph_rules", [])),
        "red_paragraph_text_rules": len(rules.get("red_paragraph_text_rules", [])),
        "text_replacements": sum(
            len(rule.get("replacements", []))
            for rule in rules.get("red_paragraph_text_rules", [])
        ),
    }
    if old_rules is not None:
        summary["changed_top_level_keys"] = [
            key
            for key in sorted(set(old_rules) | set(rules))
            if old_rules.get(key) != rules.get(key)
        ]
    return summary


def merge_with_existing(base_rules: dict[str, Any], generated_rules: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base_rules)
    for key, value in generated_rules.items():
        merged[key] = value
    return merged


def read_rules_excel(path: Path) -> dict[str, Any]:
    sheets = read_xlsx(path)
    canonical_sheets: dict[str, list[dict[str, Any]]] = {}
    for sheet_name, rows in sheets.items():
        canonical_name = canonical_sheet_name(sheet_name)
        if canonical_name:
            canonical_sheets[canonical_name] = rows
    return rows_to_rules(canonical_sheets)


def write_rules_excel(path: Path, rules: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_xlsx(path, rules_to_rows(rules))


def read_rules_text(path: Path) -> dict[str, Any]:
    sheets: dict[str, list[dict[str, Any]]] = {}
    current_sheet = ""
    with open(path, "r", encoding="utf-8") as text_file:
        for line_number, raw_line in enumerate(text_file, start=1):
            line = raw_line.strip().lstrip("\ufeff")
            if not line or line.startswith("#"):
                continue
            section_match = re.fullmatch(r"\[(.+)]", line)
            if section_match:
                current_sheet = canonical_sheet_name(section_match.group(1)) or ""
                if not current_sheet:
                    raise RuleGenerationError(f"Unknown text section at line {line_number}: {line}")
                sheets.setdefault(current_sheet, [])
                continue
            natural_row = parse_natural_language_line(line)
            if natural_row:
                sheet_name, row = natural_row
                sheets.setdefault(sheet_name, []).append(row)
                continue
            if not current_sheet:
                raise RuleGenerationError(f"Text rule line {line_number} is outside a known section")
            sheets.setdefault(current_sheet, []).append(parse_key_value_line(line, line_number=line_number))
    return rows_to_rules(sheets)


def parse_key_value_line(line: str, *, line_number: int) -> dict[str, str]:
    row: dict[str, str] = {}
    for part in re.split(r";\s*", line):
        if not part:
            continue
        if "=" not in part:
            raise RuleGenerationError(f"Text rule line {line_number} must use key=value pairs: {part}")
        key, value = part.split("=", 1)
        row[key.strip()] = value.strip()
    return row


def parse_natural_language_line(line: str) -> tuple[str, dict[str, str]] | None:
    section_delete = re.search(
        r"检查\s+`?(?P<field>[^`，,]+)`?\s*[，,]\s*如果不包含\s+`?(?P<required>.+?)`?\s*[，,]\s*则删除\s+`?(?P<section>\d+(?:\.\d+)*)",
        line,
    )
    if section_delete:
        field_label = section_delete.group("field").strip()
        if field_label.lower() not in {"calibration scope", "章节", "章节范围"}:
            section_delete = None
    if section_delete:
        required_text = section_delete.group("required")
        required_text = re.split(r"\s*[，,]\s*说明|\s*。", required_text)[0]
        return (
            "calibration_scope",
            {
                "field_label": section_delete.group("field").strip(),
                "required_any": "|".join(split_condition_keywords(required_text)),
                "sections": section_delete.group("section"),
                "description": line,
            },
        )

    red_delete = re.search(
        r"检查\s+`?(?P<field>[^`，,]+)`?\s*[，,]\s*如果(?P<condition>.+?)\s*[，,]\s*则删除\s+`?(?P<section>\d+(?:\.\d+)*)`?\s*第\s*(?P<groups>[\d、,，\s]+)\s*组红字段落",
        line,
    )
    if red_delete:
        return (
            "red_paragraph_rules",
            {
                "description": line,
                "section": red_delete.group("section"),
                "delete_groups": "|".join(split_list(red_delete.group("groups"))),
                "when_json": json.dumps(
                    condition_phrase_to_when(
                        red_delete.group("field").strip(),
                        red_delete.group("condition"),
                    ),
                    ensure_ascii=False,
                ),
            },
        )
    return None


def split_condition_keywords(text: str) -> list[str]:
    cleaned = text.replace("`", "").strip()
    return [
        value.strip()
        for value in re.split(r"\s*(?:或|和|、|,|，|\|)\s*", cleaned)
        if value.strip()
    ]


def condition_phrase_to_when(field_label: str, phrase: str) -> dict[str, dict[str, Any]]:
    phrase = phrase.replace("`", "").strip()
    if "不只是 1 个 SMAx" in phrase or "不只含有1个SMAx" in phrase:
        return {field_label: {"not_only_matches": r"SMA\d+"}}
    if "只有 1 个 SMAx" in phrase or "只含有1个SMAx" in phrase:
        return {field_label: {"only_matches": r"SMA\d+"}}
    if "不包含" in phrase:
        keywords = split_condition_keywords(phrase.split("不包含", 1)[1])
        return {field_label: {"not_matches_any": keyword_pattern(keywords)}}
    if "同时包含" in phrase:
        keywords = split_condition_keywords(phrase.split("同时包含", 1)[1])
        return {field_label: {"matches_all": [keyword_pattern([keyword]) for keyword in keywords]}}
    if "包含" in phrase:
        keywords = split_condition_keywords(phrase.split("包含", 1)[1])
        if "和" in phrase or "同时" in phrase:
            return {field_label: {"matches_all": [keyword_pattern([keyword]) for keyword in keywords]}}
        return {field_label: {"matches_any": keyword_pattern(keywords)}}
    raise RuleGenerationError(f"Unsupported natural language condition: {phrase}")


def keyword_pattern(keywords: list[str]) -> str:
    escaped = [re.escape(keyword.strip().upper()) for keyword in keywords if keyword.strip()]
    if not escaped:
        return ""
    if len(escaped) == 1:
        return escaped[0] + SENSOR_PATTERN_SUFFIX
    return "(" + "|".join(escaped) + ")" + SENSOR_PATTERN_SUFFIX


def read_xlsx(path: Path) -> dict[str, list[dict[str, str]]]:
    with zipfile.ZipFile(path, "r") as workbook_zip:
        shared_strings = read_shared_strings(workbook_zip)
        workbook_root = ET.fromstring(workbook_zip.read("xl/workbook.xml"))
        rels_root = ET.fromstring(workbook_zip.read("xl/_rels/workbook.xml.rels"))
        rels = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels_root
            if rel.attrib.get("Id") and rel.attrib.get("Target")
        }
        ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        sheets: dict[str, list[dict[str, str]]] = {}
        rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        for sheet in workbook_root.findall(".//main:sheet", ns):
            sheet_name = sheet.attrib.get("name", "")
            relationship_id = sheet.attrib.get(rel_ns, "")
            target = rels.get(relationship_id)
            if not sheet_name or not target:
                continue
            target_path = Path("xl") / target
            rows = read_sheet_rows(workbook_zip.read(str(target_path).replace("\\", "/")), shared_strings)
            if rows:
                sheets[sheet_name] = rows
    return sheets


def read_shared_strings(workbook_zip: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(workbook_zip.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    values = []
    for item in root.findall(".//main:si", ns):
        values.append("".join(text.text or "" for text in item.findall(".//main:t", ns)))
    return values


def read_sheet_rows(sheet_xml: bytes, shared_strings: list[str]) -> list[dict[str, str]]:
    root = ET.fromstring(sheet_xml)
    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    raw_rows: list[list[str]] = []
    for row in root.findall(".//main:row", ns):
        values: dict[int, str] = {}
        max_index = 0
        for cell in row.findall("main:c", ns):
            cell_ref = cell.attrib.get("r", "")
            column_index = column_ref_to_index(cell_ref)
            max_index = max(max_index, column_index)
            values[column_index] = cell_value(cell, shared_strings, ns)
        raw_rows.append([values.get(index, "") for index in range(1, max_index + 1)])
    if not raw_rows:
        return []
    header = [value.strip() for value in raw_rows[0]]
    rows = []
    for raw_row in raw_rows[1:]:
        row = {
            header[index]: raw_row[index] if index < len(raw_row) else ""
            for index in range(len(header))
            if header[index]
        }
        if any(str(value).strip() for value in row.values()):
            rows.append(row)
    return rows


def cell_value(cell: ET.Element, shared_strings: list[str], ns: dict[str, str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//main:t", ns))
    value_node = cell.find("main:v", ns)
    if value_node is None or value_node.text is None:
        return ""
    if cell_type == "s":
        try:
            return shared_strings[int(value_node.text)]
        except (ValueError, IndexError):
            return ""
    return value_node.text


def column_ref_to_index(cell_ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", cell_ref.upper())
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter) - ord("A") + 1
    return index


def column_index_to_ref(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def write_xlsx(path: Path, sheets: dict[str, list[dict[str, Any]]]) -> None:
    sheet_items = list(sheets.items())
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as workbook_zip:
        workbook_zip.writestr("[Content_Types].xml", content_types_xml(len(sheet_items)))
        workbook_zip.writestr("_rels/.rels", package_rels_xml())
        workbook_zip.writestr("xl/workbook.xml", workbook_xml(sheet_items))
        workbook_zip.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml(len(sheet_items)))
        workbook_zip.writestr("xl/styles.xml", styles_xml())
        for index, (_, rows) in enumerate(sheet_items, start=1):
            workbook_zip.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml(rows))


def content_types_xml(sheet_count: int) -> str:
    worksheet_overrides = "\n".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{worksheet_overrides}</Types>"
    )


def package_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )


def workbook_xml(sheet_items: list[tuple[str, list[dict[str, Any]]]]) -> str:
    sheets_xml = "".join(
        f'<sheet name="{xml_escape(sheet_name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, (sheet_name, _) in enumerate(sheet_items, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets_xml}</sheets></workbook>"
    )


def workbook_rels_xml(sheet_count: int) -> str:
    relationships = [
        f'<Relationship Id="rId{index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    ]
    relationships.append(
        f'<Relationship Id="rId{sheet_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(relationships)}</Relationships>"
    )


def styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellXfs>'
        '</styleSheet>'
    )


def sheet_xml(rows: list[dict[str, Any]]) -> str:
    headers = list(rows[0].keys()) if rows else ["description"]
    all_rows = [headers] + [[str(row.get(header, "")) for header in headers] for row in rows]
    row_xml = []
    for row_index, row_values in enumerate(all_rows, start=1):
        cells = []
        for column_index, value in enumerate(row_values, start=1):
            cell_ref = f"{column_index_to_ref(column_index)}{row_index}"
            cells.append(
                f'<c r="{cell_ref}" t="inlineStr"><is><t>{xml_escape(value)}</t></is></c>'
            )
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    )


def xml_escape(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
