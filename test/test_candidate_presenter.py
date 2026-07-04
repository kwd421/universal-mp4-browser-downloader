import subprocess
import sys
import unittest

from tools import candidate_presenter as presenter


class CandidatePresenterTests(unittest.TestCase):
    def test_module_does_not_import_gui_toolkits(self):
        script = (
            "import sys; "
            "from tools import candidate_presenter; "
            "print('tkinter' in sys.modules); "
            "print('PySide6' in sys.modules)"
        )
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)

        self.assertEqual(result.stdout.splitlines(), ["False", "False"])

    def test_group_candidates_collapses_same_video_into_quality_list(self):
        candidates = [
            {"id": "1", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "720p", "height": 720, "sort_bytes": 20},
            {"id": "2", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "sort_bytes": 30},
            {"id": "3", "source": "other", "title": "Other", "display_title": "Other", "thumbnail": "t2", "ext": "mp4", "output_ext": "mp4", "resolution": "360p", "height": 360, "sort_bytes": 10},
        ]

        rows = presenter.group_candidates(candidates)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["candidate"]["resolution"], "1080p")
        self.assertEqual([candidate["resolution"] for candidate in rows[0]["qualities"]], ["1080p", "720p"])

    def test_group_candidates_prefers_hls_when_direct_same_quality_has_unknown_size(self):
        candidates = [
            {"id": "direct-720", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "720p", "height": 720, "sort_bytes": 0, "is_manifest": False, "protocol": "https", "note": "h264-720p - 720p"},
            {"id": "hls-720", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "1280x720", "height": 720, "sort_bytes": 333_000_000, "is_manifest": True, "protocol": "m3u8_native", "note": "hls-759-0 - 1280x720"},
            {"id": "hls-480", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "854x480", "height": 480, "sort_bytes": 138_000_000, "is_manifest": True, "protocol": "m3u8_native", "note": "hls-316-0 - 854x480"},
        ]

        rows = presenter.group_candidates(candidates)

        self.assertEqual([candidate["id"] for candidate in rows[0]["qualities"]], ["hls-720", "hls-480"])

    def test_group_candidates_prefers_h264_aac_over_av1_for_same_video_quality(self):
        candidates = [
            {"id": "hls-av1", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "1280x720", "height": 720, "sort_bytes": 194_000, "is_manifest": True, "vcodec": "av1", "acodec": "unknown", "note": "hls-402-1 - 1280x720"},
            {"id": "hls-h264", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "1280x720", "height": 720, "sort_bytes": 190_000, "is_manifest": True, "vcodec": "avc1.4d401f", "acodec": "mp4a.40.2", "note": "hls-759-1 - 1280x720"},
        ]

        rows = presenter.group_candidates(candidates)

        self.assertEqual([candidate["id"] for candidate in rows[0]["qualities"]], ["hls-h264"])

    def test_group_candidates_keeps_one_quality_per_resolution_when_formats_look_identical(self):
        candidates = [
            {"id": "small-1080", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "fps": 30, "sort_bytes": 40},
            {"id": "large-1080", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "fps": 30, "sort_bytes": 80},
            {"id": "720", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "ext": "mp4", "output_ext": "mp4", "resolution": "720p", "height": 720, "fps": 30, "sort_bytes": 20},
        ]

        rows = presenter.group_candidates(candidates)

        self.assertEqual([candidate["id"] for candidate in rows[0]["qualities"]], ["large-1080", "720"])

    def test_wav_quality_label_does_not_show_resolution(self):
        label = presenter.quality_label({"output_ext": "wav", "ext": "wav", "media_type": "audio", "sort_bytes": 1000, "note": "audio"})

        self.assertIn("WAV", label)
        self.assertNotIn("p", label.lower())

    def test_select_candidate_auto_prefers_sized_unknown_height_over_low_labeled_stream(self):
        candidates = [
            {
                "id": "browser-240",
                "output_ext": "mp4",
                "height": 240,
                "sort_bytes": 0,
                "url": "https://cdn.example.test/240p.h264.mp4",
                "is_manifest": False,
            },
            {
                "id": "browser-html-video",
                "output_ext": "mp4",
                "height": 0,
                "sort_bytes": 2_463_314,
                "url": "https://cdn.example.test/preview.mp4",
                "is_manifest": False,
            },
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="자동", output_format="자동", codec="자동"),
        )

        self.assertEqual(selected["id"], "browser-html-video")

    def test_select_candidate_auto_quality_and_frame_prefers_best_available(self):
        candidates = [
            {"id": "1080-30", "output_ext": "mp4", "height": 1080, "fps": 30, "vcodec": "avc1", "sort_bytes": 100},
            {"id": "1080-60", "output_ext": "mp4", "height": 1080, "fps": 60, "vcodec": "avc1", "sort_bytes": 120},
            {"id": "720-60", "output_ext": "mp4", "height": 720, "fps": 60, "vcodec": "avc1", "sort_bytes": 90},
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="자동", output_format="MP4", codec="자동", frame_rate="자동"),
        )

        self.assertEqual(selected["id"], "1080-60")

    def test_select_candidate_auto_format_prefers_best_mp4_video_candidate(self):
        candidates = [
            {"id": "mp4-1080", "output_ext": "mp4", "height": 1080, "fps": 30, "vcodec": "avc1", "sort_bytes": 200},
            {"id": "webm-1440", "output_ext": "webm", "height": 1440, "fps": 30, "vcodec": "vp9", "sort_bytes": 240},
            {"id": "audio", "media_type": "audio", "output_ext": "mp3", "height": 0, "fps": 0, "vcodec": "none", "sort_bytes": 20},
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="자동", output_format="자동", codec="자동", frame_rate="자동"),
        )

        self.assertEqual(selected["id"], "mp4-1080")

    def test_select_candidate_auto_quality_and_codec_prefers_highest_resolution(self):
        candidates = [
            {"id": "mp4-av1-2160", "output_ext": "mp4", "height": 2160, "fps": 30, "vcodec": "av01", "acodec": "none", "sort_bytes": 300},
            {"id": "mp4-h264-1080", "output_ext": "mp4", "height": 1080, "fps": 30, "vcodec": "avc1.640028", "acodec": "mp4a.40.2", "sort_bytes": 200},
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="자동", output_format="자동", codec="자동", frame_rate="자동"),
        )

        self.assertEqual(selected["id"], "mp4-av1-2160")

    def test_select_candidate_codec_preference_can_choose_lower_resolution_match(self):
        candidates = [
            {"id": "mp4-av1-2160", "output_ext": "mp4", "height": 2160, "fps": 30, "vcodec": "av01", "acodec": "none", "sort_bytes": 300},
            {"id": "mp4-h264-1080", "output_ext": "mp4", "height": 1080, "fps": 30, "vcodec": "avc1.640028", "acodec": "mp4a.40.2", "sort_bytes": 200},
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="자동", output_format="자동", codec="H264", frame_rate="자동"),
        )

        self.assertEqual(selected["id"], "mp4-h264-1080")

    def test_select_candidate_hdr_off_filters_hdr_candidates(self):
        candidates = [
            {"id": "hdr-2160", "output_ext": "mp4", "height": 2160, "fps": 30, "vcodec": "avc1", "dynamic_range": "HDR10", "sort_bytes": 300},
            {"id": "sdr-1080", "output_ext": "mp4", "height": 1080, "fps": 30, "vcodec": "avc1", "dynamic_range": "SDR", "sort_bytes": 200},
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="자동", output_format="자동", codec="자동", frame_rate="자동", hdr="끔"),
        )

        self.assertEqual(selected["id"], "sdr-1080")

    def test_select_candidate_hdr_on_allows_hdr_candidates(self):
        candidates = [
            {"id": "hdr-2160", "output_ext": "mp4", "height": 2160, "fps": 30, "vcodec": "avc1", "dynamic_range": "HDR10", "sort_bytes": 300},
            {"id": "sdr-1080", "output_ext": "mp4", "height": 1080, "fps": 30, "vcodec": "avc1", "dynamic_range": "SDR", "sort_bytes": 200},
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="자동", output_format="자동", codec="자동", frame_rate="자동", hdr="켬"),
        )

        self.assertEqual(selected["id"], "hdr-2160")

    def test_select_candidate_hdr_on_falls_back_to_sdr_when_hdr_missing(self):
        candidates = [
            {"id": "sdr-2160", "output_ext": "mp4", "height": 2160, "fps": 30, "vcodec": "avc1", "dynamic_range": "SDR", "sort_bytes": 300},
            {"id": "sdr-1080", "output_ext": "mp4", "height": 1080, "fps": 30, "vcodec": "avc1", "dynamic_range": "SDR", "sort_bytes": 200},
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="자동", output_format="자동", codec="자동", frame_rate="자동", hdr="켬"),
        )

        self.assertEqual(selected["id"], "sdr-2160")

    def test_select_candidate_auto_prefers_remote_mp4_api_over_hls_manifest(self):
        candidates = [
            {
                "id": "browser-hls",
                "output_ext": "mp4",
                "height": 0,
                "sort_bytes": 0,
                "is_manifest": True,
                "url": "https://www.example-stream.test/media/hls?s=token",
            },
            {
                "id": "browser-mp4",
                "output_ext": "mp4",
                "height": 0,
                "sort_bytes": 0,
                "is_manifest": False,
                "url": "https://www.example-stream.test/media/mp4?s=token",
            },
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="자동", output_format="자동", codec="자동", frame_rate="자동"),
        )

        self.assertEqual(selected["id"], "browser-mp4")

    def test_select_candidate_prefers_direct_https_over_manifest_at_same_quality(self):
        candidates = [
            {"id": "hls-1080", "output_ext": "mp4", "height": 1080, "fps": 30, "vcodec": "avc1.640028", "acodec": "mp4a.40.2", "sort_bytes": 50_000_000, "is_manifest": True, "protocol": "m3u8_native"},
            {"id": "direct-1080", "output_ext": "mp4", "height": 1080, "fps": 30, "vcodec": "avc1.640028", "acodec": "mp4a.40.2", "sort_bytes": 40_000_000, "is_manifest": False, "protocol": "https"},
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="1080p", output_format="MP4", codec="?먮룞", frame_rate="?먮룞"),
        )

        self.assertEqual(selected["id"], "direct-1080")

    def test_select_candidate_prefers_hls_over_risky_youtube_direct_format(self):
        candidates = [
            {"id": "hls-1080", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "output_ext": "mp4", "height": 1080, "fps": 60, "vcodec": "avc1.640028", "acodec": "mp4a.40.2", "sort_bytes": 466_000_000, "is_manifest": True, "protocol": "m3u8_native"},
            {"id": "direct-1080", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "output_ext": "mp4", "height": 1080, "fps": 60, "vcodec": "avc1.640028", "acodec": "bestaudio", "sort_bytes": 133_000_000, "is_manifest": False, "protocol": "https", "download_risk": "youtube_tv_https_po_token"},
        ]

        rows = presenter.group_candidates(candidates)
        selected = presenter.select_candidate_for_preferences(
            rows[0]["qualities"],
            presenter.DownloadPreferences(quality="1080p", output_format="MP4", codec="?먮룞", frame_rate="?먮룞"),
        )

        self.assertEqual([candidate["id"] for candidate in rows[0]["qualities"]], ["hls-1080"])
        self.assertEqual(selected["id"], "hls-1080")

    def test_group_candidates_defaults_to_downloadable_candidate_over_risky_direct(self):
        candidates = [
            {"id": "direct-2160", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "output_ext": "mp4", "height": 2160, "fps": 60, "vcodec": "vp9", "sort_bytes": 500_000_000, "is_manifest": False, "protocol": "https", "download_risk": "youtube_tv_https_po_token"},
            {"id": "hls-1080", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "output_ext": "mp4", "height": 1080, "fps": 60, "vcodec": "avc1.640028", "acodec": "mp4a.40.2", "sort_bytes": 300_000_000, "is_manifest": True, "protocol": "m3u8_native"},
        ]

        rows = presenter.group_candidates(candidates)

        self.assertEqual(rows[0]["candidate"]["id"], "hls-1080")

    def test_group_candidates_dedupes_same_quality_using_downloadability(self):
        candidates = [
            {"id": "direct-1080", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "output_ext": "mp4", "height": 1080, "fps": 60, "vcodec": "avc1.640028", "acodec": "bestaudio", "sort_bytes": 900_000_000, "is_manifest": False, "protocol": "https", "download_risk": "youtube_tv_https_po_token"},
            {"id": "hls-1080", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "output_ext": "mp4", "height": 1080, "fps": 60, "vcodec": "avc1.640028", "acodec": "mp4a.40.2", "sort_bytes": 300_000_000, "is_manifest": True, "protocol": "m3u8_native"},
        ]

        rows = presenter.group_candidates(candidates)

        self.assertEqual(rows[0]["candidate"]["id"], "hls-1080")
        self.assertEqual([candidate["id"] for candidate in rows[0]["qualities"]], ["hls-1080"])

    def test_select_candidate_uses_same_family_format_fallback(self):
        candidates = [
            {"id": "webm", "output_ext": "webm", "height": 1080, "fps": 30, "vcodec": "vp9", "sort_bytes": 100},
            {"id": "audio", "media_type": "audio", "output_ext": "wav", "height": 0, "fps": 0, "vcodec": "none", "sort_bytes": 200},
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="1080p", output_format="MP4", codec="자동", frame_rate="자동"),
        )

        self.assertEqual(selected["id"], "webm")

    def test_select_candidate_never_falls_between_video_and_audio_families(self):
        candidates = [
            {"id": "audio", "media_type": "audio", "output_ext": "wav", "height": 0, "fps": 0, "vcodec": "none", "sort_bytes": 200},
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="자동", output_format="MP4", codec="자동", frame_rate="자동"),
        )

        self.assertIsNone(selected)

    def test_grouped_video_keeps_audio_variants_for_global_preferences(self):
        candidates = [
            {"id": "video", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "output_ext": "mp4", "height": 1080, "fps": 30, "vcodec": "avc1", "sort_bytes": 100},
            {"id": "audio", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "media_type": "audio", "output_ext": "mp3", "height": 0, "fps": 0, "vcodec": "none", "sort_bytes": 20},
        ]

        rows = presenter.group_candidates(candidates)
        selected = presenter.select_candidate_for_preferences(
            rows[0]["qualities"],
            presenter.DownloadPreferences(quality="자동", output_format="MP3", codec="자동", frame_rate="자동"),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(selected["id"], "audio")

    def test_audio_candidates_do_not_hide_manifest_video_candidates(self):
        candidates = [
            {"id": "hls-1080", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "output_ext": "mp4", "height": 1080, "fps": 30, "vcodec": "avc1", "sort_bytes": 0, "is_manifest": True, "protocol": "m3u8_native"},
            {"id": "audio-mp3", "source": "s", "title": "Video", "display_title": "Video", "thumbnail": "t", "media_type": "audio", "output_ext": "mp3", "height": 0, "fps": 0, "vcodec": "none", "sort_bytes": 20},
        ]

        rows = presenter.group_candidates(candidates)
        selected_video = presenter.select_candidate_for_preferences(
            rows[0]["qualities"],
            presenter.DownloadPreferences(quality="자동", output_format="MP4", codec="자동", frame_rate="자동"),
        )

        self.assertEqual([candidate["id"] for candidate in rows[0]["qualities"]], ["hls-1080", "audio-mp3"])
        self.assertEqual(selected_video["id"], "hls-1080")

    def test_video_preferences_do_not_fallback_to_unlisted_video_formats(self):
        candidates = [
            {"id": "mkv", "output_ext": "mkv", "height": 1080, "fps": 30, "vcodec": "avc1", "sort_bytes": 100},
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="자동", output_format="MP4", codec="자동", frame_rate="자동"),
        )

        self.assertIsNone(selected)

    def test_select_candidate_specific_quality_ignores_unknown_height_for_target_filter(self):
        candidates = [
            {"id": "known-1080", "output_ext": "mp4", "height": 1080, "fps": 30, "vcodec": "avc1", "sort_bytes": 100},
            {"id": "unknown", "output_ext": "mp4", "height": 0, "fps": 30, "vcodec": "avc1", "sort_bytes": 200},
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="720p", output_format="MP4", codec="자동", frame_rate="자동"),
        )

        self.assertEqual(selected["id"], "known-1080")

    def test_select_candidate_specific_quality_uses_nearest_lower_then_best_same_family(self):
        candidates = [
            {"id": "1440", "output_ext": "mp4", "height": 1440, "fps": 30, "vcodec": "avc1", "sort_bytes": 200},
            {"id": "720", "output_ext": "mp4", "height": 720, "fps": 30, "vcodec": "avc1", "sort_bytes": 100},
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="1080p", output_format="MP4", codec="자동", frame_rate="자동"),
        )
        fallback = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="360p", output_format="MP4", codec="자동", frame_rate="자동"),
        )

        self.assertEqual(selected["id"], "720")
        self.assertEqual(fallback["id"], "1440")

    def test_select_candidate_codec_prefers_exact_match_then_falls_back(self):
        candidates = [
            {"id": "vp9", "output_ext": "webm", "height": 1080, "fps": 30, "vcodec": "vp9", "sort_bytes": 100},
            {"id": "av1", "output_ext": "webm", "height": 1080, "fps": 30, "vcodec": "av01", "sort_bytes": 90},
        ]

        selected = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="자동", output_format="WEBM", codec="AV1", frame_rate="자동"),
        )
        fallback = presenter.select_candidate_for_preferences(
            candidates,
            presenter.DownloadPreferences(quality="자동", output_format="WEBM", codec="H264", frame_rate="자동"),
        )

        self.assertEqual(selected["id"], "av1")
        self.assertEqual(fallback["id"], "vp9")


if __name__ == "__main__":
    unittest.main()
