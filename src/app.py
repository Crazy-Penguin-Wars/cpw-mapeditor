"""Editor window and high-level document commands."""
from __future__ import annotations
import copy
import os
import json
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from PIL import Image, ImageTk
from .canvas import MapCanvas
from .assets import available_item_exports
from .config import FIXTURES, ITEM_EXPORTS, ITEM_MATERIALS, TERRAIN_MATERIALS, TEST_SERVER_URL, THEMES
from .dialogs import ItemDialog, LayerDialog, PositionDialog, TerrainDialog
from .model import LevelModel
import subprocess


class Editor(tk.Tk):
    def __init__(self):
        super().__init__(); self.title("Crazy Penguin Wars: Map Editor"); self.geometry("1440x900"); self.minsize(1020, 650)
        # Set app icon (True = apply to all future Toplevel windows too)
        try:
            from .config import ROOT as _ROOT
            _icon_img = Image.open(_ROOT / "assets" / "icon.png")
            self._app_icon = ImageTk.PhotoImage(_icon_img)
            self.wm_iconphoto(True, self._app_icon)
        except Exception:
            pass
        self.model = LevelModel(); self.dirty = False; self.terrain_material = tk.StringVar(value="Wood"); self.grass = tk.BooleanVar(value=True); self.show_parallax_images = tk.BooleanVar(value=True); self.show_background_gradient = tk.BooleanVar(value=True); self.show_game_client_size = tk.BooleanVar(value=False); self.show_terrain = tk.BooleanVar(value=True); self.show_terrain_images = tk.BooleanVar(value=True); self.show_water_images = tk.BooleanVar(value=True); self.show_items = tk.BooleanVar(value=True); self.show_item_labels = tk.BooleanVar(value=False); self.show_spawnpoints = tk.BooleanVar(value=True); self.show_reference_image = tk.BooleanVar(value=True)
        self.reference_image_pil = None
        self.reference_image_path = None
        self.reference_image_scale_mode = "fit"  # "fit" or "original"
        self._prev_terrain_images = True  # remembered value when Terrain is toggled off
        self._prev_item_labels = False    # remembered value when Items is toggled off
        self.undo_stack = []
        self.redo_stack = []
        self._build_ui()
        self.bind_all("<Control-n>", lambda e: self.new())
        self.bind_all("<Control-N>", lambda e: self.new())
        self.bind_all("<Control-o>", lambda e: self.open_level())
        self.bind_all("<Control-O>", lambda e: self.open_level())
        self.bind_all("<Control-s>", lambda e: self.save())
        self.bind_all("<Control-S>", lambda e: self.save())
        self.bind_all("<Control-z>", lambda e: self.undo())
        self.bind_all("<Control-Z>", lambda e: self.undo())
        self.bind_all("<Control-y>", lambda e: self.redo())
        self.bind_all("<Control-Y>", lambda e: self.redo())
        self.bind_all("<Control-Shift-Z>", lambda e: self.redo())
        self.bind_all("<Control-Shift-z>", lambda e: self.redo())
        self.bind_all("<Delete>", lambda e: self.context_delete())
        self.bind_all("<Return>", lambda e: self.canvas.finish_polygon() if self.canvas.tool == "terrain" else None)
        self.bind_all("<Escape>", lambda e: self.canvas.handle_escape())
        for key, (dx, dy) in [
            ("<Left>", (-1, 0)), ("<Right>", (1, 0)),
            ("<Up>", (0, -1)), ("<Down>", (0, 1)),
            ("<Shift-Left>", (-1, 0)), ("<Shift-Right>", (1, 0)),
            ("<Shift-Up>", (0, -1)), ("<Shift-Down>", (0, 1)),
        ]:
            self.bind_all(key, lambda e, dx=dx, dy=dy: self._handle_arrow_key(dx, dy, e))
        self.after(100, self.canvas.fit)

    def _handle_arrow_key(self, dx, dy, event):
        focused = self.focus_get()
        if isinstance(focused, (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox, tk.Listbox)):
            return
        self.canvas.nudge_selected(dx, dy, event)

    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 8)); top.pack(fill="x")

        # File dropdown menu
        file_btn = ttk.Menubutton(top, text="File")
        file_menu = tk.Menu(file_btn, tearoff=False)
        file_menu.add_command(label="New", command=self.new, accelerator="Ctrl+N")
        file_menu.add_command(label="Open…", command=self.open_level, accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self.save, accelerator="Ctrl+S")
        file_menu.add_command(label="Save as…", command=self.save_as)
        file_btn["menu"] = file_menu
        file_btn.pack(side="left", padx=(0, 2))

        # Edit dropdown menu
        edit_btn = ttk.Menubutton(top, text="Edit")
        self.edit_menu = tk.Menu(edit_btn, tearoff=False)
        self.edit_menu.add_command(label="Undo", command=self.undo, accelerator="Ctrl+Z")
        self.edit_menu.add_command(label="Redo", command=self.redo, accelerator="Ctrl+Y")
        edit_btn["menu"] = self.edit_menu
        edit_btn.pack(side="left", padx=(0, 2))

        # Example levels bundled with the editor
        examples_btn = ttk.Menubutton(top, text="Examples")
        examples_menu = tk.Menu(examples_btn, tearoff=False)
        examples_dir = Path(__file__).resolve().parents[1] / "examples"
        for example_path in sorted(examples_dir.glob("*.lvl")):
            label = example_path.stem.replace("_", " ").title()
            examples_menu.add_command(label=label, command=lambda path=example_path: self.open_level_path(path))
        examples_btn["menu"] = examples_menu
        examples_btn.pack(side="left", padx=(0, 5))

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8)

        # Tools: Select, Pan, Place spawnpoint
        for text, tool in [("Select", "select"), ("Pan", "pan"), ("Place spawnpoint", "spawn")]:
            ttk.Button(top, text=text, command=lambda t=tool: self.canvas.set_tool(t)).pack(side="left", padx=2)

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8)

        # Rescale map & Load screenshot
        ttk.Button(top, text="Rescale map", command=self.rescale_map).pack(side="left", padx=2)
        ttk.Button(top, text="Load screenshot", command=self.load_screenshot).pack(side="left", padx=2)

        # Test in game on the right
        ttk.Button(top, text="Test in game", command=self.test_in_game).pack(side="right")

        body = ttk.PanedWindow(self, orient="horizontal"); body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        left = ttk.Frame(body, padding=8); center = ttk.Frame(body); right = ttk.Frame(body, padding=8); body.add(left, weight=0); body.add(center, weight=1); body.add(right, weight=0)
        # Create the canvas before the option panels: their preview toggles bind to it.
        self.canvas = MapCanvas(center, self); self.canvas.pack(fill="both", expand=True)
        self._build_left(left); self._build_right(right)
        self.status = tk.StringVar(value="Ready. Open a .lvl or start drawing."); ttk.Label(self, textvariable=self.status, anchor="w", relief="sunken", padding=(10, 4)).pack(fill="x")

    def _build_left(self, frame):
        ttk.Label(frame, text="Build", font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        box = ttk.LabelFrame(frame, text="Terrain", padding=8); box.pack(fill="x", pady=(6, 8))
        ttk.Label(box, text="Material").pack(anchor="w"); ttk.Combobox(box, textvariable=self.terrain_material, values=TERRAIN_MATERIALS, state="readonly", width=16).pack(fill="x", pady=(2, 4))
        ttk.Checkbutton(box, text="Grass on top", variable=self.grass).pack(anchor="w", pady=(0, 6))
        ttk.Button(box, text="Place Element", command=lambda: self.canvas.set_tool("terrain")).pack(fill="x")
        ttk.Label(box, text="Right-click an existing element for extra options", foreground="#59656d", wraplength=170).pack(anchor="w", pady=(6, 0))
        box = ttk.LabelFrame(frame, text="Item", padding=8); box.pack(fill="x", pady=(0, 8))
        self.item_material = tk.StringVar(value="Wood"); self.item_fixture = tk.StringVar(value="Cube medium")
        ttk.Label(box, text="Material").pack(anchor="w"); ttk.Combobox(box, textvariable=self.item_material, values=ITEM_MATERIALS, state="readonly", width=16).pack(fill="x", pady=(2, 5))
        ttk.Label(box, text="Fixture").pack(anchor="w"); self.item_fixture_box = ttk.Combobox(box, textvariable=self.item_fixture, state="readonly", width=16); self.item_fixture_box.pack(fill="x", pady=(2, 6))
        self.item_material.trace_add("write", self.refresh_item_fixtures)
        self.refresh_item_fixtures()
        ttk.Button(box, text="Place Item", command=lambda: self.canvas.set_tool("item")).pack(fill="x")
        ttk.Label(box, text="Right-click an existing item for extra options", foreground="#59656d", wraplength=170).pack(anchor="w", pady=(6, 0))
        box = ttk.LabelFrame(frame, text="Preview", padding=8); box.pack(fill="x")
        ttk.Checkbutton(box, text="Grid", variable=self.canvas.show_grid, command=self.canvas.draw).pack(anchor="w")
        ttk.Checkbutton(box, text="Spawnpoints", variable=self.show_spawnpoints, command=self.canvas.draw).pack(anchor="w")
        ttk.Checkbutton(box, text="Terrain", variable=self.show_terrain, command=self._on_show_terrain_changed).pack(anchor="w")
        row_terrain_img = ttk.Frame(box); row_terrain_img.pack(fill="x", anchor="w")
        self.lbl_terrain_tree = ttk.Label(row_terrain_img, text="   └ ")
        self.lbl_terrain_tree.pack(side="left")
        self.cb_terrain_images = ttk.Checkbutton(row_terrain_img, text="Terrain images", variable=self.show_terrain_images, command=self.canvas.draw)
        self.cb_terrain_images.pack(side="left")
        ttk.Checkbutton(box, text="Water", variable=self.show_water_images, command=self.canvas.draw).pack(anchor="w")
        ttk.Checkbutton(box, text="Items", variable=self.show_items, command=self._on_show_items_changed).pack(anchor="w")
        row_item_lbl = ttk.Frame(box); row_item_lbl.pack(fill="x", anchor="w")
        self.lbl_item_tree = ttk.Label(row_item_lbl, text="   └ ")
        self.lbl_item_tree.pack(side="left")
        self.cb_item_labels = ttk.Checkbutton(row_item_lbl, text="Item labels", variable=self.show_item_labels, command=self.canvas.draw)
        self.cb_item_labels.pack(side="left")
        ttk.Checkbutton(box, text="Parallax layers", variable=self.show_parallax_images, command=self.canvas.draw).pack(anchor="w")
        ttk.Checkbutton(box, text="Background gradient", variable=self.show_background_gradient, command=self.canvas.draw).pack(anchor="w")
        ttk.Checkbutton(box, text="Game client size", variable=self.show_game_client_size, command=self.canvas.draw).pack(anchor="w")
        ttk.Checkbutton(box, text="Screenshot", variable=self.show_reference_image, command=self.canvas.draw).pack(anchor="w")

    def refresh_item_fixtures(self, *_):
        """Limit the item selector to the assets that exist for this material."""
        allowed_exports = available_item_exports(self.item_material.get())
        labels = [
            label for label, (name, *_rest) in FIXTURES.items()
            if allowed_exports is None or ITEM_EXPORTS[name] in allowed_exports
        ]
        self.item_fixture_box["values"] = labels
        if self.item_fixture.get() not in labels:
            self.item_fixture.set(labels[0] if labels else "")

    def _build_right(self, frame):
        settings = ttk.LabelFrame(frame, text="Level settings", padding=8)
        settings.pack(fill="x")
        settings.columnconfigure(0, weight=1)
        settings.columnconfigure(1, weight=1)

        self.setting_vars = {
            key: tk.StringVar(value=str(self.model.settings.get(key, "")))
            for key in (
                "level_name", "theme", "zoom_side", "width", "height",
                "water_line", "water_density", "water_lineardrag", "water_angulardrag",
                "water_velocity_x", "water_velocity_y"
            )
        }

        # Row 0: Name (full width)
        ttk.Label(settings, text="Name").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 1))
        ttk.Entry(settings, textvariable=self.setting_vars["level_name"]).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        # Row 1: Theme & Zoom side
        ttk.Label(settings, text="Theme").grid(row=2, column=0, sticky="w", pady=(0, 1), padx=(0, 4))
        ttk.Label(settings, text="Zoom side").grid(row=2, column=1, sticky="w", pady=(0, 1), padx=(4, 0))
        ttk.Combobox(settings, textvariable=self.setting_vars["theme"], values=list(THEMES), state="readonly", width=10).grid(row=3, column=0, sticky="ew", pady=(0, 4), padx=(0, 4))
        ttk.Combobox(settings, textvariable=self.setting_vars["zoom_side"], values=("width", "height"), state="readonly", width=10).grid(row=3, column=1, sticky="ew", pady=(0, 4), padx=(4, 0))

        # Row 2: Width & Height
        ttk.Label(settings, text="Width").grid(row=4, column=0, sticky="w", pady=(0, 1), padx=(0, 4))
        ttk.Label(settings, text="Height").grid(row=4, column=1, sticky="w", pady=(0, 1), padx=(4, 0))
        ttk.Entry(settings, textvariable=self.setting_vars["width"], width=10).grid(row=5, column=0, sticky="ew", pady=(0, 4), padx=(0, 4))
        ttk.Entry(settings, textvariable=self.setting_vars["height"], width=10).grid(row=5, column=1, sticky="ew", pady=(0, 4), padx=(4, 0))

        # Row 3: Water line & Water density
        ttk.Label(settings, text="Water line").grid(row=6, column=0, sticky="w", pady=(0, 1), padx=(0, 4))
        ttk.Label(settings, text="Water density").grid(row=6, column=1, sticky="w", pady=(0, 1), padx=(4, 0))
        ttk.Entry(settings, textvariable=self.setting_vars["water_line"], width=10).grid(row=7, column=0, sticky="ew", pady=(0, 4), padx=(0, 4))
        ttk.Entry(settings, textvariable=self.setting_vars["water_density"], width=10).grid(row=7, column=1, sticky="ew", pady=(0, 4), padx=(4, 0))

        # Row 4: Linear drag & Angular drag
        ttk.Label(settings, text="Water linear drag").grid(row=8, column=0, sticky="w", pady=(0, 1), padx=(0, 4))
        ttk.Label(settings, text="Water angular drag").grid(row=8, column=1, sticky="w", pady=(0, 1), padx=(4, 0))
        ttk.Entry(settings, textvariable=self.setting_vars["water_lineardrag"], width=10).grid(row=9, column=0, sticky="ew", pady=(0, 4), padx=(0, 4))
        ttk.Entry(settings, textvariable=self.setting_vars["water_angulardrag"], width=10).grid(row=9, column=1, sticky="ew", pady=(0, 4), padx=(4, 0))

        # Row 5: Water velocity X & Y
        ttk.Label(settings, text="Water velocity X").grid(row=10, column=0, sticky="w", pady=(0, 1), padx=(0, 4))
        ttk.Label(settings, text="Water velocity Y").grid(row=10, column=1, sticky="w", pady=(0, 1), padx=(4, 0))
        ttk.Entry(settings, textvariable=self.setting_vars["water_velocity_x"], width=10).grid(row=11, column=0, sticky="ew", pady=(0, 4), padx=(0, 4))
        ttk.Entry(settings, textvariable=self.setting_vars["water_velocity_y"], width=10).grid(row=11, column=1, sticky="ew", pady=(0, 4), padx=(4, 0))

        ttk.Button(settings, text="Apply settings", command=self.apply_settings).grid(row=12, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        layers = ttk.LabelFrame(frame, text="Parallax layers (front → back)", padding=8); layers.pack(fill="both", expand=True, pady=(8, 0))
        self.layer_list = tk.Listbox(layers, height=10, exportselection=False); self.layer_list.pack(fill="both", expand=True)
        self.layer_list.bind("<Button-1>", self.on_layer_list_click)
        self.layer_list.bind("<ButtonRelease-1>", lambda e: self.after_idle(self.canvas.focus_set), add="+")
        self.layer_list.bind("<<ListboxSelect>>", self.layer_selected)
        for key, (dx, dy) in [
            ("<Left>", (-1, 0)), ("<Right>", (1, 0)),
            ("<Up>", (0, -1)), ("<Down>", (0, 1)),
            ("<Shift-Left>", (-1, 0)), ("<Shift-Right>", (1, 0)),
            ("<Shift-Up>", (0, -1)), ("<Shift-Down>", (0, 1)),
        ]:
            self.layer_list.bind(key, lambda e, dx=dx, dy=dy: [self.canvas.nudge_selected(dx, dy, e), "break"][-1])
        buttons = ttk.Frame(layers); buttons.pack(fill="x", pady=(5, 0))
        for text, command in [("Add", self.add_layer), ("Edit", self.edit_layer), ("Remove", self.remove_layer), ("↑", lambda: self.move_layer(-1)), ("↓", lambda: self.move_layer(1))]: ttk.Button(buttons, text=text, command=command).pack(side="left", padx=1)

    def push_undo(self, description=""):
        snapshot = {
            "model": self.model.snapshot(),
            "selected": copy.deepcopy(self.canvas.selected),
            "description": description,
        }
        self.undo_stack.append(snapshot)
        if len(self.undo_stack) > 100:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.dirty = True

    def undo(self):
        if not self.undo_stack:
            self.set_status("Nothing to undo.")
            return
        current = {
            "model": self.model.snapshot(),
            "selected": copy.deepcopy(self.canvas.selected),
            "description": "Current state",
        }
        self.redo_stack.append(current)
        prev = self.undo_stack.pop()
        self.model.restore_snapshot(prev["model"])
        self.canvas.selected = copy.deepcopy(prev.get("selected"))
        self.dirty = True
        self.sync_settings()
        self.refresh_lists()
        self.canvas.draw()
        desc = prev.get("description", "")
        self.set_status(f"Undid {desc}." if desc else "Undid last action.")

    def redo(self):
        if not self.redo_stack:
            self.set_status("Nothing to redo.")
            return
        current = {
            "model": self.model.snapshot(),
            "selected": copy.deepcopy(self.canvas.selected),
            "description": "Current state",
        }
        self.undo_stack.append(current)
        nxt = self.redo_stack.pop()
        self.model.restore_snapshot(nxt["model"])
        self.canvas.selected = copy.deepcopy(nxt.get("selected"))
        self.dirty = True
        self.sync_settings()
        self.refresh_lists()
        self.canvas.draw()
        desc = nxt.get("description", "")
        self.set_status(f"Redid {desc}." if desc else "Redid last action.")

    def apply_settings(self):
        try:
            new_settings = {}
            for key, var in self.setting_vars.items():
                value = var.get().strip()
                new_settings[key] = value if key in ("level_name", "theme", "zoom_side") else float(value)
            new_settings["width"] = int(new_settings["width"]); new_settings["height"] = int(new_settings["height"])
        except ValueError: messagebox.showerror("Invalid setting", "Width, height, water line and physics values must be numbers."); return
        changed = any(self.model.settings.get(k) != v for k, v in new_settings.items())
        if changed:
            self.push_undo("apply level settings")
            self.model.settings.update(new_settings)
            self.dirty = True
            self.canvas.fit()
            self.set_status("Settings applied.")

    def sync_settings(self):
        for key, var in self.setting_vars.items(): var.set(str(self.model.settings.get(key, "")))

    def place_item(self, x, y, angle=0.0, unbreakable=False, sleep=False):
        if not self.show_items.get():
            self.show_items.set(True)
            self._on_show_items_changed()
        self.push_undo("place dynamic item")
        label = self.item_fixture.get(); name, fixture, _, _ = FIXTURES[label]
        self.model.elements.append({
            "id": f"dynamic_{len(self.model.elements) + 1}",
            "element_type": "DynamicObject",
            "unbreakable": bool(unbreakable),
            "sleep": bool(sleep),
            "angle": round(float(angle), 2),
            "x": round(x, 2),
            "y": round(y, 2),
            "theme": self.item_material.get(),
            "fixture": fixture,
            "name": name,
        })
        self.canvas.selected = ("element", len(self.model.elements)-1); self.dirty = True; self.canvas.draw()

    def place_spawn(self, x, y):
        self.push_undo("place spawnpoint")
        self.model.spawns.append({"x": round(x, 2), "y": round(y, 2), "name": f"SpawnPoint{len(self.model.spawns)}"})
        self.canvas.selected = ("spawn", len(self.model.spawns)-1); self.dirty = True; self.canvas.draw()

    def selection_changed(self, hit):
        if hit:
            self.layer_list.selection_clear(0, "end")
        self.set_status(f"Selected {hit[0]} {hit[1]+1}." if hit else "Ready.")

    def open_context(self, hit):
        kind, i = hit
        if kind == "spawn": PositionDialog(self, "Spawn point", self.model.spawns[i], lambda x, y: self.update_position("spawn", i, x, y), lambda: self.delete_hit(hit))
        else:
            e = self.model.elements[i]
            if e.get("element_type") == "TerrainBlockEntity": TerrainDialog(self, e, lambda value: self.replace_element(i, value), lambda: self.delete_hit(hit))
            else: ItemDialog(self, e, lambda value: self.replace_element(i, value), lambda: self.delete_hit(hit))

    def replace_element(self, i, value):
        self.push_undo("edit terrain" if value.get("element_type") == "TerrainBlockEntity" else "edit item")
        self.model.elements[i] = value
        self.dirty = True
        self.canvas.draw()
        self.set_status("Item updated." if value.get("element_type") != "TerrainBlockEntity" else "Terrain updated.")

    def update_position(self, kind, index, x, y):
        self.push_undo("update position")
        value = self.model.elements[index] if kind == "element" else self.model.spawns[index]
        value["x"], value["y"] = x, y
        self.canvas.selected = (kind, index)
        self.dirty = True
        self.canvas.draw()
        self.set_status("Position updated.")
    def delete_hit(self, hit):
        self.canvas.selected = hit
        self.context_delete()
    def context_delete(self):
        if not self.canvas.selected: return
        kind, i = self.canvas.selected
        self.push_undo(f"delete {kind}")
        if kind == "spawn": self.model.spawns.pop(i); [s.update(name=f"SpawnPoint{n}") for n, s in enumerate(self.model.spawns)]
        else: self.model.elements.pop(i)
        self.canvas.selected = None; self.dirty = True; self.refresh_lists(); self.canvas.draw(); self.set_status("Deleted selected element.")
    def refresh_lists(self):
        self.layer_list.delete(0, "end")
        for i, layer in enumerate(self.model.parallaxes): self.layer_list.insert("end", f"{i+1}. {', '.join(layer.get('graphics_export', [])) or 'Untitled'}  @ ({layer.get('x', 0)}, {layer.get('y', 0)})")
    def on_layer_list_click(self, event):
        nearest_idx = self.layer_list.nearest(event.y)
        bbox = self.layer_list.bbox(nearest_idx)
        if not bbox or event.y < bbox[1] or event.y > bbox[1] + bbox[3]:
            self.layer_list.selection_clear(0, "end")
            self.canvas.draw()
            self.set_status("Ready.")
            return "break"
    def layer_selected(self, event=None):
        indices = self.layer_list.curselection()
        if indices:
            self.canvas.selected = None
            self.after_idle(self.canvas.focus_set)
            self.set_status(f"Selected parallax layer {indices[0] + 1}.")
        self.canvas.draw()
    def _on_show_terrain_changed(self):
        state = "normal" if self.show_terrain.get() else "disabled"
        self.lbl_terrain_tree.configure(state=state)
        self.cb_terrain_images.configure(state=state)
        self.canvas.draw()

    def _on_show_items_changed(self):
        state = "normal" if self.show_items.get() else "disabled"
        self.lbl_item_tree.configure(state=state)
        self.cb_item_labels.configure(state=state)
        self.canvas.draw()
    def add_layer(self):
        theme = self.model.settings["theme"]
        layer = {"element_type":"ParallaxLayer", "camera_y_pan":0, "graphics_export":[], "graphics_swf": f"level_graphics/level_bg_{theme.lower()}.swf", "camera_z":0, "id":"parallax_1", "gap":800, "y":800, "camera_x_pan":0, "tile_horizontally":True, "x":0}
        LayerDialog(self, layer, theme, self.append_layer)
    def append_layer(self, layer):
        self.push_undo("add parallax layer")
        self.model.parallaxes.append(layer); self.dirty = True; self.refresh_lists(); self.layer_list.selection_set("end"); self.canvas.draw()
    def current_layer(self):
        selection = self.layer_list.curselection(); return selection[0] if selection else None
    def edit_layer(self):
        i = self.current_layer()
        if i is None: self.set_status("Select a parallax layer first."); return
        LayerDialog(self, self.model.parallaxes[i], self.model.settings["theme"], lambda value: self.replace_layer(i, value))
    def replace_layer(self, i, value):
        self.push_undo("edit parallax layer")
        self.model.parallaxes[i] = value; self.dirty = True; self.refresh_lists(); self.layer_list.selection_set(i); self.canvas.draw()
    def remove_layer(self):
        i = self.current_layer()
        if i is not None:
            self.push_undo("remove parallax layer")
            self.model.parallaxes.pop(i); self.dirty = True; self.refresh_lists(); self.canvas.draw()
    def move_layer(self, direction):
        i = self.current_layer(); j = None if i is None else i + direction
        if j is not None and 0 <= j < len(self.model.parallaxes):
            self.push_undo("reorder parallax layers")
            self.model.parallaxes[i], self.model.parallaxes[j] = self.model.parallaxes[j], self.model.parallaxes[i]; self.dirty = True; self.refresh_lists(); self.layer_list.selection_set(j); self.canvas.draw()
    def rescale_map(self):
        """Ask for a scale factor and uniformly resize all world-space coordinates."""
        dialog = tk.Toplevel(self)
        dialog.title("Rescale map")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        s = self.model.settings
        w, h = float(s.get("width", 3000)), float(s.get("height", 1174))
        wl = float(s.get("water_line", 880))

        ttk.Label(dialog, text="Scale factor:", padding=(12, 12, 12, 4)).pack(anchor="w")
        factor_var = tk.StringVar(value="1.0")
        entry = ttk.Entry(dialog, textvariable=factor_var, width=16)
        entry.pack(padx=12, pady=(0, 4))
        entry.select_range(0, "end")
        entry.focus_set()

        # Explanatory note
        ttk.Label(
            dialog,
            text="This is useful if you don't know the exact scale of a map when making it. Unlike terrain elements, penguins and items are fixed sized and might look very big or small if your terrain is on a different scale.",
            wraplength=320,
            foreground="#59656d",
            padding=(12, 4, 12, 6)
        ).pack(anchor="w")

        # Live preview of resulting dimensions
        info_var = tk.StringVar()
        ttk.Label(dialog, textvariable=info_var, foreground="#59656d", padding=(12, 0, 12, 0)).pack(anchor="w")

        def _update_info(*_):
            try:
                f = float(factor_var.get())
                info_var.set(f"Result: {round(w * f)} × {round(h * f)}, water line {round(wl * f)}")
            except ValueError:
                info_var.set("Enter a valid number")

        factor_var.trace_add("write", _update_info)
        _update_info()

        def _apply():
            try:
                factor = float(factor_var.get())
            except ValueError:
                messagebox.showerror("Invalid factor", "Please enter a valid number.", parent=dialog)
                return
            if factor <= 0:
                messagebox.showerror("Invalid factor", "Scale factor must be greater than 0.", parent=dialog)
                return
            if not messagebox.askyesno(
                "Confirm rescale",
                f"Scale all elements by ×{factor}?\n\n"
                f"Map size: {round(w)} × {round(h)}  →  {round(w * factor)} × {round(h * factor)}\n"
                f"Water line: {round(wl)}  →  {round(wl * factor)}\n\n"
                "This cannot be undone.",
                parent=dialog,
            ):
                return
            dialog.destroy()
            self._apply_rescale(factor)

        buttons = ttk.Frame(dialog, padding=(12, 8, 12, 12))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Apply", command=_apply).pack(side="right", padx=(4, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right")
        dialog.bind("<Return>", lambda e: _apply())
        dialog.bind("<Escape>", lambda e: dialog.destroy())

        # Centre dialog over the editor window
        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = self.winfo_y() + (self.winfo_height() - dialog.winfo_reqheight()) // 3
        dialog.geometry(f"+{x}+{y}")

    def _apply_rescale(self, factor: float):
        """Apply a uniform scale factor to every world-space coordinate in the map."""
        self.push_undo(f"rescale map by ×{factor}")
        s = self.model.settings

        # --- Map dimensions & key scalars ---
        for key in ("width", "height"):
            s[key] = round(float(s[key]) * factor)
        for key in ("water_line",):
            if key in s:
                s[key] = round(float(s[key]) * factor, 2)

        # --- Terrain polygon points ---
        for e in self.model.elements:
            if e.get("element_type") == "TerrainBlockEntity":
                e["points"] = [
                    {"x": round(float(p["x"]) * factor, 2), "y": round(float(p["y"]) * factor, 2)}
                    for p in e.get("points", [])
                ]
            else:
                # Items / physics objects
                if "x" in e:
                    e["x"] = round(float(e["x"]) * factor, 2)
                if "y" in e:
                    e["y"] = round(float(e["y"]) * factor, 2)

        # --- Spawn points ---
        for sp in self.model.spawns:
            sp["x"] = round(float(sp["x"]) * factor, 2)
            sp["y"] = round(float(sp["y"]) * factor, 2)

        # --- Parallax layers (x, y, gap) ---
        for layer in self.model.parallaxes:
            for key in ("x", "y", "gap"):
                if key in layer:
                    layer[key] = round(float(layer[key]) * factor, 2)

        self.dirty = True
        self.sync_settings()
        self.canvas.fit()
        self.set_status(f"Map rescaled by ×{factor}. New size: {s['width']} × {s['height']}.")

    def _clear_reference_image(self):
        """Discard the loaded reference screenshot and clear its cache."""
        self.reference_image_pil = None
        self.reference_image_path = None
        self.canvas._reference_scaled.clear()

    def new(self):
        if not self.confirm_discard(): return
        self._clear_reference_image()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.model.new(); self.dirty = False; self.sync_settings(); self.refresh_lists(); self.canvas.fit(); self.set_status("New level.")
    def open_level(self):
        if not self.confirm_discard(): return
        path = filedialog.askopenfilename(title="Open level", filetypes=[("CPW level", "*.lvl *.json"), ("All files", "*.*")])
        if path: self.open_level_path(path, confirm=False)
    def open_level_path(self, path, confirm=True):
        if confirm and not self.confirm_discard(): return
        try: self.model.load(path)
        except (OSError, json.JSONDecodeError) as e: messagebox.showerror("Cannot open level", str(e)); return
        self._clear_reference_image()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.dirty = False; self.sync_settings(); self.refresh_lists(); self.canvas.fit(); self.set_status(f"Opened {os.path.basename(path)}.")
    def save(self):
        self.apply_settings()
        if self.model.path: self.write(self.model.path)
        else: self.save_as()
    def save_as(self):
        self.apply_settings(); path = filedialog.asksaveasfilename(title="Save level as", defaultextension=".lvl", filetypes=[("CPW level", "*.lvl"), ("JSON", "*.json")])
        if path: self.write(path)
    def write(self, path):
        try: self.model.save(path)
        except OSError as e: messagebox.showerror("Cannot save level", str(e)); return
        self.dirty = False; self.title(f"Crazy Penguin Wars: Map Editor — {os.path.basename(path)}"); self.set_status(f"Saved {path}")
    def test_in_game(self):
        """Upload the in-memory level and hand the short test URL to the launcher."""
        if len(self.model.spawns) < 4:
            messagebox.showerror("Cannot start test", "Please place at least 4 spawn points before testing.")
            return
        self.apply_settings()
        payload = json.dumps(self.model.data()).encode("utf-8")
        request_data = urllib.request.Request(
            f"{TEST_SERVER_URL}/test-map",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request_data, timeout=12) as response:
                result = json.loads(response.read().decode("utf-8"))
            launch_url = result["launch_url"]
        except (KeyError, OSError, ValueError, urllib.error.HTTPError) as error:
            messagebox.showerror(
                "Cannot start test",
                f"Could not upload the map to {TEST_SERVER_URL}.\n\n{error}",
            )
            return

        launcher_arg = "cpw://test-map?" + urllib.parse.urlencode({"url": launch_url})
        try:
            LAUNCHER_EXE = Path(__file__).resolve().parent.parent / "assets" / "testlauncher" / "Crazy Penguin Wars.exe"
            subprocess.Popen([str(LAUNCHER_EXE), launcher_arg])
        except OSError as error:
            messagebox.showerror(
                "Launcher not found",
                f"The level was uploaded, but the CPW launcher could not be started "
                f"from {LAUNCHER_EXE}.\n\n{error}",
            )
            return
        self.set_status("Uploaded map and opened test session.")

    def load_screenshot(self):
        """Prompt to load a reference screenshot (intended size 760x668) to overlay on the canvas."""
        path = filedialog.askopenfilename(
            parent=self,
            title="Load reference screenshot",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.webp"),
                ("All files", "*.*")
            ]
        )
        if not path:
            return
        try:
            with Image.open(path) as img:
                pil_img = img.convert("RGBA")
            w, h = pil_img.width, pil_img.height
            scale_mode = "fit"
            if w != 760 or h != 668:
                answer = messagebox.askyesnocancel(
                    "Image size mismatch",
                    f"The image is {w}×{h}px, but the game client area is 760×668px.\n\n"
                    "• Yes — Scale the image to fit exactly (stretches width and height)\n"
                    "• No — Fit height only, keep aspect ratio (width may overflow or underflow, centered)\n"
                    "• Cancel — Abort loading",
                    parent=self,
                )
                if answer is None:  # Cancel
                    return
                scale_mode = "fit" if answer else "original"
            self.reference_image_pil = pil_img
            self.reference_image_path = path
            self.reference_image_scale_mode = scale_mode
            self.show_reference_image.set(True)
            self.canvas._reference_scaled.clear()
            self.canvas.draw()
            mode_label = "scaled to fit" if scale_mode == "fit" else "original size (centered)"
            self.set_status(f"Loaded reference screenshot: {Path(path).name} ({w}×{h}px, {mode_label})")
        except Exception as err:
            messagebox.showerror("Failed to load image", f"Could not load image:\n{err}", parent=self)



    def confirm_discard(self): return not self.dirty or messagebox.askyesno("Unsaved changes", "Discard unsaved changes?")
    def set_status(self, text): self.status.set(text)


