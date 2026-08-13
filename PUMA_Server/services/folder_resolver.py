from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable


class FuzzyFolderError(RuntimeError):
    """Base error for fuzzy folder resolution."""


class FuzzyFolderAmbiguousError(FuzzyFolderError):
    """Raised when multiple folders are equally plausible matches."""


_SEPARATORS_RE = re.compile(r"[^0-9a-zA-Z]+")
_NUMBER_PREFIX_RE = re.compile(r"^\s*(\d{1,3})(?=\D|$)")
_GENERIC_TOKENS = {
    "folder",
    "dir",
    "directory",
}
_NEGATIVE_TOKENS = {
    "old",
    "backup",
    "bak",
    "archive",
    "archived",
    "temp",
    "tmp",
    "copy",
}


def normalize_folder_name(name: str) -> str:
    """
    Normalize a folder name for tolerant comparison.

    Examples:
        06_TCU_No_9_Sens_dir -> 06tcuno9sensdir
        06.TCU No 9         -> 06tcuno9
        06-TCU              -> 06tcu
        06TCU               -> 06tcu
    """
    text = unicodedata.normalize("NFKC", str(name or "")).casefold()
    return "".join(ch for ch in text if ch.isalnum())


def _tokens(name: str) -> list[str]:
    text = unicodedata.normalize("NFKC", str(name or "")).casefold()
    pieces = [x for x in _SEPARATORS_RE.split(text) if x]

    # Also split compact forms such as 06TCU / No9 into alpha/number pieces.
    compact_pieces: list[str] = []
    for piece in pieces:
        compact_pieces.extend(re.findall(r"[a-z]+|\d+", piece))

    return [x for x in compact_pieces if x and x not in _GENERIC_TOKENS]


def _number_prefix(name: str) -> str | None:
    match = _NUMBER_PREFIX_RE.match(str(name or ""))
    if not match:
        return None
    # 06 and 6 should be treated as the same folder number.
    try:
        return str(int(match.group(1)))
    except ValueError:
        return match.group(1)


def _score_folder_name(expected_name: str, candidate_name: str) -> float:
    expected_raw = str(expected_name or "").strip()
    candidate_raw = str(candidate_name or "").strip()

    if not expected_raw or not candidate_raw:
        return -1.0

    if expected_raw.casefold() == candidate_raw.casefold():
        return 10000.0

    expected_norm = normalize_folder_name(expected_raw)
    candidate_norm = normalize_folder_name(candidate_raw)

    if expected_norm == candidate_norm:
        return 9000.0

    score = 0.0

    expected_number = _number_prefix(expected_raw)
    candidate_number = _number_prefix(candidate_raw)
    if expected_number is not None:
        if candidate_number == expected_number:
            score += 500.0
        elif candidate_number is not None:
            # A different explicit folder number should almost never win.
            score -= 900.0

    expected_tokens = set(_tokens(expected_raw))
    candidate_tokens = set(_tokens(candidate_raw))

    # Ignore the leading directory number while measuring semantic keywords.
    if expected_number is not None:
        expected_tokens.discard(expected_number)
    if candidate_number is not None:
        candidate_tokens.discard(candidate_number)

    if expected_tokens:
        overlap = expected_tokens & candidate_tokens
        score += 350.0 * (len(overlap) / len(expected_tokens))

        # Strong bonus for important expected keywords that are literally present.
        for token in overlap:
            if len(token) >= 3:
                score += 35.0

    if expected_norm and candidate_norm:
        score += 180.0 * SequenceMatcher(None, expected_norm, candidate_norm).ratio()

        # Compact prefix forms such as 06TCU are useful short aliases for
        # 06_TCU_No_9_Sens_dir.
        if expected_norm.startswith(candidate_norm) or candidate_norm.startswith(expected_norm):
            score += 120.0

    negative_hits = _NEGATIVE_TOKENS & candidate_tokens
    expected_negative_hits = _NEGATIVE_TOKENS & expected_tokens
    for token in negative_hits - expected_negative_hits:
        score -= 120.0

    return score


def _iter_child_directories(parent: Path) -> Iterable[Path]:
    try:
        return [item for item in parent.iterdir() if item.is_dir()]
    except (OSError, PermissionError):
        return []


def resolve_fuzzy_folder(
    parent_path: str | Path,
    expected_name: str,
    *,
    min_score: float = 430.0,
    ambiguity_margin: float = 20.0,
) -> Path | None:
    """
    Resolve one folder level below ``parent_path``.

    Matching priority:
      1. Exact existing folder.
      2. Normalized exact match (ignores punctuation, spaces and case).
      3. Number + keyword + similarity scoring.

    Returns None when there is no safe match.  It does NOT create a folder.
    """
    parent = Path(parent_path)
    if not parent.is_dir():
        return None

    expected_name = str(expected_name or "").strip()
    if not expected_name:
        return None

    exact_path = parent / expected_name
    if exact_path.is_dir():
        return exact_path

    children = list(_iter_child_directories(parent))
    if not children:
        return None

    expected_norm = normalize_folder_name(expected_name)
    normalized_matches = [
        child for child in children if normalize_folder_name(child.name) == expected_norm
    ]
    if len(normalized_matches) == 1:
        return normalized_matches[0]
    if len(normalized_matches) > 1:
        names = ", ".join(sorted(child.name for child in normalized_matches))
        raise FuzzyFolderAmbiguousError(
            f"Multiple normalized folder matches for {expected_name!r} under {str(parent)!r}: {names}"
        )

    ranked = sorted(
        ((_score_folder_name(expected_name, child.name), child) for child in children),
        key=lambda item: (-item[0], len(item[1].name), item[1].name.casefold()),
    )

    best_score, best_path = ranked[0]
    if best_score < min_score:
        return None

    if len(ranked) > 1:
        second_score, second_path = ranked[1]
        if second_score >= min_score and abs(best_score - second_score) <= ambiguity_margin:
            raise FuzzyFolderAmbiguousError(
                "Ambiguous fuzzy folder match for "
                f"{expected_name!r} under {str(parent)!r}: "
                f"{best_path.name!r} (score={best_score:.1f}) and "
                f"{second_path.name!r} (score={second_score:.1f})."
            )

    return best_path


def resolve_fuzzy_relative_path(
    root_path: str | Path,
    relative_path: str,
) -> str:
    """
    Resolve every existing directory level of a Windows-style relative path.

    If a level does not yet exist, the remaining standard path is appended
    unchanged.  This preserves the existing behavior for output folders that
    need to be created later by the client/server.

    Important: fuzzy resolution can only inspect folders visible from the
    process running this function.  If ``root_path`` is a client-only C:\\ path
    and this code runs on the 8086 server, it cannot inspect that client disk;
    in that case the standard path is returned unchanged.
    """
    root_text = str(root_path or "").strip()
    relative_text = str(relative_path or "").strip()
    if not root_text:
        return relative_text
    if not relative_text:
        return root_text

    parts = [part for part in re.split(r"[\\/]+", relative_text) if part]
    if not parts:
        return root_text

    current = Path(root_text)
    resolved_parts: list[str] = []

    for index, expected_part in enumerate(parts):
        if current.is_dir():
            matched = resolve_fuzzy_folder(current, expected_part)
            if matched is not None:
                resolved_parts.append(matched.name)
                current = matched
                continue

        # Parent cannot be inspected or no safe match exists.  Keep this and
        # all remaining levels exactly as configured so creation still works.
        resolved_parts.extend(parts[index:])
        break

    separator = "\\"
    return root_text.rstrip("\\/") + separator + separator.join(resolved_parts)
