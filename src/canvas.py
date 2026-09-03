"""Interactive map preview canvas and editing tools."""
from __future__ import annotations
import glob
import math
from pathlib import Path
import tkinter as tk
import numpy as np
from PIL import Image, ImageDraw, ImageTk
from .assets import asset_folder, asset_path, parallax_theme_for_layer
from .config import ASSET_ROOT, FIXTURES, GRID_SIZE, ITEM_EXPORTS, MATERIAL_COLORS, PREVIEW_PARALLAX_OFFSET_X, PREVIEW_WATER_SURFACE_OFFSET, TERRAIN_TEXTURE_SWFS, TERRAIN_TOP_BORDER_ANGLE, THEMES

PARALLAX_RESAMPLING = Image.Resampling.NEAREST
TERRAIN_FILL_RESAMPLING = Image.Resampling.NEAREST
PREVIEW_MAX_IMAGE_DIMENSION = 360



def resize_preview_image(image, size, resampling):
    """Keep preview images blocky while preserving their exact display footprint."""
    target_width, target_height = size
    longest_side = max(target_width, target_height)
    if longest_side <= PREVIEW_MAX_IMAGE_DIMENSION:
        return image.resize(size, resampling)
    scale = PREVIEW_MAX_IMAGE_DIMENSION / longest_side
    reduced_size = (
        max(1, round(target_width * scale)),
        max(1, round(target_height * scale)),
    )
    reduced = image.resize(reduced_size, resampling)
    return reduced.resize(size, resampling)
class MapCanvas(tk.Canvas):
    def __init__(self, master, app):
        super().__init__(master, bg="#24313b", highlightthickness=0, cursor="crosshair")
        self.app = app
        self.scale, self.offset_x, self.offset_y = 0.25, 0, 0
        self.asset_root = str(ASSET_ROOT)
        self._gradient_colors = {}
        self._parallax_sources = {}
        self._item_sources = {}
        self._item_originals = {}
        self._item_scaled = {}
        self._parallax_originals = {}
        self._parallax_scaled = {}
        self._terrain_originals = {}
        self._terrain_scaled = {}
        self._terrain_fill_cache = {}
        self._water_originals = {}
        self._water_scaled = {}
        self._spawn_original = None
        self._spawn_scaled = {}
        self._reference_scaled = {}
        self._frame_images = []
        self._draw_after_id = None
        self.tool = "select"
        self.selected = None  # (kind, index)
        self.polygon = []
        self.drag = None
        self.pan_start = None
        self.right_pan_start = None
        self.right_pan_moved = False
        self._drag_moved = False
        self.item_placing_angle = 0.0
        self.hover_pos = None
        self.show_grid = tk.BooleanVar(value=True)
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Motion>", self.mouse_motion)
        self.bind("<Leave>", self.mouse_leave)
        self.bind("<Button-1>", self.left_click)
        self.bind("<Button-3>", self.right_press)
        self.bind("<B1-Motion>", self.drag_motion)
        self.bind("<ButtonRelease-1>", self.release)
        self.bind("<B3-Motion>", self.right_drag_motion)
        self.bind("<ButtonRelease-3>", self.right_release)
        self.bind("<MouseWheel>", self.wheel)
        self.bind("<Button-4>", self._on_scroll_up)
        self.bind("<Button-5>", self._on_scroll_down)
        self.bind("<Escape>", lambda e: self.handle_escape())
        self.focus_set()

    @property
    def model(self): return self.app.model
    def world_to_screen(self, x, y): return x * self.scale + self.offset_x, y * self.scale + self.offset_y
    def screen_to_world(self, x, y): return (x - self.offset_x) / self.scale, (y - self.offset_y) / self.scale

    def fit(self):
        w, h = max(1, self.winfo_width()), max(1, self.winfo_height())
        lw, lh = float(self.model.settings["width"]), float(self.model.settings["height"])
        self.scale = min((w - 54) / lw, (h - 54) / lh)
        self.offset_x, self.offset_y = (w - lw * self.scale) / 2, (h - lh * self.scale) / 2
        self._clear_scaled_images()
        self.draw()

    def zoom(self, amount, sx, sy):
        oldx, oldy = self.screen_to_world(sx, sy)
        self.scale = max(.03, min(3, self.scale * amount))
        self.offset_x, self.offset_y = sx - oldx * self.scale, sy - oldy * self.scale
        self._clear_scaled_images()
        self.draw()

    def _get_gradient_colors(self, theme, num_bands=48):
        """Return pre-sampled vertical color stops for the theme gradient."""
        key = (theme, num_bands)
        if key in self._gradient_colors:
            return self._gradient_colors[key]
        path = asset_path("gradients", theme)
        if not path or not path.is_file():
            direct = Path(self.asset_root) / "gradients" / f"{theme.lower()}.png"
            if direct.is_file():
                path = direct
            else:
                self._gradient_colors[key] = None
                return None
        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                w, h = img.width, img.height
                colors = []
                for i in range(num_bands):
                    sy = int(i * (h - 1) / (num_bands - 1))
                    r, g, b = img.getpixel((w // 2, sy))
                    colors.append(f"#{r:02x}{g:02x}{b:02x}")
                self._gradient_colors[key] = colors
                return colors
        except (OSError, ValueError):
            self._gradient_colors[key] = None
            return None

    def _draw_background_gradient(self, theme, x0, y0, x1, y1, sky_fallback):
        """Draw a fast, banded gradient rectangle for the background."""
        colors = self._get_gradient_colors(theme, num_bands=48)
        if not colors:
            self.create_rectangle(x0, y0, x1, y1, fill=sky_fallback, outline="")
            return
        total_h = y1 - y0
        if total_h <= 0:
            return
        viewport_h = self.winfo_height()
        n = len(colors)
        step = total_h / n
        for i, color in enumerate(colors):
            yt = y0 + i * step
            yb = y0 + (i + 1) * step
            if yb < -10 or yt > viewport_h + 10:
                continue
            self.create_rectangle(x0, yt, x1, yb + 0.5, fill=color, outline="")

    def request_draw(self):
        """Coalesce high-frequency pointer redraws to keep the UI responsive."""
        if self._draw_after_id is None:
            self._draw_after_id = self.after(16, self._run_requested_draw)

    def _run_requested_draw(self):
        self._draw_after_id = None
        self.draw()
    def draw(self):
        self.delete("all")
        # Canvas does not retain Python references to PhotoImage objects.
        # Keep non-cached terrain renders alive until the next redraw.
        self._frame_images = []
        if self.winfo_width() < 2: return
        s = self.model.settings; width, height = float(s["width"]), float(s["height"])
        x0, y0 = self.world_to_screen(0, 0); x1, y1 = self.world_to_screen(width, height)
        sky, hill, _, border = THEMES.get(s["theme"], THEMES["Forest"])
        if self.app.show_background_gradient.get():
            self._draw_background_gradient(s.get("theme", "Forest"), x0, y0, x1, y1, sky)
        else:
            self.create_rectangle(x0, y0, x1, y1, fill=sky, outline="")
        self._draw_reference_image()
        self._draw_parallax(hill, x0, y0, x1, y1)
        self._draw_water(s, x0, y0, x1, y1)
        self._draw_map_boundary_mask(x0, y0, x1, y1, border)
        if self.show_grid.get(): self._draw_grid(width, height)
        for i, element in enumerate(self.model.elements): self._draw_element(i, element)
        self._draw_selected_parallax_highlight(x0, y0, x1, y1)
        vw, vh = self.winfo_width(), self.winfo_height()
        if self.app.show_spawnpoints.get():
            for i, spawn in enumerate(self.model.spawns):
                x, y = self.world_to_screen(float(spawn["x"]), float(spawn["y"]))
                selected = self.selected == ("spawn", i)
                if not selected and (x < -60 or x > vw + 60 or y < -60 or y > vh + 60):
                    continue
                penguin = self._get_spawn_image()
                if penguin:
                    # AvatarGameObject keeps the player container at the physics
                    # body/spawn location. The supplied idle frame's registration
                    # is its feet, represented here by the bottom-centre anchor.
                    self.create_image(x, y, image=penguin, anchor="s")
                self.create_oval(x-9, y-9, x+9, y+9, fill="#f5db35", outline="#1e3542", width=3 if selected else 1)
                self.create_text(x, y, text=str(i + 1), font=("TkDefaultFont", 8, "bold"), fill="#26343e")
        if self.polygon:
            pts = [self.world_to_screen(x, y) for x, y in self.polygon]
            flat = [v for point in pts for v in point]
            if len(flat) >= 4: self.create_line(*flat, fill="#ffffff", width=2, dash=(5, 3))
            for x, y in pts: self.create_oval(x-4, y-4, x+4, y+4, fill="#ffffff", outline="#17364d")
        self._draw_game_client_size()
        self._draw_item_placement_preview()
        self._draw_hud()

    def _draw_parallax(self, hill, x0, y0, x1, y1):
        """Draw actual bundled Forest art, with a guide placeholder for other themes.

        In the Flash client each sprite has its registration point at its bottom
        centre.  The canvas uses that exact anchor, so x/y and the graphics order
        have the same meaning in the preview as they do in a .lvl file.
        """
        # PhysicsWorld draws the saved array from its last entry down to index
        # zero.  Canvas items stack in creation order, so mirror that exact
        if not self.app.show_parallax_images.get():
            return
        vw, vh = self.winfo_width(), self.winfo_height()
        for n, layer in enumerate(reversed(self.model.parallaxes)):
            layer_y = float(layer.get("y", 0))
            y = self.world_to_screen(0, layer_y)[1]
            if y < -1000 or y > vh + 1000:
                continue
            layer_x = float(layer.get("x", 0))
            gap = float(layer.get("gap", 0))
            graphics = layer.get("graphics_export", [])
            if not graphics:
                continue
            tile_end = float(self.model.settings["width"]) + float(layer.get("camera_x_pan", 0)) if layer.get("tile_horizontally") else 1.0
            
            if gap > 0 and layer.get("tile_horizontally"):
                gap_screen = gap * self.scale
                base_x = self.world_to_screen(layer_x, 0)[0]
                start_k = max(0, int((-800 - base_x) // gap_screen)) if gap_screen > 0 else 0
                end_k = min(int(tile_end // gap) + 1, int((vw + 800 - base_x) // gap_screen) + 1) if gap_screen > 0 else 1
            else:
                start_k = 0
                end_k = 1

            for k in range(start_k, end_k):
                cursor = k * gap
                if cursor >= tile_end and k > 0:
                    break
                layer_zoom = float(layer.get("zoom", 1.0))
                for export in graphics:
                    sx = self.world_to_screen(layer_x + cursor, 0)[0]
                    if sx < -800 or sx > vw + 800:
                        continue
                    image = self._get_parallax_image(export, parallax_theme_for_layer(layer, self.model.settings.get("theme", "Forest")), layer_zoom)
                    if image:
                        self.create_image(sx, y, image=image, anchor="s")
                    else:
                        # Placeholders are deliberately distinct but retain the layer's real position and spacing.
                        color = hill if n % 2 == 0 else "#ffffff"
                        self.create_oval(sx - gap*.45*self.scale, y - gap*.22*self.scale, sx + gap*.45*self.scale, y + gap*.18*self.scale, fill=color, outline="", stipple="gray50")

    def _draw_selected_parallax_highlight(self, x0, y0, x1, y1):
        """Draw a bold top-level highlight overlay for the currently selected parallax layer."""
        if not self.app.show_parallax_images.get():
            return
        selected_idx = self.app.current_layer()
        if selected_idx is None or selected_idx < 0 or selected_idx >= len(self.model.parallaxes):
            return
        vw, vh = self.winfo_width(), self.winfo_height()
        layer = self.model.parallaxes[selected_idx]
        layer_y = float(layer.get("y", 0))
        y = self.world_to_screen(0, layer_y)[1]
        layer_x = float(layer.get("x", 0))
        x = self.world_to_screen(layer_x, 0)[0]
        gap_world = float(layer.get("gap", 0))
        gap = max(10, (gap_world or 400) * self.scale)
        exports = ", ".join(layer.get("graphics_export", []))
        graphics = layer.get("graphics_export", [])
        tile_end = float(self.model.settings["width"]) + float(layer.get("camera_x_pan", 0)) if layer.get("tile_horizontally") else 1.0

        if gap_world > 0 and layer.get("tile_horizontally"):
            gap_screen = gap_world * self.scale
            start_k = max(0, int((-800 - x) // gap_screen)) if gap_screen > 0 else 0
            end_k = min(int(tile_end // gap_world) + 1, int((vw + 800 - x) // gap_screen) + 1) if gap_screen > 0 else 1
        else:
            start_k = 0
            end_k = 1

        layer_zoom = float(layer.get("zoom", 1.0))
        for k in range(start_k, end_k):
            cursor = k * gap_world
            if cursor >= tile_end and k > 0:
                break
            for export in graphics:
                sx = self.world_to_screen(layer_x + cursor, 0)[0]
                if sx < -800 or sx > vw + 800:
                    continue
                # Always show a highlight, even when parallax images are hidden.
                image = self._get_parallax_image(export, parallax_theme_for_layer(layer, self.model.settings.get("theme", "Forest")), layer_zoom)
                if image and self.app.show_parallax_images.get():
                    iw, ih = image.width(), image.height()
                    self.create_rectangle(sx - iw/2, y - ih, sx + iw/2, y, outline="#ff2222", width=3, dash=(6, 3))
                else:
                    self.create_oval(sx - gap*.45, y - gap*.22, sx + gap*.45, y + gap*.18, outline="#ff2222", width=3, dash=(6, 3))

        star_id = self.create_text(x + 5, y - 12, text="★", anchor="w", fill="#ff2222", font=("TkDefaultFont", 10, "bold"))
        star_bbox = self.bbox(star_id)
        offset = (star_bbox[2] - star_bbox[0] + 3) if star_bbox else 14
        self.create_text(x + 5 + offset, y - 12, text=exports or "parallax", anchor="w", fill="#ff2222", font=("TkDefaultFont", 8, "bold"))

    def _get_parallax_image(self, export, theme, zoom=1.0):
        """Return a cached, viewport-scaled PNG for a layer's artwork theme/export."""
        source_key = (theme, export)
        source_path = self._parallax_sources.get(source_key)
        if source_path is None:
            folder = asset_folder("parallax", theme)
            matches = glob.glob(str(folder / f"*_{export}.png")) if folder else []
            source_path = matches[0] if matches else ""
            self._parallax_sources[source_key] = source_path
        if not source_path:
            return None
        if source_path not in self._parallax_originals:
            try:
                with Image.open(source_path) as original:
                    self._parallax_originals[source_path] = original.convert("RGBA")
            except (OSError, ValueError):
                return None
        original = self._parallax_originals[source_path]
        target_w = max(1, round(original.width * self.scale * zoom))
        target_h = max(1, round(original.height * self.scale * zoom))
        size = (target_w, target_h)
        key = (source_path, size)
        if key not in self._parallax_scaled:
            self._parallax_scaled[key] = ImageTk.PhotoImage(resize_preview_image(original, size, PARALLAX_RESAMPLING))
        return self._parallax_scaled[key]

    def _draw_map_boundary_mask(self, x0, y0, x1, y1, border):
        """Mask parallax and water that overflow outside the playable map area."""
        w, h = self.winfo_width(), self.winfo_height()
        bg = self["bg"] or "#24313b"
        # Mask Left
        if x0 > -4000:
            self.create_rectangle(-4000, -4000, x0, h + 4000, fill=bg, outline="")
        # Mask Right
        if x1 < w + 4000:
            self.create_rectangle(x1, -4000, w + 4000, h + 4000, fill=bg, outline="")
        # Mask Top
        if y0 > -4000:
            self.create_rectangle(-4000, -4000, w + 4000, y0, fill=bg, outline="")
        # Mask Bottom
        if y1 < h + 4000:
            self.create_rectangle(-4000, y1, w + 4000, h + 4000, fill=bg, outline="")
        # Map framing border
        self.create_rectangle(x0, y0, x1, y1, fill="", outline=border, width=3)

    def _draw_game_client_size(self):
        """Highlight the visible world bounds as rendered in Fullscreen (1536x864) and Windowed (760x668)."""
        if not getattr(self.app, "show_game_client_size", None) or not self.app.show_game_client_size.get():
            return
        s = self.model.settings
        level_w = float(s.get("width", 3000))
        level_h = float(s.get("height", 1174))
        zoom_side = s.get("zoom_side", "width")

        viewports = [
            ("Fullscreen (1536 × 864)", 1536.0, 864.0, "#00e5ff", 2, (8, 4)),
            ("Windowed (760 × 668)", 760.0, 668.0, "#ffb300", 1, (4, 4)),
        ]

        for name, stage_w, stage_h, color, width, dash in viewports:
            if zoom_side == "height":
                zoom = stage_h / level_h if level_h > 0 else 1.0
            else:
                zoom = stage_w / level_w if level_w > 0 else 1.0
            if zoom <= 0:
                continue

            visible_world_w = stage_w / zoom
            visible_world_h = stage_h / zoom

            min_world_x = (level_w - visible_world_w) / 2.0
            max_world_x = (level_w + visible_world_w) / 2.0
            min_world_y = (level_h - visible_world_h) / 2.0
            max_world_y = (level_h + visible_world_h) / 2.0

            sx0, sy0 = self.world_to_screen(min_world_x, min_world_y)
            sx1, sy1 = self.world_to_screen(max_world_x, max_world_y)

            self.create_rectangle(sx0, sy0, sx1, sy1, outline=color, width=width, dash=dash)

            # Corner brackets
            corner_len = min(20.0, max(6.0, abs(sx1 - sx0) * 0.08), max(6.0, abs(sy1 - sy0) * 0.08))
            self.create_line(sx0, sy0, sx0 + corner_len, sy0, fill=color, width=width + 1)
            self.create_line(sx0, sy0, sx0, sy0 + corner_len, fill=color, width=width + 1)
            self.create_line(sx1, sy0, sx1 - corner_len, sy0, fill=color, width=width + 1)
            self.create_line(sx1, sy0, sx1, sy0 + corner_len, fill=color, width=width + 1)
            self.create_line(sx0, sy1, sx0 + corner_len, sy1, fill=color, width=width + 1)
            self.create_line(sx0, sy1, sx0, sy1 - corner_len, fill=color, width=width + 1)
            self.create_line(sx1, sy1, sx1 - corner_len, sy1, fill=color, width=width + 1)
            self.create_line(sx1, sy1, sx1, sy1 - corner_len, fill=color, width=width + 1)

            tag_text = f"{name}  •  zoom_side: {zoom_side} (zoom: {zoom:.3f})"
            label_y = sy0 - 14 if sy0 >= 24 else sy0 + 14
            label_x = sx0 + 8 if stage_w > 1000 else sx0 + 8
            label_id = self.create_text(
                label_x, label_y,
                text=tag_text,
                anchor="w",
                fill=color,
                font=("TkDefaultFont", 8, "bold")
            )
            bbox = self.bbox(label_id)
            if bbox:
                bg_id = self.create_rectangle(
                    bbox[0] - 5, bbox[1] - 3, bbox[2] + 5, bbox[3] + 3,
                    fill="#102530", outline=color, width=1
                )
                self.tag_lower(bg_id, label_id)

    def _draw_grid(self, width, height):
        step = GRID_SIZE
        for x in range(0, int(width) + 1, step):
            sx, _ = self.world_to_screen(x, 0); self.create_line(sx, self.offset_y, sx, self.offset_y + height*self.scale, fill="#ffffff", stipple="gray75")
        for y in range(0, int(height) + 1, step):
            _, sy = self.world_to_screen(0, y); self.create_line(self.offset_x, sy, self.offset_x + width*self.scale, sy, fill="#ffffff", stipple="gray75")

    def _clear_scaled_images(self):
        """Bound zoom-image caches without throwing useful nearby zoom levels away."""
        if len(self._parallax_scaled) > 48:
            self._parallax_scaled.clear()
        if len(self._item_scaled) > 96:
            self._item_scaled.clear()
        if len(self._water_scaled) > 16:
            self._water_scaled.clear()
        if len(self._terrain_scaled) > 64:
            self._terrain_scaled.clear()
        if len(self._terrain_fill_cache) > 60:
            self._terrain_fill_cache.clear()
        if len(self._reference_scaled) > 8:
            self._reference_scaled.clear()

    def _draw_reference_image(self):
        """Draw the loaded reference screenshot positioned in the game client viewport bounds."""
        if not self.app.show_reference_image.get() or not self.app.reference_image_pil:
            return

        orig = self.app.reference_image_pil
        s = self.model.settings
        level_w = float(s.get("width", 3000))
        level_h = float(s.get("height", 1174))
        zoom_side = s.get("zoom_side", "width")

        stage_w, stage_h = 760.0, 668.0
        zoom = stage_h / level_h if zoom_side == "height" else stage_w / level_w
        if zoom <= 0:
            return

        visible_world_w = stage_w / zoom
        visible_world_h = stage_h / zoom

        min_world_x = (level_w - visible_world_w) / 2.0
        min_world_y = (level_h - visible_world_h) / 2.0

        sx0, sy0 = self.world_to_screen(min_world_x, min_world_y)
        sx1, sy1 = self.world_to_screen(min_world_x + visible_world_w, min_world_y + visible_world_h)

        scale_mode = getattr(self.app, "reference_image_scale_mode", "fit")

        if scale_mode == "original":
            # Scale height to match the viewport height exactly; keep aspect ratio.
            # Width may overflow or underflow — image is centered horizontally.
            target_h = max(1, round(sy1 - sy0))
            ratio = target_h / orig.height if orig.height > 0 else 1.0
            target_w = max(1, round(orig.width * ratio))
            center_sx = (sx0 + sx1) / 2.0
            draw_x = round(center_sx - target_w / 2)
            key = (id(orig), target_w, target_h, "original")
            if key not in self._reference_scaled:
                resized = resize_preview_image(orig, (target_w, target_h), Image.Resampling.NEAREST)
                r, g, b, a = resized.split()
                a = a.point(lambda p: int(p * 0.60))
                transparent_img = Image.merge("RGBA", (r, g, b, a))
                self._reference_scaled[key] = ImageTk.PhotoImage(transparent_img)
            img = self._reference_scaled[key]
            self._frame_images.append(img)
            self.create_image(draw_x, round(sy0), image=img, anchor="nw")
        else:
            # "fit": scale image to exactly cover the client viewport
            target_w = max(1, round(sx1 - sx0))
            target_h = max(1, round(sy1 - sy0))
            key = (id(orig), target_w, target_h, "fit")
            if key not in self._reference_scaled:
                resized = resize_preview_image(orig, (target_w, target_h), Image.Resampling.NEAREST)
                r, g, b, a = resized.split()
                a = a.point(lambda p: int(p * 0.60))
                transparent_img = Image.merge("RGBA", (r, g, b, a))
                self._reference_scaled[key] = ImageTk.PhotoImage(transparent_img)
            img = self._reference_scaled[key]
            self._frame_images.append(img)
            self.create_image(sx0, sy0, image=img, anchor="nw")

    def _get_water_tile(self, theme):
        """Return (scaled_tile, water_color) for the theme."""
        folder = asset_folder("water", theme) or asset_folder("water", "Winter") or asset_folder("water", "Forest")
        if not folder or not folder.is_dir():
            return None, None
        tile_file = folder / "water_tile.png"
        if not tile_file.is_file():
            matches = glob.glob(str(folder / "*.png"))
            if not matches:
                return None, None
            tile_file = Path(matches[0])
        key = str(tile_file)
        if key not in self._water_originals:
            try:
                with Image.open(tile_file) as img:
                    orig = img.convert("RGBA")
                    pixel = orig.getpixel((orig.width // 2, orig.height - 1))
                    color = f"#{pixel[0]:02x}{pixel[1]:02x}{pixel[2]:02x}"
                    self._water_originals[key] = (orig, color)
            except (OSError, ValueError):
                return None, None
        original, water_color = self._water_originals[key]
        cache_scale = round(self.scale, 3)
        size = (max(1, round(original.width * cache_scale)), max(1, round(original.height * cache_scale)))
        scaled_key = (key, size)
        if scaled_key not in self._water_scaled:
            self._water_scaled[scaled_key] = ImageTk.PhotoImage(resize_preview_image(original, size, Image.Resampling.NEAREST))
        return self._water_scaled[scaled_key], water_color

    def _draw_water(self, s, x0, y0, x1, y1):
        """Draw realistic water/mud wave tiles or the simplified placeholder."""
        water_line = float(s.get("water_line", 880))
        level_width = float(s.get("width", 3000))
        level_height = float(s.get("height", 1174))
        theme = s.get("theme", "Forest")
        water_tile, water_color = self._get_water_tile(theme) if self.app.show_water_images.get() else (None, None)

        vw, vh = self.winfo_width(), self.winfo_height()
        if water_tile:
            tile_w = 198.0 * self.scale
            wave_y = self.world_to_screen(0, water_line + PREVIEW_WATER_SURFACE_OFFSET)[1]
            solid_y = self.world_to_screen(0, water_line + 106.0)[1]
            
            # Draw solid water rectangle if within visible height
            if level_height - water_line > 106.0 and solid_y < vh + 10 and y1 > -10:
                self.create_rectangle(x0, solid_y, x1, y1, fill=water_color or "#224a96", outline="")
                
            # Only draw wave tiles if visible on Y axis
            if wave_y > -tile_w - 50 and wave_y < vh + 50:
                # Fast direct visible tile index calculation
                tile_world = 198.0
                min_world_x = max(0.0, self.screen_to_world(-tile_w - 50, 0)[0])
                max_world_x = min(level_width + tile_world, self.screen_to_world(vw + tile_w + 50, 0)[0])
                start_idx = max(0, int(min_world_x // tile_world))
                end_idx = min(int((level_width + tile_world) // tile_world) + 1, int(max_world_x // tile_world) + 1)
                
                for idx in range(start_idx, end_idx):
                    sx = self.world_to_screen(idx * tile_world, 0)[0]
                    self.create_image(sx, wave_y, image=water_tile, anchor="nw")
        else:
            wy = self.world_to_screen(0, water_line + PREVIEW_WATER_SURFACE_OFFSET)[1]
            if wy < vh + 10 and y1 > -10:
                self.create_rectangle(x0, wy, x1, y1, fill="#3d9ed1", stipple="gray25", outline="")
                self.create_line(x0, wy, x1, wy, fill="#c5f4ff", width=2)

    def _get_item_image(self, name, material, angle=0.0, alpha=1.0):
        """Return sprite artwork at its exact viewport-scaled size, rotation, and opacity."""
        folder = asset_folder("items", material)
        if not folder or name not in ITEM_EXPORTS:
            return None
        export = ITEM_EXPORTS[name]
        source_key = (str(folder), export)
        source_path = self._item_sources.get(source_key)
        if source_path is None:
            matches = glob.glob(str(folder / f"*_{export}_1.png"))
            source_path = matches[0] if matches else ""
            self._item_sources[source_key] = source_path
        if not source_path:
            return None
        if source_path not in self._item_originals:
            try:
                with Image.open(source_path) as original:
                    self._item_originals[source_path] = original.convert("RGBA")
            except (OSError, ValueError):
                return None
        original = self._item_originals[source_path]
        cache_scale = round(self.scale, 3)
        size = (max(1, round(original.width * cache_scale)), max(1, round(original.height * cache_scale)))
        norm_angle = round(angle % 360, 1)
        norm_alpha = round(alpha, 2)
        key = (source_path, size, norm_angle, norm_alpha)
        if key not in self._item_scaled:
            resized = resize_preview_image(original, size, Image.Resampling.NEAREST)
            if norm_angle != 0:
                resized = resized.rotate(-norm_angle, expand=True, resample=Image.Resampling.NEAREST)
            if norm_alpha < 1.0:
                r, g, b, a = resized.split()
                a = a.point(lambda p: int(p * norm_alpha))
                resized = Image.merge("RGBA", (r, g, b, a))
            self._item_scaled[key] = ImageTk.PhotoImage(resized)
        return self._item_scaled[key]

    def _get_spawn_image(self):
        """Return the idle penguin at the same world-to-screen scale as play.

        The client zooms its object container by ``stageHeight / level.height``.
        ``self.scale`` is this editor preview's equivalent world-to-screen
        scale, so no additional map-size multiplier is needed (or correct).
        """
        if self._spawn_original is None:
            folder = asset_folder("characters", "Penguin")
            path = folder / "idle.png" if folder else None
            try:
                with Image.open(path) as source:
                    self._spawn_original = source.convert("RGBA")
            except (OSError, ValueError, TypeError):
                self._spawn_original = False
        if self._spawn_original is False:
            return None
        cache_scale = round(self.scale, 3)
        size = (
            max(1, round(self._spawn_original.width * cache_scale)),
            max(1, round(self._spawn_original.height * cache_scale)),
        )
        if size not in self._spawn_scaled:
            self._spawn_scaled[size] = ImageTk.PhotoImage(
                resize_preview_image(self._spawn_original, size, Image.Resampling.NEAREST)
            )
        return self._spawn_scaled[size]

    def _draw_element(self, i, e):
        selected = self.selected == ("element", i)
        if e.get("element_type") == "TerrainBlockEntity":
            if not self.app.show_terrain.get():
                return
            points = e.get("points", [])
            if len(points) < 3: return
            screen_points = [self.world_to_screen(float(p["x"]), float(p["y"])) for p in points]
            flat = [coordinate for point in screen_points for coordinate in point]
            material = e.get("theme", "Wood")
            show_outline = e.get("outline", True)
            is_dynamic = e.get("dynamic", False)
            no_fixtures = e.get("no_fixtures", False)

            # Color adjustments: game formula is offset = channel_val + red/green/blue + (tint - shade)
            shade = int(e.get("shade", 0)); tint = int(e.get("tint", 0))
            r_off = int(e.get("red", 0)); g_off = int(e.get("green", 0)); b_off = int(e.get("blue", 0))

            if not self.app.show_terrain_images.get() or not self._draw_terrain_texture(screen_points, material, shade=shade, tint=tint, r_off=r_off, g_off=g_off, b_off=b_off):
                base_color = MATERIAL_COLORS.get(material, "#888888")
                # Apply color adjustments to fallback color
                br, bg, bb = int(base_color[1:3], 16), int(base_color[3:5], 16), int(base_color[5:7], 16)
                delta = tint - shade
                fr = max(0, min(255, br + r_off + delta))
                fg = max(0, min(255, bg + g_off + delta))
                fb = max(0, min(255, bb + b_off + delta))
                fill_color = f"#{fr:02x}{fg:02x}{fb:02x}"
                stipple = "gray50" if no_fixtures else ""
                self.create_polygon(*flat, fill=fill_color, outline="", stipple=stipple)

            # Outline: border line (dashed if no_fixtures, dotted dash if dynamic)
            if show_outline or selected:
                if selected:
                    line_color, line_width, dash = "#ffffff", 3, None
                elif is_dynamic:
                    line_color, line_width, dash = "#f0a020", 2, (8, 4)
                elif no_fixtures:
                    line_color, line_width, dash = "#8080ff", 1, (4, 4)
                else:
                    line_color, line_width, dash = "#273840", 1, None
                kw = {"fill": line_color, "width": line_width}
                if dash:
                    kw["dash"] = dash
                self.create_line(*flat, *screen_points[0], **kw)

            if e.get("grass_theme") == "[Material]": self._draw_terrain_top_border(screen_points, material)
            if selected:
                for x, y in zip(flat[::2], flat[1::2]):
                    self.create_oval(x-5, y-5, x+5, y+5, fill="#ffffff", outline="#17364d", width=2)

        else:
            if not self.app.show_items.get():
                return
            vw, vh = self.winfo_width(), self.winfo_height()
            x, y = self.world_to_screen(float(e.get("x", 0)), float(e.get("y", 0)))
            angle = float(e.get("angle", 0.0))
            name = e.get("name", "Object"); dims = next((v[2:] for v in FIXTURES.values() if v[0] == name), (50, 50))
            w, h = dims[0] * self.scale, dims[1] * self.scale
            max_r = max(w, h) / 2 + 30
            if not selected and (x < -max_r or x > vw + max_r or y < -max_r or y > vh + max_r):
                return
            color = MATERIAL_COLORS.get(e.get("theme", "Wood"), "#999999")
            image = self._get_item_image(name, e.get("theme", "Wood"), angle=angle)
            if image:
                self.create_image(x, y, image=image, anchor="center")
                if selected:
                    iw, ih = image.width(), image.height()
                    self.create_rectangle(x-iw/2, y-ih/2, x+iw/2, y+ih/2, outline="#ffffff", width=2)
            else:
                rad = math.radians(angle)
                cos_a, sin_a = math.cos(rad), math.sin(rad)
                if "Ball" in name:
                    self.create_oval(x-w/2, y-h/2, x+w/2, y+h/2, fill=color, outline="#ffffff" if selected else "#273840", width=3 if selected else 1)
                elif "Triangle" in name:
                    raw_pts = [(0, -h/2), (-w/2, h/2), (w/2, h/2)]
                    rot_pts = [
                        coord for px, py in raw_pts
                        for coord in (x + px * cos_a - py * sin_a, y + px * sin_a + py * cos_a)
                    ]
                    self.create_polygon(*rot_pts, fill=color, outline="#ffffff" if selected else "#273840", width=3 if selected else 1)
                else:
                    raw_pts = [(-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)]
                    rot_pts = [
                        coord for px, py in raw_pts
                        for coord in (x + px * cos_a - py * sin_a, y + px * sin_a + py * cos_a)
                    ]
                    self.create_polygon(*rot_pts, fill=color, outline="#ffffff" if selected else "#273840", width=3 if selected else 1)
            if self.app.show_item_labels.get():
                label_text = name.replace("Medium", " M").replace("Large", " L").replace("Small", " S")
                if angle != 0:
                    label_text += f" {int(angle)}°"
                self.create_text(x, y, text=label_text, font=("TkDefaultFont", 7), fill="#17232c")

    def _draw_item_placement_preview(self):
        """Draw a semi-transparent preview of the item at cursor position during item placing mode."""
        if self.tool != "item" or self.hover_pos is None or not self.app.show_items.get():
            return
        hx, hy = self.hover_pos
        label = self.app.item_fixture.get()
        if label not in FIXTURES:
            return
        name, fixture, _, _ = FIXTURES[label]
        material = self.app.item_material.get()
        angle = getattr(self, "item_placing_angle", 0.0)
        dims = next((v[2:] for v in FIXTURES.values() if v[0] == name), (50, 50))
        w, h = dims[0] * self.scale, dims[1] * self.scale

        image = self._get_item_image(name, material, angle=angle, alpha=0.55)
        if image:
            self.create_image(hx, hy, image=image, anchor="center")
            iw, ih = image.width(), image.height()
            self.create_rectangle(hx - iw/2, hy - ih/2, hx + iw/2, hy + ih/2, outline="#38bdf8", width=1, dash=(4, 2))
        else:
            color = MATERIAL_COLORS.get(material, "#999999")
            rad = math.radians(angle)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            raw_pts = [(-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)]
            rot_pts = [
                coord for px, py in raw_pts
                for coord in (hx + px * cos_a - py * sin_a, hy + px * sin_a + py * cos_a)
            ]
            self.create_polygon(*rot_pts, fill=color, outline="#38bdf8", stipple="gray50", width=1)

        # Draw angle label under preview
        self.create_text(hx, hy + max(w, h)/2 + 14, text=f"{int(angle)}°", font=("TkDefaultFont", 8, "bold"), fill="#38bdf8")

    def _terrain_image(self, material, name):
        """Load a supplied terrain sprite for this material, if available."""
        folder = asset_folder("terrain", material)
        path = folder / name if folder else None
        if not path or not path.is_file():
            return None, None
        key = str(path)
        if key not in self._terrain_originals:
            try:
                with Image.open(path) as source:
                    self._terrain_originals[key] = source.convert("RGBA")
            except (OSError, ValueError):
                return None, None
        return key, self._terrain_originals[key]

    # Above this pixel-area, a shape's fully-composited fill is not cached (it
    # would use too much memory); it falls back to the old per-frame,
    # viewport-clipped render instead.
    _TERRAIN_CACHE_MAX_PX = 3_000_000

    def _draw_terrain_texture(self, points, material, shade=0, tint=0, r_off=0, g_off=0, b_off=0):
        """Tile a supplied landmass texture and clip it to the terrain polygon.

        The composited (tiled + color-adjusted + masked) result is cached per
        shape/material/color/zoom so that panning or redrawing an unchanged
        map — the overwhelming majority of frames — just re-blits an existing
        PhotoImage instead of rebuilding it pixel-by-pixel every time.
        """
        _key, tile = self._terrain_image(material, "landmass_bg_tile.jpg")
        if tile is None:
            return False
        tile_size = (max(1, round(tile.width * self.scale)), max(1, round(tile.height * self.scale)))
        scaled_key = ("fill", id(tile), tile_size)
        if scaled_key not in self._terrain_scaled:
            self._terrain_scaled[scaled_key] = resize_preview_image(tile, tile_size, TERRAIN_FILL_RESAMPLING)
        scaled = self._terrain_scaled[scaled_key]

        vw, vh = self.winfo_width(), self.winfo_height()
        xs = [x for x, _y in points]; ys = [y for _x, y in points]
        left_f, top_f, right_f, bottom_f = min(xs), min(ys), max(xs), max(ys)
        if right_f <= 0 or bottom_f <= 0 or left_f >= vw or top_f >= vh:
            return True  # entirely off-screen; nothing to draw

        full_left, full_top = math.floor(left_f), math.floor(top_f)
        full_right, full_bottom = math.ceil(right_f), math.ceil(bottom_f)
        full_size = (max(1, full_right - full_left), max(1, full_bottom - full_top))

        if full_size[0] * full_size[1] <= self._TERRAIN_CACHE_MAX_PX:
            # Cacheable path: build the texture in shape-local pixel space (independent
            # of pan/scroll), then just paste it at the current screen position.
            local_points = tuple((round(x - full_left, 1), round(y - full_top, 1)) for x, y in points)
            cache_key = ("shapefill", material, shade, tint, r_off, g_off, b_off, tile_size, local_points, full_size)
            image = self._terrain_fill_cache.get(cache_key)
            if image is None:
                texture = self._composite_terrain_texture(scaled, full_size, local_points, shade, tint, r_off, g_off, b_off)
                image = ImageTk.PhotoImage(texture)
                self._terrain_fill_cache[cache_key] = image
            self.create_image(full_left, full_top, image=image, anchor="nw")
            return True

        # Fallback for very large shapes: render only the visible slice, uncached
        # (same behavior as before), so memory stays bounded.
        left, top = max(0, full_left), max(0, full_top)
        right, bottom = min(vw, full_right), min(vh, full_bottom)
        if right <= left or bottom <= top:
            return True
        size = (right - left, bottom - top)
        local_points = [(x - left, y - top) for x, y in points]
        texture = self._composite_terrain_texture(scaled, size, local_points, shade, tint, r_off, g_off, b_off)
        image = ImageTk.PhotoImage(texture)
        self._frame_images.append(image)
        self.create_image(left, top, image=image, anchor="nw")
        return True

    def _composite_terrain_texture(self, scaled_tile, size, local_points, shade, tint, r_off, g_off, b_off):
        """Tile scaled_tile across size, apply the color formula, and mask to local_points."""
        texture = Image.new("RGB", size)
        sw, sh = scaled_tile.width, scaled_tile.height
        for y in range(0, size[1], sh):
            for x in range(0, size[0], sw):
                texture.paste(scaled_tile, (x, y))
        # Apply game color formula: offset = channel + per-channel_adj + (tint - shade)
        delta = tint - shade
        if delta != 0 or r_off != 0 or g_off != 0 or b_off != 0:
            arr = np.array(texture, dtype=np.int16)
            arr[:, :, 0] = np.clip(arr[:, :, 0] + r_off + delta, 0, 255)
            arr[:, :, 1] = np.clip(arr[:, :, 1] + g_off + delta, 0, 255)
            arr[:, :, 2] = np.clip(arr[:, :, 2] + b_off + delta, 0, 255)
            texture = Image.fromarray(arr.astype(np.uint8), "RGB")
        texture = texture.convert("RGBA")
        mask = Image.new("L", size)
        ImageDraw.Draw(mask).polygon(local_points, fill=255)
        texture.putalpha(mask)
        return texture


    def _terrain_sprite(self, material, name, angle):
        """Return a scale- and angle-correct terrain tile for the canvas."""
        key, source = self._terrain_image(material, name)
        if source is None:
            return None
        cache_scale = round(self.scale, 3)
        size = (max(1, round(source.width * cache_scale)), max(1, round(source.height * cache_scale)))
        # The game's source artwork is oriented left-to-right. Pillow's visual
        # rotation is counter-clockwise, whereas screen-space angles are clockwise.
        cache_key = ("sprite", key, size, round(angle, 1))
        if cache_key not in self._terrain_scaled:
            scaled = resize_preview_image(source, size, Image.Resampling.NEAREST)
            self._terrain_scaled[cache_key] = ImageTk.PhotoImage(
                scaled.rotate(-angle, expand=True, resample=Image.Resampling.NEAREST)
            )
        return self._terrain_scaled[cache_key]

    def _draw_terrain_top_border(self, points, material):
        """Preview the same directed top-edge test used by the Flash client.

        ``TerrainDisplayObject.drawTopTiles`` only decorates edges whose
        directed angle is within 30 degrees of left-to-right. The grass tile
        itself is rotated with that edge, so reversing node order selects the
        opposite horizontal edge of a closed shape.
        """
        thickness = max(3.0, min(14.0, 18.0 * self.scale))
        vw, vh = self.winfo_width(), self.winfo_height()
        for start, end in zip(points, [*points[1:], points[0]]):
            x1, y1 = start
            x2, y2 = end
            # Cull edges completely outside the visible viewport
            if max(x1, x2) < -60 or min(x1, x2) > vw + 60 or max(y1, y2) < -60 or min(y1, y2) > vh + 60:
                continue
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if not length:
                continue
            angle = math.degrees(math.atan2(dy, dx))
            if abs(angle) >= TERRAIN_TOP_BORDER_ANGLE:
                continue
            tile = self._terrain_sprite(material, "landmass_tile.png", angle) if self.app.show_terrain_images.get() else None
            left_cap = self._terrain_sprite(material, "landmass_end_left.png", angle) if tile else None
            right_cap = self._terrain_sprite(material, "landmass_end_right.png", angle) if tile else None
            if tile:
                self.create_image(x1, y1, image=left_cap or tile, anchor="center")
                # The client spaces the repeating sprite by half its native
                # width; using that same cadence prevents visible gaps on hills.
                step = max(8.0, 18.5 * self.scale)
                distance = step
                while distance < length - step * .35:
                    px = x1 + dx * distance / length
                    py = y1 + dy * distance / length
                    if px > -60 and px < vw + 60 and py > -60 and py < vh + 60:
                        self.create_image(px, py, image=tile, anchor="center")
                    distance += step
                self.create_image(x2, y2, image=right_cap or tile, anchor="center")
                continue
            # This is the right-hand normal of the directed edge.  For a
            # conventional left-to-right top edge it points upward. It is the
            # fallback when artwork for a material has not been installed yet.
            nx, ny = dy / length, -dx / length
            outer_start = (x1 + nx * thickness, y1 + ny * thickness)
            outer_end = (x2 + nx * thickness, y2 + ny * thickness)
            self.create_polygon(
                x1, y1, x2, y2, *outer_end, *outer_start,
                fill="#739d32", outline="",
            )
            self.create_line(*outer_start, *outer_end, fill="#d1ed72", width=max(1, round(thickness * .28)))

    def _draw_hud(self):
        name = self.model.settings["level_name"]
        self.create_text(12, 10, text=f"{name}  •  {int(self.model.settings['width'])} × {int(self.model.settings['height'])}  •  {int(self.scale*100)}%", anchor="nw", fill="#ffffff", font=("TkDefaultFont", 9, "bold"))
        if self.tool == "terrain":
            self.create_text(12, 30, text="Terrain: click corners • Enter/right-click closes polygon • Esc to cancel", anchor="nw", fill="#ffffff")
        elif self.tool == "item":
            angle_tag = f"{int(self.item_placing_angle)}°"
            self.create_text(12, 30, text=f"Item: scroll wheel to rotate ({angle_tag}) • click to place • Esc to cancel", anchor="nw", fill="#ffffff")

    def mouse_motion(self, event):
        if self.tool == "item":
            self.hover_pos = (event.x, event.y)
            self.request_draw()

    def mouse_leave(self, event):
        if self.tool == "item" and self.hover_pos is not None:
            self.hover_pos = None
            self.request_draw()

    def _on_scroll_up(self, event):
        if self.tool == "item":
            self.item_placing_angle = round((self.item_placing_angle + 15.0) % 360, 1)
            self.draw()
        else:
            self.zoom(1.15, event.x, event.y)

    def _on_scroll_down(self, event):
        if self.tool == "item":
            self.item_placing_angle = round((self.item_placing_angle - 15.0) % 360, 1)
            self.draw()
        else:
            self.zoom(1 / 1.15, event.x, event.y)

    def set_tool(self, tool):
        self.tool = tool; self.cancel_polygon(); self.configure(cursor="crosshair" if tool != "pan" else "fleur")
        if tool != "item":
            self.hover_pos = None
        if tool == "terrain" and not self.app.show_terrain.get():
            self.app.show_terrain.set(True)
            self.app._on_show_terrain_changed()
        elif tool == "item" and not self.app.show_items.get():
            self.app.show_items.set(True)
            self.app._on_show_items_changed()
        self.app.set_status({"select":"Select / move", "terrain":"Draw terrain", "item":"Place item", "spawn":"Place spawn", "pan":"Pan map"}.get(tool, tool))
        self.draw()

    def left_click(self, event):
        self.focus_set(); wx, wy = self.screen_to_world(event.x, event.y)
        if self.tool == "pan": self.pan_start = (event.x, event.y); return
        if self.tool == "terrain":
            if not self.app.show_terrain.get():
                self.app.show_terrain.set(True)
                self.app._on_show_terrain_changed()
            self.polygon.append((wx, wy)); self.draw(); return
        if self.tool == "item":
            if not self.app.show_items.get():
                self.app.show_items.set(True)
                self.app._on_show_items_changed()
            self.app.place_item(wx, wy, angle=getattr(self, "item_placing_angle", 0.0))
            return
        if self.tool == "spawn": self.app.place_spawn(wx, wy); return
        node_hit = self.terrain_node_at(event.x, event.y)
        if node_hit:
            element_index, node_index = node_hit
            self.selected = ("element", element_index)
            self.drag = ("node", element_index, node_index)
            self.app.selection_changed(self.selected)
            self.app.set_status("Dragging terrain node.")
            self.draw()
            return
        hit = self.hit_test(event.x, event.y)
        self.selected = hit
        self.app.selection_changed(hit)
        if hit: self.drag = ("move", hit, wx, wy)
        self.draw()

    def right_click(self, event):
        if self.tool == "terrain" and self.polygon:
            self.finish_polygon()
            return
        node_hit = self.terrain_node_at(event.x, event.y)
        hit = ("element", node_hit[0]) if node_hit else self.hit_test(event.x, event.y)
        if hit:
            self.selected = hit
            self.app.selection_changed(hit)
            self.draw()
            self.app.open_context(hit)

    def right_press(self, event):
        """Start a right-button pan; a stationary click keeps its old action."""
        self.focus_set()
        self.right_pan_start = (event.x, event.y)
        self.right_pan_moved = False

    def right_drag_motion(self, event):
        if self.right_pan_start is None:
            return
        old_x, old_y = self.right_pan_start
        dx, dy = event.x - old_x, event.y - old_y
        if dx or dy:
            self.right_pan_moved = True
            self.offset_x += dx
            self.offset_y += dy
            self.right_pan_start = (event.x, event.y)
            self.request_draw()

    def right_release(self, event):
        if not self.right_pan_moved:
            self.right_click(event)
        self.right_pan_start = None
        self.right_pan_moved = False

    def drag_motion(self, event):
        if self.pan_start:
            ox, oy = self.pan_start; self.offset_x += event.x - ox; self.offset_y += event.y - oy; self.pan_start = (event.x, event.y); self.request_draw(); return
        if not self.drag: return
        if not self._drag_moved:
            self.app.push_undo("Move object" if self.drag[0] == "move" else "Move terrain node")
            self._drag_moved = True
        wx, wy = self.screen_to_world(event.x, event.y)
        if self.drag[0] == "node":
            _, element_index, node_index = self.drag
            point = self.model.elements[element_index].get("points", [])[node_index]
            point["x"], point["y"] = round(wx, 2), round(wy, 2)
            self.app.dirty = True
            self.request_draw()
            return
        _, hit, oldx, oldy = self.drag; dx, dy = wx-oldx, wy-oldy
        kind, i = hit
        if kind == "spawn": self.model.spawns[i]["x"] += dx; self.model.spawns[i]["y"] += dy
        else:
            e = self.model.elements[i]
            if e.get("element_type") == "TerrainBlockEntity":
                for p in e.get("points", []): p["x"] += dx; p["y"] += dy
            else: e["x"] += dx; e["y"] += dy
        self.drag = ("move", hit, wx, wy); self.app.dirty = True; self.request_draw()

    def release(self, event):
        self.drag = self.pan_start = None
        self._drag_moved = False
    def wheel(self, event):
        if self.tool == "item":
            step = 15.0
            delta = step if event.delta > 0 else -step
            self.item_placing_angle = round((self.item_placing_angle + delta) % 360, 1)
            self.draw()
        else:
            self.zoom(1.15 if event.delta > 0 else 1 / 1.15, event.x, event.y)
    def finish_polygon(self):
        if len(self.polygon) < 3: self.app.set_status("Terrain needs at least 3 corners."); return
        self.app.push_undo("Draw terrain element")
        theme = self.app.terrain_material.get()
        self.model.elements.append({"shade": 0, "id": f"terrain_{len(self.model.elements) + 1}", "element_type": "TerrainBlockEntity", "texture_export": "landmass_bg_tile.png", "blue": 0, "red": 0, "texture_rotation": 0, "no_fixtures": False, "green": 0, "outline": True, "unbreakable": False, "dynamic": False, "shape": "edgeShape", "tint": 0, "points": [{"x": round(x, 2), "y": round(y, 2)} for x, y in self.polygon], "theme": theme, "texture_swf": TERRAIN_TEXTURE_SWFS[theme], "grass_theme": "[Material]" if self.app.grass.get() else "[None]"})
        self.selected = ("element", len(self.model.elements)-1); self.polygon = []; self.app.dirty = True; self.app.refresh_lists(); self.draw()
    def cancel_polygon(self): self.polygon = []; self.draw()
    def handle_escape(self):
        """Cancel current tool or active terrain polygon."""
        if self.tool == "terrain" and self.polygon:
            self.cancel_polygon()
            self.app.set_status("Terrain polygon cancelled.")
        elif self.tool in ("item", "spawn", "terrain", "pan"):
            self.set_tool("select")
            self.hover_pos = None
            self.draw()
    def hit_test(self, sx, sy):
        for i in range(len(self.model.spawns)-1, -1, -1):
            x, y = self.world_to_screen(float(self.model.spawns[i]["x"]), float(self.model.spawns[i]["y"]))
            if math.hypot(sx-x, sy-y) < 14: return ("spawn", i)
        for i in range(len(self.model.elements)-1, -1, -1):
            e = self.model.elements[i]
            if e.get("element_type") == "TerrainBlockEntity":
                if not self.app.show_terrain.get(): continue
                points = [self.world_to_screen(float(p["x"]), float(p["y"])) for p in e.get("points", [])]
                if self.point_in_polygon(sx, sy, points): return ("element", i)
            else:
                if not self.app.show_items.get(): continue
                x, y = self.world_to_screen(float(e.get("x", 0)), float(e.get("y", 0)))
                if abs(sx-x) < 25 and abs(sy-y) < 25: return ("element", i)
        return None

    def terrain_node_at(self, sx, sy):
        """Return the terrain/node beneath a visible edit handle, if any."""
        if not self.app.show_terrain.get():
            return None
        for i in range(len(self.model.elements)-1, -1, -1):
            element = self.model.elements[i]
            if element.get("element_type") != "TerrainBlockEntity" or self.selected != ("element", i):
                continue
            for node_index, point in enumerate(element.get("points", [])):
                x, y = self.world_to_screen(float(point["x"]), float(point["y"]))
                if math.hypot(sx - x, sy - y) <= 9:
                    return i, node_index
        return None
    def nudge_selected(self, dir_x: int, dir_y: int, event=None):
        """Move the selected element, item, spawnpoint, or parallax layer with arrow keys."""
        # Move step based on current zoom: 1 screen pixel (or 10 with Shift)
        pixels = 10.0 if (event and event.state & 0x0001) else 1.0
        step = max(0.1, round(pixels / self.scale, 2))
        dx = dir_x * step
        dy = dir_y * step

        if self.selected:
            if self.tool != "select":
                return
            kind, i = self.selected
            if kind == "spawn" and 0 <= i < len(self.model.spawns):
                self.app.push_undo("nudge spawn")
                sp = self.model.spawns[i]
                sp["x"] = round(float(sp["x"]) + dx, 2)
                sp["y"] = round(float(sp["y"]) + dy, 2)
                self.app.set_status(f"Moved spawnpoint {i+1} to ({sp['x']}, {sp['y']}).")
                self.app.dirty = True
                self.draw()
            elif kind == "element" and 0 <= i < len(self.model.elements):
                self.app.push_undo("nudge element")
                e = self.model.elements[i]
                if e.get("element_type") == "TerrainBlockEntity":
                    for p in e.get("points", []):
                        p["x"] = round(float(p["x"]) + dx, 2)
                        p["y"] = round(float(p["y"]) + dy, 2)
                    self.app.set_status(f"Moved terrain element {i+1}.")
                else:
                    e["x"] = round(float(e.get("x", 0)) + dx, 2)
                    e["y"] = round(float(e.get("y", 0)) + dy, 2)
                    self.app.set_status(f"Moved item {i+1} to ({e['x']}, {e['y']}).")
                self.app.dirty = True
                self.draw()
        else:
            layer_idx = self.app.current_layer()
            if layer_idx is not None and 0 <= layer_idx < len(self.model.parallaxes):
                self.app.push_undo("nudge parallax layer")
                layer = self.model.parallaxes[layer_idx]
                layer["x"] = round(float(layer.get("x", 0)) + dx, 2)
                layer["y"] = round(float(layer.get("y", 0)) + dy, 2)
                self.app.set_status(f"Moved parallax layer {layer_idx+1} to ({layer['x']}, {layer['y']}).")
                self.app.dirty = True
                self.app.refresh_lists()
                self.app.layer_list.selection_set(layer_idx)
                self.draw()

    @staticmethod
    def point_in_polygon(x, y, pts):
        inside = False; j = len(pts)-1
        for i in range(len(pts)):
            xi, yi = pts[i]; xj, yj = pts[j]
            if (yi > y) != (yj > y) and x < (xj-xi)*(y-yi)/(yj-yi or .00001)+xi: inside = not inside
            j = i
        return inside