from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps


TARGET_SIZE = (160, 128)


@dataclass(frozen=True)
class PixelStyle:
    label: str
    working_size: tuple[int, int]
    colors: int


PIXEL_STYLES: dict[str, PixelStyle] = {
    "Delikatny (piksel 2x)": PixelStyle("Delikatny (piksel 2x)", (80, 64), 64),
    "Klasyczny (piksel 4x)": PixelStyle("Klasyczny (piksel 4x)", (40, 32), 32),
    "Gruby (piksel 8x)": PixelStyle("Gruby (piksel 8x)", (20, 16), 16),
}


PALETTES: dict[str, list[str] | None] = {
    "Automatyczna": None,
    "PICO-8": [
        "#000000", "#1d2b53", "#7e2553", "#008751", "#ab5236", "#5f574f",
        "#c2c3c7", "#fff1e8", "#ff004d", "#ffa300", "#ffec27", "#00e436",
        "#29adff", "#83769c", "#ff77a8", "#ffccaa",
    ],
    "Game Boy": ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"],
    "CGA": [
        "#000000", "#0000aa", "#00aa00", "#00aaaa", "#aa0000", "#aa00aa",
        "#aa5500", "#aaaaaa", "#555555", "#5555ff", "#55ff55", "#55ffff",
        "#ff5555", "#ff55ff", "#ffff55", "#ffffff",
    ],
    "Szarość": ["#000000", "#242424", "#494949", "#6d6d6d", "#929292", "#b6b6b6", "#dbdbdb", "#ffffff"],
}


SUPPORTED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif",
}


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _palette_image(colors: Iterable[str]) -> Image.Image:
    flat: list[int] = []
    for color in colors:
        flat.extend(_hex_to_rgb(color))
    flat.extend([0] * (768 - len(flat)))
    palette = Image.new("P", (1, 1))
    palette.putpalette(flat[:768])
    return palette


def _flatten_alpha(frame: Image.Image) -> Image.Image:
    # Telefony często zapisują piksele bez obracania obrazu, a prawidłowy
    # kierunek umieszczają tylko w polu EXIF Orientation. Normalizujemy go przed
    # kadrowaniem, aby zdjęcie nie wyszło bokiem w gotowym GIF-ie.
    rgba = ImageOps.exif_transpose(frame).convert("RGBA")
    background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


def _fit(frame: Image.Image, size: tuple[int, int], method: int) -> Image.Image:
    return ImageOps.fit(frame, size, method=method, centering=(0.5, 0.5))


def _read_frames(source: Path) -> tuple[list[Image.Image], list[int], int]:
    frames: list[Image.Image] = []
    durations: list[int] = []
    with Image.open(source) as image:
        loop = int(image.info.get("loop", 0))
        default_duration = max(20, int(image.info.get("duration", 100)))
        for index in range(getattr(image, "n_frames", 1)):
            image.seek(index)
            frames.append(_flatten_alpha(image.copy()))
            durations.append(max(20, int(image.info.get("duration", default_duration))))
    return frames, durations, loop


def _quantize(frame: Image.Image, palette_name: str, colors: int) -> Image.Image:
    palette = PALETTES[palette_name]
    if palette is None:
        return frame.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
    return frame.quantize(palette=_palette_image(palette), dither=Image.Dither.FLOYDSTEINBERG)


def _safe_output_path(output_dir: Path, stem: str, suffix: str) -> Path:
    candidate = output_dir / f"{stem}{suffix}.gif"
    counter = 2
    while candidate.exists():
        candidate = output_dir / f"{stem}{suffix}-{counter}.gif"
        counter += 1
    return candidate


def _save_gif(frames: list[Image.Image], durations: list[int], loop: int, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=loop,
        disposal=2,
        optimize=False,
    )


def convert_standard(source: Path, output_dir: Path) -> Path:
    frames, durations, loop = _read_frames(source)
    converted = [
        _fit(frame, TARGET_SIZE, Image.Resampling.LANCZOS).quantize(
            colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG
        )
        for frame in frames
    ]
    output = _safe_output_path(output_dir, source.stem, "-160x128")
    _save_gif(converted, durations, loop, output)
    return output


def convert_pixel_art(source: Path, output_dir: Path, style_name: str, palette_name: str) -> Path:
    style = PIXEL_STYLES[style_name]
    frames, durations, loop = _read_frames(source)
    converted: list[Image.Image] = []
    for frame in frames:
        small = _fit(frame, style.working_size, Image.Resampling.LANCZOS)
        indexed = _quantize(small, palette_name, style.colors)
        converted.append(indexed.resize(TARGET_SIZE, Image.Resampling.NEAREST))
    style_slug = style.working_size[0]
    palette_slug = palette_name.lower().replace(" ", "-").replace("ś", "s").replace("ć", "c")
    output = _safe_output_path(output_dir, source.stem, f"-pixel-{style_slug}-{palette_slug}")
    _save_gif(converted, durations, loop, output)
    return output


def validate_source(path: Path) -> None:
    if not path.is_file():
        raise ValueError("Upuszczony element nie jest plikiem.")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("Nieobsługiwany format. Użyj PNG, JPG, WEBP, BMP, TIFF lub GIF.")
