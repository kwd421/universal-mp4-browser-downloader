import concurrent.futures
import contextlib
import io
import json
import subprocess
import time
import unittest
import tempfile
import sys
from pathlib import Path
from unittest import mock

from tools import downloader_engine as engine
from tools import clipflow_analysis_process


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

    def test_youtube_tvhtml5_direct_video_candidate_is_marked_download_risky(self):
        info = {
            "id": "yt-id",
            "title": "YouTube Video",
            "webpage_url": "https://www.youtube.com/watch?v=yt-id",
            "formats": [
                {
                    "format_id": "299",
                    "url": "https://rr1---sn.googlevideo.com/videoplayback?c=TVHTML5&itag=299",
                    "protocol": "https",
                    "ext": "mp4",
                    "height": 1080,
                    "fps": 60,
                    "vcodec": "avc1",
                    "acodec": "none",
                    "filesize": 123,
                },
                {
                    "format_id": "301",
                    "url": "https://manifest.googlevideo.com/api/manifest/hls_playlist/playlist/index.m3u8",
                    "protocol": "m3u8_native",
                    "ext": "mp4",
                    "height": 1080,
                    "fps": 60,
                    "vcodec": "avc1",
                    "acodec": "mp4a",
                    "tbr": 1000,
                    "duration": 10,
                },
            ],
        }

        candidates = {candidate["format_id"]: candidate for candidate in engine.candidates_from_info(info)}

        self.assertEqual(candidates["299"]["download_risk"], "youtube_tv_https_po_token")
        self.assertFalse(candidates["301"].get("download_risk"))

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

    def test_display_title_prefixes_uploader_when_available(self):
        info = dict(SAMPLE_INFO)
        info["uploader"] = "Sample Channel"

        candidates = engine.candidates_from_info(info)

        self.assertEqual(candidates[0]["display_title"], "Sample Channel - Sample Video")

    def test_candidates_can_be_filtered_by_requested_extension(self):
        mp4 = engine.candidates_from_info(SAMPLE_INFO, output_ext="MP4")
        webm = engine.candidates_from_info(SAMPLE_INFO, output_ext="WEBM")
        wav = engine.candidates_from_info(SAMPLE_INFO, output_ext="WAV")
        mp3 = engine.candidates_from_info(SAMPLE_INFO, output_ext="MP3")
        aac = engine.candidates_from_info(SAMPLE_INFO, output_ext="AAC")

        self.assertEqual([candidate["ext"] for candidate in mp4], ["mp4", "mp4", "mp4"])
        self.assertEqual([candidate["ext"] for candidate in webm], ["webm"])
        self.assertEqual([candidate["ext"] for candidate in wav], ["wav"])
        self.assertEqual(wav[0]["format_selector"], "140")
        self.assertEqual(wav[0]["resolution"], "")
        self.assertEqual(wav[0]["output_ext"], "wav")
        self.assertEqual([candidate["ext"] for candidate in mp3], ["mp3"])
        self.assertEqual(mp3[0]["media_type"], "audio")
        self.assertEqual([candidate["ext"] for candidate in aac], ["aac"])

    def test_all_output_preserves_audio_candidates_for_global_preferences(self):
        candidates = engine.candidates_from_info(SAMPLE_INFO, output_ext="all")

        output_exts = [candidate["output_ext"] for candidate in candidates]

        self.assertIn("mp3", output_exts)
        self.assertIn("wav", output_exts)
        self.assertIn("aac", output_exts)
        self.assertIn("mp4", output_exts)
        self.assertIn("webm", output_exts)

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
        # display_size matches the host file browser: binary (1024) on Windows,
        # decimal (1000) elsewhere.
        expected_size = "162.1 MB" if engine.SIZE_UNIT_BASE == 1024 else "170.0 MB"
        self.assertEqual(engine.display_size(candidates[0]["sort_bytes"]), expected_size)

    def test_cookie_source_maps_to_yt_dlp_options(self):
        self.assertNotIn("cookiesfrombrowser", engine.build_ydl_options(cookie_source="없음"))
        self.assertEqual(
            engine.build_ydl_options(cookie_source="Chrome")["cookiesfrombrowser"],
            engine.cookiesfrombrowser_spec("Chrome"),
        )
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
        self.assertEqual(options["cookiesfrombrowser"], engine.cookiesfrombrowser_spec("Chrome"))
        self.assertEqual(options["proxy"], "http://127.0.0.1:8080")

    def test_parse_timecode_accepts_seconds_minutes_and_hours(self):
        self.assertIsNone(engine.parse_timecode(""))
        self.assertIsNone(engine.parse_timecode(None))
        self.assertEqual(engine.parse_timecode("90"), 90)
        self.assertEqual(engine.parse_timecode("1:30"), 90)
        self.assertEqual(engine.parse_timecode("01:02:03.5"), 3723.5)
        with self.assertRaises(ValueError):
            engine.parse_timecode("abc")
        with self.assertRaises(ValueError):
            engine.parse_timecode("-1")

    def test_normalize_clip_range_handles_empty_start_and_end_validation(self):
        self.assertIsNone(engine.normalize_clip_range("", ""))
        self.assertEqual(engine.normalize_clip_range("10", ""), {"start": 10.0, "end": None})
        self.assertEqual(engine.normalize_clip_range("", "20"), {"start": 0.0, "end": 20.0})
        self.assertEqual(engine.normalize_clip_range("10", "20"), {"start": 10.0, "end": 20.0})
        with self.assertRaises(ValueError):
            engine.normalize_clip_range("20", "10")

    def test_clip_range_suffix_keeps_segment_download_filenames_distinct(self):
        full = engine.final_output_path_for_candidate({"title": "Video", "output_ext": "mp4"}, "C:/Temp")
        clipped = engine.final_output_path_for_candidate(
            {"title": "Video", "output_ext": "mp4", "clip_range": {"start": 10, "end": 20}},
            "C:/Temp",
        )

        self.assertEqual(full.name, "Video.mp4")
        self.assertEqual(clipped.name, "Video [00m10s-00m20s].mp4")

    def test_clip_range_suffix_is_not_duplicated_in_filename_stem(self):
        candidate = {
            "title": "Video [00m10s-00m20s]",
            "output_ext": "mp4",
            "clip_range": {"start": 10, "end": 20},
        }

        self.assertEqual(engine.filename_stem_for_candidate(candidate), "Video [00m10s-00m20s]")

    def test_existing_full_output_does_not_skip_segment_output(self):
        with tempfile.TemporaryDirectory() as temp:
            full_path = Path(temp) / "Video.mp4"
            full_path.write_bytes(b"full")
            segment = {"title": "Video", "output_ext": "mp4", "clip_range": {"start": 10, "end": 20}}

            self.assertIsNone(engine.existing_output_path_for_candidate(segment, temp))

    def test_candidate_with_clip_range_metadata_updates_title_duration_and_size(self):
        candidate = {
            "title": "Video",
            "display_title": "Video",
            "duration": 120,
            "filesize": 1200,
            "filesize_approx": 0,
            "sort_bytes": 1200,
            "clip_range": {"start": 10, "end": 20},
        }

        prepared = engine.candidate_with_clip_range_metadata(candidate)

        self.assertEqual(prepared["title"], "Video [00m10s-00m20s]")
        self.assertEqual(prepared["display_title"], "Video [00m10s-00m20s]")
        self.assertEqual(prepared["duration"], 10)
        self.assertEqual(prepared["source_duration"], 120)
        self.assertEqual(prepared["source_filesize"], 1200)
        self.assertEqual(prepared["sort_bytes"], 100)
        self.assertEqual(prepared["filesize"], 100)
        self.assertEqual(prepared["size_source"], "clip_estimate")
        self.assertEqual(engine.clip_range_from_candidate(prepared), {"start": 10.0, "end": 20.0})

    def test_candidate_with_clip_range_metadata_handles_start_only_range(self):
        candidate = {
            "title": "Video",
            "display_title": "Video",
            "duration": 120,
            "sort_bytes": 1200,
            "clip_range": {"start": 30, "end": None},
        }

        prepared = engine.candidate_with_clip_range_metadata(candidate)

        self.assertEqual(prepared["display_title"], "Video [00m30s-end]")
        self.assertEqual(prepared["duration"], 90)
        self.assertEqual(prepared["sort_bytes"], 900)

    def test_candidate_with_clip_range_metadata_caps_end_to_known_duration(self):
        candidate = {
            "title": "Short",
            "display_title": "Short",
            "duration": 15,
            "sort_bytes": 1500,
            "clip_range": {"start": 10, "end": 20},
        }

        prepared = engine.candidate_with_clip_range_metadata(candidate)

        self.assertEqual(prepared["clip_range"], {"start": 10.0, "end": 15.0})
        self.assertEqual(prepared["display_title"], "Short [00m10s-00m15s]")
        self.assertEqual(prepared["duration"], 5)
        self.assertEqual(prepared["sort_bytes"], 500)

    def test_download_options_add_download_ranges_for_clipped_candidate(self):
        options = engine.build_download_options(
            {
                "format_selector": "137+bestaudio[ext=m4a]/bestaudio/best",
                "output_ext": "mp4",
                "clip_range": {"start": 10, "end": 20},
            },
            "C:/Temp",
        )

        self.assertIn("download_ranges", options)
        self.assertFalse(options["force_keyframes_at_cuts"])
        self.assertIn("ffmpeg", str(options.get("external_downloader") or "").lower())
        self.assertEqual(Path(options["external_downloader"]).name.lower(), "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg")

    def test_ffmpeg_path_for_yt_dlp_exposes_standard_ffmpeg_name(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "ffmpeg-win-x86_64-v7.1.exe"
            source.write_bytes(b"fake")
            cache_dir = Path(temp) / "cache"

            result = Path(engine.ffmpeg_path_for_yt_dlp(str(source), cache_dir=cache_dir))

            self.assertEqual(result.name.lower(), "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg")
            self.assertTrue(result.exists())
            self.assertEqual(result.read_bytes(), b"fake")

    def test_download_options_enable_force_keyframes_for_accurate_clip_cut(self):
        options = engine.build_download_options(
            {
                "format_selector": "137+bestaudio[ext=m4a]/bestaudio/best",
                "output_ext": "mp4",
                "clip_range": {"start": 10, "end": 20},
                "clip_cut_mode": "accurate",
            },
            "C:/Temp",
        )

        self.assertTrue(options["force_keyframes_at_cuts"])

    def test_download_options_keep_native_hls_progress_for_mp4_manifest(self):
        options = engine.build_download_options(
            {
                "format_selector": "301",
                "output_ext": "mp4",
                "is_manifest": True,
                "protocol": "m3u8_native",
            },
            "C:/Temp",
        )

        self.assertNotIn("external_downloader", options)
        self.assertNotIn("postprocessors", options)
        self.assertEqual(options.get("fixup"), "never")

    def test_download_options_disable_hls_fixup_for_m3u8_url_even_with_https_protocol(self):
        options = engine.build_download_options(
            {
                "format_selector": "hls-1080",
                "output_ext": "mp4",
                "protocol": "https",
                "url": "https://media.test/playlist.m3u8",
            },
            "C:/Temp",
        )

        self.assertEqual(options.get("fixup"), "never")

    def test_download_options_only_convert_video_when_target_is_not_mp4(self):
        options = engine.build_download_options(
            {
                "format_selector": "bestvideo*+bestaudio/best",
                "output_ext": "webm",
                "ext": "webm",
            },
            "C:/Temp",
        )

        self.assertEqual(options["postprocessors"], [{"key": "FFmpegVideoConvertor", "preferedformat": "webm"}])

    def test_download_candidate_retries_progressive_mp4_after_video_data_403(self):
        calls = []

        class FailingThenOkYDL:
            def __init__(self, options):
                self.options = options
                calls.append(options["format"])

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def download(self, urls):
                if len(calls) == 1:
                    raise RuntimeError("ERROR: unable to download video data: HTTP Error 403: Forbidden")

        result = engine.download_candidate(
            "https://youtube.test/watch?v=one",
            {"format_selector": "137+bestaudio[ext=m4a]/bestaudio/best", "output_ext": "mp4"},
            "C:/Temp",
            ydl_factory=FailingThenOkYDL,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(calls, ["137+bestaudio[ext=m4a]/bestaudio/best", "18/best[ext=mp4]/best"])

    def test_download_candidate_retries_progressive_mp4_without_cookies_after_second_403(self):
        calls = []

        class FailingTwiceThenOkYDL:
            def __init__(self, options):
                self.options = options
                calls.append((options["format"], options.get("cookiesfrombrowser")))

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def download(self, urls):
                if len(calls) <= 2:
                    raise RuntimeError("ERROR: unable to download video data: HTTP Error 403: Forbidden")

        result = engine.download_candidate(
            "https://youtube.test/watch?v=one",
            {"format_selector": "137+bestaudio[ext=m4a]/bestaudio/best", "output_ext": "mp4"},
            "C:/Temp",
            cookie_source="Firefox",
            ydl_factory=FailingTwiceThenOkYDL,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            calls,
            [
                ("137+bestaudio[ext=m4a]/bestaudio/best", ("firefox",)),
                ("18/best[ext=mp4]/best", ("firefox",)),
                ("18/best[ext=mp4]/best", None),
            ],
        )

    def test_download_candidate_retries_without_cookies_after_browser_cookie_decrypt_error(self):
        calls = []
        events = []

        class CookieDecryptFailThenOkYDL:
            def __init__(self, options):
                self.options = options
                calls.append(options.get("cookiesfrombrowser"))

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def download(self, urls):
                if len(calls) == 1:
                    raise RuntimeError("ERROR: Failed to decrypt with DPAPI")

        result = engine.download_candidate(
            "https://youtube.test/watch?v=one",
            {"format_selector": "137+bestaudio[ext=m4a]/bestaudio/best", "output_ext": "mp4"},
            "C:/Temp",
            cookie_source="Chrome",
            ydl_factory=CookieDecryptFailThenOkYDL,
            on_event=lambda event: events.append(event),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [engine.cookiesfrombrowser_spec("Chrome"), None])
        self.assertTrue(any("쿠키 없이 다시 시도" in event.get("message", "") for event in events))

    def test_download_candidate_uses_analyzed_info_without_reextracting_url(self):
        calls = []
        analyzed_info = {
            "id": "video-id",
            "title": "Analyzed Video",
            "webpage_url": "https://youtube.test/watch?v=video-id",
            "extractor": "youtube",
            "formats": [
                {
                    "format_id": "18",
                    "url": "https://media.test/video.mp4",
                    "ext": "mp4",
                    "vcodec": "avc1",
                    "acodec": "mp4a",
                }
            ],
        }

        class RecordingYDL:
            def __init__(self, options):
                self.options = options
                calls.append(("options", options.get("format")))

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def process_video_result(self, info, download=True):
                calls.append(("process_video_result", info["id"], download, self.options.get("format")))
                info["processed"] = True
                return info

            def download(self, urls):
                raise AssertionError("download() should not re-extract the URL when analyzed info is available")

        result = engine.download_candidate(
            "https://youtube.test/watch?v=video-id",
            {
                "id": "best",
                "title": "Analyzed Video",
                "display_title": "Analyzed Video",
                "source": "https://youtube.test/watch?v=video-id",
                "format_selector": "18",
                "output_ext": "mp4",
                "_download_info": analyzed_info,
            },
            "C:/Temp",
            ydl_factory=RecordingYDL,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            calls,
            [
                ("options", "18"),
                ("process_video_result", "video-id", True, "18"),
            ],
        )
        self.assertNotIn("processed", analyzed_info)

    def test_download_candidate_does_not_serialize_reused_info_for_youtube(self):
        calls = []

        class RecordingYDL:
            def __init__(self, options):
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def process_video_result(self, info, download=True):
                raise AssertionError("YouTube analyzed info carries runtime extractor state and must not be reused across processes")

            def download(self, urls):
                calls.append(urls)

        result = engine.download_candidate(
            "https://www.youtube.com/watch?v=video-id",
            {
                "id": "best",
                "title": "YouTube Video",
                "display_title": "YouTube Video",
                "source": "https://www.youtube.com/watch?v=video-id",
                "format_selector": "301",
                "output_ext": "mp4",
                "_download_info": {"id": "video-id", "formats": []},
            },
            "C:/Temp",
            ydl_factory=RecordingYDL,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [["https://www.youtube.com/watch?v=video-id"]])

    def test_download_candidate_in_subprocess_relays_events_and_result(self):
        events = []
        script = (
            "import json, sys; "
            "print(json.dumps({'type':'event','event':{'type':'progress','percent':25,'message':'25%'}}), flush=True); "
            "print(json.dumps({'type':'finished','result':{'ok':True,'output_dir':'C:/Out','target_url':'https://media.test/watch'}}), flush=True)"
        )

        result = engine.download_candidate_in_subprocess(
            "https://media.test/watch",
            {"format_selector": "best", "output_ext": "mp4"},
            "C:/Out",
            on_event=events.append,
            process_command=[sys.executable, "-u", "-c", script],
        )

        self.assertEqual(events, [{"type": "progress", "percent": 25, "message": "25%"}])
        self.assertEqual(result["target_url"], "https://media.test/watch")

    def test_download_candidate_in_subprocess_keeps_partial_event_file_line(self):
        script = r'''
import json
import sys
import time
from pathlib import Path

request = json.loads(Path(sys.argv[-1]).read_text(encoding="utf-8"))
event_path = Path(request["event_path"])
line = json.dumps({"type": "finished", "result": {"ok": True, "target_url": "partial-line"}}) + "\n"
with event_path.open("a", encoding="utf-8") as file:
    file.write(line[:20])
    file.flush()
    time.sleep(0.2)
    file.write(line[20:])
    file.flush()
'''
        original_command = engine.download_worker_command
        engine.download_worker_command = lambda request_path: [sys.executable, "-u", "-c", script, str(request_path)]
        try:
            result = engine._download_candidate_in_one_shot_worker(
                engine._download_worker_request(
                    "https://media.test/watch",
                    {"format_selector": "best", "output_ext": "mp4"},
                    "C:/Out",
                ),
            )
        finally:
            engine.download_worker_command = original_command

        self.assertEqual(result["target_url"], "partial-line")

    def test_download_candidate_in_subprocess_uses_reusable_worker_pool_by_default(self):
        events = []

        class FakePool:
            def __init__(self):
                self.requests = []

            def run(self, request, on_event=None):
                self.requests.append(request)
                if on_event:
                    on_event({"type": "progress", "percent": 33, "message": "33%"})
                return {"ok": True, "target_url": request["page_url"], "output_dir": request["output_dir"]}

        fake_pool = FakePool()
        original_pool = getattr(engine, "_DOWNLOAD_PROCESS_POOL", None)
        original_command = engine.download_worker_command
        engine._DOWNLOAD_PROCESS_POOL = fake_pool
        engine.download_worker_command = lambda request_path: (_ for _ in ()).throw(AssertionError("one-shot worker should not be started"))
        try:
            result = engine.download_candidate_in_subprocess(
                "https://media.test/watch",
                {"format_selector": "best", "output_ext": "mp4"},
                "C:/Out",
                cookie_source="Firefox",
                on_event=events.append,
                proxy_url="http://127.0.0.1:8080",
            )
        finally:
            engine._DOWNLOAD_PROCESS_POOL = original_pool
            engine.download_worker_command = original_command

        self.assertEqual(events, [{"type": "progress", "percent": 33, "message": "33%"}])
        self.assertEqual(result["target_url"], "https://media.test/watch")
        self.assertEqual(fake_pool.requests[0]["cookie_source"], "Firefox")
        self.assertEqual(fake_pool.requests[0]["proxy_url"], "http://127.0.0.1:8080")

    def test_warm_download_worker_warms_reusable_pool(self):
        class FakePool:
            def __init__(self):
                self.warmed = 0

            def warm(self):
                self.warmed += 1

        fake_pool = FakePool()
        original_pool = getattr(engine, "_DOWNLOAD_PROCESS_POOL", None)
        engine._DOWNLOAD_PROCESS_POOL = fake_pool
        try:
            engine.warm_download_worker()
        finally:
            engine._DOWNLOAD_PROCESS_POOL = original_pool

        self.assertEqual(fake_pool.warmed, 1)

    def test_download_process_pool_reuses_persistent_worker_process(self):
        script = r'''
import json
import os
import sys

for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({"type": "event", "event": {"type": "status", "message": request["page_url"]}}), flush=True)
    print(json.dumps({"type": "finished", "result": {"ok": True, "target_url": request["page_url"], "pid": os.getpid()}}), flush=True)
'''
        pool = engine.DownloadProcessPool(
            idle_seconds=60,
            max_idle=1,
            command_factory=lambda: [sys.executable, "-u", "-c", script],
        )
        events = []
        try:
            pool.warm()
            first = pool.run(engine._download_worker_request("https://media.test/one", {}, "C:/Out"), on_event=events.append)
            second = pool.run(engine._download_worker_request("https://media.test/two", {}, "C:/Out"), on_event=events.append)
        finally:
            pool.close_all()

        self.assertEqual(first["target_url"], "https://media.test/one")
        self.assertEqual(second["target_url"], "https://media.test/two")
        self.assertEqual(first["pid"], second["pid"])
        self.assertEqual(
            events,
            [
                {"type": "status", "message": "https://media.test/one"},
                {"type": "status", "message": "https://media.test/two"},
            ],
        )

    def test_download_process_pool_keeps_parallel_events_on_their_request_callbacks(self):
        script = r'''
import json
import os
import sys
import time

for line in sys.stdin:
    request = json.loads(line)
    label = request["candidate"]["id"]
    print(json.dumps({"type": "event", "event": {"type": "progress", "label": label, "percent": 50}}), flush=True)
    time.sleep(0.2)
    print(json.dumps({"type": "finished", "result": {"ok": True, "target_url": request["page_url"], "label": label, "pid": os.getpid()}}), flush=True)
'''
        pool = engine.DownloadProcessPool(
            idle_seconds=60,
            max_idle=2,
            command_factory=lambda: [sys.executable, "-u", "-c", script],
        )
        events = {"one": [], "two": []}

        def run(label):
            return pool.run(
                engine._download_worker_request(f"https://media.test/{label}", {"id": label}, "C:/Out"),
                on_event=events[label].append,
            )

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(run, "one")
                second = executor.submit(run, "two")
                results = [first.result(), second.result()]
        finally:
            pool.close_all()

        self.assertEqual({result["label"] for result in results}, {"one", "two"})
        self.assertEqual(events["one"], [{"type": "progress", "label": "one", "percent": 50}])
        self.assertEqual(events["two"], [{"type": "progress", "label": "two", "percent": 50}])
        self.assertNotEqual(results[0]["pid"], results[1]["pid"])

    def test_analysis_process_run_request_emits_events_before_finished_result(self):
        def fake_analyze(url, cookie_source=None, output_ext=None, proxy_url=None, on_event=None):
            on_event({"type": "status", "message": "URL 분석 중"})
            return {
                "webpage_url": url,
                "cookie_source": cookie_source,
                "output_ext": output_ext,
                "proxy_url": proxy_url,
                "candidates": [],
                "warnings": [],
            }

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            clipflow_analysis_process.run_request(
                {
                    "url": "https://media.test/watch",
                    "cookie_source": "Firefox",
                    "output_ext": "MP4",
                    "proxy_url": "http://127.0.0.1:8080",
                },
                analyze_func=fake_analyze,
            )

        payloads = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(payloads[0], {"type": "event", "event": {"type": "status", "message": "URL 분석 중"}})
        self.assertEqual(payloads[1]["type"], "finished")
        self.assertEqual(payloads[1]["result"]["webpage_url"], "https://media.test/watch")
        self.assertEqual(payloads[1]["result"]["cookie_source"], "Firefox")
        self.assertEqual(payloads[1]["result"]["output_ext"], "MP4")
        self.assertEqual(payloads[1]["result"]["proxy_url"], "http://127.0.0.1:8080")

    def test_analysis_process_writes_payloads_as_utf8_bytes(self):
        class FakeStdout:
            def __init__(self):
                self.buffer = io.BytesIO()

        original_stdout = sys.stdout
        fake_stdout = FakeStdout()
        try:
            sys.stdout = fake_stdout
            clipflow_analysis_process._write_payload({"type": "event", "event": {"message": "한글 제목"}})
        finally:
            sys.stdout = original_stdout

        payload = json.loads(fake_stdout.buffer.getvalue().decode("utf-8"))
        self.assertEqual(payload["event"]["message"], "한글 제목")

    def test_analysis_process_pool_reuses_persistent_worker_process(self):
        script = r'''
import json
import os
import sys

for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({"type": "event", "event": {"type": "status", "message": request["url"]}}), flush=True)
    print(json.dumps({"type": "finished", "result": {"url": request["url"], "pid": os.getpid()}}), flush=True)
'''
        pool = engine.AnalysisProcessPool(
            idle_seconds=60,
            max_idle=1,
            command_factory=lambda: [sys.executable, "-u", "-c", script],
        )
        events = []
        try:
            first = pool.run(engine._analysis_worker_request("https://media.test/one"), on_event=events.append)
            second = pool.run(engine._analysis_worker_request("https://media.test/two"), on_event=events.append)
        finally:
            pool.close_all()

        self.assertEqual(first["url"], "https://media.test/one")
        self.assertEqual(second["url"], "https://media.test/two")
        self.assertEqual(first["pid"], second["pid"])
        self.assertEqual(
            events,
            [
                {"type": "status", "message": "https://media.test/one"},
                {"type": "status", "message": "https://media.test/two"},
            ],
        )

    def test_analysis_process_reports_failed_payload_with_side_output_context(self):
        script = r'''
import json
import sys

for line in sys.stdin:
    print("side diagnostic", flush=True)
    print(json.dumps({"type": "failed", "message": "\u001b[31mbad analysis\u001b[0m"}), flush=True)
'''
        worker = engine.PersistentAnalysisProcess(command=[sys.executable, "-u", "-c", script])
        try:
            with self.assertRaises(RuntimeError) as raised:
                worker.run(engine._analysis_worker_request("https://media.test/fail"))
        finally:
            worker.close()

        self.assertEqual(str(raised.exception), "bad analysis")

    def test_analysis_process_pool_trims_stale_idle_worker_with_timer(self):
        script = r'''
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({"type": "finished", "result": {"url": request["url"]}}), flush=True)
'''
        pool = engine.AnalysisProcessPool(
            idle_seconds=0.05,
            max_idle=1,
            command_factory=lambda: [sys.executable, "-u", "-c", script],
        )
        try:
            result = pool.run(engine._analysis_worker_request("https://media.test/trim"))
            self.assertEqual(result["url"], "https://media.test/trim")
            self.assertEqual(len(pool._idle), 1)
            time.sleep(0.25)
            with pool._lock:
                idle = list(pool._idle)
            self.assertEqual(idle, [])
        finally:
            pool.close_all()

    def test_download_process_pool_trims_stale_idle_worker_with_timer(self):
        script = r'''
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({"type": "finished", "result": {"ok": True, "target_url": request["page_url"]}}), flush=True)
'''
        pool = engine.DownloadProcessPool(
            idle_seconds=0.05,
            max_idle=1,
            command_factory=lambda: [sys.executable, "-u", "-c", script],
        )
        try:
            result = pool.run(engine._download_worker_request("https://media.test/trim", {}, "C:/Out"))
            self.assertEqual(result["target_url"], "https://media.test/trim")
            self.assertEqual(len(pool._idle), 1)
            time.sleep(0.25)
            with pool._lock:
                idle = list(pool._idle)
            self.assertEqual(idle, [])
        finally:
            pool.close_all()

    def test_download_options_convert_audio_candidates_to_wav(self):
        candidate = {"format_selector": "140", "output_ext": "wav"}

        options = engine.build_download_options(candidate, "C:/Temp")

        self.assertEqual(options["format"], "140")
        self.assertEqual(options["final_ext"], "wav")
        self.assertEqual(options["postprocessors"][0]["key"], "FFmpegExtractAudio")
        self.assertEqual(options["postprocessors"][0]["preferredcodec"], "wav")

    def test_download_options_convert_audio_candidates_to_mp3_and_aac(self):
        for output_ext in ("mp3", "aac"):
            options = engine.build_download_options({"format_selector": "140", "output_ext": output_ext}, "C:/Temp")

            self.assertEqual(options["format"], "140")
            self.assertEqual(options["final_ext"], output_ext)
            self.assertEqual(options["postprocessors"][0]["key"], "FFmpegExtractAudio")
            self.assertEqual(options["postprocessors"][0]["preferredcodec"], output_ext)

    def test_convert_existing_media_to_audio_uses_ffmpeg_without_downloading(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "Already Downloaded.mp4"
            source.write_bytes(b"video")
            output = Path(temp) / "Already Downloaded.mp3"
            calls = []
            events = []

            class Completed:
                returncode = 0
                stderr = ""
                stdout = ""

            def fake_runner(command, **kwargs):
                calls.append((command, kwargs))
                output.write_bytes(b"audio")
                return Completed()

            result = engine.convert_existing_media_to_audio(
                source,
                "MP3",
                on_event=events.append,
                ffmpeg_exe="ffmpeg-test",
                runner=fake_runner,
            )

            self.assertEqual(result["output_path"], str(output))
            self.assertEqual(calls[0][0], ["ffmpeg-test", "-y", "-i", str(source), "-vn", str(output)])
            self.assertTrue(any(event.get("type") == "file" and event.get("path") == str(output) for event in events))

    def test_extract_existing_media_segment_uses_local_file_without_downloading(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "Already Downloaded.mp4"
            source.write_bytes(b"video")
            calls = []
            events = []

            class Completed:
                returncode = 0
                stderr = ""
                stdout = ""

            def fake_runner(command, **kwargs):
                calls.append((command, kwargs))
                Path(command[-1]).write_bytes(b"segment")
                return Completed()

            result = engine.extract_existing_media_segment(
                source,
                {
                    "title": "Already Downloaded",
                    "display_title": "Already Downloaded [00m10s-00m20s]",
                    "output_ext": "mp4",
                    "clip_range": {"start": 10, "end": 20},
                    "clip_cut_mode": "fast",
                },
                output_dir=temp,
                on_event=events.append,
                ffmpeg_exe="ffmpeg-test",
                runner=fake_runner,
            )

            output = Path(result["output_path"])
            self.assertEqual(output.name, "Already Downloaded [00m10s-00m20s].mp4")
            self.assertEqual(output.read_bytes(), b"segment")

        command = calls[0][0]
        self.assertIn(str(source), command)
        self.assertIn("-ss", command)
        self.assertIn("10.0", command)
        self.assertIn("-t", command)
        self.assertIn("-c", command)
        self.assertEqual(command[command.index("-c") + 1], "copy")
        self.assertTrue(any(event.get("type") == "status" and event.get("message") == "Extracting selected segment" for event in events))

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

    def test_download_options_put_playlist_in_named_subfolder(self):
        candidate = {
            "media_type": "playlist",
            "format_selector": "bestvideo*+bestaudio/best",
            "output_ext": "mp4",
            "display_title": "Road Trip Mix",
            "title": "Road Trip Mix",
        }

        options = engine.build_download_options(candidate, "C:/Temp")

        output_template = Path(options["outtmpl"])
        self.assertEqual(output_template.parent.name, "Road Trip Mix")
        self.assertFalse(options["noplaylist"])
        self.assertIn("playlist_index", output_template.name)

    def test_watch_urls_with_list_query_are_treated_as_playlist_links(self):
        self.assertTrue(engine.looks_like_playlist_url("https://video.example/watch?v=one&list=RDone&index=1"))
        self.assertTrue(engine.looks_like_playlist_url("https://video.example/watch?v=one&list=PL123"))
        self.assertFalse(engine.looks_like_playlist_url("https://www.youtube.com/watch?v=one&list=RDone&start_radio=1"))
        self.assertFalse(engine.looks_like_playlist_url("https://www.youtube.com/watch?v=one&list=RDone"))
        self.assertFalse(engine.looks_like_playlist_url("https://youtu.be/one?list=RDone"))
        self.assertTrue(engine.looks_like_playlist_url("https://www.youtube.com/watch?v=one&list=PL123"))
        self.assertFalse(engine.looks_like_playlist_url("https://video.example/watch?v=one"))

    def test_youtube_video_list_urls_resolve_to_single_or_playlist_urls(self):
        short_url = "https://youtu.be/7DAFS8sga2k?list=PL5cMV8jURyS9R5ideqDxaIguOnbby9MVs"
        watch_url = "https://www.youtube.com/watch?v=7DAFS8sga2k&list=PL5cMV8jURyS9R5ideqDxaIguOnbby9MVs&index=3&pp=abc"

        self.assertTrue(engine.needs_youtube_playlist_choice(short_url))
        self.assertTrue(engine.needs_youtube_playlist_choice(watch_url))
        self.assertFalse(engine.needs_youtube_playlist_choice("https://www.youtube.com/playlist?list=PL5cMV8jURyS9R5ideqDxaIguOnbby9MVs"))
        self.assertFalse(engine.needs_youtube_playlist_choice("https://youtu.be/Kc-JF2eSmt8"))
        self.assertEqual(engine.youtube_single_video_url(short_url), "https://youtu.be/7DAFS8sga2k")
        self.assertEqual(engine.youtube_single_video_url(watch_url), "https://www.youtube.com/watch?v=7DAFS8sga2k")
        self.assertEqual(
            engine.youtube_playlist_url(short_url),
            "https://www.youtube.com/playlist?list=PL5cMV8jURyS9R5ideqDxaIguOnbby9MVs",
        )
        self.assertEqual(
            engine.youtube_playlist_url(watch_url),
            "https://www.youtube.com/playlist?list=PL5cMV8jURyS9R5ideqDxaIguOnbby9MVs",
        )

    def test_analyze_youtube_radio_watch_url_strips_playlist_query(self):
        class RadioYoutubeDL(FakeYoutubeDL):
            requested_urls = []

            def extract_info(self, url, download=False):
                RadioYoutubeDL.requested_urls.append(url)
                return {
                    "id": "one",
                    "title": "One",
                    "webpage_url": url,
                    "duration": 60,
                    "formats": [
                        {
                            "format_id": "18",
                            "ext": "mp4",
                            "height": 720,
                            "width": 1280,
                            "vcodec": "avc1.64001F",
                            "acodec": "mp4a.40.2",
                            "filesize": 800,
                        }
                    ],
                }

        result = engine.analyze_url(
            "https://www.youtube.com/watch?v=I8Lqr6NeG5o&list=RDI8Lqr6NeG5o&start_radio=1&pp=oAcB",
            ydl_factory=RadioYoutubeDL,
            output_ext="mp4",
            on_event=lambda event: None,
        )

        self.assertFalse(result.get("is_playlist"))
        self.assertEqual(RadioYoutubeDL.requested_urls, ["https://www.youtube.com/watch?v=I8Lqr6NeG5o"])

    def test_analyze_url_emits_playlist_analysis_events(self):
        class PlaylistYoutubeDL(FakeYoutubeDL):
            requested_urls = []

            def extract_info(self, url, download=False):
                PlaylistYoutubeDL.requested_urls.append(url)
                if self.options.get("extract_flat"):
                    return {
                        "title": "Road Mix",
                        "webpage_url": url,
                        "playlist_count": 2,
                        "entries": [
                            {"id": "one", "title": "One", "webpage_url": "https://example.test/watch/one"},
                            {"id": "two", "title": "Two", "webpage_url": "https://example.test/watch/two"},
                        ],
                    }
                title = "One" if url.endswith("/one") else "Two"
                height = 1080 if title == "One" else 720
                return {
                    "id": title.lower(),
                    "title": title,
                    "webpage_url": url,
                    "duration": 60,
                    "formats": [
                        {
                            "format_id": "18",
                            "ext": "mp4",
                            "height": height,
                            "width": 1920,
                            "vcodec": "avc1.640028",
                            "acodec": "mp4a.40.2",
                            "filesize": 1000,
                        }
                    ],
                }

        events = []

        result = engine.analyze_url(
            "https://example.test/playlist/road",
            ydl_factory=PlaylistYoutubeDL,
            output_ext="mp4",
            on_event=events.append,
        )

        playlist_events = [event for event in events if str(event.get("type", "")).startswith("playlist_")]
        self.assertTrue(result["is_playlist"])
        self.assertEqual(
            [event["type"] for event in playlist_events],
            [
                "playlist_parent",
                "playlist_entry_loading",
                "playlist_entry",
                "playlist_entry_loading",
                "playlist_entry",
                "playlist_complete",
            ],
        )
        self.assertEqual(playlist_events[0]["title"], "Road Mix")
        self.assertEqual(playlist_events[0]["count"], 2)
        self.assertEqual([event.get("candidates", [{}])[0].get("display_title") for event in playlist_events if event["type"] == "playlist_entry"], ["One", "Two"])
        self.assertEqual(
            PlaylistYoutubeDL.requested_urls,
            [
                "https://example.test/playlist/road",
                "https://example.test/watch/one",
                "https://example.test/watch/two",
            ],
        )

    def test_analyze_youtube_watch_playlist_uses_canonical_playlist_url_for_entries(self):
        class PlaylistYoutubeDL(FakeYoutubeDL):
            requested_urls = []

            def extract_info(self, url, download=False):
                PlaylistYoutubeDL.requested_urls.append(url)
                if self.options.get("extract_flat"):
                    return {
                        "title": "Road Mix",
                        "webpage_url": url,
                        "playlist_count": 1,
                        "entries": [
                            {"id": "one", "title": "One", "webpage_url": "https://www.youtube.com/watch?v=one"},
                        ],
                    }
                return {
                    "id": "one",
                    "title": "One",
                    "webpage_url": url,
                    "duration": 60,
                    "formats": [
                        {
                            "format_id": "18",
                            "ext": "mp4",
                            "height": 720,
                            "width": 1280,
                            "vcodec": "avc1.64001F",
                            "acodec": "mp4a.40.2",
                            "filesize": 800,
                        }
                    ],
                }

        result = engine.analyze_url(
            "https://www.youtube.com/watch?v=one&list=PLROAD&pp=sAgC",
            ydl_factory=PlaylistYoutubeDL,
            output_ext="mp4",
            on_event=lambda event: None,
        )

        self.assertTrue(result["is_playlist"])
        self.assertEqual(PlaylistYoutubeDL.requested_urls[0], "https://www.youtube.com/playlist?list=PLROAD")
        self.assertEqual(PlaylistYoutubeDL.requested_urls[1], "https://www.youtube.com/watch?v=one")

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
        self.assertEqual(FakeYoutubeDL.calls[0]["cookiesfrombrowser"], engine.cookiesfrombrowser_spec("Chrome"))
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

    def test_browser_dom_extracts_generic_video_src_with_duration_and_size(self):
        html = """
        <html><head>
        <title>Generic Video</title>
        <meta name="description" content="Video Duration: 00:56:57 File Size: 1065.87 MB">
        </head><body>
        <video poster="https://media.example.test/thumb.webp" src="https://cdn.example.test/video-1080p.mp4"></video>
        </body></html>
        """

        result = engine.analyze_browser_dom_media(
            "https://media.example.test/watch",
            html,
            output_ext=engine.ALL_OUTPUT_EXT,
        )
        candidate = result["candidates"][0]

        self.assertEqual(candidate["url"], "https://cdn.example.test/video-1080p.mp4")
        self.assertEqual(candidate["duration"], 3417)
        self.assertEqual(candidate["thumbnail"], "https://media.example.test/thumb.webp")
        self.assertEqual(candidate["height"], 1080)
        self.assertEqual(candidate["sort_bytes"], 1_117_645_701)
        self.assertEqual(candidate["size_source"], "metadata")

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

    def test_analyze_uses_browser_dom_fallback_after_unsupported_error(self):
        class UnsupportedYoutubeDL(FakeYoutubeDL):
            def extract_info(self, url, download=False):
                raise RuntimeError("unsupported URL")

        html = """
        <html><head><title>Script Fallback</title></head><body>
        <video src="https://cdn.example.test/video-720p.mp4"></video>
        </body></html>
        """

        result = engine.analyze_url(
            "https://example.test/watch",
            ydl_factory=UnsupportedYoutubeDL,
            browser_dom_fetcher=lambda url, on_event=None: html,
        )

        self.assertEqual(result["source"], "browser-dom")
        self.assertEqual(result["title"], "Script Fallback")
        self.assertEqual(result["candidates"][0]["height"], 720)

    def test_analyze_uses_browser_dom_fallback_when_extractor_has_no_video_candidates(self):
        class AudioOnlyYoutubeDL(FakeYoutubeDL):
            def extract_info(self, url, download=False):
                return {
                    "title": "Audio Only",
                    "webpage_url": url,
                    "formats": [
                        {
                            "format_id": "140",
                            "ext": "m4a",
                            "vcodec": "none",
                            "acodec": "mp4a.40.2",
                            "filesize": 1000,
                        }
                    ],
                }

        html = """
        <html><head><title>Rendered Video</title></head><body>
        <script>
        var flashvars = {"mediaDefinitions":[
          {"height":1080,"width":1920,"format":"hls","videoUrl":"https:\\/\\/cdn.example.test\\/master.m3u8","quality":"1080"}
        ]};
        </script></body></html>
        """

        result = engine.analyze_url(
            "https://example.test/watch",
            ydl_factory=AudioOnlyYoutubeDL,
            browser_dom_fetcher=lambda url, on_event=None: html,
        )

        self.assertEqual(result["source"], "browser-dom")
        self.assertEqual(result["title"], "Rendered Video")
        self.assertTrue(result["candidates"][0]["is_manifest"])

    def test_browser_dom_media_definitions_site_metadata_matches_page(self):
        html = """
        <html><head>
          <meta name="twitter:title" content="Demo clip for mediaDefinitions parsing">
          <meta property="og:video:duration" content="361">
        </head><body>
        <h1 class="title">Demo clip for mediaDefinitions parsing</h1>
        <div>From:&nbsp;<a href="/users/demo-creator"><span class="username">Demo Creator</span></a></div>
        <script>
        var flashvars_123 = {"video_duration":361,"mediaDefinitions":[
          {"height":720,"width":1280,"format":"hls","videoUrl":"https:\\/\\/cdn.example.test\\/720\\/master.m3u8","quality":"720"},
          {"height":480,"width":854,"format":"mp4","videoUrl":"https:\\/\\/cdn.example.test\\/480\\/video.mp4","quality":"480","filesize":52428800}
        ]};
        </script></body></html>
        """

        result = engine.analyze_browser_dom_media(
            "https://www.example-stream.test/view_video.php?viewkey=demo123",
            html,
            output_ext="MP4",
        )
        best_mp4 = next(candidate for candidate in result["candidates"] if candidate["height"] == 480)

        self.assertEqual(result["title"], "Demo Creator - Demo clip for mediaDefinitions parsing")
        self.assertEqual(best_mp4["display_title"], result["title"])
        self.assertEqual(best_mp4["uploader"], "Demo Creator")
        self.assertEqual(best_mp4["duration"], 361)
        self.assertEqual(best_mp4["sort_bytes"], 52_428_800)
        self.assertEqual(best_mp4["size_source"], "metadata")
        self.assertEqual(
            engine.final_output_path_for_candidate(best_mp4, "/tmp/downloads").name,
            "Demo Creator - Demo clip for mediaDefinitions parsing.mp4",
        )

    def test_browser_dom_player_script_metadata_matches_page(self):
        html = """
        <html><head>
          <title>Player Script Demo Clip</title>
          <meta property="video:duration" content="1238">
          <meta name="description" content="File Size: 70.00 MB">
        </head><body>
        <span class="duration">20:38</span>
        <a href="/profiles/demo-creator">Demo Creator</a>
        <script>
          html5player.setVideoTitle('A Beautiful Red-Haired Stranger Was Refused, But Still Came To My Room For Sex');
          html5player.setVideoUrlLow('https://mp4.example.test/path/video_240p.mp4');
          html5player.setVideoUrlHigh('https://mp4.example.test/path/video_360p.mp4?bytes=73400320');
          html5player.setVideoHLS('https://hls.example.test/path/hls.m3u8');
          html5player.setThumbUrl('https://thumb.example.test/thumb.jpg');
        </script></body></html>
        """

        result = engine.analyze_browser_dom_media(
            "https://www.example-stream.test/video.demo123/example",
            html,
            output_ext="MP4",
        )
        best_mp4 = result["candidates"][0]

        self.assertEqual(
            result["title"],
            "Demo Creator - A Beautiful Red-Haired Stranger Was Refused, But Still Came To My Room For Sex",
        )
        self.assertEqual(best_mp4["duration"], 1238)
        self.assertEqual(best_mp4["height"], 360)
        self.assertEqual(engine.display_duration(best_mp4["duration"]), "20:38")
        self.assertEqual(best_mp4["sort_bytes"], 73_400_320)
        self.assertEqual(best_mp4["size_source"], "metadata")

    def test_browser_dom_page_script_initials_metadata_matches_page(self):
        html = """
        <html><head><title>Page Script Demo Clip</title></head><body>
        <script>
        window.initials = {
          "videoModel": {
            "title": "FemaleAgent Shy beauty takes the bait",
            "duration": 893,
            "thumbURL": "https://thumb.example.test/xh.jpg",
            "author": {"name": "Ruseful2011", "pageURL": "https://example-stream.test/users/ruseful2011"},
            "sources": {
              "standard": {
                "720p": "https://cdn.example.test/xh-720p.mp4",
                "480p": "https://cdn.example.test/xh-480p.mp4"
              },
              "download": {
                "720p": {"size": 94371840},
                "480p": {"size": 47185920}
              }
            }
          }
        };
        </script></body></html>
        """

        result = engine.analyze_browser_dom_media(
            "https://example-stream.test/videos/femaleagent-shy-beauty-takes-the-bait-1509445",
            html,
            output_ext="MP4",
        )
        best = result["candidates"][0]

        self.assertEqual(result["title"], "Ruseful2011 - FemaleAgent Shy beauty takes the bait")
        self.assertEqual(best["display_title"], result["title"])
        self.assertEqual(best["uploader"], "Ruseful2011")
        self.assertEqual(best["duration"], 893)
        self.assertEqual(best["sort_bytes"], 94_371_840)
        self.assertEqual(engine.display_duration(best["duration"]), "14:53")
        self.assertEqual(best["thumbnail"], "https://thumb.example.test/xh.jpg")

    def test_curl_resolve_entries_for_url_uses_system_dns(self):
        with mock.patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("162.159.138.60", 0))]):
            self.assertEqual(
                engine.curl_resolve_entries_for_url("https://vimeo.com/watch"),
                ["vimeo.com:443:162.159.138.60"],
            )

    def test_dom_html_looks_usable_detects_player_scripts(self):
        html = "<html><body><script>html5player.setVideoHLS('https://cdn.example.test/a.m3u8');</script></body></html>"
        self.assertTrue(engine.dom_html_looks_usable("x" * 600 + html))

    def test_fetch_dom_for_fallback_prefers_urllib_html(self):
        html = "x" * 600 + "<script>html5player.setVideoUrlHigh('https://cdn.example.test/a.mp4');</script>"

        with mock.patch.object(engine, "fetch_dom_html_with_urllib", return_value=html):
            with mock.patch.object(engine, "dump_dom_with_browser") as dump_dom:
                result = engine.fetch_dom_for_fallback("https://example.test/watch")
        self.assertEqual(result, html)
        dump_dom.assert_not_called()

    def test_should_try_browser_dom_fallback_skips_tiktok_ip_block(self):
        self.assertFalse(
            engine.should_try_browser_dom_fallback("ERROR: [TikTok] 123: Your IP address is blocked from accessing this post")
        )

    def test_should_retry_with_browser_cookies_for_instagram_empty_media(self):
        self.assertTrue(
            engine.should_retry_with_browser_cookies(
                "ERROR: [Instagram] abc: Instagram sent an empty media response."
            )
        )

    def test_thumbnail_from_browser_dom_keeps_full_image_url(self):
        long_url = "https://cdn.example.test/" + ("a" * 120) + "/thumb.jpg"
        html = f'<html><head><meta property="og:image" content="{long_url}"></head></html>'
        self.assertEqual(engine.thumbnail_from_browser_dom(html), long_url)

    def test_favicon_urls_from_html_discovers_link_icons(self):
        html = """
        <html><head>
          <link rel="shortcut icon" href="/static/favicon.ico">
          <link rel="apple-touch-icon" href="https://cdn.example.test/icon.png">
        </head></html>
        """
        self.assertEqual(
            engine.favicon_urls_from_html(html, "https://media.example.test/watch/1"),
            [
                "https://media.example.test/static/favicon.ico",
                "https://cdn.example.test/icon.png",
            ],
        )

    def test_save_thumbnail_asset_writes_image_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(engine, "fetch_binary_url", return_value=(b"x" * 1200, "image/jpeg")):
                saved = engine.save_thumbnail_asset(
                    "https://cdn.example.test/thumb.jpg",
                    Path(tmp),
                    "video-title",
                    referer="https://media.example.test/watch/1",
                )
            path = Path(saved["path"])
            self.assertTrue(path.exists())
            self.assertEqual(path.stat().st_size, 1200)
            self.assertIn("video-title.thumb", path.name)

    def test_save_favicon_asset_tries_candidates_until_one_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                engine,
                "download_image_asset",
                side_effect=[RuntimeError("404"), {"ok": True, "path": str(Path(tmp) / "video-title.favicon.ico"), "bytes": 256, "url": "https://media.example.test/favicon.ico", "content_type": "image/x-icon"}],
            ) as download_image:
                saved = engine.save_favicon_asset(
                    "https://media.example.test/watch/1",
                    Path(tmp),
                    "video-title",
                    dom_html='<link rel="icon" href="/missing.ico">',
                )
            self.assertEqual(download_image.call_count, 2)
            self.assertEqual(saved["bytes"], 256)

    def test_is_browser_remote_media_api_url_detects_remote_media_paths(self):
        self.assertTrue(engine.is_browser_remote_media_api_url("https://www.example-stream.test/media/mp4?s=abc"))
        self.assertTrue(engine.is_browser_remote_media_api_url("https://www.example-stream.test/video/get_media?s=abc"))
        self.assertFalse(engine.is_browser_remote_media_api_url("https://cdn.example.test/video.mp4"))

    def test_analyze_browser_dom_media_includes_remote_mp4_api_candidates(self):
        html = """
        <html><head><title>Remote API Video</title></head><body>
        <script>
        var flashvars = {"mediaDefinitions":[
          {"format":"mp4","videoUrl":"/media/mp4?s=token","remote":true},
          {"format":"hls","videoUrl":"/media/hls?s=token","remote":true}
        ]};
        </script></body></html>
        """

        page_url = "https://www.example-stream.test/watch/demo123"
        result = engine.analyze_browser_dom_media(page_url, html)

        self.assertEqual(result["candidates"][0]["url"], "https://www.example-stream.test/media/mp4?s=token")
        self.assertFalse(result["candidates"][0]["is_manifest"])

    def test_prepare_browser_dom_candidate_auto_quality_picks_highest_remote_api_entry(self):
        page_url = "https://www.example-stream.test/watch/demo123"
        candidate = {
            "format_id": "browser-mp4",
            "url": "https://www.example-stream.test/media/mp4?s=token",
            "height": 0,
            "source": page_url,
        }
        payload = [
            {"quality": "240", "videoUrl": "https://cdn.example.test/240.mp4"},
            {"quality": "720", "videoUrl": "https://cdn.example.test/720.mp4"},
            {"quality": "1080", "videoUrl": "https://cdn.example.test/1080.mp4"},
        ]

        with mock.patch.object(
            engine,
            "refresh_browser_dom_candidate_media",
            side_effect=lambda page_url, candidate, on_event=None: dict(candidate),
        ), mock.patch.object(engine, "fetch_json_via_browser", return_value=payload):
            prepared = engine.prepare_browser_dom_candidate(page_url, candidate)

        self.assertEqual(prepared["url"], "https://cdn.example.test/1080.mp4")
        self.assertEqual(prepared["height"], 1080)

    def test_prepare_browser_dom_candidate_resolves_remote_api_url(self):
        page_url = "https://www.example-stream.test/watch/demo123"
        candidate = {
            "format_id": "browser-480",
            "url": "https://www.example-stream.test/media/mp4?s=token",
            "height": 480,
            "source": page_url,
        }
        payload = [
            {"quality": "480", "videoUrl": "https://cdn.example.test/480.mp4"},
            {"quality": "720", "videoUrl": "https://cdn.example.test/720.mp4"},
        ]

        with mock.patch.object(
            engine,
            "refresh_browser_dom_candidate_media",
            side_effect=lambda page_url, candidate, on_event=None: dict(candidate),
        ), mock.patch.object(engine, "fetch_json_via_browser", return_value=payload):
            prepared = engine.prepare_browser_dom_candidate(page_url, candidate)

        self.assertEqual(prepared["url"], "https://cdn.example.test/480.mp4")
        self.assertFalse(prepared["is_manifest"])

    def test_pick_refreshed_browser_dom_candidate_prefers_direct_mp4_over_remote_api(self):
        candidates = [
            {"height": 480, "url": "https://www.example.test/video/get_media?s=token", "is_manifest": False},
            {"height": 480, "url": "https://cdn.example.test/480.mp4", "is_manifest": False},
            {"height": 480, "url": "https://cdn.example.test/480/master.m3u8", "is_manifest": True},
        ]
        picked = engine._pick_refreshed_browser_dom_candidate(candidates, 480)
        self.assertEqual(picked["url"], "https://cdn.example.test/480.mp4")

    def test_prepare_browser_dom_candidate_refreshes_remote_api_to_manifest(self):
        page_url = "https://www.example-stream.test/view_video.php?viewkey=abc"
        candidate = {
            "format_id": "browser-480",
            "url": "https://www.example-stream.test/video/get_media?s=token",
            "height": 480,
            "source": page_url,
        }
        refreshed_dom = """
        <html><head><title>Refresh Video</title></head><body>
        <script>
        var flashvars = {"mediaDefinitions":[
          {"format":"mp4","videoUrl":"/video/get_media?s=new","remote":true},
          {"format":"hls","videoUrl":"https://cdn.example.test/480/master.m3u8","quality":"480","height":480}
        ]};
        </script>
        """ + ("<!-- padding -->" * 40)

        with mock.patch.object(engine, "fetch_dom_html_with_urllib", return_value=refreshed_dom), mock.patch.object(
            engine, "fetch_dom_for_fallback", return_value=refreshed_dom
        ):
            prepared = engine.prepare_browser_dom_candidate(page_url, candidate)

        self.assertEqual(prepared["url"], "https://cdn.example.test/480/master.m3u8")
        self.assertTrue(prepared["is_manifest"])

    def test_browser_dom_html_cache_is_reused_for_manifest_refresh(self):
        page_url = "https://www.example-stream.test/watch/cache-demo"
        cached_dom = """
        <html><body><video src="https://cdn.example.test/fresh/master.m3u8"></video></body></html>
        """ + ("<!-- padding -->" * 40)
        engine._BROWSER_DOM_HTML_CACHE.clear()
        engine.remember_browser_dom_html(page_url, cached_dom)
        candidate = {
            "format_id": "browser-hls",
            "url": "https://cdn.example.test/stale/master.m3u8",
            "is_manifest": True,
            "output_ext": "mp4",
        }

        with mock.patch.object(engine, "fetch_dom_for_fallback") as fetch_dom:
            refreshed = engine.refresh_browser_dom_candidate_media(page_url, dict(candidate))

        fetch_dom.assert_not_called()
        self.assertEqual(refreshed["url"], "https://cdn.example.test/fresh/master.m3u8")

    def test_emit_manifest_download_progress_includes_speed_and_eta(self):
        events = []

        def on_event(event):
            events.append(event)

        with mock.patch.object(engine.time, "monotonic", return_value=10.0):
            engine.emit_manifest_download_progress(
                on_event=on_event,
                current_sec=120,
                duration_sec=600,
                downloaded_bytes=50_000_000,
                total_bytes=250_000_000,
                started_at=0.0,
                last_bytes=40_000_000,
                last_emit_at=9.0,
            )
        self.assertEqual(events[-1]["type"], "progress")
        self.assertIn("ETA", events[-1].get("message") or "")
        self.assertIn("/s", events[-1].get("message") or "")
        self.assertIn("/s", events[-1].get("speed_text") or "")

    def test_probe_stream_duration_reads_ffprobe_output(self):
        with mock.patch.object(engine, "ffprobe_path", return_value="/usr/bin/ffprobe"), mock.patch.object(
            subprocess,
            "run",
            return_value=mock.Mock(stdout="777\n", returncode=0),
        ):
            duration = engine.probe_stream_duration("https://cdn.example.test/master.m3u8", {"referer": "https://example.test/"})

        self.assertEqual(duration, 777)

    def test_manifest_progress_total_bytes_caps_unstable_early_estimate(self):
        candidate = {"sort_bytes": 0, "duration": 600}
        self.assertEqual(engine.manifest_progress_total_bytes(candidate, 1_000_000, 10, 600), 0)
        capped = engine.manifest_progress_total_bytes(candidate, 1_000_000, 120, 600)
        self.assertLessEqual(capped, 16 * 1024 * 1024)
        self.assertGreater(capped, 1_000_000)

    def test_manifest_progress_total_bytes_uses_candidate_size_when_known(self):
        candidate = {"sort_bytes": 900_000, "duration": 120}
        self.assertEqual(engine.manifest_progress_total_bytes(candidate, 200_000, 10, 600), 900_000)

    def test_iter_hls_segment_urls_resolves_relative_paths(self):
        playlist = "\n".join(
            [
                "#EXTM3U",
                "#EXT-X-VERSION:3",
                "#EXTINF:2.0,",
                "seg-001.html",
                "#EXTINF:2.0,",
                "seg-002.html",
            ]
        )
        urls = engine.iter_hls_segment_urls(playlist, "https://cdn.example.test/stream/index.m3u8")
        self.assertEqual(
            urls,
            [
                "https://cdn.example.test/stream/seg-001.html",
                "https://cdn.example.test/stream/seg-002.html",
            ],
        )

    def test_browser_dom_hls_prefers_parallel_download_for_small_unencrypted_playlists(self):
        playlist = "#EXTM3U\n#EXTINF:1,\nseg.ts\n"
        segments = engine.iter_hls_segment_urls(playlist, "https://cdn.example.test/index.m3u8")
        candidate = {"url": "https://cdn.example.test/index.m3u8", "duration": 30, "sort_bytes": 800_000}
        self.assertTrue(engine.browser_dom_hls_prefers_parallel_download(candidate, playlist, segments))
        encrypted = "#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"key\"\n#EXTINF:1,\nseg.ts\n"
        self.assertFalse(engine.browser_dom_hls_prefers_parallel_download(candidate, encrypted, segments))

    def test_is_browser_dom_manifest_candidate_detects_hls_entries(self):
        self.assertTrue(
            engine.is_browser_dom_manifest_candidate(
                {"format_id": "browser-480", "url": "https://cdn.example.test/master.m3u8", "is_manifest": True}
            )
        )
        self.assertFalse(
            engine.is_browser_dom_manifest_candidate(
                {"format_id": "browser-480", "url": "https://cdn.example.test/video.mp4", "is_manifest": False}
            )
        )

    def test_browser_dom_download_pipeline_writes_file(self):
        sample_mp4 = "https://filesamples.com/samples/video/mp4/sample_640x360.mp4"
        html = f"""
        <html><head><title>Pipeline Video - Example</title></head><body>
        <script>
        var flashvars_1 = {{"video_duration":15,"mediaDefinitions":[
          {{"height":360,"format":"mp4","videoUrl":"{sample_mp4}","quality":"360"}}
        ]}};
        </script></body></html>
        """
        page_url = "https://www.example-stream.test/view_video.php?viewkey=pipeline"

        class FailYoutubeDL(FakeYoutubeDL):
            def extract_info(self, url, download=False):
                raise RuntimeError("curl: (35) TLS connect error")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = engine.analyze_url(
                page_url,
                ydl_factory=FailYoutubeDL,
                browser_dom_fetcher=lambda url, on_event=None: html,
            )
            candidate = result["candidates"][0]
            self.assertEqual(result["source"], "browser-dom")
            before = time.time()
            engine.download_candidate(page_url, candidate, temp_dir, cookie_source="없음")
            newest = engine.newest_file(temp_dir, "mp4", since=before - 2)
            self.assertTrue(newest and newest.exists())
            self.assertGreater(newest.stat().st_size, 100_000)

    def test_analyze_url_browser_fallback_keeps_site_title_duration_and_uploader(self):
        class ResetYoutubeDL(FakeYoutubeDL):
            def extract_info(self, url, download=False):
                raise RuntimeError("ConnectionResetError forcibly closed")

        html = """
        <html><head>
          <meta name="twitter:title" content="Weekend Vlog">
          <meta property="og:video:duration" content="245">
        </head><body>
        <div>From:&nbsp;<a href="/users/demo-creator"><span class="username">Demo Creator</span></a></div>
        <script>
        var flashvars_1 = {"video_duration":245,"mediaDefinitions":[
          {"height":1080,"format":"mp4","videoUrl":"https:\\/\\/cdn.example.test\\/1080\\/video.mp4","quality":"1080","filesize":104857600}
        ]};
        </script></body></html>
        """

        result = engine.analyze_url(
            "https://www.example-stream.test/view_video.php?viewkey=weekend",
            ydl_factory=ResetYoutubeDL,
            browser_dom_fetcher=lambda url, on_event=None: html,
        )

        candidate = result["candidates"][0]
        self.assertEqual(result["source"], "browser-dom")
        self.assertEqual(result["title"], "Demo Creator - Weekend Vlog")
        self.assertEqual(candidate["duration"], 245)
        self.assertEqual(candidate["sort_bytes"], 104_857_600)
        self.assertEqual(candidate["uploader"], "Demo Creator")

    def test_chzzk_clip_uid_is_detected(self):
        self.assertEqual(
            engine.find_chzzk_clip_uid("https://chzzk.naver.com/clips/qwr3h4r3Yn"),
            "qwr3h4r3Yn",
        )

    def test_chzzk_clip_analysis_prefixes_channel_and_uses_duration(self):
        original_detail = engine.chzzk_clip_detail
        original_card = engine.chzzk_shortform_card
        original_enrich = engine.enrich_missing_sizes
        try:
            engine.chzzk_clip_detail = lambda clip_uid: {
                "content": {
                    "clipTitle": "Clip Title",
                    "duration": 15,
                    "videoId": "video-id",
                    "recId": "rec-id",
                }
            }
            engine.chzzk_shortform_card = lambda clip_uid, video_id, rec_id: {
                "card": {"vod": {"BaseURL": ["https://cdn.example.test/clip.mp4"], "@width": 1280, "@height": 720}},
                "interaction": {"subscription": {"name": "독케익"}},
            }
            engine.enrich_missing_sizes = lambda candidates, *args, **kwargs: candidates

            result = engine.analyze_chzzk_clip("https://chzzk.naver.com/clips/z0DUTFaKDZ")

            self.assertEqual(result["title"], "독케익 - Clip Title")
            self.assertEqual(result["candidates"][0]["title"], "독케익 - Clip Title")
            self.assertEqual(result["candidates"][0]["duration"], 15)
        finally:
            engine.chzzk_clip_detail = original_detail
            engine.chzzk_shortform_card = original_card
            engine.enrich_missing_sizes = original_enrich

    def test_extract_chzzk_media_urls_reads_neonplayer_base_urls(self):
        payload = {
            "period": [
                {
                    "adaptationSet": [
                        {
                            "representation": [
                                {
                                    "width": 1920,
                                    "height": 1080,
                                    "bandwidth": 8202000,
                                    "frameRate": "60",
                                    "baseURL": [{"value": "https://cdn.example.test/video-1080.mp4"}],
                                }
                            ]
                        }
                    ]
                }
            ]
        }

        mp4_candidates, hls_candidates = engine.extract_chzzk_media_urls(payload)

        self.assertEqual(hls_candidates, [])
        self.assertEqual(mp4_candidates[0]["url"], "https://cdn.example.test/video-1080.mp4")
        self.assertEqual(mp4_candidates[0]["height"], 1080)
        self.assertEqual(mp4_candidates[0]["width"], 1920)
        self.assertEqual(mp4_candidates[0]["bandwidth"], 8202000)

    def test_chzzk_display_title_keeps_channel_separator_when_title_starts_with_channel(self):
        self.assertEqual(
            engine.chzzk_display_title("독케익 퇴근각", "독케익"),
            "독케익 - 퇴근각",
        )

    def test_chzzk_video_analysis_uses_neonplayer_playback(self):
        original_detail = getattr(engine, "chzzk_video_detail", None)
        original_playback = getattr(engine, "chzzk_video_playback", None)
        original_enrich = engine.enrich_missing_sizes
        try:
            engine.chzzk_video_detail = lambda video_no: {
                "content": {
                    "videoNo": 13929299,
                    "videoId": "video-id",
                    "inKey": "in-key",
                    "videoTitle": "Replay Title",
                    "duration": 6632,
                    "thumbnailImageUrl": "https://cdn.example.test/thumb.jpg",
                    "vodStatus": "ABR_HLS",
                    "channel": {"channelName": "독케익"},
                }
            }
            engine.chzzk_video_playback = lambda video_id, in_key, video_no: {
                "period": [
                    {
                        "adaptationSet": [
                            {
                                "representation": [
                                    {
                                        "width": 1920,
                                        "height": 1080,
                                        "bandwidth": 8202000,
                                        "frameRate": "60",
                                        "baseURL": [{"value": "https://cdn.example.test/replay.mp4"}],
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
            engine.enrich_missing_sizes = lambda candidates, *args, **kwargs: candidates

            result = engine.analyze_chzzk_video("https://chzzk.naver.com/video/13929299")

            self.assertEqual(result["title"], "독케익 - Replay Title")
            self.assertEqual(result["candidates"][0]["title"], "독케익 - Replay Title")
            self.assertEqual(result["candidates"][0]["duration"], 6632)
            self.assertEqual(result["candidates"][0]["url"], "https://cdn.example.test/replay.mp4")
            self.assertEqual(result["candidates"][0]["source"], "https://chzzk.naver.com/video/13929299")
        finally:
            if original_detail is None:
                delattr(engine, "chzzk_video_detail")
            else:
                engine.chzzk_video_detail = original_detail
            if original_playback is None:
                delattr(engine, "chzzk_video_playback")
            else:
                engine.chzzk_video_playback = original_playback
            engine.enrich_missing_sizes = original_enrich

    def test_download_candidate_uses_direct_http_for_chzzk_mp4_candidates(self):
        calls = []
        original_direct = getattr(engine, "download_direct_media", None)

        class FailingYDL:
            def __init__(self, options):
                raise AssertionError("yt-dlp should not run for CHZZK direct MP4 candidates")

        def fake_direct(url, candidate, output_dir, on_event=None):
            calls.append((url, candidate["title"], output_dir))
            output_path = Path(output_dir) / "독케익 - Clip.mp4"
            output_path.write_bytes(b"video")
            return {"ok": True, "output_dir": output_dir, "output_path": str(output_path), "target_url": url}

        try:
            engine.download_direct_media = fake_direct
            with tempfile.TemporaryDirectory() as temp:
                result = engine.download_candidate(
                    "https://chzzk.naver.com/clips/z0DUTFaKDZ",
                    {
                        "url": "https://cdn.example.test/clip.mp4",
                        "source": "https://chzzk.naver.com/clips/z0DUTFaKDZ",
                        "format_selector": "best",
                        "title": "독케익 - Clip",
                        "output_ext": "mp4",
                        "ext": "mp4",
                    },
                    temp,
                    ydl_factory=FailingYDL,
                )

            self.assertEqual(calls[0][0], "https://cdn.example.test/clip.mp4")
            self.assertTrue(result["output_path"].endswith("독케익 - Clip.mp4"))
        finally:
            if original_direct is None:
                delattr(engine, "download_direct_media")
            else:
                engine.download_direct_media = original_direct

    def test_download_candidate_uses_segment_download_for_clipped_chzzk_mp4_candidates(self):
        calls = []
        original_segment = getattr(engine, "download_direct_media_segment", None)
        original_direct = getattr(engine, "download_direct_media", None)

        class FailingYDL:
            def __init__(self, options):
                raise AssertionError("yt-dlp should not run for CHZZK direct MP4 segment candidates")

        def fake_segment(url, candidate, output_dir, on_event=None):
            calls.append((url, candidate.get("clip_range"), output_dir))
            output_path = Path(output_dir) / "독케익 - Clip [00m10s-00m20s].mp4"
            output_path.write_bytes(b"segment")
            return {"ok": True, "output_dir": output_dir, "output_path": str(output_path), "target_url": url}

        def fake_direct(*args, **kwargs):
            raise AssertionError("whole direct downloader should not run for clipped candidates")

        try:
            engine.download_direct_media_segment = fake_segment
            engine.download_direct_media = fake_direct
            with tempfile.TemporaryDirectory() as temp:
                result = engine.download_candidate(
                    "https://chzzk.naver.com/clips/z0DUTFaKDZ",
                    {
                        "url": "https://cdn.example.test/clip.mp4",
                        "source": "https://chzzk.naver.com/clips/z0DUTFaKDZ",
                        "format_selector": "best",
                        "title": "독케익 - Clip",
                        "output_ext": "mp4",
                        "ext": "mp4",
                        "clip_range": {"start": 10, "end": 20},
                    },
                    temp,
                    ydl_factory=FailingYDL,
                )

            self.assertEqual(calls[0][0], "https://cdn.example.test/clip.mp4")
            self.assertEqual(calls[0][1], {"start": 10, "end": 20})
            self.assertTrue(result["output_path"].endswith("[00m10s-00m20s].mp4"))
        finally:
            if original_segment is None:
                delattr(engine, "download_direct_media_segment")
            else:
                engine.download_direct_media_segment = original_segment
            if original_direct is None:
                delattr(engine, "download_direct_media")
            else:
                engine.download_direct_media = original_direct

    def test_download_direct_media_segment_uses_ffmpeg_and_replaces_part_file(self):
        events = []
        calls = []

        class FakeProcess:
            returncode = 0

            def __init__(self):
                self.stdout = iter(["out_time_ms=5000000\n", "progress=continue\n", "out_time_ms=10000000\n", "progress=end\n"])

            def wait(self, timeout=None):
                del timeout
                return self.returncode

            def communicate(self, timeout=None):
                del timeout
                return "", ""

        def fake_runner(command, **kwargs):
            calls.append((command, kwargs))
            Path(command[-1]).write_bytes(b"segment")
            return FakeProcess()

        with tempfile.TemporaryDirectory() as temp:
            result = engine.download_direct_media_segment(
                "https://cdn.example.test/clip.mp4",
                {
                    "title": "독케익 - Clip",
                    "output_ext": "mp4",
                    "ext": "mp4",
                    "source": "https://chzzk.naver.com/clips/z0DUTFaKDZ",
                    "clip_range": {"start": 10, "end": 20},
                },
                temp,
                on_event=events.append,
                ffmpeg_exe="ffmpeg-test",
                runner=fake_runner,
            )
            self.assertEqual(Path(result["output_path"]).read_bytes(), b"segment")
            self.assertFalse(Path(result["output_path"] + ".part").exists())

        command = calls[0][0]
        self.assertIn("-ss", command)
        self.assertIn("10.0", command)
        self.assertIn("-t", command)
        self.assertIn("10.0", command)
        self.assertIn("-c", command)
        self.assertEqual(command[command.index("-c") + 1], "copy")
        self.assertIn("-headers", command)
        format_index = command.index("-f")
        self.assertEqual(command[format_index + 1], "mp4")
        self.assertEqual(calls[0][1].get("creationflags"), engine._download_worker_creationflags())
        progress_events = [event for event in events if event.get("type") == "progress"]
        self.assertTrue(progress_events)
        self.assertEqual(progress_events[-1]["percent"], 100)
        self.assertTrue(any(event.get("type") == "file" and event.get("path") == result["output_path"] for event in events))

    def test_download_direct_media_segment_proxy_uses_original_source_size(self):
        calls = []
        proxy_totals = []
        original_popen = engine.subprocess.Popen
        original_range_supported = engine.direct_media_range_supported
        original_proxy = engine.direct_media_parallel_proxy_url

        class FakeProcess:
            returncode = 0

            def __init__(self, command):
                self.stdout = iter(["out_time_ms=10000000\n", "total_size=1000\n", "progress=end\n"])
                Path(command[-1]).write_bytes(b"segment")

            def wait(self, timeout=None):
                del timeout
                return self.returncode

            def communicate(self, timeout=None):
                del timeout
                return "", ""

        @contextlib.contextmanager
        def fake_proxy(url, headers, total, workers=None, part_size=None):
            del url, headers, workers, part_size
            proxy_totals.append(total)
            yield "http://127.0.0.1:9999/media"

        def fake_popen(command, **kwargs):
            calls.append(command)
            return FakeProcess(command)

        try:
            engine.direct_media_range_supported = lambda url, headers: True
            engine.direct_media_parallel_proxy_url = fake_proxy
            engine.subprocess.Popen = fake_popen
            with tempfile.TemporaryDirectory() as temp:
                engine.download_direct_media_segment(
                    "https://cdn.example.test/video.mp4",
                    {
                        "title": "Clip",
                        "output_ext": "mp4",
                        "source": "https://chzzk.naver.com/video/1",
                        "clip_range": {"start": 10, "end": 20},
                        "filesize_approx": 10 * 1024 * 1024,
                        "source_filesize": 100 * 1024 * 1024,
                    },
                    temp,
                    ffmpeg_exe="ffmpeg-test",
                )
        finally:
            engine.subprocess.Popen = original_popen
            engine.direct_media_range_supported = original_range_supported
            engine.direct_media_parallel_proxy_url = original_proxy

        self.assertEqual(proxy_totals, [100 * 1024 * 1024])
        self.assertIn("http://127.0.0.1:9999/media", calls[0])

    def test_download_direct_media_segment_accurate_mode_reencodes_for_keyframe_precise_cut(self):
        calls = []

        class FakeProcess:
            returncode = 0

            def __init__(self):
                self.stdout = iter(["out_time_ms=10000000\n", "progress=end\n"])

            def wait(self, timeout=None):
                del timeout
                return self.returncode

            def communicate(self, timeout=None):
                del timeout
                return "", ""

        def fake_runner(command, **kwargs):
            calls.append(command)
            Path(command[-1]).write_bytes(b"segment")
            return FakeProcess()

        with tempfile.TemporaryDirectory() as temp:
            engine.download_direct_media_segment(
                "https://cdn.example.test/clip.mp4",
                {
                    "title": "Clip",
                    "output_ext": "mp4",
                    "source": "https://chzzk.naver.com/clips/z0DUTFaKDZ",
                    "clip_range": {"start": 10, "end": 20},
                    "clip_cut_mode": "accurate",
                },
                temp,
                ffmpeg_exe="ffmpeg-test",
                runner=fake_runner,
            )

        command = calls[0]
        self.assertNotEqual(command[command.index("-c:v") + 1], "copy")
        self.assertIn("libx264", command)
        self.assertIn("-c:a", command)
        self.assertIn("aac", command)

    def test_download_direct_media_segment_no_progress_timeout_removes_part_file(self):
        class FakeProcess:
            returncode = 0

            def __init__(self, part_path):
                self.stdout = iter([])
                self.part_path = part_path
                Path(part_path).write_bytes(b"segment")
                self.killed = False

            def poll(self):
                return None

            def kill(self):
                self.killed = True

            def wait(self, timeout=None):
                del timeout
                return self.returncode

            def communicate(self, timeout=None):
                del timeout
                return "", ""

        processes = []

        def fake_runner(command, **kwargs):
            del kwargs
            process = FakeProcess(command[-1])
            processes.append(process)
            return process

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                engine.download_direct_media_segment(
                    "https://cdn.example.test/clip.mp4",
                    {
                        "title": "Clip",
                        "output_ext": "mp4",
                        "source": "https://chzzk.naver.com/clips/z0DUTFaKDZ",
                        "clip_range": {"start": 10, "end": 20},
                    },
                    temp,
                    ffmpeg_exe="ffmpeg-test",
                    runner=fake_runner,
                    no_progress_timeout=0,
                )
            self.assertTrue(processes[0].killed)
            self.assertFalse(any(Path(temp).glob("*.part")))

    def test_download_direct_media_segment_raises_when_ffmpeg_fails(self):
        class Completed:
            returncode = 1

            def __init__(self):
                self.stdout = iter([])
                self.stderr = "ffmpeg failed"

            def wait(self, timeout=None):
                del timeout
                return self.returncode

            def communicate(self, timeout=None):
                del timeout
                return "", "ffmpeg failed"

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "ffmpeg failed"):
                engine.download_direct_media_segment(
                    "https://cdn.example.test/clip.mp4",
                    {
                        "title": "Clip",
                        "output_ext": "mp4",
                        "source": "https://chzzk.naver.com/clips/z0DUTFaKDZ",
                        "clip_range": {"start": 10, "end": 20},
                    },
                    temp,
                    ffmpeg_exe="ffmpeg-test",
                    runner=lambda command, **kwargs: Completed(),
                )

    def test_direct_media_download_progress_includes_speed_text(self):
        events = []
        chunks = [b"a" * (512 * 1024), b"b" * (512 * 1024)]
        original_urlopen = engine.urllib.request.urlopen
        original_monotonic = engine.time.monotonic
        ticks = iter([10.0, 10.5, 10.5, 11.0, 11.0, 11.0])

        class FakeResponse:
            headers = {"Content-Length": str(sum(len(chunk) for chunk in chunks))}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size):
                del size
                return chunks.pop(0) if chunks else b""

        try:
            engine.urllib.request.urlopen = lambda request, timeout=30: FakeResponse()
            engine.time.monotonic = lambda: next(ticks)
            with tempfile.TemporaryDirectory() as temp:
                engine.download_direct_media(
                    "https://cdn.example.test/video.mp4",
                    {
                        "title": "Video",
                        "output_ext": "mp4",
                        "ext": "mp4",
                        "source": "https://chzzk.naver.com/video/1",
                    },
                    temp,
                    on_event=events.append,
                )
        finally:
            engine.urllib.request.urlopen = original_urlopen
            engine.time.monotonic = original_monotonic

        progress_events = [event for event in events if event.get("type") == "progress"]
        self.assertTrue(progress_events)
        self.assertTrue(progress_events[0].get("speed_text"))
        self.assertIn("/s", progress_events[0]["speed_text"])
        self.assertIn(progress_events[0]["speed_text"], progress_events[0]["message"])

    def test_direct_media_single_rejects_short_download_when_total_is_known(self):
        original_urlopen = engine.urllib.request.urlopen

        class FakeResponse:
            headers = {"Content-Length": str(1024 * 1024)}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size):
                del size
                if not hasattr(self, "sent"):
                    self.sent = True
                    return b"x" * 128
                return b""

        try:
            engine.urllib.request.urlopen = lambda request, timeout=30: FakeResponse()
            with tempfile.TemporaryDirectory() as temp:
                candidate = {
                    "title": "Video",
                    "output_ext": "mp4",
                    "ext": "mp4",
                    "sort_bytes": 1024 * 1024,
                    "source": "https://chzzk.naver.com/video/1",
                }
                with self.assertRaisesRegex(RuntimeError, "incomplete"):
                    engine.download_direct_media("https://cdn.example.test/video.mp4", candidate, temp)
                self.assertFalse((Path(temp) / "Video.mp4").exists())
        finally:
            engine.urllib.request.urlopen = original_urlopen

    def test_direct_media_single_resumes_existing_part_file(self):
        original_urlopen = engine.urllib.request.urlopen
        requested_ranges = []

        class FakeResponse:
            status = 206
            headers = {"Content-Length": "5"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size):
                del size
                if not hasattr(self, "sent"):
                    self.sent = True
                    return b"world"
                return b""

        def fake_urlopen(request, timeout=30):
            del timeout
            requested_ranges.append(request.get_header("Range"))
            return FakeResponse()

        try:
            engine.urllib.request.urlopen = fake_urlopen
            with tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "Video.mp4"
                output.with_name("Video.mp4.part").write_bytes(b"hello")
                part = engine.download_direct_media_single(
                    "https://cdn.example.test/video.mp4",
                    output,
                    {},
                    total=10,
                )
                self.assertEqual(part.read_bytes(), b"helloworld")
        finally:
            engine.urllib.request.urlopen = original_urlopen

        self.assertEqual(requested_ranges, ["bytes=5-"])

    def test_large_direct_media_download_uses_parallel_range_requests(self):
        content = bytes((index % 251 for index in range(1024 * 1024)))
        events = []
        ranges = []
        original_urlopen = engine.urllib.request.urlopen
        original_threshold = engine.DIRECT_MEDIA_PARALLEL_THRESHOLD
        original_part_size = engine.DIRECT_MEDIA_PARALLEL_PART_SIZE
        original_workers = engine.DIRECT_MEDIA_PARALLEL_WORKERS

        class FakeResponse:
            def __init__(self, payload, headers):
                self.payload = payload
                self.headers = headers
                self.offset = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size):
                if self.offset >= len(self.payload):
                    return b""
                chunk = self.payload[self.offset : self.offset + size]
                self.offset += len(chunk)
                return chunk

        def fake_urlopen(request, timeout=30):
            del timeout
            range_header = request.get_header("Range")
            if not range_header:
                return FakeResponse(content, {"Content-Length": str(len(content))})
            ranges.append(range_header)
            start_text, end_text = range_header.removeprefix("bytes=").split("-", 1)
            start = int(start_text)
            end = int(end_text)
            return FakeResponse(
                content[start : end + 1],
                {
                    "Content-Length": str(end - start + 1),
                    "Content-Range": f"bytes {start}-{end}/{len(content)}",
                },
            )

        try:
            engine.urllib.request.urlopen = fake_urlopen
            engine.DIRECT_MEDIA_PARALLEL_THRESHOLD = 1
            engine.DIRECT_MEDIA_PARALLEL_PART_SIZE = 256 * 1024
            engine.DIRECT_MEDIA_PARALLEL_WORKERS = 2
            with tempfile.TemporaryDirectory() as temp:
                result = engine.download_direct_media(
                    "https://cdn.example.test/video.mp4",
                    {
                        "title": "Video",
                        "output_ext": "mp4",
                        "ext": "mp4",
                        "sort_bytes": len(content),
                        "source": "https://chzzk.naver.com/video/1",
                    },
                    temp,
                    on_event=events.append,
                )
                self.assertEqual(Path(result["output_path"]).read_bytes(), content)
        finally:
            engine.urllib.request.urlopen = original_urlopen
            engine.DIRECT_MEDIA_PARALLEL_THRESHOLD = original_threshold
            engine.DIRECT_MEDIA_PARALLEL_PART_SIZE = original_part_size
            engine.DIRECT_MEDIA_PARALLEL_WORKERS = original_workers

        self.assertGreater(len(ranges), 1)
        self.assertTrue(all(value.startswith("bytes=") for value in ranges))
        self.assertTrue(any(event.get("type") == "progress" and event.get("speed_text") for event in events))

    def test_parallel_direct_media_resumes_existing_segment_part(self):
        content = b"abcdefghij"
        requested_ranges = []
        original_urlopen = engine.urllib.request.urlopen
        original_part_size = engine.DIRECT_MEDIA_PARALLEL_PART_SIZE
        original_workers = engine.DIRECT_MEDIA_PARALLEL_WORKERS

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload
                self.status = 206
                self.headers = {"Content-Length": str(len(payload))}
                self.offset = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size):
                if self.offset >= len(self.payload):
                    return b""
                chunk = self.payload[self.offset : self.offset + size]
                self.offset += len(chunk)
                return chunk

        def fake_urlopen(request, timeout=30):
            del timeout
            range_header = request.get_header("Range")
            requested_ranges.append(range_header)
            start_text, end_text = range_header.removeprefix("bytes=").split("-", 1)
            start = int(start_text)
            end = int(end_text)
            return FakeResponse(content[start : end + 1])

        try:
            engine.urllib.request.urlopen = fake_urlopen
            engine.DIRECT_MEDIA_PARALLEL_PART_SIZE = 5
            engine.DIRECT_MEDIA_PARALLEL_WORKERS = 1
            with tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "Video.mp4"
                part = output.with_name("Video.mp4.part")
                part.with_name("Video.mp4.part.0").write_bytes(b"abc")
                result = engine.download_direct_media_parallel(
                    "https://cdn.example.test/video.mp4",
                    output,
                    {},
                    len(content),
                )
                self.assertEqual(result.read_bytes(), content)
        finally:
            engine.urllib.request.urlopen = original_urlopen
            engine.DIRECT_MEDIA_PARALLEL_PART_SIZE = original_part_size
            engine.DIRECT_MEDIA_PARALLEL_WORKERS = original_workers

        self.assertIn("bytes=3-4", requested_ranges)

    def test_parallel_direct_media_falls_back_when_range_request_is_ignored(self):
        content = b"x" * (512 * 1024)
        events = []
        original_urlopen = engine.urllib.request.urlopen
        original_threshold = engine.DIRECT_MEDIA_PARALLEL_THRESHOLD
        original_part_size = engine.DIRECT_MEDIA_PARALLEL_PART_SIZE

        class FakeResponse:
            def __init__(self, payload, status):
                self.payload = payload
                self.status = status
                self.headers = {"Content-Length": str(len(payload))}
                self.offset = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size):
                if self.offset >= len(self.payload):
                    return b""
                chunk = self.payload[self.offset : self.offset + size]
                self.offset += len(chunk)
                return chunk

        def fake_urlopen(request, timeout=30):
            del timeout
            if request.get_header("Range"):
                return FakeResponse(b"", 200)
            return FakeResponse(content, 200)

        try:
            engine.urllib.request.urlopen = fake_urlopen
            engine.DIRECT_MEDIA_PARALLEL_THRESHOLD = 1
            engine.DIRECT_MEDIA_PARALLEL_PART_SIZE = 256 * 1024
            with tempfile.TemporaryDirectory() as temp:
                result = engine.download_direct_media(
                    "https://cdn.example.test/video.mp4",
                    {
                        "title": "Video",
                        "output_ext": "mp4",
                        "ext": "mp4",
                        "sort_bytes": len(content),
                        "source": "https://chzzk.naver.com/video/1",
                    },
                    temp,
                    on_event=events.append,
                )
                self.assertEqual(Path(result["output_path"]).read_bytes(), content)
        finally:
            engine.urllib.request.urlopen = original_urlopen
            engine.DIRECT_MEDIA_PARALLEL_THRESHOLD = original_threshold
            engine.DIRECT_MEDIA_PARALLEL_PART_SIZE = original_part_size

        self.assertTrue(
            any(
                event.get("type") == "status" and "retrying direct download" in event.get("message", "")
                for event in events
            )
        )

    def test_error_classification_uses_required_public_labels(self):
        self.assertEqual(engine.classify_error("DRM encrypted stream"), "DRM 가능성")
        self.assertEqual(engine.classify_error("ConnectionResetError forcibly closed"), "브라우저 지문/TLS 차단 가능성")
        self.assertEqual(engine.classify_error("HTTP Error 403 Forbidden"), "로그인/권한 필요")
        self.assertEqual(engine.classify_error("captcha required"), "네트워크/추출 오류")
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
