from __future__ import annotations

import unicodedata
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps


TARGET_SIZE = (160, 128)
OUTPUT_FOLDER_NAME = "wyniki"
LARGE_FOLDER_NAME = "duze_wersje"


@dataclass(frozen=True)
class PixelStyle:
    label: str
    pixel_size: int
    colors: int


@dataclass(frozen=True)
class CompressionPreset:
    target_kb: int
    starting_colors: int


@dataclass(frozen=True)
class ConversionOptions:
    pixel_style_name: str
    palette_name: str
    compression_name: str


@dataclass(frozen=True)
class ConversionResult:
    output: Path
    large_output: Path | None = None

    @property
    def output_kb(self) -> float:
        return self.output.stat().st_size / 1024


@dataclass(frozen=True)
class ConversionFailure:
    source: Path
    error: str


@dataclass(frozen=True)
class BatchConversionResult:
    results: tuple[ConversionResult, ...]
    failures: tuple[ConversionFailure, ...]

    @property
    def output_kb(self) -> float:
        return sum(result.output_kb for result in self.results)


FrameTransformer = Callable[[Image.Image, tuple[int, int], ConversionOptions], Image.Image]
FrameFinalizer = Callable[[Image.Image], Image.Image]


@dataclass(frozen=True)
class ConversionStyle:
    key: str
    button_label: str
    filename_tag: str
    color: str
    transformer: FrameTransformer
    finalizer: FrameFinalizer
    saves_large_version: bool = True


PIXEL_STYLES: dict[str, PixelStyle] = {
    "Delikatny (piksel 2x)": PixelStyle("Delikatny (piksel 2x)", 2, 64),
    "Klasyczny (piksel 4x)": PixelStyle("Klasyczny (piksel 4x)", 4, 32),
    "Gruby (piksel 8x)": PixelStyle("Gruby (piksel 8x)", 8, 16),
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


COMPRESSION_PRESETS: dict[str, CompressionPreset] = {
    "Normalna (do 250 KB)": CompressionPreset(target_kb=250, starting_colors=128),
    "Mocna (do 100 KB)": CompressionPreset(target_kb=100, starting_colors=64),
    "Ekstremalna (do 25 KB)": CompressionPreset(target_kb=25, starting_colors=32),
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
    rgba = ImageOps.exif_transpose(frame).convert("RGBA")
    background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


CropBox = tuple[float, float, float, float]


def _fit(
    frame: Image.Image,
    size: tuple[int, int],
    method: int,
    crop_box: CropBox | None = None,
) -> Image.Image:
    if crop_box is not None:
        x0, y0, x1, y1 = crop_box
        width, height = frame.size
        left = round(x0 * width)
        top = round(y0 * height)
        right = max(left + 1, round(x1 * width))
        bottom = max(top + 1, round(y1 * height))
        crop_width, crop_height = right - left, bottom - top
        # Kadr może wyjść poza zdjęcie. Dzięki temu da się pokazać
        # cały pionowy obraz, a wolne miejsce po bokach staje się czarnym tłem.
        cropped = Image.new("RGB", (crop_width, crop_height), "black")
        cropped.paste(frame.convert("RGB"), (-left, -top))
        frame = cropped
    return ImageOps.fit(frame, size, method=method, centering=(0.5, 0.5))


def _read_frames(source: Path) -> tuple[list[Image.Image], list[int], int]:
    frames: list[Image.Image] = []
    durations: list[int] = []
    with Image.open(source) as image:
        # GIF-y przeznaczone do ramki mają odtwarzać się bez końca,
        # niezależnie od ustawienia pętli w pliku źródłowym.
        loop = 0
        default_duration = max(20, int(image.info.get("duration", 100)))
        for index in range(getattr(image, "n_frames", 1)):
            image.seek(index)
            frames.append(_flatten_alpha(image.copy()))
            durations.append(max(20, int(image.info.get("duration", default_duration))))
    return frames, durations, loop


def _quantize(frame: Image.Image, palette_name: str, colors: int) -> Image.Image:
    palette = PALETTES[palette_name]
    if palette is None:
        return frame.convert("RGB").quantize(
            colors=colors,
            method=Image.Quantize.MEDIANCUT,
            dither=Image.Dither.FLOYDSTEINBERG,
        )
    return frame.convert("RGB").quantize(
        palette=_palette_image(palette),
        dither=Image.Dither.FLOYDSTEINBERG,
    )


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return "-".join(part for part in normalized.lower().replace("_", "-").split() if part)


def metadata_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9-]+", "-", normalized.lower()).strip("-")


def normalize_tags(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        token = metadata_token(value)
        if token and token not in result:
            result.append(token)
    return tuple(result)


def _safe_output_path(output_dir: Path, stem: str, tag: str, extension: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate = output_dir / f"{stem}-{tag}{extension}"
    counter = 2
    while candidate.exists():
        candidate = output_dir / f"{stem}-{tag}-{counter}{extension}"
        counter += 1
    return candidate


def _safe_tagged_output_path(
    output_dir: Path,
    stem: str,
    descriptor: str,
    extension: str,
    tags: Iterable[str],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = metadata_token(stem) or "obraz"
    safe_tags = normalize_tags(tags)
    tag_suffix = f"__{'_'.join(safe_tags)}" if safe_tags else ""
    counter = 1
    while True:
        duplicate = "" if counter == 1 else f"-{counter}"
        candidate = output_dir / f"{safe_stem}-{descriptor}{duplicate}{tag_suffix}{extension}"
        if not candidate.exists():
            return candidate
        counter += 1


def _save_gif(
    frames: list[Image.Image],
    durations: list[int],
    loop: int,
    output: Path,
    optimize: bool = True,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=loop,
        disposal=2,
        optimize=optimize,
    )


def _collapse_identical_frames(
    frames: list[Image.Image], durations: list[int]
) -> tuple[list[Image.Image], list[int]]:
    collapsed_frames: list[Image.Image] = []
    collapsed_durations: list[int] = []
    previous: bytes | None = None
    for frame, duration in zip(frames, durations):
        fingerprint = frame.convert("RGB").tobytes()
        if fingerprint == previous:
            collapsed_durations[-1] += duration
            continue
        collapsed_frames.append(frame)
        collapsed_durations.append(duration)
        previous = fingerprint
    return collapsed_frames, collapsed_durations


def _sample_frames(
    frames: list[Image.Image], durations: list[int], stride: int
) -> tuple[list[Image.Image], list[int]]:
    if stride <= 1 or len(frames) <= 1:
        return frames, durations
    sampled_frames: list[Image.Image] = []
    sampled_durations: list[int] = []
    for index in range(0, len(frames), stride):
        sampled_frames.append(frames[index])
        sampled_durations.append(sum(durations[index:index + stride]))
    return sampled_frames, sampled_durations


def _shared_palette(frames: list[Image.Image], colors: int) -> Image.Image:
    sample_count = min(16, len(frames))
    indexes = [round(index * (len(frames) - 1) / max(1, sample_count - 1)) for index in range(sample_count)]
    samples = [frames[index].convert("RGB").resize((80, 64), Image.Resampling.LANCZOS) for index in indexes]
    sheet = Image.new("RGB", (80 * len(samples), 64))
    for index, sample in enumerate(samples):
        sheet.paste(sample, (index * 80, 0))
    return sheet.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def _palette_frames(frames: list[Image.Image], colors: int) -> list[Image.Image]:
    palette = _shared_palette(frames, colors)
    return [
        frame.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE)
        for frame in frames
    ]


def _native_color_count(frames: list[Image.Image]) -> int:
    maximum = 2
    for frame in frames:
        colors = frame.convert("RGB").getcolors(maxcolors=257)
        maximum = max(maximum, 256 if colors is None else len(colors))
    return maximum


def _save_compressed_gif(
    frames: list[Image.Image],
    durations: list[int],
    loop: int,
    output: Path,
    preset: CompressionPreset,
) -> None:
    frames, durations = _collapse_identical_frames(frames, durations)
    base_colors = min(_native_color_count(frames), preset.starting_colors)
    strategies = (
        (1, base_colors),
        (1, max(2, base_colors // 2)),
        (2, max(2, base_colors // 2)),
        (2, max(2, base_colors // 4)),
        (3, max(2, base_colors // 4)),
        (4, max(2, base_colors // 8)),
        (6, 8),
        (8, 4),
        (12, 4),
        (16, 2),
    )
    target_bytes = preset.target_kb * 1024
    seen: set[tuple[int, int]] = set()
    for stride, colors in strategies:
        colors = min(colors, base_colors)
        strategy = (min(stride, len(frames)), colors)
        if strategy in seen:
            continue
        seen.add(strategy)
        candidate_frames, candidate_durations = _sample_frames(frames, durations, stride)
        paletted = _palette_frames(candidate_frames, colors)
        _save_gif(paletted, candidate_durations, loop, output, optimize=True)
        if output.stat().st_size <= target_bytes:
            return
    stride = 32
    while output.stat().st_size > target_bytes:
        candidate_frames, candidate_durations = _sample_frames(frames, durations, stride)
        paletted = _palette_frames(candidate_frames, 2)
        _save_gif(paletted, candidate_durations, loop, output, optimize=True)
        if len(candidate_frames) == 1:
            break
        stride *= 2


def _save_large(
    frames: list[Image.Image], durations: list[int], loop: int, output: Path
) -> None:
    if len(frames) == 1:
        frames[0].save(output, format="PNG", optimize=True)
    else:
        prepared = [frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=256) for frame in frames]
        _save_gif(prepared, durations, loop, output)


def _large_canvas_size(frame: Image.Image) -> tuple[int, int]:
    target_ratio = TARGET_SIZE[0] / TARGET_SIZE[1]
    width, height = frame.size
    if width / height > target_ratio:
        cropped = (round(height * target_ratio), height)
    else:
        cropped = (width, round(width / target_ratio))
    return cropped


def _standard_transform(
    frame: Image.Image, _size: tuple[int, int], _options: ConversionOptions
) -> Image.Image:
    return frame.convert("RGB")


def _standard_finalizer(frame: Image.Image) -> Image.Image:
    return frame.convert("RGB").quantize(
        colors=256,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.FLOYDSTEINBERG,
    )


def _pixelart_transform(
    frame: Image.Image, size: tuple[int, int], options: ConversionOptions
) -> Image.Image:
    pixel_style = PIXEL_STYLES[options.pixel_style_name]
    working_size = (
        max(1, TARGET_SIZE[0] // pixel_style.pixel_size),
        max(1, TARGET_SIZE[1] // pixel_style.pixel_size),
    )
    small = _fit(frame, working_size, Image.Resampling.LANCZOS)
    indexed = _quantize(small, options.palette_name, pixel_style.colors)
    return indexed.resize(size, Image.Resampling.NEAREST)


def _pixelart_finalizer(frame: Image.Image) -> Image.Image:
    return frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)


_BAYER = (
    (0, 48, 12, 60, 3, 51, 15, 63),
    (32, 16, 44, 28, 35, 19, 47, 31),
    (8, 56, 4, 52, 11, 59, 7, 55),
    (40, 24, 36, 20, 43, 27, 39, 23),
    (2, 50, 14, 62, 1, 49, 13, 61),
    (34, 18, 46, 30, 33, 17, 45, 29),
    (10, 58, 6, 54, 9, 57, 5, 53),
    (42, 26, 38, 22, 41, 25, 37, 21),
)


def _ordered_halftone(frame: Image.Image, pattern_scale: int) -> Image.Image:
    width, height = frame.size
    matrix_size = 8 * pattern_scale
    rows: list[bytes] = []
    for matrix_y in range(8):
        expanded = bytes(
            round((_BAYER[matrix_y][matrix_x] + 0.5) * 4)
            for matrix_x in range(8)
            for _ in range(pattern_scale)
        )
        row = (expanded * ((width // matrix_size) + 1))[:width]
        rows.extend([row] * pattern_scale)
    threshold_data = b"".join(rows[y % matrix_size] for y in range(height))
    threshold = Image.frombytes("L", frame.size, threshold_data)
    result = ImageChops.subtract(frame, threshold).point(lambda value: 255 if value else 0)
    result.paste(0, mask=frame.point(lambda value: 255 if value <= 42 else 0))
    result.paste(255, mask=frame.point(lambda value: 255 if value >= 224 else 0))
    return result


def _manga_transform(
    frame: Image.Image, size: tuple[int, int], _options: ConversionOptions
) -> Image.Image:
    gray = ImageOps.grayscale(frame)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(1.35)
    visual_scale = max(1, min(4, round(size[0] / TARGET_SIZE[0])))
    tones = _ordered_halftone(gray, visual_scale)
    edges = gray.filter(ImageFilter.GaussianBlur(0.8 * visual_scale)).filter(ImageFilter.FIND_EDGES)
    edges = ImageOps.autocontrast(edges)
    ink = edges.point(lambda value: 0 if value >= 52 else 255)
    if visual_scale > 1:
        ink = ImageOps.invert(
            ImageOps.invert(ink).filter(ImageFilter.MaxFilter(visual_scale * 2 + 1))
        )
    return ImageChops.darker(tones, ink)


def _manga_finalizer(frame: Image.Image) -> Image.Image:
    return frame.convert("L").point(lambda value: 255 if value >= 128 else 0).convert(
        "P", palette=Image.Palette.ADAPTIVE, colors=2
    )


def _anime_transform(
    frame: Image.Image, size: tuple[int, int], _options: ConversionOptions
) -> Image.Image:
    source = frame.convert("RGB")
    visual_scale = max(1, min(4, round(size[0] / TARGET_SIZE[0])))

    # Miękkie, malarskie plamy koloru zamiast twardej posteryzacji.
    # Median zachowuje granice obiektów, a lekki blur usuwa fotograficzny szum.
    smooth = source.filter(ImageFilter.MedianFilter(3))
    painted = smooth.filter(ImageFilter.GaussianBlur(0.38 * visual_scale))
    color = Image.blend(smooth, painted, 0.42)

    # Pastelowa krzywa z podniesionymi cieniami i ciepłymi światłami.
    red, green, blue = color.split()
    red = red.point(lambda value: min(255, round(9 + 246 * (value / 255) ** 0.91)))
    green = green.point(lambda value: min(255, round(7 + 248 * (value / 255) ** 0.96)))
    blue = blue.point(lambda value: min(255, round(5 + 245 * (value / 255) ** 1.02)))
    color = Image.merge("RGB", (red, green, blue))
    color = ImageEnhance.Color(color).enhance(1.16)
    color = ImageEnhance.Contrast(color).enhance(0.94)
    color = ImageEnhance.Brightness(color).enhance(1.025)
    color = Image.blend(color, Image.new("RGB", color.size, (255, 226, 184)), 0.035)

    # Więcej odcieni i mniej plastikowych, płaskich powierzchni niż wcześniej.
    color = color.quantize(
        colors=96,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    ).convert("RGB")

    # Selektywne, brązowo-grafitowe linie tylko na mocnych krawędziach.
    # Maska jest półprzezroczysta, więc nie tworzy czarnej obwódki wokół wszystkiego.
    gray = ImageOps.grayscale(source).filter(ImageFilter.GaussianBlur(0.9 * visual_scale))
    edges = ImageOps.autocontrast(gray.filter(ImageFilter.FIND_EDGES))
    ink_mask = edges.point(
        lambda value: 0 if value < 82 else min(132, round((value - 82) * 1.35))
    )
    if visual_scale > 1:
        ink_mask = ink_mask.filter(ImageFilter.MaxFilter(visual_scale * 2 - 1))
    ink_mask = ink_mask.filter(ImageFilter.GaussianBlur(0.35 * visual_scale))
    color.paste((48, 40, 43), mask=ink_mask)
    return color


def _anime_finalizer(frame: Image.Image) -> Image.Image:
    return frame.convert("RGB").quantize(
        colors=128,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )


# Dodanie kolejnego efektu wymaga transformera, finalizera i jednego wpisu tutaj.
# Interfejs automatycznie zbuduje dla niego przycisk.
CONVERSION_STYLES: dict[str, ConversionStyle] = {
    "standard": ConversionStyle(
        key="standard",
        button_label="SKALUJ DO GIF",
        filename_tag="standard",
        color="#3b82f6",
        transformer=_standard_transform,
        finalizer=_standard_finalizer,
        saves_large_version=False,
    ),
    "pixelart": ConversionStyle(
        key="pixelart",
        button_label="ZRÓB PIXEL ART",
        filename_tag="pixelart",
        color="#22c55e",
        transformer=_pixelart_transform,
        finalizer=_pixelart_finalizer,
    ),
    "manga": ConversionStyle(
        key="manga",
        button_label="MANGA CZARNO-BIAŁA",
        filename_tag="manga",
        color="#a855f7",
        transformer=_manga_transform,
        finalizer=_manga_finalizer,
    ),
    "anime": ConversionStyle(
        key="anime",
        button_label="ANIME MALARSKIE",
        filename_tag="anime",
        color="#f97316",
        transformer=_anime_transform,
        finalizer=_anime_finalizer,
    ),
}


def _style_tag(style: ConversionStyle, options: ConversionOptions) -> str:
    if style.key != "pixelart":
        return style.filename_tag
    pixel_style = PIXEL_STYLES[options.pixel_style_name]
    return f"{style.filename_tag}-{pixel_style.pixel_size}x-{_slug(options.palette_name)}"


def convert_style(
    source: Path,
    application_dir: Path,
    style_key: str,
    pixel_style_name: str | None = None,
    palette_name: str | None = None,
    compression_name: str | None = None,
    tags: Iterable[str] = (),
    output_subfolder: str | None = None,
    crop_box: CropBox | None = None,
) -> ConversionResult:
    style = CONVERSION_STYLES[style_key]
    options = ConversionOptions(
        pixel_style_name=pixel_style_name or list(PIXEL_STYLES)[1],
        palette_name=palette_name or list(PALETTES)[0],
        compression_name=compression_name or list(COMPRESSION_PRESETS)[1],
    )
    frames, durations, loop = _read_frames(source)
    tag = _style_tag(style, options)
    results_dir = application_dir / OUTPUT_FOLDER_NAME
    safe_folder = metadata_token(output_subfolder or "")
    if safe_folder:
        results_dir /= safe_folder
    output = _safe_tagged_output_path(results_dir, source.stem, f"{tag}-160x128", ".gif", tags)
    final_frames = [
        style.finalizer(
            style.transformer(
                _fit(frame, TARGET_SIZE, Image.Resampling.LANCZOS, crop_box),
                TARGET_SIZE,
                options,
            )
        )
        for frame in frames
    ]
    _save_compressed_gif(
        final_frames,
        durations,
        loop,
        output,
        COMPRESSION_PRESETS[options.compression_name],
    )

    large_output: Path | None = None
    if style.saves_large_version:
        large_size = _large_canvas_size(frames[0])
        large_frames = [
            style.transformer(
                _fit(frame, large_size, Image.Resampling.LANCZOS, crop_box),
                large_size,
                options,
            )
            for frame in frames
        ]
        large_dir = results_dir / LARGE_FOLDER_NAME
        extension = ".gif" if len(large_frames) > 1 else ".png"
        large_output = _safe_output_path(large_dir, source.stem, f"{tag}-duza", extension)
        _save_large(large_frames, durations, loop, large_output)
    return ConversionResult(output=output, large_output=large_output)


def convert_many(
    sources: Iterable[Path],
    application_dir: Path,
    style_key: str,
    pixel_style_name: str | None = None,
    palette_name: str | None = None,
    compression_name: str | None = None,
    tags: Iterable[str] = (),
    output_subfolder: str | None = None,
    crop_boxes: Mapping[Path, CropBox] | None = None,
) -> BatchConversionResult:
    results: list[ConversionResult] = []
    failures: list[ConversionFailure] = []
    for source in sources:
        try:
            results.append(
                convert_style(
                    source,
                    application_dir,
                    style_key,
                    pixel_style_name,
                    palette_name,
                    compression_name,
                    tags,
                    output_subfolder,
                    None if crop_boxes is None else crop_boxes.get(source),
                )
            )
        except Exception as error:
            failures.append(ConversionFailure(source=source, error=str(error)))
    return BatchConversionResult(tuple(results), tuple(failures))


# Zachowane funkcje upraszczają użycie konwertera poza interfejsem.
def convert_standard(source: Path, application_dir: Path) -> Path:
    return convert_style(source, application_dir, "standard").output


def convert_pixel_art(
    source: Path, application_dir: Path, style_name: str, palette_name: str
) -> Path:
    return convert_style(source, application_dir, "pixelart", style_name, palette_name).output


def convert_manga(source: Path, application_dir: Path) -> Path:
    return convert_style(source, application_dir, "manga").output


def convert_anime(source: Path, application_dir: Path) -> Path:
    return convert_style(source, application_dir, "anime").output


def validate_source(path: Path) -> None:
    if not path.is_file():
        raise ValueError("Upuszczony element nie jest plikiem.")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("Nieobsługiwany format. Użyj PNG, JPG, WEBP, BMP, TIFF lub GIF.")
