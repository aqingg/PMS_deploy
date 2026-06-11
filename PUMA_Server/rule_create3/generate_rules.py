# 运行指令：
#   python PUMA_Server/rule_create3/generate_rules.py --from-catalog PUMA_Server/rule_create3/tcd08_rule_catalog_example_line39.xlsx
#   python PUMA_Server/rule_create3/generate_rules.py --from-catalog ... --output PUMA_Server/rule_create3/generated_catalog_rules.json
"""CLI: generate TCD08 JSON from catalog-style rule workbook (rule_create3)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

THIS_DIR = Path(__file__).resolve().parent
SERVER_ROOT = THIS_DIR.parent
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from rule_create3.catalog import CatalogGenerationError, read_rules_catalog  # noqa: E402
from services.tcd08.rule_generator import (  # noqa: E402
    read_rules_json,
    summarize_rules,
    validate_rules,
    write_rules_json,
)


DEFAULT_CATALOG_XLSX = THIS_DIR / "tcd08_rule_catalog_example_line39.xlsx"
DEFAULT_CONDITION_REFS_JSON = SERVER_ROOT / "config" / "tcd08_section_rules.json"
DEFAULT_OUTPUT_JSON = THIS_DIR / "generated_catalog_rules.json"
DEFAULT_SUMMARY_JSON = THIS_DIR / "generation_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate TCD08 rule JSON from catalog workbook (规则清单 + 技术映射).",
    )
    source = parser.add_mutually_exclusive_group(required=False)
    source.add_argument(
        "--from-catalog",
        nargs="?",
        const=str(DEFAULT_CATALOG_XLSX),
        help="Read catalog xlsx and generate runtime JSON.",
    )
    source.add_argument(
        "--validate",
        nargs="?",
        const=str(DEFAULT_OUTPUT_JSON),
        help="Validate a generated JSON file.",
    )
    parser.add_argument(
        "--condition-refs-json",
        default=str(DEFAULT_CONDITION_REFS_JSON),
        help="JSON file that supplies condition_refs (default: config/tcd08_section_rules.json).",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_JSON),
        help="Output JSON path for --from-catalog.",
    )
    parser.add_argument(
        "--summary-json",
        default=str(DEFAULT_SUMMARY_JSON),
        help="Optional path to save generation summary JSON.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create a timestamped backup before overwriting output JSON.",
    )
    args = parser.parse_args()

    # Backward-compatible default: run catalog generation when no command is passed.
    if not args.from_catalog and not args.validate:
        args.from_catalog = str(DEFAULT_CATALOG_XLSX)

    return args


def print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def write_summary(path_text: str, data: dict[str, Any]) -> None:
    if not path_text:
        return
    path = Path(path_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as summary_file:
        json.dump(data, summary_file, ensure_ascii=False, indent=2)
        summary_file.write("\n")


def load_condition_refs(path: Path) -> dict[str, Any]:
    payload = read_rules_json(path)
    condition_refs = payload.get("condition_refs", {})
    if not isinstance(condition_refs, dict):
        raise CatalogGenerationError(f"condition_refs must be an object in {path}")
    return condition_refs


def main() -> int:
    args = parse_args()

    try:
        if args.from_catalog:
            catalog_path = Path(args.from_catalog)
            condition_refs = load_condition_refs(Path(args.condition_refs_json))
            generated = read_rules_catalog(catalog_path, condition_refs=condition_refs)
            validation = validate_rules(generated)
            validation.raise_if_invalid()

            output_path = Path(args.output)
            old_rules = read_rules_json(output_path) if output_path.exists() else None
            backup_path = write_rules_json(
                generated,
                output_path,
                backup=not args.no_backup,
            )
            result = {
                "catalog": str(catalog_path),
                "output": str(output_path),
                "backup": str(backup_path) if backup_path else None,
                "summary": summarize_rules(generated, old_rules=old_rules),
                "warnings": validation.warnings,
            }
            print_json(result)
            write_summary(args.summary_json, result)
            return 0

        if args.validate:
            rules = read_rules_json(Path(args.validate))
            validation = validate_rules(rules)
            result = {
                "valid": validation.ok,
                "summary": summarize_rules(rules),
                "errors": validation.errors,
                "warnings": validation.warnings,
            }
            print_json(result)
            write_summary(args.summary_json, result)
            return 0 if validation.ok else 1

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    raise CatalogGenerationError("No command was selected")


if __name__ == "__main__":
    raise SystemExit(main())
