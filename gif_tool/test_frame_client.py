import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from urllib.parse import parse_qs, urlparse

from frame_client import FrameClient


class FrameHandler(BaseHTTPRequestHandler):
    files = {"existing.gif": b"old"}

    def log_message(self, _format: str, *_args) -> None:
        pass

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        body = self.rfile.read(int(self.headers["Content-Length"]))
        match = re.search(br'filename="([^"]+)"', body)
        assert match is not None
        name = match.group(1).decode("utf-8")
        folder = parse_qs(parsed.query).get("folder", [""])[0]
        if folder:
            name = f"{folder}/{name}"
        content = body.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
        self.files[name] = content
        self.send_response(200)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/files":
            payload = {
                "files": [
                    {"name": name, "size": len(content)}
                    for name, content in sorted(self.files.items())
                ]
            }
            data = json.dumps(payload).encode("utf-8")
        elif parsed.path == "/file":
            name = parse_qs(parsed.query)["name"][0]
            data = self.files[name]
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FrameClientTests(TestCase):
    def setUp(self) -> None:
        FrameHandler.files = {"existing.gif": b"old"}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FrameHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.client = FrameClient(f"http://{host}:{port}")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_upload_overwrites_and_download_all_overwrites_locally(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            outbound = root / "outbound"
            inbound = root / "inbound"
            outbound.mkdir()
            inbound.mkdir()
            (outbound / "existing.gif").write_bytes(b"new-content")
            (outbound / "second.gif").write_bytes(b"second")
            (outbound / "gify").mkdir()
            (outbound / "gify" / "nested.gif").write_bytes(b"nested")
            (outbound / "ignored.png").write_bytes(b"ignored")
            (inbound / "existing.gif").write_bytes(b"stale")

            uploaded = self.client.upload_all(outbound)
            downloaded = self.client.download_all(inbound)

            self.assertEqual(
                [path.relative_to(outbound).as_posix() for path in uploaded],
                ["existing.gif", "gify/nested.gif", "second.gif"],
            )
            self.assertEqual(len(downloaded), 3)
            self.assertEqual((inbound / "existing.gif").read_bytes(), b"new-content")
            self.assertEqual((inbound / "second.gif").read_bytes(), b"second")
            self.assertEqual((inbound / "gify" / "nested.gif").read_bytes(), b"nested")


if __name__ == "__main__":
    main()
