"""The lossless .lvl JSON document model."""
import copy
import json
from .config import DEFAULT_SETTINGS

class LevelModel:
    def __init__(self): self.new()
    def new(self):
        self.settings = copy.deepcopy(DEFAULT_SETTINGS); self.elements = []; self.spawns = []; self.parallaxes = []; self.extra = {}; self.path = None
    def load(self, path):
        with open(path, encoding="utf-8") as source: raw = json.load(source)
        self.settings = copy.deepcopy(DEFAULT_SETTINGS); self.settings.update({key: raw[key] for key in DEFAULT_SETTINGS if key in raw})
        self.elements = copy.deepcopy(raw.get("elements", [])); self.spawns = copy.deepcopy(raw.get("spawn_points", [])); self.parallaxes = copy.deepcopy(raw.get("parallax_layers", []))
        known = set(DEFAULT_SETTINGS) | {"elements", "spawn_points", "parallax_layers", "power_ups", "power_up_percentage", "joints"}
        self.extra = {key: copy.deepcopy(value) for key, value in raw.items() if key not in known}
        for key in ("power_ups", "power_up_percentage", "joints"):
            if key in raw: self.extra[key] = copy.deepcopy(raw[key])
        self.path = path
    def snapshot(self):
        return {
            "settings": copy.deepcopy(self.settings),
            "elements": copy.deepcopy(self.elements),
            "spawns": copy.deepcopy(self.spawns),
            "parallaxes": copy.deepcopy(self.parallaxes),
            "extra": copy.deepcopy(self.extra),
        }

    def restore_snapshot(self, snap):
        self.settings = copy.deepcopy(snap["settings"])
        self.elements = copy.deepcopy(snap["elements"])
        self.spawns = copy.deepcopy(snap["spawns"])
        self.parallaxes = copy.deepcopy(snap["parallaxes"])
        self.extra = copy.deepcopy(snap["extra"])

    def data(self):
        result = copy.deepcopy(self.extra); result.update(copy.deepcopy(self.settings)); result.update(elements=copy.deepcopy(self.elements), spawn_points=copy.deepcopy(self.spawns), parallax_layers=copy.deepcopy(self.parallaxes)); return result
    def save(self, path):
        with open(path, "w", encoding="utf-8") as target: json.dump(self.data(), target, indent=2); target.write("\n")
        self.path = path
