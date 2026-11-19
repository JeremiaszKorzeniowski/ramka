from __future__ import annotations

import json
import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


SEND_FOLDER_NAME = "wyslij do ramki"
FRAME_IMAGES_FOLDER_NAME = "obrazy w ramce"


@dataclass(frozen=True)
class FrameFile:
    name: str
    size: int


class FrameClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        normalized = base_url.strip()
        if not normalized.startswith(("http://", "https://")):
            normalized = "http://" + normalized
        self.base_url = normalized.rstrip("/") + "/"
        self.timeout = timeout

    def _open(self, request: Request):
        try:
            return urlopen(request, timeout=self.timeout)
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Ramka zwróciła HTTP {error.code}: {details or error.reason}") from error
        except (URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise RuntimeError(
                f"Nie można połączyć się z {self.base_url} ({reason}). "
                "Sprawdź Wi-Fi, adres ramki i wgrane firmware."
            ) from error

    def list_files(self) -> list[FrameFile]:
        request = Request(urljoin(self.base_url, "api/files"), headers={"Accept": "application/json"})
        with self._open(request) as response:
            try:
                payload = json.load(response)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise RuntimeError("Ramka nie udostępniła poprawnej listy plików. Wgraj nowe firmware.") from error
        files: list[FrameFile] = []
        for item in payload.get("files", []):
            name = Path(str(item.get("name", ""))).name
            if name.lower().endswith(".gif"):
                files.append(FrameFile(name=name, size=int(item.get("size", 0))))
        return files

    def upload_file(self, path: Path) -> None:
        boundary = "----GifTool" + uuid.uuid4().hex
        mime_type = mimetypes.guess_type(path.name)[0] or "image/gif"
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="gif"; filename="{path.name}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
        body = header + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("ascii")
        request = Request(
            urljoin(self.base_url, "upload"),
            data=body,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
        )
        with self._open(request) as response:
            response.read()

    def upload_all(self, folder: Path) -> list[Path]:
        files = sorted(
            (path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".gif"),
            key=lambda path: path.name.lower(),
        )
        for path in files:
            self.upload_file(path)
        return files

    def download_file(self, file: FrameFile, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / Path(file.name).name
        request = Request(urljoin(self.base_url, f"file?name={quote(file.name)}"))
        with self._open(request) as response:
            data = response.read()
        destination.write_bytes(data)
        return destination

    def download_all(self, folder: Path) -> list[Path]:
        return [self.download_file(file, folder) for file in self.list_files()]
