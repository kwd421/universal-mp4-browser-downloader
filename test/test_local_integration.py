import functools
import http.server
import socketserver
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tools import downloader_engine as engine


class LocalIntegrationTests(unittest.TestCase):
    def test_local_video_page_analyzes_and_downloads_mp4(self):
        with tempfile.TemporaryDirectory() as site_dir, tempfile.TemporaryDirectory() as output_dir:
            site = Path(site_dir)
            video = site / "sample.mp4"
            ffmpeg = engine.ffmpeg_path()
            self.assertTrue(ffmpeg, "ffmpeg must be bundled by imageio_ffmpeg")
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=160x90:rate=10",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=880:duration=1",
                    "-t",
                    "1",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    str(video),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            (site / "index.html").write_text(
                '<!doctype html><title>Local Video</title><video src="/sample.mp4" controls></video>',
                encoding="utf-8",
            )

            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=site_dir)
            with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                page_url = f"http://127.0.0.1:{server.server_address[1]}/index.html"

                analysis = engine.analyze_url(page_url)
                self.assertGreaterEqual(len(analysis["candidates"]), 1)
                before = time.time()
                engine.download_candidate(page_url, analysis["candidates"][0], output_dir)
                downloaded = engine.newest_mp4(output_dir, since=before - 2)

                self.assertIsNotNone(downloaded)
                self.assertTrue(downloaded.exists())
                self.assertGreater(downloaded.stat().st_size, 0)
                server.shutdown()


if __name__ == "__main__":
    unittest.main()
