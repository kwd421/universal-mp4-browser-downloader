import os
import sys
import unittest
from unittest import mock

from tools import clipflow_updater as updater


class ClipFlowUpdaterTests(unittest.TestCase):
    def test_updater_feed_url_prefers_platform_specific_env_on_windows(self):
        with mock.patch.object(updater.sys, "platform", "win32"):
            with mock.patch.dict(
                os.environ,
                {
                    "CLIPFLOW_WINSPARKLE_FEED_URL": "https://example.test/windows.xml",
                    "CLIPFLOW_SPARKLE_FEED_URL": "https://example.test/macos.xml",
                },
                clear=False,
            ):
                self.assertEqual(updater.updater_feed_url(), "https://example.test/windows.xml")

    def test_updater_feed_url_uses_sparkle_env_on_macos(self):
        with mock.patch.object(updater.sys, "platform", "darwin"):
            with mock.patch.dict(
                os.environ,
                {
                    "CLIPFLOW_WINSPARKLE_FEED_URL": "https://example.test/windows.xml",
                    "CLIPFLOW_SPARKLE_FEED_URL": "https://example.test/macos.xml",
                },
                clear=False,
            ):
                self.assertEqual(updater.updater_feed_url(), "https://example.test/macos.xml")

    def test_updater_configured_reads_baked_values_in_frozen_build(self):
        baked = mock.Mock(
            FEED_URL="https://example.test/windows.xml",
            PUBLIC_ED_KEY="abc123",
            VERSION="1.2.3",
            BUILD_NUMBER="123",
        )
        with mock.patch.object(updater.sys, "frozen", True, create=True):
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(updater, "_frozen_build_config", return_value=baked):
                    self.assertTrue(updater.updater_configured())
                    self.assertEqual(updater.updater_feed_url(), "https://example.test/windows.xml")
                    self.assertEqual(updater.updater_public_ed_key(), "abc123")
                    self.assertEqual(updater.updater_app_version(), "1.2.3")
                    self.assertEqual(updater.updater_build_number(), "123")

    def test_updater_configured_requires_feed_url(self):
        with mock.patch.object(updater.sys, "platform", "win32"):
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(updater, "_frozen_build_value", return_value=""):
                    self.assertTrue(updater.updater_configured())
        with mock.patch.dict(
            os.environ,
            {
                "CLIPFLOW_WINSPARKLE_FEED_URL": "https://example.test/windows.xml",
                "CLIPFLOW_SPARKLE_PUBLIC_ED_KEY": "abc123",
            },
            clear=False,
        ):
            self.assertTrue(updater.updater_configured())
            self.assertTrue(updater.winsparkle_installer_ready())

    def test_startup_update_is_available_uses_feed_fallbacks(self):
        with mock.patch.object(updater, "updater_feed_url", return_value=""), mock.patch.object(
            updater, "_latest_appcast_build_number", side_effect=[Exception("pages down"), 105]
        ), mock.patch.object(updater, "updater_build_number", return_value="104"):
            self.assertTrue(updater.startup_update_is_available())

    def test_start_winsparkle_updater_returns_http_checker_without_installer_key(self):
        baked = mock.Mock(
            FEED_URL="https://example.test/windows.xml",
            PUBLIC_ED_KEY="",
            VERSION="1.0.4",
            BUILD_NUMBER="104",
        )
        with mock.patch.object(updater.sys, "frozen", True, create=True), mock.patch.object(
            updater.sys, "platform", "win32"
        ), mock.patch.object(updater, "_frozen_build_config", return_value=baked), mock.patch.object(
            updater, "_load_winsparkle_library", return_value=None
        ):
            instance = updater.start_winsparkle_updater()
        self.assertIsNotNone(instance)
        self.assertIsNone(instance._library)

    def test_start_app_updater_returns_none_in_dev_mode(self):
        with mock.patch.object(updater.sys, "frozen", False, create=True):
            self.assertIsNone(updater.start_app_updater())

    def test_start_winsparkle_updater_requires_frozen_build(self):
        with mock.patch.object(updater.sys, "frozen", False, create=True):
            self.assertIsNone(updater.start_winsparkle_updater())

    def test_latest_appcast_build_number_reads_first_item(self):
        xml = (
            b'<?xml version="1.0"?>'
            b'<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">'
            b"<channel><item><sparkle:version>104</sparkle:version></item></channel></rss>"
        )
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.side_effect = [xml, b""]
            self.assertEqual(
                updater._latest_appcast_build_number("https://example.test/appcast.xml"),
                104,
            )

    def test_winsparkle_updater_schedule_startup_check_notifies_when_appcast_is_newer(self):
        library = mock.Mock()
        instance = updater.WinSparkleUpdater(library)
        seen = []

        def run_worker_immediately(target=None, daemon=None, name=None):
            target()
            return mock.Mock()

        on_found = lambda: seen.append(True)
        with mock.patch.object(updater, "startup_update_is_available", return_value=True), mock.patch.object(
            updater, "_dispatch_to_main_thread", side_effect=lambda callback: callback()
        ), mock.patch.object(updater.threading, "Thread", side_effect=run_worker_immediately):
            instance.schedule_startup_check(on_found)

        self.assertEqual(seen, [True])
        self.assertIs(instance._on_found, on_found)


if __name__ == "__main__":
    unittest.main()