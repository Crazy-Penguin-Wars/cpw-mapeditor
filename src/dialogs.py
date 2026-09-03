"""Small editor dialogs."""
import copy
import glob
import tkinter as tk
from tkinter import messagebox, ttk

from .assets import asset_folder, available_parallax_exports, parallax_theme_for_layer, parallax_themes
from .config import ITEM_MATERIALS, TERRAIN_MATERIALS, TERRAIN_TEXTURE_SWFS


class LayerDialog(tk.Toplevel):
    """Choose a supplied theme sprite instead of entering Flash metadata by hand."""

    def __init__(self, parent, layer, theme, on_save):
        super().__init__(parent)
        self.title("Choose parallax layer")
        self.transient(parent)
        self.grab_set()
        self.on_save = on_save
        self.layer = copy.deepcopy(layer)
        self.level_theme = theme
        self.art_theme = tk.StringVar(value=parallax_theme_for_layer(self.layer, theme))
        self.preview_image = None

        form = ttk.Frame(self, padding=14)
        form.pack(fill="both", expand=True)
        ttk.Label(form, text="Parallax decorations", font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        ttk.Label(form, text="Theme").pack(anchor="w", pady=(2, 0))
        theme_picker = ttk.Combobox(form, textvariable=self.art_theme, values=parallax_themes(), state="readonly", width=25)
        theme_picker.pack(anchor="w", pady=(0, 4))
        theme_picker.bind("<<ComboboxSelected>>", self.refresh_exports)

        picker = ttk.Frame(form)
        picker.pack(fill="both", expand=True)
        self.exports = tk.Listbox(picker, height=9, exportselection=False, width=28)
        self.exports.pack(side="left", fill="both", expand=True)
        self.exports.bind("<<ListboxSelect>>", self.update_preview)
        preview_box = ttk.LabelFrame(picker, text="Preview", padding=6)
        preview_box.pack(side="left", fill="both", padx=(10, 0))
        self.preview = ttk.Label(preview_box, text="Select a layer", anchor="center", width=30)
        self.preview.pack(fill="both", expand=True)

        target_export = self.layer.get("graphics_export", [None])[0] if self.layer.get("graphics_export") else None
        self.refresh_exports(existing=self.layer.get("graphics_export", []), target=target_export)

        values = ttk.Frame(form)
        values.pack(fill="x", pady=(10, 0))
        defaults = (("x", 0), ("y", 800), ("gap", 800), ("zoom", 1.0), ("camera_x_pan", 0))
        self.vars = {key: tk.StringVar(value=str(self.layer.get(key, default))) for key, default in defaults}
        for column, (key, label) in enumerate((("x", "X"), ("y", "Y"), ("gap", "Repeat gap"), ("zoom", "Zoom"), ("camera_x_pan", "Camera X pan"))):
            if key == "camera_x_pan":
                header = ttk.Frame(values)
                header.grid(row=0, column=column, sticky="w", padx=(0, 5))
                ttk.Label(header, text=label).pack(side="left")
                ttk.Button(header, text="ℹ", width=2, command=self.show_camera_pan_info).pack(side="left", padx=(2, 0))
            else:
                ttk.Label(values, text=label).grid(row=0, column=column, sticky="w", padx=(0, 5))
            ttk.Entry(values, textvariable=self.vars[key], width=9).grid(row=1, column=column, sticky="ew", padx=(0, 5))
        self.tile = tk.BooleanVar(value=bool(self.layer.get("tile_horizontally", True)))
        ttk.Checkbutton(form, text="Repeat horizontally", variable=self.tile).pack(anchor="w", pady=(8, 10))
        ttk.Button(form, text="Use selected layer", command=self.save).pack(fill="x")

    def show_camera_pan_info(self):
        messagebox.showinfo(
            "Info",
            "Camera X pan is used only in combination with \"Repeat horizontally\" and indicates until where to repeat. The default value is 0 and means repeating for the entire level width. Positive values repeat beyond that (you should never use those), negative values stop repeating earlier.\n\n You'll rarely need to use this option.",
            parent=self
        )

    def selected_export(self):
        selection = self.exports.curselection()
        return self.exports.get(selection[0]) if selection else None

    def refresh_exports(self, _event=None, existing=(), target=None):
        self.exports.delete(0, "end")
        available = available_parallax_exports(self.art_theme.get())
        items = list(dict.fromkeys([*available, *existing]))
        for export in items:
            self.exports.insert("end", export)
        if self.exports.size():
            selected_idx = 0
            if target and target in items:
                selected_idx = items.index(target)
            self.exports.selection_set(selected_idx)
            self.exports.see(selected_idx)
            self.update_preview()
        else:
            theme = self.art_theme.get()
            self.preview.configure(image="", text=f"No {theme} PNGs installed yet.\nAdd them under:\nassets/parallax/{theme.lower()}")

    def update_preview(self, _event=None):
        export = self.selected_export()
        if not export:
            return
        folder = asset_folder("parallax", self.art_theme.get())
        matches = glob.glob(str(folder / f"*_{export}.png")) if folder else []
        if not matches:
            self.preview_image = None
            self.preview.configure(image="", text=f"{export}\nPreview image not installed")
            return
        try:
            image = tk.PhotoImage(file=matches[0])
            divisor = max(1, (max(image.width(), image.height()) + 219) // 220)
            self.preview_image = image.subsample(divisor, divisor) if divisor > 1 else image
            self.preview.configure(image=self.preview_image, text="")
        except tk.TclError:
            self.preview.configure(image="", text="Could not load preview image")

    def save(self):
        export = self.selected_export()
        if not export:
            messagebox.showerror("Choose a layer", "Select a parallax sprite first.", parent=self)
            return
        try:
            values = {key: float(var.get()) for key, var in self.vars.items()}
        except ValueError:
            messagebox.showerror("Invalid layer", "Position, gap and camera pan values must be numbers.", parent=self)
            return
        self.layer.update({
            "element_type": "ParallaxLayer",
            "graphics_export": [export],
            "graphics_swf": f"level_graphics/level_bg_{self.art_theme.get().lower()}.swf",
            "id": self.layer.get("id") or "parallax_1",
            **values,
            "tile_horizontally": self.tile.get(),
            "camera_z": self.layer.get("camera_z", 0),
            "camera_y_pan": self.layer.get("camera_y_pan", 0),
        })
        self.on_save(self.layer)
        self.destroy()


class TerrainDialog(tk.Toplevel):
    """Edit terrain-wide properties and move its bounding-box origin exactly."""

    SHAPES = ["edgeShape", "polygonShape"]

    def __init__(self, parent, terrain, on_save, on_delete):
        super().__init__(parent)
        self.title("Edit terrain")
        self.transient(parent)
        self.grab_set()
        self.terrain = copy.deepcopy(terrain)
        self.on_save, self.on_delete = on_save, on_delete
        points = self.terrain.get("points", [])
        self.origin_x = min((float(point["x"]) for point in points), default=0)
        self.origin_y = min((float(point["y"]) for point in points), default=0)

        # Make dialog scrollable so it fits all options
        outer = ttk.Frame(self, padding=(0, 0))
        outer.pack(fill="both", expand=True)
        canvas_scroll = tk.Canvas(outer, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas_scroll.yview)
        canvas_scroll.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas_scroll.pack(side="left", fill="both", expand=True)
        form = ttk.Frame(canvas_scroll, padding=14)
        form_window = canvas_scroll.create_window((0, 0), window=form, anchor="nw")

        def _on_frame_configure(e):
            canvas_scroll.configure(scrollregion=canvas_scroll.bbox("all"))
        def _on_canvas_configure(e):
            canvas_scroll.itemconfig(form_window, width=e.width)
        def _on_mousewheel(e):
            if canvas_scroll.winfo_exists():
                canvas_scroll.yview_scroll(-1 if e.delta > 0 else 1, "units")
        self.bind("<MouseWheel>", _on_mousewheel)

        # ── Material ─────────────────────────────────────────────────────────
        ttk.Label(form, text="Terrain properties", font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        ttk.Label(form, text="Material").pack(anchor="w", pady=(9, 0))
        self.material = tk.StringVar(value=self.terrain.get("theme", "Wood"))
        ttk.Combobox(form, textvariable=self.material, values=TERRAIN_MATERIALS, state="readonly", width=24).pack(fill="x", pady=(2, 8))

        # ── Color section ────────────────────────────────────────────────────
        color_frame = ttk.LabelFrame(form, text="Color (values from –255 to +255)", padding=8)
        color_frame.pack(fill="x", pady=(0, 8))
        color_rows = [("Shade", "shade", 0), ("Tint", "tint", 0),
                      ("Red", "red", 0), ("Green", "green", 0), ("Blue", "blue", 0)]
        self.color_vars = {}
        for col, (label, key, default) in enumerate(color_rows):
            ttk.Label(color_frame, text=label).grid(row=0, column=col, sticky="w", padx=(0, 6))
            var = tk.StringVar(value=str(self.terrain.get(key, default)))
            self.color_vars[key] = var
            ttk.Entry(color_frame, textvariable=var, width=7).grid(row=1, column=col, sticky="ew", padx=(0, 6))

        # ── Texture section ──────────────────────────────────────────────────
        tex_frame = ttk.LabelFrame(form, text="Texture", padding=8)
        tex_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(tex_frame, text="Rotation (°)").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(tex_frame, text="Shape").grid(row=0, column=1, sticky="w")
        self.tex_rotation = tk.StringVar(value=str(self.terrain.get("texture_rotation", 0)))
        ttk.Entry(tex_frame, textvariable=self.tex_rotation, width=10).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.shape = tk.StringVar(value=self.terrain.get("shape", "edgeShape"))
        ttk.Combobox(tex_frame, textvariable=self.shape, values=self.SHAPES, state="readonly", width=14).grid(row=1, column=1, sticky="ew")
        ttk.Label(
            tex_frame,
            text="edgeShape bases physics on the edges of the terrain, polygonShape also on the inner terrain. Almost always use edgeShape (faster, less physics calculations).",
            wraplength=310,
            foreground="#59656d",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # ── Flags section ────────────────────────────────────────────────────
        flags_frame = ttk.LabelFrame(form, text="Flags", padding=8)
        flags_frame.pack(fill="x", pady=(0, 8))
        self.border = tk.BooleanVar(value=self.terrain.get("grass_theme") == "[Material]")
        self.outline = tk.BooleanVar(value=bool(self.terrain.get("outline", True)))
        self.dynamic = tk.BooleanVar(value=bool(self.terrain.get("dynamic", False)))
        self.no_fixtures = tk.BooleanVar(value=bool(self.terrain.get("no_fixtures", False)))
        self.unbreakable = tk.BooleanVar(value=bool(self.terrain.get("unbreakable", False)))
        ttk.Checkbutton(flags_frame, text="Grass on top", variable=self.border).pack(anchor="w", pady=(0, 3))
        ttk.Checkbutton(flags_frame, text="Show outline", variable=self.outline).pack(anchor="w", pady=(0, 3))
        ttk.Checkbutton(flags_frame, text="Dynamic (enables physics)", variable=self.dynamic).pack(anchor="w", pady=(0, 3))
        ttk.Checkbutton(flags_frame, text="No collisions (decoration)", variable=self.no_fixtures).pack(anchor="w", pady=(0, 3))
        ttk.Checkbutton(flags_frame, text="Unbreakable", variable=self.unbreakable).pack(anchor="w")

        # ── Exact position ───────────────────────────────────────────────────
        position = ttk.LabelFrame(form, text="Position", padding=8)
        position.pack(fill="x", pady=(0, 8))
        self.x = tk.StringVar(value=f"{self.origin_x:.2f}")
        self.y = tk.StringVar(value=f"{self.origin_y:.2f}")
        ttk.Label(position, text="X").grid(row=1, column=0, sticky="w")
        ttk.Entry(position, textvariable=self.x, width=16).grid(row=2, column=0, padx=(0, 8))
        ttk.Label(position, text="Y").grid(row=1, column=1, sticky="w")
        ttk.Entry(position, textvariable=self.y, width=16).grid(row=2, column=1)

        # ── Actions ──────────────────────────────────────────────────────────
        ttk.Button(
            form,
            text="Swap grass from top to bottom or vice versa",
            command=self.swap_border,
        ).pack(fill="x", pady=(4, 0))
        ttk.Label(
            form,
            text="This reverses the node order without changing the shape.",
            wraplength=310,
            foreground="#59656d",
        ).pack(anchor="w", pady=(4, 0))
        actions = ttk.Frame(form)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Save changes", command=self.save).pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="Delete terrain", command=self.delete).pack(side="left", padx=(8, 0))

        self.geometry("420x680")

    def swap_border(self):
        """Reverse the directed polygon, then apply all dialog changes."""
        self.terrain["points"].reverse()
        self.save()

    def save(self):
        try:
            x, y = float(self.x.get()), float(self.y.get())
        except ValueError:
            messagebox.showerror("Invalid position", "X and Y must be numbers.", parent=self)
            return
        try:
            tex_rot = int(float(self.tex_rotation.get()))
        except ValueError:
            messagebox.showerror("Invalid value", "Texture rotation must be a number.", parent=self)
            return
        try:
            color_vals = {key: int(float(var.get())) for key, var in self.color_vars.items()}
        except ValueError:
            messagebox.showerror("Invalid color", "Color values must be integers.", parent=self)
            return
        x, y = round(x, 2), round(y, 2)
        dx, dy = x - self.origin_x, y - self.origin_y
        for point in self.terrain.get("points", []):
            point["x"] = round(float(point["x"]) + dx, 2)
            point["y"] = round(float(point["y"]) + dy, 2)
        self.terrain["theme"] = self.material.get()
        self.terrain["texture_swf"] = TERRAIN_TEXTURE_SWFS[self.material.get()]
        self.terrain["grass_theme"] = "[Material]" if self.border.get() else "[None]"
        self.terrain["texture_rotation"] = tex_rot
        self.terrain["shape"] = self.shape.get()
        self.terrain["outline"] = self.outline.get()
        self.terrain["dynamic"] = self.dynamic.get()
        self.terrain["no_fixtures"] = self.no_fixtures.get()
        self.terrain["unbreakable"] = self.unbreakable.get()
        for key, val in color_vals.items():
            self.terrain[key] = val
        self.on_save(self.terrain)
        self.destroy()

    def delete(self):
        if messagebox.askyesno("Delete terrain", "Delete this terrain element?", parent=self):
            self.on_delete()
            self.destroy()


class PositionDialog(tk.Toplevel):
    """Small context editor for dynamic objects and spawn points."""

    def __init__(self, parent, title, value, on_save, on_delete):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.on_save, self.on_delete = on_save, on_delete
        form = ttk.Frame(self, padding=14)
        form.pack(fill="both", expand=True)
        ttk.Label(form, text=title, font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        self.x, self.y = tk.StringVar(value=str(value.get("x", 0))), tk.StringVar(value=str(value.get("y", 0)))
        for label, variable in (("X", self.x), ("Y", self.y)):
            ttk.Label(form, text=label).pack(anchor="w", pady=(8, 0))
            ttk.Entry(form, textvariable=variable, width=28).pack(fill="x")
        actions = ttk.Frame(form)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Save position", command=self.save).pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="Delete", command=self.delete).pack(side="left", padx=(8, 0))

    def save(self):
        try:
            self.on_save(round(float(self.x.get()), 2), round(float(self.y.get()), 2))
        except ValueError:
            messagebox.showerror("Invalid position", "X and Y must be numbers.", parent=self)
            return
        self.destroy()

    def delete(self):
        if messagebox.askyesno("Delete", "Delete this element?", parent=self):
            self.on_delete()
            self.destroy()


class ItemDialog(tk.Toplevel):
    """Edit dynamic object position, angle, material, and physics flags (unbreakable, sleep)."""

    def __init__(self, parent, item, on_save, on_delete):
        super().__init__(parent)
        self.title(f"Edit {item.get('name', 'Object')}")
        self.transient(parent)
        self.grab_set()
        self.item = copy.deepcopy(item)
        self.on_save, self.on_delete = on_save, on_delete

        form = ttk.Frame(self, padding=14)
        form.pack(fill="both", expand=True)
        ttk.Label(form, text=f"Item: {self.item.get('name', 'Object')}", font=("TkDefaultFont", 11, "bold")).pack(anchor="w")

        # Material / Theme
        ttk.Label(form, text="Material").pack(anchor="w", pady=(8, 0))
        self.material = tk.StringVar(value=self.item.get("theme", "Wood"))
        ttk.Combobox(form, textvariable=self.material, values=ITEM_MATERIALS, state="readonly", width=26).pack(fill="x", pady=(2, 4))

        # Position & Angle
        pos_frame = ttk.Frame(form)
        pos_frame.pack(fill="x", pady=(6, 0))
        self.x = tk.StringVar(value=str(self.item.get("x", 0)))
        self.y = tk.StringVar(value=str(self.item.get("y", 0)))
        self.angle = tk.StringVar(value=str(self.item.get("angle", 0)))

        for col, (label, var) in enumerate((("X", self.x), ("Y", self.y), ("Angle (°)", self.angle))):
            ttk.Label(pos_frame, text=label).grid(row=0, column=col, sticky="w", padx=(0, 6))
            ttk.Entry(pos_frame, textvariable=var, width=10).grid(row=1, column=col, sticky="ew", padx=(0, 6))

        # Flags: Unbreakable and Sleep
        flags_frame = ttk.LabelFrame(form, text="Physics properties", padding=8)
        flags_frame.pack(fill="x", pady=(10, 0))

        self.unbreakable = tk.BooleanVar(value=bool(self.item.get("unbreakable", False)))
        ttk.Checkbutton(flags_frame, text="Unbreakable", variable=self.unbreakable).pack(anchor="w", pady=(0, 4))

        self.sleep = tk.BooleanVar(value=bool(self.item.get("sleep", False)))
        ttk.Checkbutton(flags_frame, text="Sleep mode (makes items float)", variable=self.sleep).pack(anchor="w")

        # Actions
        actions = ttk.Frame(form)
        actions.pack(fill="x", pady=(14, 0))
        ttk.Button(actions, text="Save changes", command=self.save).pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="Delete item", command=self.delete).pack(side="left", padx=(8, 0))

    def save(self):
        try:
            x = float(self.x.get())
            y = float(self.y.get())
            angle = float(self.angle.get())
        except ValueError:
            messagebox.showerror("Invalid values", "X, Y, and Angle must be numbers.", parent=self)
            return
        self.item["x"] = round(x, 2)
        self.item["y"] = round(y, 2)
        self.item["angle"] = round(angle % 360, 2)
        self.item["theme"] = self.material.get()
        self.item["unbreakable"] = self.unbreakable.get()
        self.item["sleep"] = self.sleep.get()
        self.on_save(self.item)
        self.destroy()

    def delete(self):
        if messagebox.askyesno("Delete", "Delete this item?", parent=self):
            self.on_delete()
            self.destroy()
