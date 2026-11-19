from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk
from tkinterdnd2 import DND_FILES, TkinterDnD

from converter import (
    COMPRESSION_PRESETS,
    CONVERSION_STYLES,
    CropBox,
    OUTPUT_FOLDER_NAME,
    PALETTES,
    PIXEL_STYLES,
    BatchConversionResult,
    convert_many,
    metadata_token,
    validate_source,
)
from frame_client import FRAME_IMAGES_FOLDER_NAME, SEND_FOLDER_NAME, FrameClient


BG = "#111827"
PANEL = "#1f2937"
DROP_BG = "#263449"
TEXT = "#f8fafc"
MUTED = "#aab6c8"
ACCENT = "#22c55e"
BLUE = "#3b82f6"


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


class GifTool(TkinterDnD.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("GIF 160×128 • Pixel Tool")
        self.geometry("780x900")
        self.minsize(720, 820)
        self.configure(bg=BG)
        self.sources: list[Path] = []
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.preview_source_image: Image.Image | None = None
        self.preview_image_box = (0.0, 0.0, 1.0, 1.0)
        self.crop_boxes: dict[Path, CropBox] = {}
        self.current_source_index = 0
        self.drag_position: tuple[int, int] | None = None
        self.output_dir = application_dir()
        self.send_dir = self.output_dir / SEND_FOLDER_NAME
        self.frame_images_dir = self.output_dir / FRAME_IMAGES_FOLDER_NAME
        self.send_dir.mkdir(parents=True, exist_ok=True)
        self._configure_styles()
        self._build_ui()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=DROP_BG, background=PANEL, foreground=TEXT, arrowcolor=TEXT, padding=7)
        style.map("TCombobox", fieldbackground=[("readonly", DROP_BG)], foreground=[("readonly", TEXT)])

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=32, pady=(26, 14))
        tk.Label(header, text="GIF 160×128", font=("Segoe UI", 24, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(header, text="Konwerter obrazów i animacji dla wyświetlacza", font=("Segoe UI", 10), bg=BG, fg=MUTED).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=32)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        self.drop = tk.Frame(body, bg=DROP_BG, highlightbackground="#475569", highlightthickness=2)
        self.drop.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        self.preview = tk.Canvas(
            self.drop, width=430, height=330, bg=DROP_BG,
            highlightthickness=0, cursor="fleur",
        )
        self.preview.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        self.preview.create_text(215, 155, text="↓", font=("Segoe UI", 42, "bold"), fill=BLUE)
        self.preview.create_text(215, 210, text="Przeciągnij tutaj pliki", font=("Segoe UI", 12, "bold"), fill=TEXT)
        self.preview.bind("<ButtonPress-1>", self.start_crop_drag)
        self.preview.bind("<B1-Motion>", self.drag_crop)
        self.preview.bind("<ButtonRelease-1>", lambda _event: self.stop_crop_drag())
        self.preview.bind("<MouseWheel>", self.crop_mousewheel)
        self.preview.bind("<Double-Button-1>", lambda _event: self.choose_file())
        self.preview.bind("<Configure>", lambda _event: self.render_preview())

        navigation = tk.Frame(self.drop, bg=DROP_BG)
        navigation.pack(fill="x", padx=14, pady=(2, 4))
        tk.Button(navigation, text="◀", command=lambda: self.change_preview(-1), bg=PANEL, fg=TEXT, relief="flat", width=4).pack(side="left")
        self.preview_counter = tk.Label(navigation, text="0 / 0", bg=DROP_BG, fg=MUTED, font=("Segoe UI", 9))
        self.preview_counter.pack(side="left", expand=True)
        tk.Button(navigation, text="▶", command=lambda: self.change_preview(1), bg=PANEL, fg=TEXT, relief="flat", width=4).pack(side="right")

        crop_controls = tk.Frame(self.drop, bg=DROP_BG)
        crop_controls.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(crop_controls, text="Kadr 5:4", bg=DROP_BG, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Button(crop_controls, text="−", command=lambda: self.zoom_crop(1.15), bg=PANEL, fg=TEXT, relief="flat", width=4).pack(side="left", padx=(12, 4))
        tk.Button(crop_controls, text="+", command=lambda: self.zoom_crop(0.87), bg=PANEL, fg=TEXT, relief="flat", width=4).pack(side="left")
        tk.Button(crop_controls, text="Reset", command=self.reset_crop, bg=PANEL, fg=TEXT, relief="flat", padx=10).pack(side="right")
        tk.Button(crop_controls, text="Całość", command=self.fit_whole_image, bg=PANEL, fg=TEXT, relief="flat", padx=10).pack(side="right", padx=(0, 5))
        self.file_label = tk.Label(self.drop, text="Przeciągnij tutaj pliki", font=("Segoe UI", 13, "bold"), bg=DROP_BG, fg=TEXT, wraplength=380)
        self.file_label.pack(padx=20)
        tk.Label(self.drop, text="Podwójne kliknięcie wybiera pliki • kółko zmienia zoom", font=("Segoe UI", 9), bg=DROP_BG, fg=MUTED).pack(pady=(5, 14))
        for widget in (self.drop, self.preview, self.file_label):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self.on_drop)
        self.file_label.bind("<Button-1>", lambda _event: self.choose_file())

        options = tk.Frame(body, bg=PANEL, padx=20, pady=20)
        options.grid(row=0, column=1, sticky="nsew")
        tk.Label(options, text="OPCJE PIXEL ART", font=("Segoe UI", 10, "bold"), bg=PANEL, fg=MUTED).pack(anchor="w")
        tk.Label(options, text="Styl", font=("Segoe UI", 9), bg=PANEL, fg=TEXT).pack(anchor="w", pady=(18, 5))
        self.style_var = tk.StringVar(value=list(PIXEL_STYLES)[1])
        ttk.Combobox(options, textvariable=self.style_var, values=list(PIXEL_STYLES), state="readonly").pack(fill="x")
        tk.Label(options, text="Paleta", font=("Segoe UI", 9), bg=PANEL, fg=TEXT).pack(anchor="w", pady=(18, 5))
        self.palette_var = tk.StringVar(value=list(PALETTES)[0])
        ttk.Combobox(options, textvariable=self.palette_var, values=list(PALETTES), state="readonly").pack(fill="x")
        tk.Label(options, text="Kompresja GIF", font=("Segoe UI", 9), bg=PANEL, fg=TEXT).pack(anchor="w", pady=(18, 5))
        self.compression_var = tk.StringVar(value=list(COMPRESSION_PRESETS)[1])
        ttk.Combobox(options, textvariable=self.compression_var, values=list(COMPRESSION_PRESETS), state="readonly").pack(fill="x")
        tk.Label(options, text="Folder na karcie", font=("Segoe UI", 9), bg=PANEL, fg=TEXT).pack(anchor="w", pady=(18, 5))
        self.folder_var = tk.StringVar(value="glowny")
        tk.Entry(
            options, textvariable=self.folder_var, bg=DROP_BG, fg=TEXT,
            insertbackground=TEXT, relief="flat", bd=0, font=("Segoe UI", 9),
        ).pack(fill="x", ipady=8)
        tk.Label(options, text="Tagi (przecinki lub spacje)", font=("Segoe UI", 9), bg=PANEL, fg=TEXT).pack(anchor="w", pady=(18, 5))
        self.tags_var = tk.StringVar()
        tk.Entry(
            options, textvariable=self.tags_var, bg=DROP_BG, fg=TEXT,
            insertbackground=TEXT, relief="flat", bd=0, font=("Segoe UI", 9),
        ).pack(fill="x", ipady=8)
        tk.Label(options, text="Adres ramki", font=("Segoe UI", 9), bg=PANEL, fg=TEXT).pack(anchor="w", pady=(18, 5))
        self.frame_address_var = tk.StringVar(value="http://ramka.local")
        tk.Entry(
            options,
            textvariable=self.frame_address_var,
            bg=DROP_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            font=("Segoe UI", 9),
        ).pack(fill="x", ipady=8)
        tk.Label(options, text="Do wyniku trafi obszar zaznaczony żółtą ramką 5:4.", font=("Segoe UI", 9), bg=PANEL, fg=MUTED, wraplength=210, justify="left").pack(anchor="w", pady=(22, 0))

        actions = tk.Frame(self, bg=BG)
        actions.pack(fill="x", padx=32, pady=(18, 0))
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)
        self.action_buttons: list[tk.Button] = []
        for index, conversion_style in enumerate(CONVERSION_STYLES.values()):
            button = self._button(
                actions,
                conversion_style.button_label,
                conversion_style.color,
                lambda key=conversion_style.key: self.convert(key),
            )
            button.grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=(0, 6) if index % 2 == 0 else (6, 0),
                pady=(0, 6) if index < 2 else (6, 0),
            )
            self.action_buttons.append(button)

        transfer = tk.Frame(self, bg=BG)
        transfer.pack(fill="x", padx=32, pady=(16, 0))
        transfer.grid_columnconfigure(0, weight=1)
        transfer.grid_columnconfigure(1, weight=1)
        self.send_button = self._button(transfer, "WYŚLIJ DO RAMKI", "#06b6d4", self.send_to_frame)
        self.send_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.fetch_button = self._button(transfer, "POBIERZ Z RAMKI", "#6366f1", self.download_from_frame)
        self.fetch_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.transfer_buttons = [self.send_button, self.fetch_button]

        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", padx=32, pady=(12, 22))
        self.status = tk.Label(footer, text="Wyniki zapisują się w folderze „wyniki”.", font=("Segoe UI", 9), bg=BG, fg=MUTED, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        tk.Button(footer, text="Otwórz folder", command=self.open_output_dir, bg=BG, fg=BLUE, activebackground=BG, activeforeground="#60a5fa", relief="flat", cursor="hand2", font=("Segoe UI", 9, "underline")).pack(side="right")

    def _button(self, parent: tk.Widget, text: str, color: str, command) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=color, fg="white", activebackground=color, activeforeground="white", relief="flat", bd=0, padx=18, pady=13, cursor="hand2", font=("Segoe UI", 10, "bold"))

    @staticmethod
    def default_crop_box(size: tuple[int, int]) -> CropBox:
        width, height = size
        target_ratio = 5 / 4
        if width / height > target_ratio:
            normalized_width = height * target_ratio / width
            margin = (1 - normalized_width) / 2
            return margin, 0.0, 1 - margin, 1.0
        normalized_height = width / target_ratio / height
        margin = (1 - normalized_height) / 2
        return 0.0, margin, 1.0, 1 - margin

    @staticmethod
    def whole_image_crop_box(size: tuple[int, int]) -> CropBox:
        width, height = size
        target_ratio = 5 / 4
        if width / height > target_ratio:
            normalized_height = width / target_ratio / height
            margin = (normalized_height - 1) / 2
            return 0.0, -margin, 1.0, 1 + margin
        normalized_width = height * target_ratio / width
        margin = (normalized_width - 1) / 2
        return -margin, 0.0, 1 + margin, 1.0

    @staticmethod
    def open_preview_image(path: Path) -> Image.Image:
        with Image.open(path) as image:
            image.seek(0)
            return ImageOps.exif_transpose(image).convert("RGB")

    def current_source(self) -> Path | None:
        if not self.sources:
            return None
        return self.sources[self.current_source_index]

    def load_current_preview(self) -> None:
        source = self.current_source()
        if source is None:
            self.preview_source_image = None
            self.render_preview()
            return
        self.preview_source_image = self.open_preview_image(source)
        self.crop_boxes.setdefault(source, self.default_crop_box(self.preview_source_image.size))
        self.preview_counter.configure(text=f"{self.current_source_index + 1} / {len(self.sources)}")
        self.render_preview()

    def render_preview(self) -> None:
        self.preview.delete("all")
        source = self.current_source()
        image = self.preview_source_image
        width = max(120, self.preview.winfo_width())
        height = max(120, self.preview.winfo_height())
        if source is None or image is None:
            self.preview.create_text(width / 2, height / 2 - 20, text="↓", font=("Segoe UI", 42, "bold"), fill=BLUE)
            self.preview.create_text(width / 2, height / 2 + 35, text="Przeciągnij tutaj pliki", font=("Segoe UI", 12, "bold"), fill=TEXT)
            return
        x0, y0, x1, y1 = self.crop_boxes[source]
        outer_x0, outer_y0, outer_x1, outer_y1 = self.whole_image_crop_box(image.size)
        image_width, image_height = image.size
        view_x0, view_y0 = min(0.0, outer_x0), min(0.0, outer_y0)
        view_x1, view_y1 = max(1.0, outer_x1), max(1.0, outer_y1)
        canvas_width = max(1, round((view_x1 - view_x0) * image_width))
        canvas_height = max(1, round((view_y1 - view_y0) * image_height))
        preview_canvas = Image.new("RGB", (canvas_width, canvas_height), "black")
        paste_x = round(-view_x0 * image_width)
        paste_y = round(-view_y0 * image_height)
        preview_canvas.paste(image, (paste_x, paste_y))
        shown = ImageOps.contain(preview_canvas, (max(1, width - 20), max(1, height - 20)), Image.Resampling.LANCZOS)
        x = (width - shown.width) / 2
        y = (height - shown.height) / 2
        self.preview_photo = ImageTk.PhotoImage(shown)
        self.preview.create_image(x, y, image=self.preview_photo, anchor="nw")
        scale_x = shown.width / canvas_width
        scale_y = shown.height / canvas_height
        image_x = x + paste_x * scale_x
        image_y = y + paste_y * scale_y
        shown_image_width = image_width * scale_x
        shown_image_height = image_height * scale_y
        self.preview_image_box = (image_x, image_y, shown_image_width, shown_image_height)
        left = image_x + x0 * shown_image_width
        top = image_y + y0 * shown_image_height
        right = image_x + x1 * shown_image_width
        bottom = image_y + y1 * shown_image_height
        self.preview.create_rectangle(left, top, right, bottom, outline="#facc15", width=3)
        handle = 5
        for hx, hy in ((left, top), (right, top), (left, bottom), (right, bottom)):
            self.preview.create_rectangle(hx - handle, hy - handle, hx + handle, hy + handle, fill="#ef4444", outline="#fef08a")
        self.preview.create_text(left + 7, top + 7, text="KADR 5:4", anchor="nw", fill="#facc15", font=("Segoe UI", 8, "bold"))

    def crop_canvas_box(self) -> tuple[float, float, float, float] | None:
        source = self.current_source()
        if source is None:
            return None
        x, y, width, height = self.preview_image_box
        x0, y0, x1, y1 = self.crop_boxes[source]
        return x + x0 * width, y + y0 * height, x + x1 * width, y + y1 * height

    def start_crop_drag(self, event) -> None:
        box = self.crop_canvas_box()
        if box is None:
            self.choose_file()
            return
        left, top, right, bottom = box
        self.drag_position = (event.x, event.y) if left <= event.x <= right and top <= event.y <= bottom else None

    def drag_crop(self, event) -> None:
        source = self.current_source()
        if source is None or self.drag_position is None:
            return
        _x, _y, shown_width, shown_height = self.preview_image_box
        previous_x, previous_y = self.drag_position
        dx = (event.x - previous_x) / shown_width
        dy = (event.y - previous_y) / shown_height
        x0, y0, x1, y1 = self.crop_boxes[source]
        crop_width, crop_height = x1 - x0, y1 - y0
        assert self.preview_source_image is not None
        outer_x0, outer_y0, outer_x1, outer_y1 = self.whole_image_crop_box(self.preview_source_image.size)
        new_x0 = min(max(outer_x0, x0 + dx), outer_x1 - crop_width)
        new_y0 = min(max(outer_y0, y0 + dy), outer_y1 - crop_height)
        self.crop_boxes[source] = new_x0, new_y0, new_x0 + crop_width, new_y0 + crop_height
        self.drag_position = (event.x, event.y)
        self.render_preview()

    def stop_crop_drag(self) -> None:
        self.drag_position = None

    def zoom_crop(self, factor: float) -> None:
        source = self.current_source()
        if source is None:
            return
        x0, y0, x1, y1 = self.crop_boxes[source]
        center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
        new_width = (x1 - x0) * factor
        new_height = (y1 - y0) * factor
        if new_width < 0.08 or new_height < 0.08:
            return
        assert self.preview_source_image is not None
        outer_x0, outer_y0, outer_x1, outer_y1 = self.whole_image_crop_box(self.preview_source_image.size)
        max_width, max_height = outer_x1 - outer_x0, outer_y1 - outer_y0
        scale = min(1.0, max_width / new_width, max_height / new_height)
        new_width *= scale
        new_height *= scale
        new_x0 = min(max(outer_x0, center_x - new_width / 2), outer_x1 - new_width)
        new_y0 = min(max(outer_y0, center_y - new_height / 2), outer_y1 - new_height)
        self.crop_boxes[source] = new_x0, new_y0, new_x0 + new_width, new_y0 + new_height
        self.render_preview()

    def crop_mousewheel(self, event) -> None:
        self.zoom_crop(0.9 if event.delta > 0 else 1.1)

    def reset_crop(self) -> None:
        source = self.current_source()
        if source is None or self.preview_source_image is None:
            return
        self.crop_boxes[source] = self.default_crop_box(self.preview_source_image.size)
        self.render_preview()

    def fit_whole_image(self) -> None:
        source = self.current_source()
        if source is None or self.preview_source_image is None:
            return
        self.crop_boxes[source] = self.whole_image_crop_box(self.preview_source_image.size)
        self.render_preview()

    def change_preview(self, step: int) -> None:
        if not self.sources:
            return
        self.current_source_index = (self.current_source_index + step) % len(self.sources)
        self.load_current_preview()

    def choose_file(self) -> None:
        filenames = filedialog.askopenfilenames(title="Wybierz obrazy lub GIF-y", filetypes=[("Obrazy", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.gif"), ("Wszystkie pliki", "*.*")])
        if filenames:
            self.load_sources([Path(filename) for filename in filenames])

    def on_drop(self, event) -> None:
        files = self.tk.splitlist(event.data)
        if files:
            self.load_sources([Path(filename) for filename in files])

    def load_sources(self, paths: list[Path]) -> None:
        valid: list[Path] = []
        errors: list[str] = []
        for path in paths:
            try:
                validate_source(path)
                valid.append(path)
            except Exception as error:
                errors.append(f"{path.name}: {error}")
        if not valid:
            messagebox.showerror(
                "Nie można otworzyć plików",
                "\n".join(errors),
                parent=self,
            )
            return
        try:
            self.sources = valid
            self.current_source_index = 0
            retained = self.crop_boxes
            self.crop_boxes = {}
            for path in valid:
                image = self.open_preview_image(path)
                self.crop_boxes[path] = retained.get(path, self.default_crop_box(image.size))
            self.load_current_preview()
            assert self.preview_source_image is not None
            oriented = self.preview_source_image
            orientation = "pionowy" if oriented.height > oriented.width else "poziomy"
            if oriented.height == oriented.width:
                orientation = "kwadratowy"
            if len(valid) == 1:
                label = valid[0].name
            else:
                examples = ", ".join(path.name for path in valid[:3])
                if len(valid) > 3:
                    examples += ", …"
                label = f"Wybrano {len(valid)} plików\n{examples}"
            self.file_label.configure(text=label)
            self.status.configure(
                text=f"Gotowe: {len(valid)} plików • pierwszy układ {orientation}",
                fg=MUTED,
            )
            if errors:
                messagebox.showwarning(
                    "Pominięto część plików",
                    "\n".join(errors),
                    parent=self,
                )
        except Exception as error:
            messagebox.showerror("Nie można otworzyć pliku", str(error), parent=self)

    def convert(self, mode: str) -> None:
        if not self.sources:
            messagebox.showinfo("Najpierw wybierz pliki", "Przeciągnij obrazy do okna albo kliknij strefę wyboru.", parent=self)
            return
        self._set_busy(True)
        sources = list(self.sources)
        style_name = self.style_var.get()
        palette_name = self.palette_var.get()
        compression_name = self.compression_var.get()
        tags = [value for value in re.split(r"[\s,;]+", self.tags_var.get()) if value]
        output_subfolder = metadata_token(self.folder_var.get()) or None
        crop_boxes = {source: self.crop_boxes[source] for source in sources}
        self.status.configure(text=f"Przetwarzanie plików: {len(sources)}…", fg=MUTED)

        def work() -> None:
            try:
                result = convert_many(
                    sources,
                    self.output_dir,
                    mode,
                    style_name,
                    palette_name,
                    compression_name,
                    tags,
                    output_subfolder,
                    crop_boxes,
                )
                self.after(0, lambda: self._conversion_done(result))
            except Exception as error:
                self.after(0, lambda message=str(error): self._conversion_failed(message))

        threading.Thread(target=work, daemon=True).start()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in self.action_buttons:
            button.configure(state=state)
        for button in self.transfer_buttons:
            button.configure(state=state)
        self.status.configure(text="Przetwarzanie…" if busy else "Gotowe.", fg=MUTED)

    def _conversion_done(self, batch: BatchConversionResult) -> None:
        self._set_busy(False)
        for result in batch.results:
            relative = result.output.relative_to(self.output_dir / OUTPUT_FOLDER_NAME)
            destination = self.send_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(result.output, destination)
        success_count = len(batch.results)
        failure_count = len(batch.failures)
        self.status.configure(
            text=f"Gotowe: {success_count} plików • {batch.output_kb:.1f} KB",
            fg=ACCENT if success_count else "#fb7185",
        )
        details = (
            f"Utworzono GIF-ów: {success_count}\n"
            f"Łączny rozmiar: {batch.output_kb:.1f} KB\n\n"
            f"Wyniki: {self.output_dir / OUTPUT_FOLDER_NAME}\n"
            f"Do wysłania: {self.send_dir}"
        )
        if failure_count:
            failures = "\n".join(
                f"• {failure.source.name}: {failure.error}"
                for failure in batch.failures[:8]
            )
            if failure_count > 8:
                failures += f"\n… i jeszcze {failure_count - 8}"
            details += f"\n\nBłędy ({failure_count}):\n{failures}"
        messagebox.showinfo("Konwersja wsadowa zakończona", details, parent=self)

    def _conversion_failed(self, error: str) -> None:
        self._set_busy(False)
        self.status.configure(text="Operacja nie powiodła się.", fg="#fb7185")
        messagebox.showerror("Błąd operacji", error, parent=self)

    def open_output_dir(self) -> None:
        results_dir = self.output_dir / OUTPUT_FOLDER_NAME
        results_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(results_dir)

    def send_to_frame(self) -> None:
        files = [
            path for path in self.send_dir.rglob("*.gif")
            if path.is_file() and path.suffix.lower() == ".gif"
        ]
        if not files:
            messagebox.showinfo(
                "Brak plików do wysłania",
                f"Umieść pliki GIF w folderze:\n{self.send_dir}",
                parent=self,
            )
            return
        self._set_busy(True)
        self.status.configure(text=f"Wysyłanie {len(files)} plików do ramki…", fg=MUTED)
        address = self.frame_address_var.get()

        def work() -> None:
            try:
                uploaded = FrameClient(address).upload_all(self.send_dir)
                self.after(0, lambda: self._transfer_done("wysłano", uploaded, self.send_dir))
            except Exception as error:
                self.after(0, lambda message=str(error): self._conversion_failed(message))

        threading.Thread(target=work, daemon=True).start()

    def download_from_frame(self) -> None:
        self._set_busy(True)
        self.status.configure(text="Pobieranie listy obrazów z ramki…", fg=MUTED)
        address = self.frame_address_var.get()

        def work() -> None:
            try:
                downloaded = FrameClient(address).download_all(self.frame_images_dir)
                self.after(
                    0,
                    lambda: self._transfer_done("pobrano", downloaded, self.frame_images_dir),
                )
            except Exception as error:
                self.after(0, lambda message=str(error): self._conversion_failed(message))

        threading.Thread(target=work, daemon=True).start()

    def _transfer_done(self, action: str, files: list[Path], folder: Path) -> None:
        self._set_busy(False)
        self.status.configure(text=f"{action.capitalize()} plików: {len(files)}", fg=ACCENT)
        messagebox.showinfo(
            "Transfer zakończony",
            f"{action.capitalize()} {len(files)} plików.\n\nFolder:\n{folder}",
            parent=self,
        )


if __name__ == "__main__":
    GifTool().mainloop()
