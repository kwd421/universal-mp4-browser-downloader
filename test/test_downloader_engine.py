import unittest
import tempfile
from pathlib import Path

from tools import downloader_engine as engine


SAMPLE_INFO = {
    "id": "sample",
    "title": "Sample Video",
    "duration": 125,
    "thumbnail": "https://example.test/thumb.jpg",
    "webpage_url": "https://example.test/watch",
    "formats": [
        {
            "format_id": "18",
            "ext": "mp4",
            "height": 360,
            "width": 640,
            "fps": 30,
            "vcodec": "avc1.42001E",
            "acodec": "mp4a.40.2",
            "filesize": 100_000_000,
            "format_note": "360p",
        },
        {
            "format_id": "137",
            "ext": "mp4",
            "height": 1080,
            "width": 1920,
            "fps": 30,
            "vcodec": "avc1.640028",
            "acodec": "none",
            "filesize": 500_000_000,
            "format_note": "1080p video",
        },
        {
            "format_id": "22",
            "ext": "mp4",
            "height": 720,
            "width": 1280,
            "fps": 30,
            "vcodec": "avc1.64001F",
            "acodec": "mp4a.40.2",
            "filesize_approx": 250_000_000,
            "format_note": "720p",
        },
        {
            "format_id": "313",
            "ext": "webm",
            "height": 2160,
            "width": 3840,
            "fps": 60,
            "vcodec": "vp9",
            "acodec": "none",
            "format_note": "2160p unknown size",
        },
        {
            "format_id": "140",
            "ext": "m4a",
            "vcodec": "none",
            "acodec": "mp4a.40.2",
            "filesize": 10_000_000,
            "format_note": "audio",
        },
    ],
}


class FakeYoutubeDL:
    calls = []
    failures_before_success = 0

    def __init__(self, options):
        self.options = options
        FakeYoutubeDL.calls.append(options)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download=False):
        if FakeYoutubeDL.failures_before_success:
            FakeYoutubeDL.failures_before_success -= 1
            raise RuntimeError("could not copy chrome cookie database")
        return SAMPLE_INFO

    def download(self, urls):
        self.downloaded_urls = urls
        return 0


class DownloaderEngineTests(unittest.TestCase):
    def setUp(self):
        FakeYoutubeDL.calls = []
        FakeYoutubeDL.failures_before_success = 0

    def test_candidates_are_video_only_and_sorted_by_size_with_unknown_last(self):
        candidates = engine.candidates_from_info(SAMPLE_INFO)

        self.assertEqual([candidate["format_id"] for candidate in candidates], ["137", "22", "18", "313"])
        self.assertEqual(candidates[0]["format_selector"], "137+bestaudio[ext=m4a]/bestaudio/best")
        self.assertEqual(candidates[0]["sort_bytes"], 510_000_000)
        self.assertEqual(candidates[0]["display_title"], "Sample Video")
        self.assertEqual(candidates[0]["thumbnail"], "https://example.test/thumb.jpg")
        self.assertEqual(candidates[0]["duration"], 125)
        self.assertEqual(candidates[-1]["sort_bytes"], 0)
        self.assertEqual(candidates[-1]["resolution"], "3840x2160")

    def test_display_duration_formats_runtime(self):
        self.assertEqual(engine.display_duration(65), "1:05")
        self.assertEqual(engine.display_duration(3661), "1:01:01")

    def test_clean_video_title_removes_trailing_domain_suffix(self):
        self.assertEqual(engine.clean_video_title("Good Video - videosite.example"), "Good Video")
        self.assertEqual(engine.clean_video_title("Good Video | example.net"), "Good Video")
        self.assertEqual(engine.clean_video_title("Good Video - Creator Name"), "Good Video - Creator Name")
        self.assertEqual(engine.clean_video_title(""), "")

    def test_generic_video_title_uses_parent_caption(self):
        info = {
            "title": "Post by someone",
            "description": "첫 문장입니다. 둘째 문장입니다.",
            "entries": [
                {
                    "title": "Video 1",
                    "formats": [
                        {
                            "format_id": "best",
                            "ext": "mp4",
                            "height": 720,
                            "vcodec": "h264",
                            "acodec": "aac",
                            "url": "https://example.test/video.mp4",
                        }
                    ],
                }
            ],
        }

        candidates = engine.candidates_from_info(info, output_ext="MP4")

        self.assertEqual(candidates[0]["display_title"], "첫 문장입니다. 둘째 문장입니다.")

    def test_candidates_can_be_filtered_by_requested_extension(self):
        mp4 = engine.candidates_from_info(SAMPLE_INFO, output_ext="MP4")
        webm = engine.candidates_from_info(SAMPLE_INFO, output_ext="WEBM")
        wav = engine.candidates_from_info(SAMPLE_INFO, output_ext="WAV")

        self.assertEqual([candidate["ext"] for candidate in mp4], ["mp4", "mp4", "mp4"])
        self.assertEqual([candidate["ext"] for candidate in webm], ["webm"])
        self.assertEqual([candidate["ext"] for candidate in wav], ["wav"])
        self.assertEqual(wav[0]["format_selector"], "140")
        self.assertEqual(wav[0]["resolution"], "")
        self.assertEqual(wav[0]["output_ext"], "wav")

    def test_missing_sizes_are_filled_from_http_content_length(self):
        candidates = [
            {
                "id": "1",
                "url": "https://cdn.example.test/video.mp4",
                "sort_bytes": 0,
                "filesize": 0,
                "filesize_approx": 0,
            }
        ]

        engine.enrich_missing_sizes(candidates, size_probe=lambda url: 321_000)

        self.assertEqual(candidates[0]["sort_bytes"], 321_000)
        self.assertEqual(candidates[0]["filesize_approx"], 321_000)
        self.assertEqual(candidates[0]["size_source"], "http")

    def test_manifest_sizes_are_not_filled_from_playlist_content_length(self):
        candidates = [
            {
                "id": "1",
                "url": "https://cdn.example.test/master.m3u8",
                "sort_bytes": 0,
                "filesize": 0,
                "filesize_approx": 0,
                "is_manifest": True,
            }
        ]

        engine.enrich_missing_sizes(candidates, size_probe=lambda url: 22_600)

        self.assertEqual(candidates[0]["sort_bytes"], 0)
        self.assertEqual(candidates[0]["filesize_approx"], 0)
        self.assertNotEqual(candidates[0].get("size_source"), "http")

    def test_manifest_candidates_prefer_bitrate_duration_estimate_over_playlist_size(self):
        info = {
            "id": "hls-sample",
            "title": "HLS Sample",
            "duration": 446,
            "webpage_url": "https://example.test/watch",
            "formats": [
                {
                    "format_id": "hls-3049-1",
                    "ext": "mp4",
                    "protocol": "m3u8_native",
                    "url": "https://cdn.example.test/master.m3u8",
                    "height": 1080,
                    "width": 1920,
                    "tbr": 3049,
                    "vcodec": "avc1.640028",
                    "acodec": "mp4a.40.2",
                    "filesize": 22_600,
                    "format_note": "1920x1080",
                }
            ],
        }

        candidates = engine.candidates_from_info(info, output_ext="MP4")

        self.assertEqual(candidates[0]["sort_bytes"], 169_981_750)
        self.assertEqual(candidates[0]["size_source"], "bitrate")
        self.assertEqual(engine.display_size(candidates[0]["sort_bytes"]), "162.1 MB")

    def test_cookie_source_maps_to_yt_dlp_options(self):
        self.assertNotIn("cookiesfrombrowser", engine.build_ydl_options(cookie_source="없음"))
        self.assertEqual(engine.build_ydl_options(cookie_source="Chrome")["cookiesfrombrowser"], ("chrome",))
        self.assertEqual(engine.build_ydl_options(cookie_source="Edge")["cookiesfrombrowser"], ("edge",))
        self.assertEqual(engine.build_ydl_options(cookie_source="Firefox")["cookiesfrombrowser"], ("firefox",))

    def test_proxy_url_maps_to_yt_dlp_options(self):
        self.assertNotIn("proxy", engine.build_ydl_options(proxy_url=""))
        self.assertEqual(
            engine.build_ydl_options(proxy_url=" http://127.0.0.1:8080 ")["proxy"],
            "http://127.0.0.1:8080",
        )

    def test_chrome_impersonation_option_is_added_when_available(self):
        options = engine.build_ydl_options(impersonate=True)

        target = options.get("impersonate")
        if engine.chrome_impersonation_target():
            self.assertEqual(str(target), "chrome-110:windows-10")
        else:
            self.assertIsNone(target)

    def test_analyze_passes_proxy_url_to_yt_dlp(self):
        result = engine.analyze_url(
            "https://example.test/watch",
            proxy_url="http://127.0.0.1:8080",
            ydl_factory=FakeYoutubeDL,
        )

        self.assertEqual(result["title"], "Sample Video")
        self.assertEqual(FakeYoutubeDL.calls[0]["proxy"], "http://127.0.0.1:8080")

    def test_download_options_use_selected_format_selector(self):
        candidate = {"format_selector": "137+bestaudio[ext=m4a]/bestaudio/best"}

        options = engine.build_download_options(
            candidate,
            "C:/Temp",
            cookie_source="Chrome",
            proxy_url="http://127.0.0.1:8080",
        )

        self.assertEqual(options["format"], "137+bestaudio[ext=m4a]/bestaudio/best")
        self.assertEqual(options["merge_output_format"], "mp4")
        self.assertEqual(options["final_ext"], "mp4")
        self.assertEqual(options["cookiesfrombrowser"], ("chrome",))
        self.assertEqual(options["proxy"], "http://127.0.0.1:8080")

    def test_download_options_convert_audio_candidates_to_wav(self):
        candidate = {"format_selector": "140", "output_ext": "wav"}

        options = engine.build_download_options(candidate, "C:/Temp")

        self.assertEqual(options["format"], "140")
        self.assertEqual(options["final_ext"], "wav")
        self.assertEqual(options["postprocessors"][0]["key"], "FFmpegExtractAudio")
        self.assertEqual(options["postprocessors"][0]["preferredcodec"], "wav")

    def test_download_options_pass_browser_dom_referer_and_origin_headers(self):
        candidate = {
            "format_selector": "best",
            "output_ext": "mp4",
            "referer": "https://example.test/watch",
            "origin": "https://example.test",
        }

        options = engine.build_download_options(candidate, "C:/Temp")

        self.assertEqual(options["http_headers"]["Referer"], "https://example.test/watch")
        self.assertEqual(options["http_headers"]["Origin"], "https://example.test")

    def test_download_options_use_display_title_not_manifest_title_for_filename(self):
        candidate = {
            "format_selector": "best",
            "output_ext": "mp4",
            "display_title": "Actual Video Title - videosite.example",
            "title": "master",
            "format_id": "master",
            "url": "https://cdn.example.test/master.m3u8",
        }

        options = engine.build_download_options(candidate, "C:/Temp")

        filename = Path(options["outtmpl"]).name
        self.assertEqual(filename, "Actual Video Title.%(ext)s")
        self.assertNotIn("videosite", filename)
        self.assertNotIn("master", filename)

    def test_effective_proxy_prefers_explicit_then_environment_then_windows(self):
        self.assertEqual(
            engine.effective_proxy_url(
                explicit_proxy=" http://127.0.0.1:8080 ",
                environ={"HTTPS_PROXY": "http://env.example:8888"},
                windows_proxy_fetcher=lambda: "http://windows.example:8888",
            ),
            "http://127.0.0.1:8080",
        )
        self.assertEqual(
            engine.effective_proxy_url(
                explicit_proxy="",
                environ={"HTTPS_PROXY": "http://env.example:8888"},
                windows_proxy_fetcher=lambda: "http://windows.example:8888",
            ),
            "http://env.example:8888",
        )
        self.assertEqual(
            engine.effective_proxy_url(
                explicit_proxy="",
                environ={},
                windows_proxy_fetcher=lambda: "http://windows.example:8888",
            ),
            "http://windows.example:8888",
        )

    def test_analyze_retries_without_cookies_when_browser_cookie_read_fails(self):
        FakeYoutubeDL.failures_before_success = 1

        result = engine.analyze_url("https://example.test/watch", cookie_source="Chrome", ydl_factory=FakeYoutubeDL)

        self.assertEqual(result["title"], "Sample Video")
        self.assertIn("쿠키 읽기 실패", result["warnings"][0])
        self.assertEqual(FakeYoutubeDL.calls[0]["cookiesfrombrowser"], ("chrome",))
        self.assertNotIn("cookiesfrombrowser", FakeYoutubeDL.calls[1])

    def test_browser_dom_media_definitions_extracts_hls_candidates(self):
        html = """
        <html><head>
          <title>Browser Title - Example</title>
          <meta property="og:image" content="https://img.example.test/thumb.jpg">
        </head><body>
        <script>
        window.flashvars = {"mediaDefinitions":[
          {"height":1080,"width":1920,"format":"hls","videoUrl":"https:\\/\\/cdn.example.test\\/1080\\/master.m3u8","quality":"1080","segmentFormats":{"audio":"ts_aac","video":"mpeg2_ts"}},
          {"height":720,"width":1280,"format":"hls","videoUrl":"https:\\/\\/cdn.example.test\\/720\\/master.m3u8","quality":"720","segmentFormats":{"audio":"ts_aac","video":"mpeg2_ts"}}
        ],"other":true};
        </script></body></html>
        """

        result = engine.analyze_browser_dom_media(
            "https://example.test/watch",
            html,
            output_ext="MP4",
        )

        self.assertEqual(result["source"], "browser-dom")
        self.assertEqual(result["title"], "Browser Title - Example")
        self.assertEqual([candidate["height"] for candidate in result["candidates"]], [1080, 720])
        self.assertEqual(result["candidates"][0]["url"], "https://cdn.example.test/1080/master.m3u8")
        self.assertEqual(result["candidates"][0]["source"], "https://example.test/watch")
        self.assertEqual(result["candidates"][0]["referer"], "https://example.test/watch")
        self.assertEqual(result["candidates"][0]["origin"], "https://example.test")
        self.assertEqual(result["candidates"][0]["format_selector"], "best")
        self.assertEqual(result["candidates"][0]["thumbnail"], "https://img.example.test/thumb.jpg")

    def test_browser_dom_player_scripts_extract_embedded_player_candidates(self):
        html = """
        <html><head><title>Script Video - videosite.example</title></head><body>
        <script>
          html5player.setVideoUrlLow('https://mp4.example.test/path/video_240p.mp4?secure=low');
          html5player.setVideoUrlHigh('https://mp4.example.test/path/video_360p.mp4?secure=high');
          html5player.setVideoHLS('https://hls.example.test/path/hls.m3u8');
          html5player.setThumbUrl('https://thumb.example.test/thumb.jpg');
        </script></body></html>
        """

        result = engine.analyze_browser_dom_media(
            "https://www.videosite.example/video123/example",
            html,
            output_ext="MP4",
        )

        self.assertEqual(result["source"], "browser-dom")
        self.assertEqual(result["title"], "Script Video")
        self.assertEqual([candidate["format_id"] for candidate in result["candidates"]], ["browser-360", "browser-240", "browser-hls"])
        self.assertEqual(result["candidates"][0]["url"], "https://mp4.example.test/path/video_360p.mp4?secure=high")
        self.assertEqual(result["candidates"][0]["height"], 360)
        self.assertFalse(result["candidates"][0]["is_manifest"])
        self.assertEqual(result["candidates"][0]["referer"], "https://www.videosite.example/video123/example")
        self.assertEqual(result["candidates"][0]["origin"], "https://www.videosite.example")
        self.assertEqual(result["candidates"][0]["thumbnail"], "https://thumb.example.test/thumb.jpg")
        self.assertTrue(result["candidates"][2]["is_manifest"])

    def test_analyze_uses_browser_dom_fallback_after_tls_reset(self):
        class ResetYoutubeDL(FakeYoutubeDL):
            def extract_info(self, url, download=False):
                raise RuntimeError("ConnectionResetError forcibly closed")

        html = """
        <html><head><title>Fallback Video</title></head><body>
        <script>
        var flashvars = {"mediaDefinitions":[
          {"height":480,"width":854,"format":"hls","videoUrl":"https:\\/\\/cdn.example.test\\/480\\/master.m3u8","quality":"480"}
        ]};
        </script></body></html>
        """

        result = engine.analyze_url(
            "https://example.test/watch",
            ydl_factory=ResetYoutubeDL,
            browser_dom_fetcher=lambda url, on_event=None: html,
        )

        self.assertEqual(result["source"], "browser-dom")
        self.assertEqual(result["title"], "Fallback Video")
        self.assertEqual(result["candidates"][0]["height"], 480)
        self.assertTrue(any("브라우저 DOM" in warning for warning in result["warnings"]))

    def test_chzzk_clip_uid_is_detected(self):
        self.assertEqual(
            engine.find_chzzk_clip_uid("https://chzzk.naver.com/clips/qwr3h4r3Yn"),
            "qwr3h4r3Yn",
        )

    def test_error_classification_uses_required_public_labels(self):
        self.assertEqual(engine.classify_error("DRM encrypted stream"), "DRM 가능성")
        self.assertEqual(engine.classify_error("ConnectionResetError forcibly closed"), "브라우저 지문/TLS 차단 가능성")
        self.assertEqual(engine.classify_error("HTTP Error 403 Forbidden"), "로그인/권한 필요")
        self.assertEqual(engine.classify_error("captcha required"), "봇 차단/CAPTCHA")
        self.assertEqual(engine.classify_error("unsupported url"), "지원되지 않는 스트림")
        self.assertEqual(engine.classify_error("connection reset"), "네트워크/추출 오류")

    def test_write_json_stringifies_non_json_event_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out = Path(temp_dir) / "result.json"

            engine.write_json(out, {"events": [{"logger": object()}]})

            self.assertIn('"logger": "<object object at', out.read_text(encoding="utf-8"))

    def test_event_logger_hides_non_actionable_ffprobe_metadata_warning(self):
        events = []
        logger = engine.EventLogger(events.append)

        logger.warning("Unable to extract metadata: ffprobe not found. Please install or provide the path using --ffmpeg-location")

        self.assertEqual(events, [])

    def test_find_browser_executable_supports_override_and_macos_paths(self):
        self.assertEqual(
            engine.find_browser_executable(
                environ={"UMP4_BROWSER_PATH": "/custom/chrome"},
                which_func=lambda name: None,
                path_exists=lambda path: str(path) == "/custom/chrome",
            ),
            "/custom/chrome",
        )

        mac_edge = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
        self.assertEqual(
            engine.find_browser_executable(
                environ={"HOME": "/Users/alice"},
                which_func=lambda name: None,
                path_exists=lambda path: str(path) == mac_edge,
            ),
            mac_edge,
        )

    def test_find_browser_executable_uses_path_lookup_on_unix_names(self):
        self.assertEqual(
            engine.find_browser_executable(
                environ={},
                which_func=lambda name: "/usr/bin/chromium" if name == "chromium" else None,
                path_exists=lambda path: str(path) == "/usr/bin/chromium",
            ),
            "/usr/bin/chromium",
        )


if __name__ == "__main__":
    unittest.main()
