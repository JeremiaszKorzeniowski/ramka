from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main

from PIL import Image, ImageDraw

from converter import (
    LARGE_FOLDER_NAME,
    OUTPUT_FOLDER_NAME,
    TARGET_SIZE,
    convert_many,
    convert_style,
)


def make_photo(path: Path) -> None:
    image = Image.new("RGB", (320, 180), "#80bde8")
    draw = ImageDraw.Draw(image)
    draw.ellipse((85, 15, 235, 165), fill="#e0a078", outline="black", width=8)
    draw.line((110, 100, 210, 100), fill="black", width=5)
    image.save(path)


class ArtisticConversionTests(TestCase):
    def test_manga_creates_small_and_large_versions_in_subfolders(self) -> None:
        with TemporaryDirectory() as directory:
            workdir = Path(directory)
            source = workdir / "photo.png"
            make_photo(source)

            result = convert_style(source, workdir, "manga")

            self.assertEqual(result.output.parent, workdir / OUTPUT_FOLDER_NAME)
            self.assertIn("-manga-160x128", result.output.name)
            self.assertIsNotNone(result.large_output)
            assert result.large_output is not None
            self.assertEqual(
                result.large_output.parent,
                workdir / OUTPUT_FOLDER_NAME / LARGE_FOLDER_NAME,
            )
            self.assertIn("-manga-duza", result.large_output.name)
            with Image.open(result.output) as small:
                self.assertEqual(small.size, TARGET_SIZE)
                self.assertLessEqual(len(small.convert("RGB").getcolors(maxcolors=256) or []), 2)
            with Image.open(result.large_output) as large:
                self.assertEqual(large.size, (225, 180))

    def test_pixelart_and_anime_use_descriptive_names(self) -> None:
        with TemporaryDirectory() as directory:
            workdir = Path(directory)
            source = workdir / "photo.png"
            make_photo(source)

            pixel = convert_style(
                source,
                workdir,
                "pixelart",
                "Klasyczny (piksel 4x)",
                "PICO-8",
            )
            anime = convert_style(source, workdir, "anime")

            self.assertIn("pixelart-4x-pico-8-160x128", pixel.output.name)
            self.assertIn("anime-160x128", anime.output.name)
            self.assertIsNotNone(pixel.large_output)
            self.assertIsNotNone(anime.large_output)
            assert anime.large_output is not None
            with Image.open(anime.large_output) as large_anime:
                colors = large_anime.convert("RGB").getcolors(maxcolors=65536) or []
                self.assertGreater(len(colors), 2)

    def test_animation_keeps_frames_and_timing_in_both_versions(self) -> None:
        with TemporaryDirectory() as directory:
            workdir = Path(directory)
            source = workdir / "animation.gif"
            first = Image.new("RGB", TARGET_SIZE, "white")
            second = Image.new("RGB", TARGET_SIZE, "black")
            first.save(source, save_all=True, append_images=[second], duration=[80, 140], loop=0)

            result = convert_style(source, workdir, "manga")

            self.assertIsNotNone(result.large_output)
            for output in (result.output, result.large_output):
                assert output is not None
                with Image.open(output) as animation:
                    self.assertEqual(animation.n_frames, 2)
                    durations = []
                    for index in range(animation.n_frames):
                        animation.seek(index)
                        durations.append(animation.info["duration"])
                    self.assertEqual(durations, [80, 140])

    def test_standard_conversion_only_creates_display_gif(self) -> None:
        with TemporaryDirectory() as directory:
            workdir = Path(directory)
            source = workdir / "photo.png"
            make_photo(source)

            result = convert_style(source, workdir, "standard")

            self.assertIn("standard-160x128", result.output.name)
            self.assertIsNone(result.large_output)

    def test_extreme_compression_targets_25_kb(self) -> None:
        with TemporaryDirectory() as directory:
            workdir = Path(directory)
            source = workdir / "large-animation.gif"
            frames = []
            for frame_index in range(24):
                data = bytes(
                    (x * 37 + y * 17 + frame_index * 53) % 256
                    for y in range(TARGET_SIZE[1])
                    for x in range(TARGET_SIZE[0])
                )
                frames.append(Image.frombytes("L", TARGET_SIZE, data).convert("RGB"))
            frames[0].save(
                source,
                save_all=True,
                append_images=frames[1:],
                duration=40,
                loop=0,
                optimize=False,
            )

            result = convert_style(
                source,
                workdir,
                "standard",
                compression_name="Ekstremalna (do 25 KB)",
            )

            self.assertLessEqual(result.output.stat().st_size, 25 * 1024)

    def test_batch_conversion_continues_after_invalid_file(self) -> None:
        with TemporaryDirectory() as directory:
            workdir = Path(directory)
            first = workdir / "first.png"
            second = workdir / "second.png"
            invalid = workdir / "broken.png"
            make_photo(first)
            make_photo(second)
            invalid.write_bytes(b"not an image")

            batch = convert_many(
                [first, invalid, second],
                workdir,
                "standard",
                compression_name="Mocna (do 100 KB)",
            )

            self.assertEqual(len(batch.results), 2)
            self.assertEqual(len(batch.failures), 1)
            self.assertEqual(batch.failures[0].source, invalid)


if __name__ == "__main__":
    main()
