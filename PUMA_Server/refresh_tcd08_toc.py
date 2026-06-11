from __future__ import annotations

import argparse
import sys
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parent
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from services.word.toc import update_tocs_with_word


WORD_SUFFIXES = {".docx", ".docm"}


def _collect_word_files(path: Path, recursive: bool = False) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in WORD_SUFFIXES else []

    if not path.is_dir():
        raise FileNotFoundError(f"Path not found: {path}")

    candidates = path.rglob("*") if recursive else path.iterdir()
    return sorted(
        candidate
        for candidate in candidates
        if candidate.is_file() and candidate.suffix.lower() in WORD_SUFFIXES
    )


def build_target_list(raw_paths: list[str], recursive: bool = False) -> list[Path]:
    targets: list[Path] = []
    seen: set[Path] = set()

    for raw_path in raw_paths:
        path = Path(raw_path).expanduser().resolve()
        for candidate in _collect_word_files(path, recursive=recursive):
            resolved_candidate = candidate.resolve()
            if resolved_candidate in seen:
                continue
            seen.add(resolved_candidate)
            targets.append(resolved_candidate)

    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh TOC for TCD08 report files on a local Windows machine with Microsoft Word.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="One or more .docx/.docm files, or folders containing generated TCD08 reports.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search folders recursively for Word documents.",
    )
    args = parser.parse_args(argv)

    targets = build_target_list(args.paths, recursive=args.recursive)
    if not targets:
        print("No Word documents found for TOC refresh.")
        return 0

    print(f"Refreshing TOC for {len(targets)} document(s)...")
    for target in targets:
        print(f"  - {target}")

    update_tocs_with_word(targets)
    print("TOC refresh completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())