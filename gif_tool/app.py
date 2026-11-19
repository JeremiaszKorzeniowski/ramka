from __future__ import annotations

import os
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
    OUTPUT_FOLDER_NAME,
    PALETTES,
    PIXEL_STYLES,
    BatchConversionResult,
    convert_many,
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
        self.geometry("760x790")
        self.minsize(700, 730)
        self.configure(bg=BG)
        self.sources: list[Path] = []
        self.preview_photo: ImageTk.PhotoImage | None = None
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

        self.drop = tk.Frame(body, bg=DROP_BG, highlightbackground="#475569", highlightthickness=2, cursor="hand2")
        self.drop.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        self.preview = tk.Label(self.drop, text="↓", font=("Segoe UI", 42, "bold"), bg=DROP_BG, fg=BLUE)
        self.preview.pack(expand=True, pady=(24, 4))
        self.file_label = tk.Label(self.drop, text="Przeciągnij tutaj pliki", font=("Segoe UI", 13, "bold"), bg=DROP_BG, fg=TEXT, wraplength=380)
        self.file_label.pack(padx=20)
        tk.Label(self.drop, text="lub kliknij, aby wybrać", font=("Segoe UI", 9), bg=DROP_BG, fg=MUTED).pack(pady=(5, 24))
        for widget in (self.drop, self.preview, self.file_label):
            widget.bind("<Button-1>", lambda _event: self.choose_file())
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self.on_drop)

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
        tk.Label(options, text="Obraz zostanie centralnie przycięty do proporcji 5:4.", font=("Segoe UI", 9), bg=PANEL, fg=MUTED, wraplength=210, justify="left").pack(anchor="w", pady=(22, 0))

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
        first = valid[0]
        try:
            with Image.open(first) as image:
                image.seek(0)
                oriented = ImageOps.exif_transpose(image).convert("RGB")
                orientation = "pionowy" if oriented.height > oriented.width else "poziomy"
                if oriented.height == oriented.width:
                    orientation = "kwadratowy"
                preview = ImageOps.contain(oriented, (360, 250), Image.Resampling.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(preview)
            self.preview.configure(image=self.preview_photo, text="")
            self.sources = valid
            if len(valid) == 1:
                label = first.name
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
            shutil.copy2(result.output, self.send_dir / result.output.name)
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
            path for path in self.send_dir.iterdir()
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
