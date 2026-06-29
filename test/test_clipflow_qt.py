import os
import subprocess
import sys
import tempfile
import unittest
import uuid


def run_qt_script(script, timeout=10):
    settings_app = f"ClipFlowTest{uuid.uuid4().hex}"
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "CLIPFLOW_SETTINGS_APP": settings_app}
    with tempfile.TemporaryDirectory() as settings_dir:
        isolated_script = (
            "import atexit, os\n"
            "from PySide6.QtCore import QSettings\n"
            "QSettings.setDefaultFormat(QSettings.IniFormat)\n"
            f"QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, {settings_dir!r})\n"
            f"QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, {settings_dir!r})\n"
            "atexit.register(lambda: QSettings(os.environ.get('CLIPFLOW_SETTINGS_ORG', 'ClipFlow'), os.environ.get('CLIPFLOW_SETTINGS_APP', 'ClipFlow')).clear())\n"
            + script
        )
        return subprocess.run(
            [sys.executable, "-c", isolated_script],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )


class ClipFlowQtTests(unittest.TestCase):
    def test_clipflow_qt_split_modules_import(self):
        script = r'''
from tools.clipflow_theme import APP_NAME, APP_STYLE, configure_app_font, create_app_icon
from tools.clipflow_widgets import CleanComboBox, PathDisplayInput
from tools.clipflow_rows import DownloadRowWidget, build_quality_options
from tools.clipflow_qt import ClipFlowWindow

print(APP_NAME)
print(bool(APP_STYLE))
print(callable(configure_app_font))
print(callable(create_app_icon))
print(CleanComboBox.__name__)
print(PathDisplayInput.__name__)
print(DownloadRowWidget.__name__)
print(callable(build_quality_options))
print(ClipFlowWindow.__name__)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "ClipFlow",
                "True",
                "True",
                "True",
                "CleanComboBox",
                "PathDisplayInput",
                "DownloadRowWidget",
                "True",
                "ClipFlowWindow",
            ],
        )

    def test_clipflow_qt_uses_bundled_lucide_icons(self):
        script = r'''
import tools.clipflow_widgets as widgets
from PySide6.QtWidgets import QApplication
from tools.clipflow_icons import LUCIDE_ICON_DIR, LucideIconButton, LucideIconWidget, icon_path

app = QApplication([])
required = ["link", "folder", "x", "trash-2", "more-vertical", "clock", "file-text", "circle-help", "chevron-down", "play", "video", "cookie", "sliders-horizontal", "arrow-down-wide-narrow", "arrow-up-narrow-wide", "circle-x", "globe-2"]
print(LUCIDE_ICON_DIR.name)
print(all(icon_path(name).is_file() for name in required))
print(hasattr(widgets, "LineIcon"))
print(hasattr(widgets, "ActionIconButton"))
print(hasattr(widgets, "ThumbnailBox"))
print(LucideIconWidget("folder").icon_name)
print(LucideIconButton("folder").icon_name)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["lucide", "True", "False", "False", "False", "folder", "folder"],
        )

    def test_clipflow_qt_discovers_favicon_links_from_html(self):
        script = r'''
from tools.clipflow_widgets import default_favicon_urls, favicon_urls_from_html

html = """
<link rel="stylesheet" href="/site.css">
<link rel="icon" href="/assets/icon.svg">
<link rel="apple-touch-icon" href="touch.png">
<link href="https://cdn.example.test/icon.png" rel="shortcut icon">
<link rel="icon">
"""
print("|".join(favicon_urls_from_html(html, "https://media.example.test/posts/1")))
print("|".join(default_favicon_urls("https://www.media.example.test/posts/1")))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "https://media.example.test/assets/icon.svg|https://media.example.test/posts/touch.png|https://cdn.example.test/icon.png",
                "https://www.media.example.test/favicon.ico|https://www.media.example.test/favicon.png|https://www.media.example.test/apple-touch-icon.png",
            ],
        )

    def test_clipflow_qt_smoke_launches_offscreen(self):
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "CLIPFLOW_QT_SMOKE": "1"}
        result = subprocess.run(
            [sys.executable, "tools/clipflow_qt.py"],
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ClipFlow smoke launch OK", result.stdout)

    def test_clipflow_qt_polished_shell_removes_format_and_log_controls(self):
        script = r'''
from PySide6.QtWidgets import QApplication, QFrame
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
print(hasattr(window, "format_combo"))
print(hasattr(window, "log_output"))
print(hasattr(window, "progress"))
print(window.primary_button.text())
print(window.cookie_combo.itemText(0))
print(hasattr(window, "cookie_help_button"))
print(hasattr(window, "preference_button"))
print(bool(window.cookie_combo.toolTip()))
print(hasattr(window, "row_container"))
print("Noto Sans KR" in window.styleSheet())
print(len(window.findChildren(QFrame, "HeaderBar")))
print(window.windowIcon().isNull())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "False",
                "False",
                "False",
                "",
                "쿠키 미사용",
                "False",
                "True",
                "True",
                "True",
                "True",
                "0",
                "False",
            ],
        )

    def test_clipflow_qt_global_download_preferences_drive_selected_candidate(self):
        script = r'''
from PySide6.QtCore import QTimer
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, SETTINGS_APP, SETTINGS_ORG
import tempfile

downloaded = []
analyze_exts = []
started_download = []

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    analyze_exts.append(output_ext)
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "webm-1080", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "webm", "output_ext": "webm", "resolution": "1080p", "height": 1080, "fps": 60, "duration": 120, "sort_bytes": 40, "vcodec": "vp9"},
            {"id": "mp4-720", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "720p", "height": 720, "fps": 30, "duration": 120, "sort_bytes": 20, "vcodec": "avc1"},
        ],
        "warnings": [],
    }

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    downloaded.append(candidate["id"])
    return {"ok": True, "output_dir": output_dir}

app = QApplication([])
settings_dir = tempfile.TemporaryDirectory()
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, settings_dir.name)
QSettings(SETTINGS_ORG, SETTINGS_APP).clear()
window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
print(window.current_preferences().quality)
print(window.current_preferences().output_format)
print(window.current_preferences().codec)
print(window.current_preferences().frame_rate)
window._set_preferences(output_format="WEBM")
window.url_input.setText("https://media.test/video")
window._start_analysis()

def drive():
    if window.analysis_thread or window.download_thread:
        return
    if window.rows and not started_download:
        started_download.append(True)
        row_widget = window.rows[0]["widget"]
        print(analyze_exts)
        print(window.current_preferences().output_format)
        print(window.selected_candidate_for_row_ref(window.rows[0])["id"])
        print(row_widget.size_label.text())
        print(row_widget.info_label.text())
        window.select_row(0)
        window._handle_primary_action()
        return
    if downloaded:
        print(downloaded[0])
        settings_dir.cleanup()
        app.quit()

timer = QTimer()
timer.timeout.connect(drive)
timer.start(20)
QTimer.singleShot(5000, app.quit)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["자동", "자동", "자동", "자동", "['all']", "WEBM", "webm-1080", "40 B", "00:02:00", "webm-1080"],
        )

    def test_clipflow_qt_audio_format_disables_codec_and_frame_preferences(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
dialog = window._create_preferences_dialog()
dialog.format_combo.setCurrentText("MP3")
dialog.refresh_controls()
print(dialog.codec_combo.isEnabled())
print(dialog.frame_combo.isEnabled())
dialog.format_combo.setCurrentText("MP4")
dialog.refresh_controls()
print(dialog.codec_combo.isEnabled())
print(dialog.frame_combo.isEnabled())
print(window.cookie_combo.maximumWidth() <= 142)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "False", "True", "True", "True"])

    def test_clipflow_qt_download_preferences_persist_with_qsettings(self):
        script = r'''
import tempfile
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, SETTINGS_APP, SETTINGS_ORG

settings_dir = tempfile.TemporaryDirectory()
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, settings_dir.name)
QSettings(SETTINGS_ORG, SETTINGS_APP).clear()

app = QApplication([])
window = ClipFlowWindow()
window._set_preferences(quality="720p", output_format="WEBM", codec="VP9", frame_rate="60fps")
second = ClipFlowWindow()

print(second.current_preferences().quality)
print(second.current_preferences().output_format)
print(second.current_preferences().codec)
print(second.current_preferences().frame_rate)
settings_dir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["720p", "WEBM", "VP9", "60fps"])

    def test_clipflow_qt_cookie_selection_persists_with_qsettings(self):
        script = r'''
import tempfile
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, SETTINGS_APP, SETTINGS_ORG

settings_dir = tempfile.TemporaryDirectory()
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, settings_dir.name)
QSettings(SETTINGS_ORG, SETTINGS_APP).clear()

app = QApplication([])
window = ClipFlowWindow()
window.cookie_combo.setCurrentText("Firefox")
second = ClipFlowWindow()

print(second.cookie_combo.currentText())
settings_dir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["Firefox"])

    def test_clipflow_qt_completed_download_history_persists_until_removed(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, SETTINGS_APP, SETTINGS_ORG

settings_dir = tempfile.TemporaryDirectory()
download_dir = tempfile.TemporaryDirectory()
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, settings_dir.name)
QSettings(SETTINGS_ORG, SETTINGS_APP).clear()

url = "https://media.test/watch/1"
output = Path(download_dir.name) / "Saved.mp4"
output.write_bytes(b"mp4")

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze)
window._set_save_folder(download_dir.name)
window._analysis_finished(fake_analyze(url))
window.active_download_row = window.rows[0]
window.rows[0]["download_started_at"] = 0
window._download_finished({"output_path": str(output), "output_dir": download_dir.name})

second = ClipFlowWindow()
print(len(second.rows))
print(second.rows[0]["widget"].title_label.text())
print(Path(second.rows[0]["output_path"]).name)
second.remove_row(second.rows[0])
third = ClipFlowWindow()
print(len(third.rows))

settings_dir.cleanup()
download_dir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["1", "Video", "Saved.mp4", "0"])

    def test_clipflow_qt_analyze_button_shows_loading_spinner(self):
        script = r'''
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    time.sleep(0.25)
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze)
window.url_input.setText("https://media.test/video")
window._start_analysis()
print(window.primary_button.is_loading())

def drive():
    if window.analysis_thread:
        return
    print(window.primary_button.is_loading())
    app.quit()

timer = QTimer()
timer.timeout.connect(drive)
timer.start(20)
QTimer.singleShot(5000, app.quit)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "False"])

    def test_clipflow_qt_window_configures_korean_font_when_created_directly(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow
from tools.clipflow_theme import FONT_FALLBACKS

app = QApplication([])
window = ClipFlowWindow()
print(" > ".join(FONT_FALLBACKS))
print("Apple SD Gothic Neo" in window.styleSheet())
print("Helvetica Neue" in window.styleSheet())
print(bool(QApplication.font().family()))
print(window.font().family())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines()[:4],
            [
                "Noto Sans KR > Apple SD Gothic Neo > Malgun Gothic > Helvetica Neue > Segoe UI",
                "True",
                "True",
                "True",
            ],
        )

    def test_clipflow_qt_theme_has_no_windows_only_font_paths(self):
        script = r'''
import inspect
from tools import clipflow_theme

source = inspect.getsource(clipflow_theme)
print(("C:" + "\\Windows") in source)
print(hasattr(clipflow_theme, "FONT_CANDIDATES"))
print(hasattr(clipflow_theme, "FONT_FALLBACKS"))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "False", "True"])

    def test_clipflow_qt_analysis_replaces_pending_rows_but_keeps_completed_rows(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    title = url.rsplit("/", 1)[-1]
    return {
        "webpage_url": url,
        "url": url,
        "title": title,
        "candidates": [
            {
                "id": title + "-1080",
                "source": url,
                "url": url,
                "title": title,
                "display_title": title,
                "thumbnail": "",
                "ext": "mp4",
                "output_ext": "mp4",
                "resolution": "1080p",
                "height": 1080,
                "duration": 240,
                "sort_bytes": 30,
            }
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze)

def row_titles():
    return [row["widget"].title_label.text() for row in window.rows]

window._analysis_finished(fake_analyze("https://media.test/one"))
print("|".join(row_titles()))
print(window.count_label.text())
window._analysis_finished(fake_analyze("https://media.test/two"))
print("|".join(row_titles()))
print(window.count_label.text())
window.rows[0]["widget"].set_status("완료")
window._analysis_finished(fake_analyze("https://media.test/three"))
print("|".join(row_titles()))
print("|".join(row["status"] for row in window.rows))
print(window.count_label.text())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["one", "1개", "two", "1개", "three|two", "준비|완료", "2개"],
        )

    def test_clipflow_qt_download_uses_selected_quality_and_row_local_progress(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtCore import QSettings
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, SETTINGS_APP, SETTINGS_ORG

downloaded = []
started_download = []

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "720", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "720p", "height": 720, "duration": 120, "sort_bytes": 20},
            {"id": "1080", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    downloaded.append(candidate["id"])
    if on_event:
        on_event({"type": "progress", "percent": 42, "message": "42.0% 7.0 MB/s ETA 00:10"})
        on_event({"type": "file", "path": str(Path(output_dir) / "Video.mp4")})
    return {"ok": True, "output_dir": output_dir}

app = QApplication([])
settings_dir = tempfile.TemporaryDirectory()
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, settings_dir.name)
QSettings(SETTINGS_ORG, SETTINGS_APP).clear()
window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
window.url_input.setText("https://media.test/video")
window._start_analysis()

def drive():
    if window.analysis_thread or window.download_thread:
        return
    if window.rows and not started_download:
        started_download.append(True)
        row_widget = window.rows[0]["widget"]
        print(row_widget.info_label.text())
        print(row_widget.size_label.text())
        print(row_widget.progress_bar.isHidden())
        print(row_widget.progress_text.isHidden())
        window.select_row(0)
        window._handle_primary_action()
        return
    if downloaded:
        row_widget = window.rows[0]["widget"]
        print(downloaded[0])
        print(row_widget.progress_bar.value())
        print(row_widget.progress_text.text())
        print(row_widget.progress_bar.isHidden())
        print(row_widget.progress_text.isHidden())
        print(hasattr(row_widget, "status_label"))
        print(hasattr(row_widget, "quality_value_label"))
        print(hasattr(row_widget, "format_label"))
        print(hasattr(window, "progress"))
        settings_dir.cleanup()
        app.quit()

timer = QTimer()
timer.timeout.connect(drive)
timer.start(20)
QTimer.singleShot(5000, app.quit)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "00:02:00",
                "30 B",
                "True",
                "True",
                "1080",
                "100",
                "",
                "True",
                "True",
                "False",
                "False",
                "False",
                "False",
            ],
        )

    def test_clipflow_qt_format_dropdown_maps_to_candidate_variant(self):
        script = r'''
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

downloaded = []
started_download = []

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "webm-1080", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "webm", "output_ext": "webm", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 40},
            {"id": "mp4-1080", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
            {"id": "mp4-720", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "720p", "height": 720, "duration": 120, "sort_bytes": 20},
        ],
        "warnings": [],
    }

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    downloaded.append(candidate["id"])
    return {"ok": True, "output_dir": output_dir}

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
window.url_input.setText("https://media.test/video")
window._start_analysis()

def drive():
    if window.analysis_thread or window.download_thread:
        return
    if window.rows and not started_download:
        started_download.append(True)
        row_widget = window.rows[0]["widget"]
        print(window.selected_candidate_for_row_ref(window.rows[0])["id"])
        print(row_widget.size_label.text())
        window._set_preferences(output_format="WEBM")
        print(window.selected_candidate_for_row_ref(window.rows[0])["id"])
        print(row_widget.size_label.text())
        window.select_row(0)
        window._handle_primary_action()
        return
    if downloaded:
        print(downloaded[0])
        app.quit()

timer = QTimer()
timer.timeout.connect(drive)
timer.start(20)
QTimer.singleShot(5000, app.quit)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["webm-1080", "40 B", "webm-1080", "40 B", "webm-1080"],
        )

    def test_clipflow_qt_status_column_has_no_done_check_and_shows_error_detail(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/video"

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze)
window._analysis_finished(fake_analyze(url))
row_widget = window.rows[0]["widget"]
print(hasattr(row_widget, "status_check_label"))
row_widget.set_status("완료")
print(hasattr(row_widget, "status_label"))
print(row_widget.progress_text.isHidden())
row_widget.set_status("오류", "network problem")
row_widget.set_progress(0, "")
print(row_widget.progress_text.isHidden())
print(row_widget.progress_text.text())
print(row_widget.progress_bar.isHidden())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["False", "False", "True", "False", "network problem", "True"],
        )

    def test_clipflow_qt_row_is_simplified_and_actions_are_hover_overlay(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

opened = []
url = "https://media.test/video"

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze, open_url_func=opened.append)
window._analysis_finished(fake_analyze(url))
row_widget = window.rows[0]["widget"]

print(hasattr(row_widget, "quality_combo"))
print(hasattr(row_widget, "format_combo"))
print(hasattr(row_widget, "status_label"))
print(row_widget.actions_widget.isHidden())
row_widget._set_hovered(True)
print(row_widget.actions_widget.isHidden())
row_widget.set_status("완료")
row_widget._set_hovered(True)
print(row_widget.actions_widget.isHidden())
row_widget._set_hovered(False)
print(row_widget.actions_widget.isHidden())
print(row_widget.delete_file_button.property("danger"))
print(hasattr(row_widget, "site_button"))
print(hasattr(row_widget, "domain_label"))
print(hasattr(row_widget, "open_source_button"))
print(row_widget.source_link_button.text())
row_widget.source_link_button.click()
print(opened)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["False", "False", "False", "True", "False", "False", "True", "true", "False", "False", "False", "media.test", "['https://media.test/video']"],
        )

    def test_clipflow_qt_hover_actions_cover_time_and_size_columns(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/video"

app = QApplication([])
window = ClipFlowWindow()
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Video",
    "candidates": [
        {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
    ],
    "warnings": [],
})
window.show()
app.processEvents()
row_widget = window.rows[0]["widget"]
row_widget._set_hovered(True)
app.processEvents()
actions = row_widget.actions_widget.geometry()
info = row_widget.info_widget.geometry()
size = row_widget.size_widget.geometry()
print(actions.x() <= info.x())
print(actions.x() + actions.width() >= size.x() + size.width())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True"])

    def test_clipflow_qt_row_sets_thumbnail_url_on_placeholder(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/video"

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "https://img.media.test/thumb.jpg", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze)
window._analysis_finished(fake_analyze(url))
row_widget = window.rows[0]["widget"]
print(row_widget.thumbnail.thumbnail_url)
print(row_widget.thumbnail.icon.isHidden())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["https://img.media.test/thumb.jpg", "False"])

    def test_clipflow_qt_media_column_expands_separately_from_quality_column(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/video"

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "A very long media title that should use extra width", "display_title": "A very long media title that should use extra width", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze)
window.resize(1500, 1100)
window._analysis_finished(fake_analyze(url))
window.show()
app.processEvents()
row_widget = window.rows[0]["widget"]
fixed_column_widgets = [row_widget.info_widget, row_widget.size_widget, row_widget.actions_widget]
print(len(window.findChildren(QFrame, "HeaderBar")))
print(row_widget.item_widget.maximumWidth() > 10000)
print(",".join(str(widget.width()) for widget in fixed_column_widgets))
print(f"{window.minimumWidth()}x{window.minimumHeight()}")
print(window.scroll_area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff)
fresh = ClipFlowWindow()
print(f"{fresh.width()}x{fresh.height()}")
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["0", "True", "84,92,230", "560x420", "True", "720x760"],
        )

    def test_clipflow_qt_sort_label_aligns_with_sort_controls(self):
        script = r'''
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
window.resize(1500, 1100)
window.show()
app.processEvents()

label_top = window.sort_label.mapTo(window, QPoint(0, 0)).y()
combo_top = window.sort_order_combo.mapTo(window, QPoint(0, 0)).y()
button_top = window.sort_direction_button.mapTo(window, QPoint(0, 0)).y()
print(window.sort_label.height())
print(window.sort_order_combo.height())
print(abs(label_top - combo_top) <= 1)
print(abs(label_top - button_top) <= 1)
print(hasattr(window, "sort_direction_combo"))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["40", "40", "True", "True", "False"])

    def test_clipflow_qt_input_controls_keep_shared_grid_edges(self):
        script = r'''
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QFrame
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
window.resize(1500, 1100)
window.show()
app.processEvents()

field_boxes = window.findChildren(QFrame, "FieldBox")
folder_box = field_boxes[1]
folder_top = folder_box.mapTo(window, QPoint(0, 0)).y()
cookie_top = window.cookie_combo.mapTo(window, QPoint(0, 0)).y()
primary_right = window.primary_button.mapTo(window, QPoint(0, 0)).x() + window.primary_button.width()
cookie_right = window.cookie_combo.mapTo(window, QPoint(0, 0)).x() + window.cookie_combo.width()

print(folder_box.height())
print(window.cookie_combo.height())
print(window.folder_button.text())
print(abs(folder_top - cookie_top) <= 1)
print(abs(primary_right - cookie_right) <= 1)
print(window.primary_button.width())
print(hasattr(window, "cookie_help_button"))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["42", "42", "저장 위치", "True", "True", "64", "False"],
        )

    def test_clipflow_qt_folder_path_is_display_only(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
window.show()
app.processEvents()
window.folder_input.selectAll()
QTest.mouseClick(window.folder_input, Qt.LeftButton)
app.processEvents()

print(window.folder_input.isReadOnly())
print(int(window.folder_input.focusPolicy()) == int(Qt.NoFocus))
print(window.folder_input.hasSelectedText())
print(window.folder_input.hasFocus())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "False", "False"])

    def test_clipflow_qt_persists_save_folder_with_qsettings(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, SAVE_FOLDER_SETTING, SETTINGS_APP, SETTINGS_ORG, default_save_folder

settings_dir = tempfile.TemporaryDirectory()
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, settings_dir.name)
QSettings(SETTINGS_ORG, SETTINGS_APP).clear()

app = QApplication([])
fallback = default_save_folder()
window = ClipFlowWindow()
saved = Path(settings_dir.name) / "Saved"
window._set_save_folder(saved)
second = ClipFlowWindow()

print(fallback.is_absolute())
print(fallback.name)
print(Path(second.folder_input.text()) == saved)
print(QSettings(SETTINGS_ORG, SETTINGS_APP).value(SAVE_FOLDER_SETTING) == str(saved))
settings_dir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "ClipFlow", "True", "True"])

    def test_clipflow_qt_builds_local_file_urls_for_folder_opening(self):
        script = r'''
from pathlib import Path
import inspect
import tempfile
from tools import clipflow_qt

tempdir = tempfile.TemporaryDirectory()
url = clipflow_qt.local_file_url(Path(tempdir.name))
source = inspect.getsource(clipflow_qt)

print(url.isLocalFile())
print(Path(url.toLocalFile()) == Path(tempdir.name).resolve())
print("QDesktopServices.openUrl" in inspect.getsource(clipflow_qt.ClipFlowWindow._open_path))
print(("os." + "startfile") in source)
print(("xdg" + "-open") in source)
print(("explorer" + ".exe") in source)
print(("Path." + "home(") in source)
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True", "False", "False", "False", "False"])

    def test_clipflow_qt_delete_file_confirms_and_deletes_resolved_download_output(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

downloaded = []
confirmed = []
started_download = []
tempdir = tempfile.TemporaryDirectory()

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    output = Path(output_dir) / "Video.mp4"
    output.write_bytes(b"mp4")
    downloaded.append(str(output))
    return {"ok": True, "output_dir": output_dir}

def confirm_delete(path):
    confirmed.append(Path(path).name)
    return True

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download, confirm_delete_func=confirm_delete)
window.folder_input.setText(tempdir.name)
window.url_input.setText("https://media.test/video")
window._start_analysis()

def drive():
    if window.analysis_thread or window.download_thread:
        return
    if window.rows and not started_download:
        started_download.append(True)
        window.select_row(0)
        window._handle_primary_action()
        return
    if downloaded:
        row = window.rows[0]
        row_widget = row["widget"]
        print(row["output_path"].endswith("Video.mp4"))
        print(row_widget.delete_file_button.isEnabled())
        row_widget.delete_file_button.click()
        print(confirmed)
        print(Path(downloaded[0]).exists())
        print(row["output_path"])
        print(row_widget.delete_file_button.isEnabled())
        tempdir.cleanup()
        app.quit()

timer = QTimer()
timer.timeout.connect(drive)
timer.start(20)
QTimer.singleShot(5000, app.quit)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["True", "True", "['Video.mp4']", "False", "", "False"],
        )

    def test_clipflow_qt_site_button_and_safe_actions(self):
        script = r'''
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

opened = []

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze, open_url_func=opened.append)
window.url_input.setText("https://media.test/watch/1")
window._start_analysis()

def drive():
    if window.analysis_thread:
        return
    if window.rows:
        row_widget = window.rows[0]["widget"]
        row_widget.source_link_button.click()
        print(opened[0])
        print("media.test" in row_widget.source_link_button.toolTip())
        print(row_widget.delete_file_button.isEnabled())
        print(row_widget.remove_button.isEnabled())
        app.quit()

timer = QTimer()
timer.timeout.connect(drive)
timer.start(20)
QTimer.singleShot(5000, app.quit)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["https://media.test/watch/1", "True", "False", "True"])

    def test_clipflow_qt_url_click_keeps_input_and_clear_button_clears_it(self):
        script = r'''
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze)
window.show()
window.url_input.setText("https://media.test/watch/1")
window._start_analysis()

def drive():
    if window.analysis_thread:
        return
    if window.rows:
        QTest.mouseClick(window.url_input, Qt.LeftButton)
        print(window.url_input.text())
        print(len(window.rows))
        print(window.primary_button.text())
        window.clear_url_button.click()
        print(window.url_input.text())
        print(len(window.rows))
        print(window.primary_button.text())
        app.quit()

timer = QTimer()
timer.timeout.connect(drive)
timer.start(20)
QTimer.singleShot(5000, app.quit)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["https://media.test/watch/1", "1", "", "", "1", ""],
        )


    def test_clipflow_qt_changed_url_analyzes_instead_of_downloading_selected_row(self):
        script = r'''
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

analyzed = []
downloaded = []

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    analyzed.append(url)
    return {
        "webpage_url": url,
        "url": url,
        "title": url.rsplit("/", 1)[-1],
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": url, "display_title": url.rsplit("/", 1)[-1], "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    downloaded.append(page_url)
    return {"ok": True, "output_dir": output_dir}

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
window.url_input.setText("https://media.test/watch/1")
window._analysis_finished(fake_analyze("https://media.test/watch/1"))
window.select_row(0)
window.url_input.setText("https://media.test/watch/2")
window._refresh_primary_action()
print("분석" not in window.primary_button.text())
window._start_analysis()

def drive():
    if window.analysis_thread or window.download_thread:
        return
    print(analyzed)
    print(downloaded)
    print(window.rows[0]["analysis_source_url"])
    app.quit()

timer = QTimer()
timer.timeout.connect(drive)
timer.start(20)
QTimer.singleShot(5000, app.quit)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "True",
                "['https://media.test/watch/1', 'https://media.test/watch/2']",
                "[]",
                "https://media.test/watch/2",
            ],
        )

    def test_clipflow_qt_confirmation_buttons_put_ok_on_the_right(self):
        script = r'''
from pathlib import Path
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
preferences = window._create_preferences_dialog()
delete_dialog = window._create_delete_confirm_dialog(Path("C:/Temp/video.mp4"))
preferences.show()
delete_dialog.show()
app.processEvents()

print(hasattr(preferences, "cancel_button"))
print(hasattr(preferences, "ok_button"))
print(preferences.cancel_button.mapTo(preferences, preferences.cancel_button.rect().topLeft()).x() < preferences.ok_button.mapTo(preferences, preferences.ok_button.rect().topLeft()).x())
print(delete_dialog.cancel_button.mapTo(delete_dialog, delete_dialog.cancel_button.rect().topLeft()).x() < delete_dialog.ok_button.mapTo(delete_dialog, delete_dialog.ok_button.rect().topLeft()).x())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True", "True"])

    def test_clipflow_qt_spinner_advances_clockwise_and_row_uses_border_progress(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow
from tools.clipflow_rows import ACTIVE_STATUSES
from tools.clipflow_theme import APP_STYLE
from tools.clipflow_widgets import PrimaryActionButton

url = "https://media.test/video"

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

app = QApplication([])
button = PrimaryActionButton()
button._angle = 0
button._advance()
window = ClipFlowWindow(analyze_func=fake_analyze)
window._analysis_finished(fake_analyze(url))
row_widget = window.rows[0]["widget"]
row_widget.set_status(next(iter(ACTIVE_STATUSES)))
row_widget.set_progress(42, "42% · 7.0 MB/s")

print(button._angle == 332)
print("border-radius: 8px" in APP_STYLE)
print(row_widget.progress_bar.isHidden())
print(row_widget.property("progressActive"))
print(row_widget.property("progressValue"))
print(row_widget.progress_text.isHidden())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True", "true", "42", "False"])

    def test_clipflow_qt_download_button_stays_enabled_while_download_runs(self):
        script = r'''
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/watch/enabled"

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    time.sleep(0.25)
    return {"ok": True, "output_dir": output_dir}

app = QApplication([])
window = ClipFlowWindow(download_func=fake_download)
window.url_input.setText(url)
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Enabled",
    "candidates": [{"id": "enabled", "source": url, "url": url, "title": "Enabled", "display_title": "Enabled", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 1}],
    "warnings": [],
})
window.select_row(0)
window._start_download()
printed = {"done": False}

def check():
    if not printed["done"]:
        print(window.primary_button.isEnabled())
        printed["done"] = True
    active = getattr(window, "active_downloads", [])
    legacy = getattr(window, "download_thread", None)
    if not active and not (legacy and legacy.isRunning()):
        app.quit()

timer = QTimer()
timer.timeout.connect(check)
timer.start(50)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True"])

    def test_clipflow_qt_downloads_three_parallel_then_queues_fourth(self):
        script = r'''
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

base = "https://media.test/watch/"

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    time.sleep(0.35)
    return {"ok": True, "output_dir": output_dir}

app = QApplication([])
window = ClipFlowWindow(download_func=fake_download)
window.url_input.setText(base + "0")
window._analysis_finished({
    "webpage_url": base + "0",
    "url": base + "0",
    "title": "Batch",
    "candidates": [
        {"id": str(i), "source": base + str(i), "url": base + str(i), "title": f"Video {i}", "display_title": f"Video {i}", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": i + 1}
        for i in range(4)
    ],
    "warnings": [],
})
for index in range(4):
    window.select_row(index)
    window._start_download()
printed = {"done": False}

def check():
    if not printed["done"]:
        print(len(getattr(window, "active_downloads", [])))
        print(len(getattr(window, "queued_download_rows", [])))
        printed["done"] = True
    active = getattr(window, "active_downloads", [])
    legacy = getattr(window, "download_thread", None)
    if not active and not getattr(window, "queued_download_rows", []) and not (legacy and legacy.isRunning()):
        app.quit()

timer = QTimer()
timer.timeout.connect(check)
timer.start(50)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["3", "1"])

    def test_clipflow_qt_repeated_click_on_same_row_does_not_duplicate_download(self):
        script = r'''
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/watch/once"
calls = []

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    calls.append(candidate.get("id"))
    time.sleep(0.25)
    return {"ok": True, "output_dir": output_dir}

app = QApplication([])
window = ClipFlowWindow(download_func=fake_download)
window.url_input.setText(url)
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Once",
    "candidates": [{"id": "once", "source": url, "url": url, "title": "Once", "display_title": "Once", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 1}],
    "warnings": [],
})
window.select_row(0)
window._start_download()
window._start_download()
printed = {"done": False}

def check():
    if not printed["done"]:
        print(len(getattr(window, "active_downloads", [])))
        print(len(getattr(window, "queued_download_rows", [])))
        print(len(calls))
        printed["done"] = True
    active = getattr(window, "active_downloads", [])
    legacy = getattr(window, "download_thread", None)
    if not active and not (legacy and legacy.isRunning()):
        app.quit()

timer = QTimer()
timer.timeout.connect(check)
timer.start(50)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["1", "0", "1"])

    def test_clipflow_qt_existing_output_skips_download_start(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/watch/existing"

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    raise AssertionError("download should not run")

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
existing = Path(tempdir.name) / "Already Here.mp4"
existing.write_bytes(b"done")
window = ClipFlowWindow(download_func=fake_download)
window._set_save_folder(tempdir.name)
window.url_input.setText(url)
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Already Here",
    "candidates": [{"id": "existing", "source": url, "url": url, "title": "Already Here", "display_title": "Already Here", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 1}],
    "warnings": [],
})
window.select_row(0)
window._start_download()
row = window.rows[0]
print(row["status"])
print(Path(row["output_path"]).name)
print(bool(getattr(window, "active_downloads", [])))
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["완료", "Already Here.mp4", "False"])

    def test_clipflow_qt_partial_existing_output_does_not_skip_retry(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/watch/partial"
started = []

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
partial = Path(tempdir.name) / "Partial Video.mp4"
partial.write_bytes(b"x")
window = ClipFlowWindow()
window._set_save_folder(tempdir.name)
window.url_input.setText(url)
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Partial Video",
    "candidates": [{"id": "partial", "source": url, "url": url, "title": "Partial Video", "display_title": "Partial Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 1, "sort_bytes": 10485760}],
    "warnings": [],
})
row = window.rows[0]
row["status"] = "오류"
row["output_path"] = str(partial)
def begin(row, candidate=None):
    started.append(candidate.get("id"))
    row["status"] = "다운로드 중"
window._begin_download = begin
window.select_row(0)
window._start_download()
print(started)
print(row["status"])
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["['partial']", "다운로드 중"])

    def test_clipflow_qt_analysis_preserves_active_and_queued_download_rows(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

def analysis(url, title):
    return {
        "webpage_url": url,
        "url": url,
        "title": title,
        "candidates": [{"id": title, "source": url, "url": url, "title": title, "display_title": title, "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 1}],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow()
window.url_input.setText("https://media.test/watch/old")
window._analysis_finished(analysis("https://media.test/watch/old", "Old"))
active_row = window.rows[0]
active_row["status"] = "다운로드 중"
window.active_downloads = [{"row": active_row, "thread": None, "worker": None}]
window.queued_download_rows = [active_row]
window.url_input.setText("https://media.test/watch/new")
window._analysis_finished(analysis("https://media.test/watch/new", "New"))
titles = [row["candidate"]["display_title"] for row in window.rows]
print("Old" in titles)
print("New" in titles)
print(active_row in window.rows)
print(active_row in window.queued_download_rows)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True", "True"])

    def test_clipflow_qt_delete_confirm_dialog_uses_no_yes_order(self):
        script = r'''
from pathlib import Path
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
dialog = window._create_delete_confirm_dialog(Path("sample.mp4"))
print(dialog.cancel_button.text())
print(dialog.ok_button.text())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["No", "Yes"])

    def test_clipflow_qt_playlist_file_view_opens_playlist_folder(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
opened = []
window = ClipFlowWindow()
window._set_save_folder(tempdir.name)
window._open_path = lambda path: opened.append(Path(path))
row = {
    "kind": "playlist",
    "candidate": {"media_type": "playlist", "title": "Road Mix", "display_title": "Road Mix", "output_ext": "mp4"},
    "playlist_entries": [],
    "output_path": "",
    "status": "완료",
}
playlist_folder = Path(tempdir.name) / "Road Mix"
playlist_folder.mkdir()
window.open_folder_for_row(row)
print(opened[0] == playlist_folder)
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True"])

    def test_clipflow_qt_playlist_file_delete_uses_same_confirm_dialog_and_deletes_folder(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication, QDialog
from tools.clipflow_qt import ClipFlowWindow, DeleteConfirmDialog

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
seen = []
window = ClipFlowWindow()
window._set_save_folder(tempdir.name)
row = {
    "kind": "playlist",
    "candidate": {"media_type": "playlist", "title": "Road Mix", "display_title": "Road Mix", "output_ext": "mp4"},
    "playlist_entries": [],
    "output_path": "",
    "status": "완료",
    "messages": [],
}
playlist_folder = Path(tempdir.name) / "Road Mix"
playlist_folder.mkdir()
video = playlist_folder / "01 - One.mp4"
video.write_bytes(b"video")

def confirm(path):
    dialog = window._create_delete_confirm_dialog(path)
    seen.append([isinstance(dialog, DeleteConfirmDialog), dialog.cancel_button.text(), dialog.ok_button.text(), Path(path).name])
    return True

window.confirm_delete_func = confirm
window.delete_file_for_row(row)
print(seen)
print(video.exists())
print(playlist_folder.exists())
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["[[True, 'No', 'Yes', 'Road Mix']]", "False", "False"])

    def test_clipflow_qt_playlist_info_text_is_single_label_with_count(self):
        script = r'''
from tools.clipflow_rows import row_info_text

print(row_info_text({"media_type": "playlist", "item_count": 7}))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["재생목록 7개"])

    def test_clipflow_qt_playlist_analysis_uses_single_disclosure_row_and_playlist_folder(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

downloaded = []
tempdir = tempfile.TemporaryDirectory()
url = "https://media.test/playlist/road"

def fake_analysis():
    return {
        "webpage_url": url,
        "url": url,
        "title": "Road Trip Mix",
        "playlist_title": "Road Trip Mix",
        "is_playlist": True,
        "playlist_count": 2,
        "candidates": [
            {"id": "one", "source": "https://media.test/watch/1", "url": "https://media.test/watch/1", "title": "One", "display_title": "One", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 60, "sort_bytes": 10},
            {"id": "two", "source": "https://media.test/watch/2", "url": "https://media.test/watch/2", "title": "Two", "display_title": "Two", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 20},
        ],
        "warnings": [],
    }

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    downloaded.append([page_url, candidate.get("media_type"), Path(output_dir).name])
    return {"ok": True, "output_dir": output_dir}

app = QApplication([])
window = ClipFlowWindow(download_func=fake_download)
window.folder_input.setText(tempdir.name)
window.url_input.setText(url)
window._analysis_finished(fake_analysis())
row = window.rows[0]
row_widget = row["widget"]

print(len(window.rows))
print(row["kind"])
print(row["candidate"]["media_type"])
print(row["candidate"]["item_count"])
print(row_widget.playlist_detail_label.isHidden())
row_widget.playlist_toggle_button.click()
print(row_widget.playlist_detail_label.isHidden())
print("One" in row_widget.playlist_detail_label.text())
window.select_row(0)
window._handle_primary_action()

def drive():
    if window.download_thread:
        return
    if downloaded:
        print(downloaded)
        tempdir.cleanup()
        app.quit()

timer = QTimer()
timer.timeout.connect(drive)
timer.start(20)
QTimer.singleShot(5000, app.quit)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "1",
                "playlist",
                "playlist",
                "2",
                "True",
                "False",
                "True",
                "[['https://media.test/playlist/road', 'playlist', 'Road Trip Mix']]",
            ],
        )

    def test_clipflow_qt_playlist_float_button_collapses_and_returns_to_row(self):
        script = r'''
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/playlist/long"

def fake_analysis():
    candidates = []
    for index in range(1, 41):
        candidates.append({
            "id": str(index),
            "source": f"https://media.test/watch/{index}",
            "url": f"https://media.test/watch/{index}",
            "title": f"Video {index}",
            "display_title": f"Video {index}",
            "thumbnail": "",
            "ext": "mp4",
            "output_ext": "mp4",
            "resolution": "1080p",
            "height": 1080,
            "duration": 60,
            "sort_bytes": 10,
        })
    return {
        "webpage_url": url,
        "url": url,
        "title": "Long Mix",
        "playlist_title": "Long Mix",
        "is_playlist": True,
        "playlist_count": len(candidates),
        "candidates": candidates,
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow()
window.resize(720, 420)
window.show()
app.processEvents()
window.url_input.setText(url)
window._analysis_finished(fake_analysis())
row = window.rows[0]
row_widget = row["widget"]
row_widget.playlist_toggle_button.click()
app.processEvents()
bar = window.scroll_area.verticalScrollBar()
bar.setValue(min(bar.maximum(), 90))
app.processEvents()
window._refresh_playlist_float_button()
print(row["expanded"])
print(bar.maximum() > 0)
print(window.playlist_float_button.isVisible())
window.playlist_float_button.click()
app.processEvents()
row_top = row_widget.mapTo(window.row_container, QPoint(0, 0)).y()
print(row["expanded"])
print(abs(bar.value() - row_top) <= 2)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True", "False", "True"])

    def test_clipflow_qt_long_titles_use_marquee_label(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/video"
long_title = "This is a very long video title that should scroll horizontally when it does not fit"

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": long_title,
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": long_title, "display_title": long_title, "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze)
window._analysis_finished(fake_analyze(url))
row_widget = window.rows[0]["widget"]
label = row_widget.title_label
label.setFixedWidth(120)
label.start_marquee_if_needed()
label._advance_marquee()
print(type(label).__name__)
print(label._marquee_offset > 0)
label.stop_marquee()
print(label._marquee_offset)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["MarqueeLabel", "True", "0"])

    def test_clipflow_qt_tooltips_are_styled_and_positioned_above_icon_buttons(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_icons import LucideIconButton
from tools.clipflow_theme import APP_STYLE

app = QApplication([])
button = LucideIconButton("folder", size=32, icon_size=18)
button.setToolTip("Folder")
button.show()
app.processEvents()
position = button.tooltip_position()
global_top = button.mapToGlobal(button.rect().topLeft()).y()
print("QToolTip" in APP_STYLE)
print(position.y() < global_top)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True"])


if __name__ == "__main__":
    unittest.main()
