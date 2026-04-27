"""Selective auto-import for MCP resources."""

import importlib
import os
from pathlib import Path

resources_dir = Path(__file__).parent

DEFAULT_RESOURCE_MODULES = {"version", "audio_files", "docs_resources", "changelog"}


def _parse_module_list(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def _all_resource_modules() -> set[str]:
    return {
        file.stem
        for file in resources_dir.glob("*.py")
        if file.name != "__init__.py" and not file.name.startswith("_")
    }


def _determine_resources_to_load() -> set[str]:
    all_modules = _all_resource_modules()
    enabled = os.environ.get("VOICEMODE_RESOURCES_ENABLED", "").strip()
    disabled = os.environ.get("VOICEMODE_RESOURCES_DISABLED", "").strip()

    if enabled:
        return _parse_module_list(enabled) & all_modules
    if disabled:
        return all_modules - _parse_module_list(disabled)
    return DEFAULT_RESOURCE_MODULES & all_modules


for module_name in sorted(_determine_resources_to_load()):
    importlib.import_module(f".{module_name}", package=__name__)
