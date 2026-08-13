from __future__ import annotations

from typing import Any
from urllib.parse import quote

from services.folder_resolver import FuzzyFolderAmbiguousError, resolve_fuzzy_relative_path
from utils.file_loader import extract_root_paths, load_folder_mapping


CONFIGURED_STORAGE_TYPES = {"local", "public"}
# Keep the existing request compatibility. Cloud is intentionally not changed
# or added as a configured mapping type in this phase.
REQUEST_STORAGE_TYPES = CONFIGURED_STORAGE_TYPES | {"cloud"}


class PathResolverError(ValueError):
    """Base error raised when a configured project path cannot be resolved."""


class PathMappingNotFoundError(PathResolverError):
    """Raised when no FolderLinkMapping entry exists for a label."""


class InvalidPathMappingError(PathResolverError):
    """Raised when a FolderLinkMapping entry has an invalid shape or value."""


class MissingProjectRootError(PathResolverError):
    """Raised when the selected storage root is missing from the project."""


class TaskContextError(PathResolverError):
    """Raised when a path placeholder cannot be resolved from the task tree."""


def get_mapping_entry(label: str) -> dict[str, Any]:
    """Return one validated FolderLinkMapping entry by TagName."""
    mappings = load_folder_mapping()
    if not isinstance(mappings, list):
        raise InvalidPathMappingError("FolderLinkMapping.json must contain a list")

    for item in mappings:
        if not isinstance(item, dict):
            continue
        if item.get("TagName") == label:
            return item

    raise PathMappingNotFoundError(f"No mapping found for label={label}")


def _mapping_by_label(label: str) -> dict[str, Any]:
    return get_mapping_entry(label)


def _resolve_storage_type(
    label: str,
    configured_value: Any,
    requested_type: str | None,
) -> str:
    """Resolve configured storage first, then preserve the old request fallback."""
    if configured_value is not None and str(configured_value).strip():
        if not isinstance(configured_value, str):
            raise InvalidPathMappingError(
                f"Invalid StorageType for label={label!r}: expected 'local' or 'public', "
                f"got {configured_value!r}"
            )

        configured_type = configured_value.strip().lower()
        if configured_type not in CONFIGURED_STORAGE_TYPES:
            raise InvalidPathMappingError(
                f"Invalid StorageType for label={label!r}: expected 'local' or 'public', "
                f"got {configured_value!r}"
            )
        return configured_type

    fallback_type = str(requested_type or "").strip().lower() or "local"
    if fallback_type not in REQUEST_STORAGE_TYPES:
        raise PathResolverError(
            f"Invalid requested path type for label={label!r}: expected one of "
            f"{sorted(REQUEST_STORAGE_TYPES)}, got {requested_type!r}"
        )
    return fallback_type


def _find_level1_parent_name(task_tree: Any, target_task_id: str) -> str | None:
    if not isinstance(task_tree, list):
        return None

    for node in task_tree:
        if not isinstance(node, dict):
            continue
        for child1 in node.get("children", []):
            if not isinstance(child1, dict):
                continue
            if child1.get("id") == target_task_id:
                return child1.get("taskName")

            for child2 in child1.get("children", []):
                if isinstance(child2, dict) and child2.get("id") == target_task_id:
                    return child1.get("taskName")

    return None


def _find_level1_name_under_root(task_tree: Any, target_task_id: str) -> str | None:
    if not isinstance(task_tree, list):
        return None

    for node in task_tree:
        if not isinstance(node, dict):
            continue
        for child1 in node.get("children", []):
            if not isinstance(child1, dict):
                continue
            if child1.get("id") == target_task_id:
                return child1.get("taskName")

            for child2 in child1.get("children", []):
                if isinstance(child2, dict) and child2.get("id") == target_task_id:
                    return child1.get("taskName")

    return None


def _replace_task_placeholders(
    path: str,
    *,
    task_tree: Any,
    task_id: str,
) -> str:
    if "AlgoID" in path:
        level1_name = _find_level1_parent_name(task_tree, task_id)
        if not level1_name:
            raise TaskContextError(f"Cannot find level1 parent for taskId {task_id}")
        path = path.replace("AlgoID", level1_name)

    if "ProjectID_Parameter_ID" in path:
        level1_name = _find_level1_name_under_root(task_tree, task_id)
        if not level1_name:
            raise TaskContextError(
                f"Cannot find parameter-level1 parent for taskId {task_id}"
            )
        path = path.replace("ProjectID_Parameter_ID", level1_name)

    return path


def _is_url(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def resolve_path(
    *,
    project_info: Any,
    project_workflow: Any,
    label: str,
    task_id: str = "",
    requested_type: str | None = None,
) -> dict[str, str | bool]:
    """Resolve one FolderLinkMapping entry into the final project path.

    Resolution order is intentionally:
      1. AbsolutePath;
      2. RelativePath with configured StorageType;
      3. RelativePath with the legacy requested type fallback.

    ``project_info`` is the flattened projectInfo list. ``project_workflow`` is
    the decoded workflow dictionary. This service does not query the database
    and does not perform filesystem operations.
    """
    if isinstance(project_info, dict):
        project_info = project_info.get("projectInfo", [])

    mapping = _mapping_by_label(label)
    absolute_path = str(mapping.get("AbsolutePath") or "").strip()
    relative_path = str(mapping.get("RelativePath") or "").strip()
    task_tree = (
        project_workflow.get("taskTree", [])
        if isinstance(project_workflow, dict)
        else []
    )

    # AbsolutePath is authoritative. Do not validate or use a requested type
    # for fixed directories and URLs.
    if absolute_path:
        final_path = _replace_task_placeholders(
            absolute_path,
            task_tree=task_tree,
            task_id=task_id,
        )
        return {
            "success": True,
            "root": "(absolute)",
            "path": final_path,
            "storage_type": "absolute",
        }

    if not relative_path:
        raise InvalidPathMappingError(f"No RelativePath found for label={label}")

    storage_type = _resolve_storage_type(
        label,
        mapping.get("StorageType"),
        requested_type,
    )
    root_paths = extract_root_paths(project_info)
    root = root_paths.get(storage_type)
    if not root:
        root_label = {
            "local": "Local Link",
            "public": "Public Link",
            "cloud": "SharePoint",
        }.get(storage_type, storage_type)
        raise MissingProjectRootError(
            f"Project does not define {root_label} required by "
            f"label={label!r}, storage_type={storage_type!r}"
        )

    relative_path = _replace_task_placeholders(
        relative_path,
        task_tree=task_tree,
        task_id=task_id,
    )

    if _is_url(str(root)):
        relative_parts = [
            quote(part)
            for part in relative_path.replace("\\", "/").split("/")
            if part
        ]
        final_path = str(root).rstrip("/") + "/" + "/".join(relative_parts)
    elif storage_type == "cloud":
        final_path = str(root).rstrip("/") + "/" + relative_path.lstrip("\\/")
    else:
        try:
            # FolderLinkMapping keeps the standard directory names. When the
            # server can inspect this root (for example a Public Link/UNC),
            # return the safest matching real directory name instead.
            final_path = resolve_fuzzy_relative_path(str(root), relative_path)
        except FuzzyFolderAmbiguousError as exc:
            raise PathResolverError(
                f"Ambiguous folder mapping for label={label!r}: {exc}"
            ) from exc

    return {
        "success": True,
        "root": str(root),
        "path": final_path,
        "storage_type": storage_type,
    }
