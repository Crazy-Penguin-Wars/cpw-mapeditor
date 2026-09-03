"""Editor configuration loaded from editable JSON, not hard-coded UI values."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
with (ROOT / "config" / "editor.json").open(encoding="utf-8") as source:
    DATA = json.load(source)

THEMES = DATA["themes"]
MATERIAL_COLORS = DATA["material_colors"]
MATERIALS = list(MATERIAL_COLORS)
ITEM_MATERIALS = DATA["item_materials"]
TERRAIN_MATERIALS = DATA["terrain_materials"]
TERRAIN_TEXTURE_SWFS = DATA["terrain_texture_swfs"]
FIXTURES = {
    label: (spec["name"], spec["fixture"], *spec["size"])
    for label, spec in DATA["fixtures"].items()
}
ITEM_EXPORTS = {spec["name"]: spec["fixture"].replace("cube_big", "cube_large") for spec in DATA["fixtures"].values()}
DEFAULT_SETTINGS = DATA["default_settings"]
GRID_SIZE = DATA["grid_size"]
TEST_SERVER_URL = DATA["test_server_url"].rstrip("/")
PREVIEW_PARALLAX_OFFSET_X = GRID_SIZE * DATA["preview_parallax_offset_cells"]
PREVIEW_WATER_SURFACE_OFFSET = DATA["preview_water_surface_offset"]
TERRAIN_TOP_BORDER_ANGLE = DATA["terrain_top_border_angle"]
ASSET_ROOT = ROOT / "assets"
