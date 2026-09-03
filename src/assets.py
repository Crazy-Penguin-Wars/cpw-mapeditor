"""Asset-manifest access point for preview renderers."""
from pathlib import Path
import json
import re
from .config import ROOT

with (ROOT / "config" / "assets.json").open(encoding="utf-8") as source:
    MANIFEST = json.load(source)

def asset_folder(kind, name):
    """Return an asset folder from the editable manifest, or None."""
    relative = MANIFEST.get(kind, {}).get(name)
    return ROOT / relative if relative else None


def asset_path(kind, name):
    """Return an asset file path from the editable manifest, or None."""
    relative = MANIFEST.get(kind, {}).get(name)
    if not relative:
        return None
    path = ROOT / relative
    return path if path.exists() else None


def available_item_exports(material):
    """Return an explicit preview/placement allow-list, or None for all fixtures."""
    return MANIFEST.get("item_exports", {}).get(material)


def available_parallax_exports(theme):
    """List preview exports discovered from the theme's supplied PNG names."""
    folder = asset_folder("parallax", theme)
    if not folder or not folder.is_dir():
        return []
    exports = set()
    for image in folder.glob("*.png"):
        match = re.search(r"(parallax_\d+_\d+)\.png$", image.name)
        if match:
            exports.add(match.group(1))
    return sorted(exports, key=lambda export: tuple(map(int, export.rsplit("_", 2)[1:])), reverse=True)


def parallax_themes():
    """Return artwork themes installed in the asset manifest."""
    return list(MANIFEST.get("parallax", {}))


def parallax_theme_for_layer(layer, fallback):
    """Identify a layer's artwork theme from its game SWF path."""
    swf = str(layer.get("graphics_swf", "")).lower()
    for theme in parallax_themes():
        if f"level_bg_{theme.lower()}.swf" in swf:
            return theme
    return fallback
