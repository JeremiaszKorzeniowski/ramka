from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk
from tkinterdnd2 import DND_FILES, TkinterDnD

from converter import PALETTES, PIXEL_STYLES, convert_pixel_art, convert_standard, validate_source


BG = "#111827"
PANEL = "#1f2937"
DROP_BG = "#263449"
TEXT = "#f8fafc"
MUTED = "#aab6c8"
ACCENT = "#22c55e"
ACCENT_HOVER = "#16a34a"
BLUE = "#3b82f6"


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


class GifTool(TkinterDnD.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("GIF 160×128 • Pixel Tool")
        self.geometry("760x590")
        self.minsize(700, 540)
        self.configure(bg=BG)
        self.source: Path | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.output_dir = application_dir()
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

        self.drop = tk.Frame(body, bg=DROP_BG, highlightbackground="#475569", highlightthickness=2, cursor="hand2")
        self.drop.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        self.preview = tk.Label(self.drop, text="↓", font=("Segoe UI", 42, "bold"), bg=DROP_BG, fg=BLUE)
        self.preview.pack(expand=True, pady=(24, 4))
        self.file_label = tk.Label(self.drop, text="Przeciągnij tutaj plik", font=("Segoe UI", 13, "bold"), bg=DROP_BG, fg=TEXT, wraplength=380)
        self.file_label.pack(padx=20)
        tk.Label(self.drop, text="lub kliknij, aby wybrać", font=("Segoe UI", 9), bg=DROP_BG, fg=MUTED).pack(pady=(5, 24))
        for widget in (self.drop, self.preview, self.file_label):
            widget.bind("<Button-1>", lambda _event: self.choose_file())
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self.on_drop)

        options = tk.Frame(body, bg=PANEL, padx=20, pady=20)
        options.grid(row=0, column=1, sticky="nsew")
        tk.Label(options, text="PIXEL ART", font=("Segoe UI", 10, "bold"), bg=PANEL, fg=MUTED).pack(anchor="w")
        tk.Label(options, text="Styl", font=("Segoe UI", 9), bg=PANEL, fg=TEXT).pack(anchor="w", pady=(18, 5))
        self.style_var = tk.StringVar(value=list(PIXEL_STYLES)[1])
        ttk.Combobox(options, textvariable=self.style_var, values=list(PIXEL_STYLES), state="readonly").pack(fill="x")
        tk.Label(options, text="Paleta", font=("Segoe UI", 9), bg=PANEL, fg=TEXT).pack(anchor="w", pady=(18, 5))
        self.palette_var = tk.StringVar(value=list(PALETTES)[0])
        ttk.Combobox(options, textvariable=self.palette_var, values=list(PALETTES), state="readonly").pack(fill="x")
        tk.Label(options, text="Obraz zostanie centralnie przycięty do proporcji 5:4.", font=("Segoe UI", 9), bg=PANEL, fg=MUTED, wraplength=210, justify="left").pack(anchor="w", pady=(22, 0))

        actions = tk.Frame(self, bg=BG)
        actions.pack(fill="x", padx=32, pady=(18, 0))
        self.resize_button = self._button(actions, "SKALUJ DO GIF", BLUE, lambda: self.convert(False))
        self.resize_button.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.pixel_button = self._button(actions, "ZRÓB PIXEL ART", ACCENT, lambda: self.convert(True))
        self.pixel_button.pack(side="left", fill="x", expand=True, padx=(8, 0))

        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", padx=32, pady=(12, 22))
        self.status = tk.Label(footer, text="Wyniki zapisują się w folderze z programem.", font=("Segoe UI", 9), bg=BG, fg=MUTED, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        tk.Button(footer, text="Otwórz folder", command=self.open_output_dir, bg=BG, fg=BLUE, activebackground=BG, activeforeground="#60a5fa", relief="flat", cursor="hand2", font=("Segoe UI", 9, "underline")).pack(side="right")

    def _button(self, parent: tk.Widget, text: str, color: str, command) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=color, fg="white", activebackground=color, activeforeground="white", relief="flat", bd=0, padx=18, pady=13, cursor="hand2", font=("Segoe UI", 10, "bold"))

    def choose_file(self) -> None:
        filename = filedialog.askopenfilename(title="Wybierz obraz lub GIF", filetypes=[("Obrazy", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.gif"), ("Wszystkie pliki", "*.*")])
        if filename:
            self.load_source(Path(filename))

    def on_drop(self, event) -> None:
        files = self.tk.splitlist(event.data)
        if files:
            self.load_source(Path(files[0]))

    def load_source(self, path: Path) -> None:
        try:
            validate_source(path)
            with Image.open(path) as image:
                image.seek(0)
                oriented = ImageOps.exif_transpose(image).convert("RGB")
                orientation = "pionowy" if oriented.height > oriented.width else "poziomy"
                if oriented.height == oriented.width:
                    orientation = "kwadratowy"
                preview = ImageOps.contain(oriented, (360, 250), Image.Resampling.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(preview)
            self.preview.configure(image=self.preview_photo, text="")
            self.file_label.configure(text=path.name)
            self.source = path
            self.status.configure(text=f"Gotowe: {path.name} • układ {orientation}", fg=MUTED)
        except Exception as error:
            messagebox.showerror("Nie można otworzyć pliku", str(error), parent=self)

    def convert(self, pixel_art: bool) -> None:
        if self.source is None:
            messagebox.showinfo("Najpierw wybierz plik", "Przeciągnij obraz do okna albo kliknij strefę wyboru.", parent=self)
            return
        self._set_busy(True)
        source = self.source
        style_name = self.style_var.get()
        palette_name = self.palette_var.get()

        def work() -> None:
            try:
                if pixel_art:
                    result = convert_pixel_art(source, self.output_dir, style_name, palette_name)
                else:
                    result = convert_standard(source, self.output_dir)
                self.after(0, lambda: self._conversion_done(result))
            except Exception as error:
                self.after(0, lambda: self._conversion_failed(str(error)))

        threading.Thread(target=work, daemon=True).start()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.resize_button.configure(state=state)
        self.pixel_button.configure(state=state)
        self.status.configure(text="Przetwarzanie…" if busy else "Gotowe.", fg=MUTED)

    def _conversion_done(self, result: Path) -> None:
        self._set_busy(False)
        self.status.configure(text=f"Zapisano: {result.name}", fg=ACCENT)
        messagebox.showinfo("GIF gotowy", f"Zapisano plik:\n{result}", parent=self)

    def _conversion_failed(self, error: str) -> None:
        self._set_busy(False)
        self.status.configure(text="Konwersja nie powiodła się.", fg="#fb7185")
        messagebox.showerror("Błąd konwersji", error, parent=self)

    def open_output_dir(self) -> None:
        os.startfile(self.output_dir)


if __name__ == "__main__":
    GifTool().mainloop()
