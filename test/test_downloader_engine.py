import concurrent.futures
import contextlib
import io
import json
import time
import unittest
import tempfile
import sys
from pathlib import Path

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
        self.assertFalse(engine.looks_like_playlist_url("https://video.example/watch?v=one"))

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

    def test_chzzk_clip_uid_is_detected(self):
        self.assertEqual(
            engine.find_chzzk_clip_uid("https://chzzk.naver.com/clips/qwr3h4r3Yn"),
            "qwr3h4r3Yn",
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
