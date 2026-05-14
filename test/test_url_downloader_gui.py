import tempfile
import unittest
from pathlib import Path
from tkinter import Tk

from tools import url_downloader_gui as gui


class UrlDownloaderGuiTests(unittest.TestCase):
    def test_cookie_choices_match_required_public_ui(self):
        self.assertEqual(gui.COOKIE_CHOICES, ["없음", "Chrome", "Edge", "Firefox"])

    def test_candidate_columns_identify_video_and_move_size_right(self):
        self.assertEqual([column[0] for column in gui.CANDIDATE_COLUMNS], ["resolution", "duration", "ext", "quality", "size", "note"])
        self.assertNotIn("fps", [column[0] for column in gui.CANDIDATE_COLUMNS])
        self.assertNotIn("vcodec", [column[0] for column in gui.CANDIDATE_COLUMNS])
        self.assertNotIn("acodec", [column[0] for column in gui.CANDIDATE_COLUMNS])

    def test_tree_row_height_can_fit_thumbnail(self):
        self.assertGreaterEqual(gui.TREE_ROW_HEIGHT, gui.THUMBNAIL_SIZE[1] + 8)

    def test_group_candidates_collapses_same_video_into_quality_list(self):
        candidates = [
            {"id": "1", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "720p", "height": 720, "sort_bytes": 20},
            {"id": "2", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "sort_bytes": 30},
            {"id": "3", "source": "other", "title": "Other", "display_title": "Other", "thumbnail": "t2", "ext": "mp4", "output_ext": "mp4", "resolution": "360p", "height": 360, "sort_bytes": 10},
        ]

        rows = gui.group_candidates(candidates)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["candidate"]["resolution"], "1080p")
        self.assertEqual([candidate["resolution"] for candidate in rows[0]["qualities"]], ["1080p", "720p"])

    def test_group_candidates_hides_manifest_original_default_when_direct_formats_exist(self):
        candidates = [
            {"id": "1", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "sort_bytes": 1000, "is_manifest": False, "note": "1080p"},
            {"id": "2", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "sort_bytes": 100, "is_manifest": True, "note": "(original)"},
        ]

        rows = gui.group_candidates(candidates)

        self.assertEqual(len(rows[0]["qualities"]), 1)
        self.assertEqual(rows[0]["qualities"][0]["id"], "1")

    def test_group_candidates_keeps_one_quality_per_resolution_when_formats_look_identical(self):
        candidates = [
            {"id": "small-1080", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "fps": 30, "sort_bytes": 40},
            {"id": "large-1080", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "fps": 30, "sort_bytes": 80},
            {"id": "720", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "720p", "height": 720, "fps": 30, "sort_bytes": 20},
        ]

        rows = gui.group_candidates(candidates)

        self.assertEqual([candidate["id"] for candidate in rows[0]["qualities"]], ["large-1080", "720"])

    def test_wav_quality_label_does_not_show_resolution(self):
        label = gui.quality_label({"output_ext": "wav", "ext": "wav", "media_type": "audio", "sort_bytes": 1000, "note": "audio"})

        self.assertIn("WAV", label)
        self.assertNotIn("p", label.lower())

    def test_analyze_button_switches_between_paste_and_analyze(self):
        root = Tk()
        root.withdraw()
        try:
            app = gui.UrlDownloaderApp(root)
            self.assertEqual(app.analyze_button.cget("text"), "붙여넣기")
            app.url.set("https://example.test/video")
            root.update_idletasks()
            self.assertEqual(app.analyze_button.cget("text"), "분석")
        finally:
            root.destroy()

    def test_headless_verification_writes_analysis_without_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "verify.json"

            def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
                self.assertEqual(cookie_source, "없음")
                self.assertIsNone(proxy_url)
                self.assertIsNone(output_ext)
                self.assertTrue(callable(on_event))
                return {
                    "url": url,
                    "title": "Fake",
                    "candidates": [
                        {
                            "id": "1",
                            "format_id": "18",
                            "format_selector": "18",
                            "url": url,
                            "title": "Fake",
                            "sort_bytes": 123,
                        }
                    ],
                    "warnings": [],
                }

            result = gui.run_headless_verification(
                url="https://example.test/video",
                output_json=str(out_path),
                output_dir=temp_dir,
                cookie_source="없음",
                should_download=False,
                analyze_func=fake_analyze,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["candidate_count"], 1)
            self.assertTrue(out_path.exists())

    def test_headless_verification_passes_proxy_without_ui(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "verify.json"

            def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
                self.assertEqual(proxy_url, "http://127.0.0.1:8080")
                return {
                    "url": url,
                    "title": "Fake",
                    "candidates": [
                        {
                            "id": "1",
                            "format_id": "18",
                            "format_selector": "18",
                            "url": url,
                            "title": "Fake",
                            "sort_bytes": 123,
                        }
                    ],
                    "warnings": [],
                }

            result = gui.run_headless_verification(
                url="https://example.test/video",
                output_json=str(out_path),
                output_dir=temp_dir,
                cookie_source="없음",
                proxy_url="http://127.0.0.1:8080",
                should_download=False,
                analyze_func=fake_analyze,
            )

            self.assertTrue(result["ok"])

    def test_headless_verification_can_download_selected_candidate_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "verify.json"
            downloaded = []

            def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
                return {
                    "url": url,
                    "title": "Fake",
                    "candidates": [
                        {"id": "high", "format_selector": "high", "output_ext": "mp4", "ext": "mp4"},
                        {"id": "low", "format_selector": "low", "output_ext": "mp4", "ext": "mp4"},
                    ],
                    "warnings": [],
                }

            def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
                downloaded.append(candidate["id"])
                path = Path(output_dir) / "fake.mp4"
                path.write_bytes(b"mp4")
                return {"ok": True, "output_dir": output_dir}

            result = gui.run_headless_verification(
                url="https://example.test/video",
                output_json=str(out_path),
                output_dir=temp_dir,
                should_download=True,
                download_candidate_index=1,
                analyze_func=fake_analyze,
                download_func=fake_download,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(downloaded, ["low"])
            self.assertEqual(result["download"]["selected_candidate"]["id"], "low")


if __name__ == "__main__":
    unittest.main()
