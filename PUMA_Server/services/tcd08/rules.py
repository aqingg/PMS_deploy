import json
import re
from pathlib import Path

from fastapi import HTTPException

from services.datamerge import flatten_project_info


TCD08_SECTION_RULES_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "generated_catalog_rules.json"
)


def load_tcd08_section_rules() -> dict:
    """读取 TCD08 的章节删除、红字段落删除、段落内改写规则。"""
    try:
        with open(TCD08_SECTION_RULES_PATH, "r", encoding="utf-8") as rules_file:
            return json.load(rules_file)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"TCD08 section rules not found: {TCD08_SECTION_RULES_PATH}",
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"TCD08 section rules JSON decode error: {exc}",
        ) from exc


def normalize_scope(value: object) -> str:
    """把 Calibration Scope 选项统一成适合比较的格式。

    前端、JSON、模板说明里可能同时出现：
    - Rose_Static
    - RoseStatic
    - Rose Static
    - rose-static

    这些在业务上是同一个选项，所以比较前统一：
    1. 去掉首尾空白
    2. 转成大写
    3. 移除下划线、空格和连字符
    """
    return re.sub(r"[_\s-]+", "", str(value).strip().upper())


def split_scope_values(raw_value: str) -> set[str]:
    """把前端传来的 Calibration Scope 字符串拆成多个选项。"""
    scopes = {
        normalize_scope(value)
        for value in re.split(r"[,;|/\\\s]+", raw_value)
        if value.strip()
    }
    # 兼容 Rose Static / Rose Angle / Pitch Over 这类中间带空格的选项。
    # 上面的通用拆分会把它们拆成两个 token，所以这里额外加入相邻 token
    # 拼接后的形式，让 Rose Static 可以匹配 JSON 里的 Rose_Static。
    whitespace_tokens = [
        value
        for value in re.split(r"[,;|/\\\s]+", raw_value)
        if value.strip()
    ]
    for index in range(len(whitespace_tokens) - 1):
        scopes.add(normalize_scope("".join(whitespace_tokens[index : index + 2])))

    return scopes


def section_sort_key(section_number: str) -> tuple[int, ...]:
    """把 3.2.1 这种章节号转成可排序的数字元组。"""
    return tuple(int(part) for part in section_number.split("."))


def is_descendant_section(section_number: str, parent_number: str) -> bool:
    """判断 section_number 是否是 parent_number 的子章节。"""
    return section_number.startswith(f"{parent_number}.")


def drop_descendant_sections(section_numbers: list[str]) -> list[str]:
    """如果父章节已删除，就去掉重复的子章节删除项。"""
    selected_sections: list[str] = []
    for section_number in sorted(set(section_numbers), key=section_sort_key):
        if any(
            is_descendant_section(section_number, parent_number)
            for parent_number in selected_sections
        ):
            continue
        selected_sections.append(section_number)
    return selected_sections


def _resolve_rule_ref_names(rule: dict, key: str) -> list[str]:
    value = rule.get(key)
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[+|,，/\\]+", value) if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _section_delete_rule_matches(
    rule: dict,
    form_values: dict[str, str],
    all_rules: dict,
    selected_scopes: set[str],
) -> bool:
    required_any = {
        normalize_scope(scope)
        for scope in rule.get("required_any", [])
        if str(scope).strip()
    }
    if required_any and selected_scopes.isdisjoint(required_any):
        return True

    required_all = {
        normalize_scope(scope)
        for scope in rule.get("required_all", [])
        if str(scope).strip()
    }
    if required_all and not required_all.issubset(selected_scopes):
        return True

    when_any_ref = _resolve_rule_ref_names(rule, "when_any_ref")
    if when_any_ref and any(
        rule_conditions_match({"when_ref": ref_name}, form_values, all_rules)
        for ref_name in when_any_ref
    ):
        return True

    return False


def sections_to_delete_by_calibration_scope(project_info: dict) -> list[str]:
    """根据 Calibration Scope 和 JSON 规则，计算需要删除的章节号。"""
    if not project_info:
        return []

    all_rules = load_tcd08_section_rules()
    rules = all_rules.get("calibration_scope", {})
    form_values = flatten_project_info(project_info)
    field_label = rules.get("field_label", "Calibration Scope")
    selected_scopes = split_scope_values(form_values.get(field_label, ""))

    sections_to_delete: list[str] = []
    for rule in rules.get("delete_when_missing", []):
        if not _section_delete_rule_matches(rule, form_values, all_rules, selected_scopes):
            continue

        sections_to_delete.extend(
            str(section).strip()
            for section in rule.get("sections", [])
            if str(section).strip()
        )

    return drop_descendant_sections(sections_to_delete)


def contains_sensor_value(raw_value: str, sensor_name: str) -> bool:
    """判断手填 Sensor 字符串中是否包含某个完整 Sensor 名称。"""
    pattern = rf"(?<![A-Z0-9]){re.escape(sensor_name.upper())}(?![A-Z0-9])"
    return re.search(pattern, raw_value.upper()) is not None


def split_sensor_values(raw_value: str) -> list[str]:
    """把 Sensor 手填字符串拆成 Sensor token，兼容 2*UFS6s 这种写法。"""
    sensor_values: list[str] = []
    for value in re.split(r"[,;|/\\+]+", raw_value):
        token = value.strip().upper()
        if not token:
            continue

        quantity_match = re.match(r"^\d+\s*\*\s*([A-Z0-9_+-]+)$", token)
        sensor_values.append(quantity_match.group(1) if quantity_match else token)

    return sensor_values


def has_only_sensor_value(raw_value: str, sensor_name: str) -> bool:
    """判断 Sensor 字符串是否只有一个指定 Sensor。"""
    sensor_values = split_sensor_values(raw_value)
    return len(sensor_values) == 1 and sensor_values[0] == sensor_name.upper()


def has_only_sensor_pattern(raw_value: str, pattern: str) -> bool:
    """判断 Sensor 字符串是否只有一个符合正则的 Sensor。"""
    sensor_values = split_sensor_values(raw_value)
    if len(sensor_values) != 1:
        return False
    return re.fullmatch(pattern, sensor_values[0], flags=re.IGNORECASE) is not None


def has_any_sensor_pattern(raw_value: str, pattern: str) -> bool:
    """判断 Sensor 字符串中是否有任意一个 Sensor 符合正则。"""
    return any(
        re.fullmatch(pattern, sensor_value, flags=re.IGNORECASE) is not None
        for sensor_value in split_sensor_values(raw_value)
    )


def has_all_sensor_patterns(raw_value: str, patterns: list[str]) -> bool:
    """判断 Sensor 字符串是否同时满足多个 Sensor 正则。"""
    return all(
        has_any_sensor_pattern(raw_value, pattern)
        for pattern in patterns
        if str(pattern).strip()
    )


def as_condition_values(expected: object) -> list[object]:
    """把单个条件值和合并后的多值条件统一转成列表。"""
    if isinstance(expected, list):
        return expected
    return [expected]


def get_form_value(form_values: dict[str, str], field_label: str) -> str:
    """按字段名取值，支持大小写与常见别名。"""
    if field_label in form_values:
        return form_values[field_label]

    normalized = str(field_label).strip().lower()
    for key, value in form_values.items():
        if str(key).strip().lower() == normalized:
            return value

    # 兼容 owner 规则字段与前端标签 Owner 的历史差异。
    if normalized == "owner":
        for alias in ("Owner", "owner", "Author", "author"):
            if alias in form_values:
                return form_values[alias]

    return ""


def field_condition_matches(raw_value: str, condition: dict) -> bool:
    """执行 JSON 规则里某个字段的 when 条件。"""
    for operator, expected in condition.items():
        expected_values = as_condition_values(expected)
        if operator == "contains" and not all(
            contains_sensor_value(raw_value, str(value)) for value in expected_values
        ):
            return False
        if operator == "not_contains" and any(
            contains_sensor_value(raw_value, str(value)) for value in expected_values
        ):
            return False
        if operator == "only_contains" and not all(
            has_only_sensor_value(raw_value, str(value)) for value in expected_values
        ):
            return False
        if operator == "not_only_contains" and any(
            has_only_sensor_value(raw_value, str(value)) for value in expected_values
        ):
            return False
        if operator == "only_matches" and not all(
            has_only_sensor_pattern(raw_value, str(value)) for value in expected_values
        ):
            return False
        if operator == "not_only_matches" and any(
            has_only_sensor_pattern(raw_value, str(value)) for value in expected_values
        ):
            return False
        if operator == "matches_any" and not all(
            has_any_sensor_pattern(raw_value, str(value)) for value in expected_values
        ):
            return False
        if operator == "not_matches_any" and any(
            has_any_sensor_pattern(raw_value, str(value)) for value in expected_values
        ):
            return False
        if operator == "matches_all":
            expected_patterns = [str(pattern) for pattern in expected_values]
            if not has_all_sensor_patterns(raw_value, [str(pattern) for pattern in expected_patterns]):
                return False
    return True


def merge_rule_conditions(target: dict, source: dict) -> None:
    """把一组 when 条件合并到 target 中。

    JSON 中的 when 是按字段名分组的，例如：
        {"Peripheral Sensor": {"matches_any": "..."}}

    when_ref 可能引用多组条件，也可能再叠加当前规则自己的 when。
    因此这里需要做“字段级合并”：同一个字段下的多个 operator 会合并到一起。
    如果同一个 operator 被重复定义，后面的定义会覆盖前面的定义。
    """
    for field_label, field_condition in source.items():
        if not isinstance(field_condition, dict):
            raise HTTPException(
                status_code=500,
                detail=f"TCD08 rule condition must be an object: {field_label}",
            )

        merged_field_condition = target.setdefault(field_label, {})
        for operator, expected in field_condition.items():
            if operator not in merged_field_condition:
                merged_field_condition[operator] = expected
                continue

            existing_values = as_condition_values(merged_field_condition[operator])
            new_values = as_condition_values(expected)
            merged_field_condition[operator] = existing_values + new_values


def resolve_condition_ref_names(rule: dict) -> list[str]:
    """读取规则里的 when_ref，兼容字符串和数组两种写法。"""
    ref_names = rule.get("when_ref", [])
    if isinstance(ref_names, str):
        return [ref_names]
    if isinstance(ref_names, list):
        return [str(ref_name) for ref_name in ref_names if str(ref_name).strip()]
    return []


def resolve_rule_conditions(rule: dict, all_rules: dict) -> dict:
    """解析一条规则最终要执行的条件。

    兼容旧写法：
        {"when": {...}}

    支持新写法：
        {"when_ref": "peripheral_has_pas"}
        {"when_ref": ["peripheral_has_pas", "inertial_only_one_sma"]}

    同时写 when_ref 和 when 时，含义是：
        先展开公共条件，再叠加本规则自己的额外条件。
    """
    condition_refs = all_rules.get("condition_refs", {})
    if not isinstance(condition_refs, dict):
        raise HTTPException(status_code=500, detail="TCD08 condition_refs must be an object")

    resolved_conditions: dict = {}
    for ref_name in resolve_condition_ref_names(rule):
        referenced_condition = condition_refs.get(ref_name)
        if not isinstance(referenced_condition, dict):
            raise HTTPException(
                status_code=500,
                detail=f"TCD08 condition_ref not found or invalid: {ref_name}",
            )
        merge_rule_conditions(resolved_conditions, referenced_condition)

    inline_conditions = rule.get("when", {})
    if not isinstance(inline_conditions, dict):
        return {}
    merge_rule_conditions(resolved_conditions, inline_conditions)
    return resolved_conditions


def rule_conditions_match(rule: dict, form_values: dict[str, str], all_rules: dict) -> bool:
    """判断一条 JSON 规则的 when 条件是否全部命中。"""
    conditions = resolve_rule_conditions(rule, all_rules)

    return all(
        isinstance(condition, dict)
        and field_condition_matches(get_form_value(form_values, field_label), condition)
        for field_label, condition in conditions.items()
    )


def section_removed_by_plan(section: str, sections_to_delete: list[str]) -> bool:
    """如果某章节已经被父章节删除计划覆盖，就不再额外处理它。"""
    return any(
        section == deleted_section
        or is_descendant_section(section, deleted_section)
        for deleted_section in sections_to_delete
    )


def red_paragraph_deletion_rules(project_info: dict, sections_to_delete: list[str]) -> list[dict]:
    """根据 JSON 规则计算需要删除的红色段落组。"""
    if not project_info:
        return []

    all_rules = load_tcd08_section_rules()
    rules = all_rules.get("red_paragraph_rules", [])
    form_values = flatten_project_info(project_info)
    deletions: list[dict] = []

    for rule in rules:
        section = str(rule.get("section", "")).strip()
        if not section or section_removed_by_plan(section, sections_to_delete):
            continue

        if rule_conditions_match(rule, form_values, all_rules):
            delete_groups = [
                int(group_index)
                for group_index in rule.get("delete_groups", [])
                if str(group_index).strip()
            ]
            if delete_groups:
                deletions.append(
                    {
                        "section": section,
                        "delete_groups": delete_groups,
                        "description": rule.get("description", ""),
                    }
                )

    return deletions


def red_paragraph_text_rewrite_rules(project_info: dict, sections_to_delete: list[str]) -> list[dict]:
    """根据 JSON 规则计算需要执行的红色段落组内文字改写。"""
    if not project_info:
        return []

    all_rules = load_tcd08_section_rules()
    rules = all_rules.get("red_paragraph_text_rules", [])
    form_values = flatten_project_info(project_info)
    rewrites: list[dict] = []

    for rule in rules:
        section = str(rule.get("section", "")).strip()
        if not section or section_removed_by_plan(section, sections_to_delete):
            continue

        if not rule_conditions_match(rule, form_values, all_rules):
            continue

        replacements = [
            {
                "from": str(replacement.get("from", "")),
                "to": str(replacement.get("to", "")),
            }
            for replacement in rule.get("replacements", [])
            if isinstance(replacement, dict) and str(replacement.get("from", ""))
        ]
        if replacements:
            rewrites.append(
                {
                    "section": section,
                    "group": int(rule.get("group")),
                    "replacements": replacements,
                    "description": rule.get("description", ""),
                }
            )

    return rewrites
