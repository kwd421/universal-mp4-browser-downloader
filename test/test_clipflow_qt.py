import os
import subprocess
import sys
import tempfile
import unittest
import uuid


def run_qt_script(script, timeout=10):
    settings_org = f"ClipFlowTestOrg{uuid.uuid4().hex}"
    settings_app = f"ClipFlowTest{uuid.uuid4().hex}"
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "CLIPFLOW_SETTINGS_ORG": settings_org,
        "CLIPFLOW_SETTINGS_APP": settings_app,
    }
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

    def test_clipflow_qt_clean_combo_toggles_popup_closed(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import CleanComboBox

app = QApplication([])
combo = CleanComboBox()
combo.addItems(["최신순", "이름순"])
combo.show()
combo.showPopup()
first_popup = combo._active_popup
print(first_popup.isVisible())
combo.showPopup()
print(combo._active_popup is None)
print(not first_popup.isVisible())
QTest.qWait(250)
combo.showPopup()
second_popup = combo._active_popup
QTest.mouseClick(combo, Qt.LeftButton)
print(combo._active_popup is None)
print(not second_popup.isVisible())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True", "True", "True"])

    def test_clipflow_qt_sort_combo_hides_inline_arrow(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
print(window.sort_order_combo.show_arrow)
print(window.sort_order_combo.text_alignment == Qt.AlignCenter)
print(window.cookie_combo.show_arrow)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "True", "True"])

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
    if window.analysis_thread or window.download_thread or window.active_downloads or window.queued_download_rows:
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

    def test_clipflow_qt_quality_button_opens_dropdown_preferences(self):
        script = r'''
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, READY_STATUS
from tools.clipflow_widgets import CleanComboBox

app = QApplication([])
window = ClipFlowWindow()
window.resize(720, 520)
window.show()
window._create_preferences_dialog = lambda: (_ for _ in ()).throw(RuntimeError("dialog should not open"))
window.preference_button.click()
popup = window.preferences_popup
combos = popup.findChildren(CleanComboBox)
print(bool(popup and popup.isVisible()))
print(len(combos))
button_right = window.preference_button.mapToGlobal(QPoint(window.preference_button.width(), 0)).x()
print(abs(popup.geometry().right() - button_right) <= 1)
combos[0].setCurrentText("720p")
combos[1].setCurrentText("WEBM")
print(window.current_preferences().quality)
print(window.current_preferences().output_format)
window.preference_button.click()
print(window.preferences_popup is None)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "4", "True", "720p", "WEBM", "True"])

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

    def test_clipflow_qt_playlist_history_restores_child_rows_under_parent(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS, SETTINGS_APP, SETTINGS_ORG

settings_dir = tempfile.TemporaryDirectory()
download_dir = tempfile.TemporaryDirectory()
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, settings_dir.name)
QSettings(SETTINGS_ORG, SETTINGS_APP).clear()

url = "https://media.test/watch?v=one&list=PLROAD"
app = QApplication([])
window = ClipFlowWindow()
window._set_save_folder(download_dir.name)
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Road Mix",
    "playlist_title": "Road Mix",
    "is_playlist": True,
    "playlist_count": 2,
    "candidates": [
        {"id": "one", "source": "https://media.test/watch/1", "url": "https://media.test/watch/1", "title": "One", "display_title": "One", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 60, "sort_bytes": 10},
        {"id": "two", "source": "https://media.test/watch/2", "url": "https://media.test/watch/2", "title": "Two", "display_title": "Two", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 20},
    ],
    "warnings": [],
})
for index, row in enumerate(window.rows):
    row["status"] = COMPLETED_STATUS
    if row.get("is_playlist_child"):
        output = Path(download_dir.name) / f"{index}.mp4"
        output.write_bytes(b"mp4")
        row["output_path"] = str(output)
window._save_completed_history()

second = ClipFlowWindow()
print([row["candidate"].get("display_title") for row in second.rows])
print([bool(row.get("is_playlist_child")) for row in second.rows])
print([row.get("parent_playlist_id") == second.rows[0]["id"] for row in second.rows[1:]])
print([row.get("render_widget").isHidden() for row in second.rows[1:]])

settings_dir.cleanup()
download_dir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "['Road Mix', 'One', 'Two']",
                "[False, True, True]",
                "[True, True]",
                "[False, False]",
            ],
        )

    def test_clipflow_qt_playlist_history_migrates_legacy_keyed_children(self):
        script = r'''
import json
import tempfile
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, DOWNLOAD_HISTORY_SETTING, SETTINGS_APP, SETTINGS_ORG

settings_dir = tempfile.TemporaryDirectory()
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, settings_dir.name)
settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
settings.clear()
key = "media.test:list:PLROAD"
settings.setValue(DOWNLOAD_HISTORY_SETTING, json.dumps([
    {"candidate": {"id": "playlist-1", "media_type": "playlist", "title": "Road Mix", "display_title": "Road Mix", "url": "https://media.test/watch?v=one&list=PLROAD"}, "source_url": "https://media.test/watch?v=one&list=PLROAD", "analysis_source_url": "https://media.test/watch?v=one&list=PLROAD", "playlist_key": key, "created_order": 1},
    {"candidate": {"id": "one", "title": "One", "display_title": "One", "url": "https://media.test/watch/1", "source": "https://media.test/watch/1", "ext": "mp4", "output_ext": "mp4"}, "source_url": "https://media.test/watch/1", "playlist_key": key, "created_order": 2},
    {"candidate": {"id": "two", "title": "Two", "display_title": "Two", "url": "https://media.test/watch/2", "source": "https://media.test/watch/2", "ext": "mp4", "output_ext": "mp4"}, "source_url": "https://media.test/watch/2", "playlist_key": key, "created_order": 3},
], ensure_ascii=False))
settings.sync()

app = QApplication([])
window = ClipFlowWindow()
print([row["candidate"].get("display_title") for row in window.rows])
print([bool(row.get("is_playlist_child")) for row in window.rows])
print([row.get("parent_playlist_id") == window.rows[0]["id"] for row in window.rows[1:]])

settings_dir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "['Road Mix', 'One', 'Two']",
                "[False, True, True]",
                "[True, True]",
            ],
        )

    def test_clipflow_qt_playlist_history_deduplicates_restored_parent_rows(self):
        script = r'''
import json
import tempfile
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, DOWNLOAD_HISTORY_SETTING, SETTINGS_APP, SETTINGS_ORG

settings_dir = tempfile.TemporaryDirectory()
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, settings_dir.name)
settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
settings.clear()
url = "https://www.youtube.com/playlist?list=PLDUPLICATE"
settings.setValue(DOWNLOAD_HISTORY_SETTING, json.dumps([
    {"candidate": {"id": "playlist-old", "media_type": "playlist", "title": "Mix", "display_title": "Mix", "source": url, "url": url, "webpage_url": url}, "source_url": url, "analysis_source_url": url, "created_order": 1},
    {"candidate": {"id": "playlist-new", "media_type": "playlist", "title": "Mix", "display_title": "Mix", "source": url, "url": url, "webpage_url": url}, "source_url": url, "analysis_source_url": url, "created_order": 2},
], ensure_ascii=False))
settings.sync()

app = QApplication([])
window = ClipFlowWindow()
playlist_rows = [row for row in window.rows if row.get("kind") == "playlist"]
print(len(playlist_rows))
print(playlist_rows[0]["id"])

settings_dir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["1", "playlist-new"])

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
        self.assertEqual(result.stdout.splitlines(), ["False", "False"])

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
            ["mp4-1080", "30 B", "webm-1080", "40 B", "webm-1080"],
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

    def test_clipflow_qt_thumbnail_preview_does_not_capture_mouse_hover(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import ThumbnailPlaceholder

app = QApplication([])
thumbnail = ThumbnailPlaceholder()
thumbnail._set_pixmap(QPixmap(120, 80))
thumbnail._show_preview()
print(thumbnail._preview.testAttribute(Qt.WA_TransparentForMouseEvents))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True"])

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
print(window.scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn)
print(hasattr(window, "status_label"))
print(len(window.findChildren(QFrame, "FooterDivider")))
fresh = ClipFlowWindow()
print(f"{fresh.width()}x{fresh.height()}")
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["0", "True", "84,92,229", "560x420", "True", "True", "False", "0", "720x760"],
        )

    def test_clipflow_qt_sort_label_aligns_with_sort_controls(self):
        script = r'''
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, READY_STATUS

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
print(("Path." + "home(") in source)
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True", "False", "False", "False"])

    def test_clipflow_qt_file_view_reveals_completed_file_instead_of_parent_only(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
opened = []
revealed = []
window = ClipFlowWindow()
window._set_save_folder(tempdir.name)
window._open_path = lambda path: opened.append(Path(path))
window._reveal_in_file_manager = lambda path: revealed.append(Path(path))
output = Path(tempdir.name) / "Video.mp4"
output.write_bytes(b"video")
row = {
    "kind": "video",
    "candidate": {"title": "Video", "source": "https://media.test/video", "url": "https://media.test/video"},
    "output_path": str(output),
    "status": "완료",
}
window.open_folder_for_row(row)
print(revealed == [output])
print(opened)
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "[]"])

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
        print(len(window.rows))
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
            ["True", "True", "['Video.mp4']", "False", "0"],
        )

    def test_clipflow_qt_child_file_delete_removes_child_row_with_explicit_output(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS, READY_STATUS

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
window = ClipFlowWindow(confirm_delete_func=lambda path: True)
window._set_save_folder(tempdir.name)
playlist_dir = Path(tempdir.name) / "Road Mix"
playlist_dir.mkdir()
output = playlist_dir / "One.mp4"
output.write_bytes(b"video")
parent = {
    "id": "playlist-1",
    "kind": "playlist",
    "candidate": {"media_type": "playlist", "title": "Road Mix", "display_title": "Road Mix", "output_ext": "mp4"},
    "qualities": [],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "status": READY_STATUS,
    "status_detail": "",
    "progress": 0,
    "progress_text": "",
    "output_path": "",
    "messages": [],
    "created_order": 1,
    "expanded": True,
    "playlist_entries": [],
}
child = {
    "id": "playlist-1-child-1",
    "kind": "video",
    "candidate": {"id": "one", "title": "One", "display_title": "One", "source": "https://media.test/one", "url": "https://media.test/one", "ext": "mp4", "output_ext": "mp4"},
    "qualities": [],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "status": COMPLETED_STATUS,
    "status_detail": "",
    "progress": 100,
    "progress_text": "",
    "output_path": str(output),
    "messages": [],
    "created_order": 2,
    "parent_playlist_id": "playlist-1",
    "is_playlist_child": True,
    "playlist_child_index": 1,
}
window.rows = [parent, child]
window._render_rows()
window.delete_file_for_row(child)
print(output.exists())
print([row["id"] for row in window.rows])
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "['playlist-1']"])

    def test_clipflow_qt_child_file_delete_removes_child_row_with_exact_expected_output(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS, READY_STATUS
from tools import downloader_engine as engine

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
window = ClipFlowWindow(confirm_delete_func=lambda path: True)
window._set_save_folder(tempdir.name)
playlist_dir = Path(tempdir.name) / "Road Mix"
playlist_dir.mkdir()
parent = {
    "id": "playlist-1",
    "kind": "playlist",
    "candidate": {"media_type": "playlist", "title": "Road Mix", "display_title": "Road Mix", "output_ext": "mp4"},
    "qualities": [],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "status": READY_STATUS,
    "status_detail": "",
    "progress": 0,
    "progress_text": "",
    "output_path": "",
    "messages": [],
    "created_order": 1,
    "expanded": True,
    "playlist_entries": [],
}
child = {
    "id": "playlist-1-child-1",
    "kind": "video",
    "candidate": {"id": "one", "title": "Episode One", "display_title": "Episode One", "source": "https://media.test/one", "url": "https://media.test/one", "ext": "mp4", "output_ext": "mp4"},
    "qualities": [],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "status": COMPLETED_STATUS,
    "status_detail": "",
    "progress": 100,
    "progress_text": "",
    "output_path": "",
    "messages": [],
    "created_order": 2,
    "parent_playlist_id": "playlist-1",
    "is_playlist_child": True,
    "playlist_child_index": 1,
}
output = engine.final_output_path_for_candidate(child["candidate"], playlist_dir)
output.write_bytes(b"video")
window.rows = [parent, child]
window._render_rows()
window.delete_file_for_row(child)
print(output.exists())
print([row["id"] for row in window.rows])
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "['playlist-1']"])

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

    def test_clipflow_qt_paste_only_fills_url_without_analysis(self):
        script = r'''
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/watch/paste"
analyzed = []

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    analyzed.append(url)
    return {
        "webpage_url": url,
        "url": url,
        "title": "Paste",
        "candidates": [
            {"id": "auto", "source": url, "url": url, "title": "Paste", "display_title": "Paste", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 60, "sort_bytes": 10},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze)
QApplication.clipboard().setText(url)
window._paste_and_analyze()

def drive():
    if window.analysis_thread:
        return
    print(window.url_input.text())
    print(analyzed)
    print(len(window.rows))
    print(window.analysis_thread is None)
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
            ["https://media.test/watch/paste", "[]", "0", "True"],
        )

    def test_clipflow_qt_download_button_analyzes_then_downloads_single_video(self):
        script = r'''
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/watch/download"
analyzed = []
downloaded = []

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    analyzed.append(url)
    return {
        "webpage_url": url,
        "url": url,
        "title": "Download",
        "candidates": [
            {"id": "auto", "source": url, "url": url, "title": "Download", "display_title": "Download", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 60, "sort_bytes": 10},
        ],
        "warnings": [],
    }

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    downloaded.append([page_url, candidate.get("id")])
    return {"ok": True, "output_dir": output_dir}

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
window.url_input.setText(url)
window._handle_primary_action()

def drive():
    if window.analysis_thread or window.download_thread:
        return
    print(analyzed)
    print([row["candidate"].get("id") for row in window.rows])
    print(window.selected_row_index)
    print(downloaded)
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
                "['https://media.test/watch/download']",
                "['auto']",
                "0",
                "[['https://media.test/watch/download', 'auto']]",
            ],
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

    def test_clipflow_qt_download_button_does_not_show_loading_spinner_for_analysis(self):
        script = r'''
import time
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/watch/loading-button"

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    time.sleep(0.2)
    return {"webpage_url": url, "url": url, "title": "Video", "candidates": [], "warnings": []}

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze)
window.url_input.setText(url)
window._start_analysis(auto_download=True)
app.processEvents()
print(window.primary_button.is_loading())
if window.analysis_thread:
    window.analysis_thread.quit()
    window.analysis_thread.wait(1000)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False"])

    def test_clipflow_qt_active_row_progress_border_is_visible_from_zero_percent(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, DOWNLOAD_STATUS

app = QApplication([])
window = ClipFlowWindow()
window._analysis_finished({
    "webpage_url": "https://media.test/watch/progress",
    "url": "https://media.test/watch/progress",
    "title": "Progress",
    "candidates": [{"id": "progress", "source": "https://media.test/watch/progress", "url": "https://media.test/watch/progress", "title": "Progress", "display_title": "Progress", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 1}],
    "warnings": [],
})
row_widget = window.rows[0]["widget"]
row_widget.set_status(DOWNLOAD_STATUS)
row_widget.set_progress(0, "0%")
print(row_widget.property("progressActive"))
print(row_widget.property("progressValue"))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["true", "0"])

    def test_clipflow_qt_row_action_overlay_has_square_left_edge(self):
        script = r'''
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from tools import clipflow_theme as theme
from tools.clipflow_rows import RowActionOverlay

app = QApplication([])
parent = QWidget()
parent.setProperty("selected", "false")
overlay = RowActionOverlay(parent)
overlay.resize(160, 70)
pixmap = QPixmap(160, 70)
pixmap.fill(QColor(0, 0, 0, 0))
overlay.render(pixmap, QPoint(0, 0))
print(QColor(pixmap.toImage().pixelColor(0, 0)).name().upper() == theme.SURFACE_SOFT)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True"])

    def test_clipflow_qt_scrollbar_space_is_reserved_but_handle_appears_only_when_scrollable(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, READY_STATUS

app = QApplication([])
window = ClipFlowWindow()
window.resize(720, 760)
window.show()
app.processEvents()
bar = window.scroll_area.verticalScrollBar()
print(window.scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn)
print(bar.property("scrollable"))

for index in range(14):
    candidate = {
        "id": f"row-{index}",
        "title": f"Video {index}",
        "display_title": f"Video {index}",
        "source": f"https://media.test/{index}",
        "url": f"https://media.test/{index}",
        "ext": "mp4",
        "output_ext": "mp4",
        "duration": 60,
        "sort_bytes": 10,
    }
    window.rows.append({
        "id": f"row-{index}",
        "kind": "video",
        "candidate": candidate,
        "qualities": [candidate],
        "quality_options": [],
        "selected_index": 0,
        "selected_format_index": 0,
        "analysis_source_url": candidate["url"],
        "source_url": candidate["url"],
        "status": READY_STATUS,
        "status_detail": "",
        "progress": 0,
        "progress_text": "",
        "output_path": "",
        "messages": [],
        "created_order": index + 1,
    })
window._render_rows()
app.processEvents()
print(bar.maximum() > 0)
print(bar.property("scrollable"))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "false", "True", "true"])

    def test_clipflow_qt_action_overlay_does_not_paint_over_right_rounded_corner(self):
        script = r'''
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from tools.clipflow_theme import APP_STYLE
from tools.clipflow_rows import RowActionOverlay

app = QApplication([])
app.setStyleSheet(APP_STYLE)
parent = QWidget()
overlay = RowActionOverlay(parent)
overlay.resize(160, 70)
pixmap = QPixmap(160, 70)
pixmap.fill(QColor(0, 0, 0, 0))
overlay.render(pixmap, QPoint(0, 0))
top_right = pixmap.toImage().pixelColor(159, 0)
bottom_right = pixmap.toImage().pixelColor(159, 69)
print(top_right.alpha())
print(bottom_right.alpha())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["0", "0"])

    def test_clipflow_qt_row_selection_has_no_visible_selected_state(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow
from tools.clipflow_theme import APP_STYLE

app = QApplication([])
window = ClipFlowWindow()
row = {
    "candidate": {"id": "one", "title": "One", "source": "https://media.test/one", "url": "https://media.test/one"},
    "qualities": [],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "source_url": "https://media.test/one",
    "status": "완료",
    "messages": [],
}
window.rows = [row]
window._render_rows()
widget = row["widget"]
widget.set_selected(True)
print(widget.property("selected"))
print('QFrame#DownloadRow[selected="true"]' in APP_STYLE and "border-color: #0070F3" in APP_STYLE.split('QFrame#DownloadRow[selected="true"]', 1)[1].split("}", 1)[0])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["false", "False"])

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
from tools import downloader_engine as engine

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
from tools import downloader_engine as engine

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
opened = []
window = ClipFlowWindow()
window._set_save_folder(tempdir.name)
window._open_path = lambda path: opened.append(Path(path))
window._reveal_in_file_manager = lambda path: opened.append(Path(path))
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
    "id": "playlist-1",
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
child = {
    "id": "playlist-1-child-1",
    "kind": "video",
    "candidate": {"title": "One", "display_title": "One", "ext": "mp4", "output_ext": "mp4"},
    "parent_playlist_id": "playlist-1",
    "is_playlist_child": True,
    "status": "?꾨즺",
    "output_path": str(video),
    "messages": [],
}
window.rows = [row, child]

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

    def test_clipflow_qt_playlist_delete_dialog_names_playlist_and_child_file_count(self):
        script = r'''
from pathlib import Path
from PySide6.QtWidgets import QApplication, QLabel
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
parent = {
    "id": "playlist-1",
    "kind": "playlist",
    "candidate": {"media_type": "playlist", "title": "Road Mix", "display_title": "Road Mix", "item_count": 3, "playlist_count": 3, "output_ext": "mp4"},
    "status": "완료",
    "messages": [],
}
for index in range(3):
    window.rows.append({
        "id": f"playlist-1-child-{index}",
        "kind": "video",
        "candidate": {"title": f"Video {index}", "display_title": f"Video {index}", "ext": "mp4", "output_ext": "mp4"},
        "parent_playlist_id": "playlist-1",
        "is_playlist_child": True,
        "status": "완료",
        "output_path": "",
        "messages": [],
    })
dialog = window._create_delete_confirm_dialog(Path("C:/Temp/Road Mix"), parent)
labels = [label.text() for label in dialog.findChildren(QLabel)]
print(dialog.windowTitle() == "재생목록 삭제")
print(any("재생목록" in text for text in labels))
print(any("하위 파일 3개" in text for text in labels))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True"])

    def test_clipflow_qt_playlist_folder_delete_removes_parent_and_children_from_list(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
window = ClipFlowWindow(confirm_delete_func=lambda path: True)
window._set_save_folder(tempdir.name)
playlist_folder = Path(tempdir.name) / "Road Mix"
playlist_folder.mkdir()
(playlist_folder / "One.mp4").write_bytes(b"one")
parent = {
    "id": "playlist-1",
    "kind": "playlist",
    "candidate": {"media_type": "playlist", "title": "Road Mix", "display_title": "Road Mix", "output_ext": "mp4"},
    "qualities": [],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "status": COMPLETED_STATUS,
    "status_detail": "",
    "progress": 100,
    "progress_text": "",
    "output_path": "",
    "messages": [],
    "created_order": 1,
    "expanded": True,
    "playlist_entries": [],
}
child = {
    "id": "playlist-1-child-1",
    "kind": "video",
    "candidate": {"id": "one", "title": "One", "display_title": "One", "source": "https://media.test/one", "url": "https://media.test/one", "ext": "mp4", "output_ext": "mp4"},
    "qualities": [],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "status": COMPLETED_STATUS,
    "status_detail": "",
    "progress": 100,
    "progress_text": "",
    "output_path": str(playlist_folder / "One.mp4"),
    "messages": [],
    "created_order": 2,
    "parent_playlist_id": "playlist-1",
    "is_playlist_child": True,
    "playlist_child_index": 1,
}
window.rows = [parent, child]
window._render_rows()
window.delete_file_for_row(parent)
print(playlist_folder.exists())
print(window.rows)
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "[]"])

    def test_clipflow_qt_playlist_info_text_does_not_show_count_without_duration(self):
        script = r'''
from tools.clipflow_rows import row_info_text

print(row_info_text({"media_type": "playlist", "item_count": 7}))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [""])

    def test_clipflow_qt_playlist_analysis_uses_parent_and_indented_child_rows(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest
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
    downloaded.append([page_url, candidate.get("media_type")])
    return {"ok": True, "output_dir": output_dir}

app = QApplication([])
window = ClipFlowWindow(download_func=fake_download)
window.resize(720, 420)
window.show()
app.processEvents()
window.folder_input.setText(tempdir.name)
window.url_input.setText(url)
window._analysis_finished(fake_analysis())
app.processEvents()
parent = window.rows[0]
parent_widget = parent["widget"]
child = window.rows[1] if len(window.rows) > 1 else {}
child_widget = child.get("widget") if isinstance(child, dict) else None

print(len(window.rows))
print([row["kind"] for row in window.rows])
print([bool(row.get("is_playlist_child")) for row in window.rows])
print([row.get("parent_playlist_id") == parent["id"] for row in window.rows[1:]])
print(parent["candidate"]["media_type"])
print(parent["candidate"]["item_count"])
print(parent_widget.playlist_detail_label.isHidden())
print(parent_widget.playlist_pill.isVisible())
print(parent_widget.playlist_toggle_button.isHidden())
QTest.mouseClick(parent_widget, Qt.LeftButton, pos=QPoint(180, parent_widget.height() // 2))
app.processEvents()
print([row.get("render_widget").isHidden() for row in window.rows[1:]])
QTest.mouseClick(parent["widget"], Qt.LeftButton, pos=QPoint(180, parent["widget"].height() // 2))
app.processEvents()
print([not row.get("render_widget").isHidden() for row in window.rows[1:]])
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
                "3",
                "['playlist', 'video', 'video']",
                "[False, True, True]",
                "[True, True]",
                "playlist",
                "2",
                "True",
                "True",
                "True",
                "[True, True]",
                "[True, True]",
                "[['https://media.test/watch/1', None], ['https://media.test/watch/2', None]]",
            ],
        )

    def test_clipflow_qt_playlist_parent_hides_quality_and_format_label(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/playlist/meta"
app = QApplication([])
window = ClipFlowWindow()
window.resize(720, 420)
window.show()
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Meta Mix",
    "playlist_title": "Meta Mix",
    "is_playlist": True,
    "playlist_count": 1,
    "candidates": [
        {"id": "one", "source": "https://media.test/watch/1", "url": "https://media.test/watch/1", "title": "One", "display_title": "One", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 60, "sort_bytes": 10},
    ],
    "warnings": [],
})
app.processEvents()
parent_widget = window.rows[0]["widget"]
child_widget = window.rows[1]["widget"]
parent_widget._set_hovered(True)
print(parent_widget.row_quality_label.isHidden())
print(parent_widget.row_quality_label.text())
print(child_widget.row_quality_label.isVisible())
print(parent_widget.actions_widget.isVisible())
print(parent_widget.remove_button.isVisible())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "", "True", "True", "True"])

    def test_clipflow_qt_playlist_parent_shows_total_duration_and_count_pill(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/playlist/meta"
app = QApplication([])
window = ClipFlowWindow()
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Meta Mix",
    "playlist_title": "Meta Mix",
    "is_playlist": True,
    "playlist_count": 2,
    "candidates": [
        {"id": "one", "source": "https://media.test/watch/1", "url": "https://media.test/watch/1", "title": "One", "display_title": "One", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 60, "sort_bytes": 10},
        {"id": "two", "source": "https://media.test/watch/2", "url": "https://media.test/watch/2", "title": "Two", "display_title": "Two", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 20},
    ],
    "warnings": [],
})
app.processEvents()
parent = window.rows[0]
parent_widget = parent["widget"]
print(parent_widget.info_label.text())
print("2" in parent_widget.playlist_pill.text())
print(parent_widget.row_quality_label.text())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["00:03:00", "True", ""])

    def test_clipflow_qt_child_delete_refreshes_playlist_parent_totals(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS

app = QApplication([])
window = ClipFlowWindow()
parent = {
    "id": "playlist-1",
    "kind": "playlist",
    "candidate": {"media_type": "playlist", "title": "Mix", "display_title": "Mix", "duration": 180, "sort_bytes": 30, "item_count": 2, "playlist_count": 2, "output_ext": "mp4", "ext": "mp4"},
    "qualities": [],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "status": COMPLETED_STATUS,
    "status_detail": "",
    "progress": 100,
    "progress_text": "",
    "output_path": "",
    "messages": [],
    "created_order": 1,
    "expanded": True,
    "playlist_entries": [],
}
child_one = {
    "id": "playlist-1-child-1",
    "kind": "video",
    "candidate": {"id": "one", "title": "One", "display_title": "One", "source": "https://media.test/one", "url": "https://media.test/one", "duration": 60, "sort_bytes": 10, "ext": "mp4", "output_ext": "mp4"},
    "qualities": [],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "status": COMPLETED_STATUS,
    "status_detail": "",
    "progress": 100,
    "progress_text": "",
    "output_path": "",
    "messages": [],
    "created_order": 2,
    "parent_playlist_id": "playlist-1",
    "is_playlist_child": True,
    "playlist_child_index": 1,
}
child_two = {
    **child_one,
    "id": "playlist-1-child-2",
    "candidate": {"id": "two", "title": "Two", "display_title": "Two", "source": "https://media.test/two", "url": "https://media.test/two", "duration": 120, "sort_bytes": 20, "ext": "mp4", "output_ext": "mp4"},
    "created_order": 3,
    "playlist_child_index": 2,
}
window.rows = [parent, child_one, child_two]
window._render_rows()
window._remove_rows_after_file_delete(child_one)
parent_widget = parent["widget"]
print(parent["candidate"]["duration"])
print(parent["candidate"]["item_count"])
print(parent_widget.info_label.text())
print("1" in parent_widget.playlist_pill.text())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["120", "1", "00:02:00", "True"])

    def test_clipflow_qt_playlist_analysis_shows_loading_child_row_while_running(self):
        script = r'''
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/playlist/loading"

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    time.sleep(0.25)
    return {
        "webpage_url": url,
        "url": url,
        "title": "Loading Mix",
        "playlist_title": "Loading Mix",
        "is_playlist": True,
        "playlist_count": 1,
        "candidates": [
            {"id": "one", "source": "https://media.test/watch/1", "url": "https://media.test/watch/1", "title": "One", "display_title": "One", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 60, "sort_bytes": 10},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow(analyze_func=fake_analyze)
window.url_input.setText(url)
window._start_analysis()
app.processEvents()
parent_id = window.rows[0].get("id") if window.rows else ""
print(len(window.rows))
print(window.rows[0].get("kind") if window.rows else "")
print(bool(len(window.rows) > 1 and window.rows[1].get("child_loading")))
print(bool(len(window.rows) > 1 and window.rows[1].get("parent_playlist_id") == parent_id))

def drive():
    if window.analysis_thread:
        return
    print([bool(row.get("child_loading")) for row in window.rows])
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
            ["2", "playlist", "True", "True", "[False, False]"],
        )

    def test_clipflow_qt_playlist_child_row_downloads_individual_video(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

downloaded = []
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

app = QApplication([])
window = ClipFlowWindow()
window.url_input.setText(url)
window._analysis_finished(fake_analysis())

def begin(row, candidate=None):
    candidate = candidate or window.selected_candidate_for_row_ref(row)
    downloaded.append([row.get("source_url"), candidate.get("id"), candidate.get("media_type", "video")])

window._begin_download = begin
window.select_row(1)
window._handle_primary_action()
print(downloaded)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["[['https://media.test/watch/1', 'one', 'video']]"],
        )

    def test_clipflow_qt_playlist_parent_queues_child_rows_not_parent_download(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

started = []
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

app = QApplication([])
window = ClipFlowWindow()
window.url_input.setText(url)
window._analysis_finished(fake_analysis())

def begin(row, candidate=None):
    candidate = candidate or window.selected_candidate_for_row_ref(row)
    started.append([row.get("id"), row.get("parent_playlist_id"), candidate.get("id"), candidate.get("media_type", "video")])

window._begin_download = begin
window.select_row(0)
window._handle_primary_action()
print(started)
print(window.rows[0]["status"])
print([row["status"] for row in window.rows[1:]])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "[['playlist-1-child-1', 'playlist-1', 'one', 'video'], ['playlist-1-child-2', 'playlist-1', 'two', 'video']]",
                "다운로드 중",
                "['다운로드 중', '다운로드 중']",
            ],
        )

    def test_clipflow_qt_playlist_parent_reflects_child_errors(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS, ERROR_STATUS

url = "https://media.test/playlist/road"

app = QApplication([])
window = ClipFlowWindow()
window._analysis_finished({
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
})
parent = window.rows[0]
window.rows[1]["status"] = COMPLETED_STATUS
window.rows[1]["progress"] = 100
window.rows[2]["status"] = ERROR_STATUS
window.rows[2]["progress"] = 0
window._refresh_playlist_parent_status(parent)
print(parent["status"])
print(parent["status_detail"])
print(parent["progress"])
print(parent["progress_text"])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["오류", "1/2", "50", "1/2"],
        )

    def test_clipflow_qt_playlist_parent_progress_uses_known_count_during_progressive_analysis(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS, WAITING_STATUS

url = "https://media.test/playlist/progressive"

app = QApplication([])
window = ClipFlowWindow()
window._handle_analysis_event({"type": "playlist_parent", "title": "Progressive Mix", "count": 8, "source_url": url})
parent = window.rows[0]
parent["analysis_loading"] = True

for index in range(1, 6):
    completed = index <= 3
    window.rows.append({
        "id": f"{parent['id']}-child-{index}",
        "kind": "video",
        "candidate": {
            "id": str(index),
            "source": f"https://media.test/watch/{index}",
            "url": f"https://media.test/watch/{index}",
            "title": f"Video {index}",
            "display_title": f"Video {index}",
            "thumbnail": "",
            "ext": "mp4",
            "output_ext": "mp4",
            "duration": 60,
            "sort_bytes": 10,
        },
        "qualities": [],
        "quality_options": [],
        "selected_index": 0,
        "selected_format_index": 0,
        "analysis_source_url": f"https://media.test/watch/{index}",
        "source_url": f"https://media.test/watch/{index}",
        "input_url": f"https://media.test/watch/{index}",
        "status": COMPLETED_STATUS if completed else WAITING_STATUS,
        "status_detail": "",
        "progress": 100 if completed else 0,
        "progress_text": "",
        "output_path": "",
        "messages": [],
        "created_order": index,
        "parent_playlist_id": parent["id"],
        "is_playlist_child": True,
        "playlist_child_index": index,
        "playlist_key": parent.get("playlist_key"),
    })

window._refresh_playlist_parent_status(parent)
print(parent["candidate"]["item_count"])
print(parent["status_detail"])
print(parent["progress"])
print(parent["progress_text"])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["8", "3/8", "37", "37%"])

    def test_clipflow_qt_download_thread_finish_refreshes_all_playlist_parents(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS, DOWNLOAD_STATUS

url = "https://media.test/playlist/road"
app = QApplication([])
window = ClipFlowWindow()
window._analysis_finished({
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
})
parent = window.rows[0]
for child in window.rows[1:]:
    child["status"] = COMPLETED_STATUS
    child["progress"] = 100
parent["status"] = DOWNLOAD_STATUS
parent["progress"] = 25
parent["progress_text"] = "25%"
parent["widget"].set_status(DOWNLOAD_STATUS)
parent["widget"].set_progress(25, "25%")
window.active_downloads = []
window.queued_download_rows = []
window._download_thread_finished_for(None, None)
print(parent["status"])
print(parent["progress"])
print(parent["progress_text"])
print(parent["widget"].progress_text.text())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["완료", "100", "", ""])

    def test_clipflow_qt_download_worker_callbacks_run_on_ui_thread(self):
        script = r'''
import time
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

def fake_download(page_url, candidate, output_dir, cookie_source=None, on_event=None):
    if on_event:
        on_event({"type": "progress", "percent": 12, "message": "12%"})
    return {"output_dir": str(output_dir)}

app = QApplication([])
window = ClipFlowWindow()
window.download_func = fake_download
row = {
    "id": "row-1",
    "kind": "video",
    "candidate": {"id": "row-1", "source": "https://media.test/watch/1", "url": "https://media.test/watch/1", "title": "One", "display_title": "One", "thumbnail": "", "ext": "mp4", "output_ext": "mp4"},
    "qualities": [{"id": "row-1", "source": "https://media.test/watch/1", "url": "https://media.test/watch/1", "title": "One", "display_title": "One", "thumbnail": "", "ext": "mp4", "output_ext": "mp4"}],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "analysis_source_url": "https://media.test/watch/1",
    "source_url": "https://media.test/watch/1",
    "input_url": "https://media.test/watch/1",
    "status": "",
    "status_detail": "",
    "progress": 0,
    "progress_text": "",
    "output_path": "",
    "messages": [],
    "created_order": 1,
}
window.rows = [row]
callback_threads = []

def capture_event(download_row, event):
    callback_threads.append(QThread.currentThread() is app.thread())

def capture_finished(download_row, result):
    callback_threads.append(QThread.currentThread() is app.thread())

window._handle_engine_event_for = capture_event
window._download_finished_for = capture_finished
window.start_download_for_row(row)
deadline = time.time() + 5
while window.active_downloads and time.time() < deadline:
    app.processEvents()
    time.sleep(0.01)
app.processEvents()
print(callback_threads)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "[True, True]")

    def test_clipflow_qt_completed_history_saves_playlist_parent_with_completed_children(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS, DOWNLOAD_STATUS

app = QApplication([])
window = ClipFlowWindow()
parent = {
    "id": "playlist-1",
    "kind": "playlist",
    "candidate": {"id": "playlist-1", "media_type": "playlist", "title": "Road Mix", "display_title": "Road Mix", "source": "https://media.test/playlist/road", "url": "https://media.test/playlist/road", "duration": 180, "sort_bytes": 30, "item_count": 2, "playlist_count": 2, "output_ext": "mp4", "ext": "mp4"},
    "qualities": [],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "analysis_source_url": "https://media.test/playlist/road",
    "source_url": "https://media.test/playlist/road",
    "playlist_key": "playlist:road",
    "status": DOWNLOAD_STATUS,
    "status_detail": "1/2",
    "progress": 50,
    "progress_text": "50%",
    "output_path": "",
    "messages": [],
    "created_order": 1,
    "expanded": True,
    "playlist_entries": [],
}
child = {
    "id": "playlist-1-child-1",
    "kind": "video",
    "candidate": {"id": "one", "title": "One", "display_title": "One", "source": "https://media.test/watch/1", "url": "https://media.test/watch/1", "duration": 60, "sort_bytes": 10, "ext": "mp4", "output_ext": "mp4"},
    "qualities": [],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "analysis_source_url": "https://media.test/watch/1",
    "source_url": "https://media.test/watch/1",
    "playlist_key": "playlist:road",
    "parent_playlist_id": "playlist-1",
    "is_playlist_child": True,
    "playlist_child_index": 1,
    "status": COMPLETED_STATUS,
    "status_detail": "",
    "progress": 100,
    "progress_text": "",
    "output_path": "C:/Temp/One.mp4",
    "messages": [],
    "created_order": 2,
}
window.rows = [parent, child]
payload = window._completed_history_payload()
print(len(payload))
print([item.get("candidate", {}).get("media_type") for item in payload])
parent = next((item for item in payload if item.get("candidate", {}).get("media_type") == "playlist"), None)
child_payload = next((item for item in payload if item.get("is_playlist_child")), None)
print(parent is not None)
print(bool(parent and child_payload and child_payload["parent_playlist_id"] == parent["candidate"]["id"]))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["2", "['playlist', None]", "True", "True"])

    def test_clipflow_qt_restores_orphan_playlist_children_with_synthetic_parent(self):
        script = r'''
import json
import os
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, DOWNLOAD_HISTORY_SETTING

app = QApplication([])
settings = QSettings(os.environ.get("CLIPFLOW_SETTINGS_ORG", "ClipFlow"), os.environ.get("CLIPFLOW_SETTINGS_APP", "ClipFlow"))
settings.setValue(DOWNLOAD_HISTORY_SETTING, json.dumps([
    {
        "candidate": {"id": "one", "title": "One", "display_title": "One", "source": "https://media.test/watch/1", "url": "https://media.test/watch/1", "duration": 60, "sort_bytes": 10, "ext": "mp4", "output_ext": "mp4"},
        "source_url": "https://media.test/watch/1",
        "analysis_source_url": "https://media.test/watch/1",
        "playlist_key": "playlist:road",
        "parent_playlist_id": "playlist-missing",
        "is_playlist_child": True,
        "playlist_child_index": 1,
        "output_path": "C:/Temp/One.mp4",
        "created_order": 2,
        "messages": [],
    },
    {
        "candidate": {"id": "two", "title": "Two", "display_title": "Two", "source": "https://media.test/watch/2", "url": "https://media.test/watch/2", "duration": 120, "sort_bytes": 20, "ext": "mp4", "output_ext": "mp4"},
        "source_url": "https://media.test/watch/2",
        "analysis_source_url": "https://media.test/watch/2",
        "playlist_key": "playlist:road",
        "parent_playlist_id": "playlist-missing",
        "is_playlist_child": True,
        "playlist_child_index": 2,
        "output_path": "C:/Temp/Two.mp4",
        "created_order": 3,
        "messages": [],
    },
], ensure_ascii=False))
settings.sync()
window = ClipFlowWindow()
persisted = json.loads(settings.value(DOWNLOAD_HISTORY_SETTING, "[]", str) or "[]")
print([(row.get("kind"), row.get("is_playlist_child"), row.get("parent_playlist_id")) for row in window.rows])
print(len(window._visible_rows()))
print(window.count_label.text())
print(window.rows[0]["candidate"]["item_count"])
print(window.rows[0]["candidate"]["duration"])
print(sum(1 for item in persisted if item.get("candidate", {}).get("media_type") == "playlist"))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "[('playlist', False, ''), ('video', True, 'playlist-missing'), ('video', True, 'playlist-missing')]",
                "3",
                "3개",
                "2",
                "180",
                "1",
            ],
        )

    def test_clipflow_qt_playlist_child_uses_parent_folder_existing_file(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow
from tools import downloader_engine as engine

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
window = ClipFlowWindow()
window.folder_input.setText(tempdir.name)
parent = {
    "id": "playlist-1",
    "kind": "playlist",
    "candidate": {"media_type": "playlist", "title": "Road Mix", "display_title": "Road Mix"},
}
child = {
    "id": "child-1",
    "kind": "video",
    "parent_playlist_id": "playlist-1",
    "is_playlist_child": True,
    "candidate": {
        "title": "Channel - Episode One",
        "display_title": "Channel - Episode One",
        "ext": "mp4",
        "output_ext": "mp4",
        "sort_bytes": 10,
    },
    "status": "준비",
}
window.rows = [parent, child]
playlist_dir = Path(tempdir.name) / "Road Mix"
playlist_dir.mkdir()
existing = engine.final_output_path_for_candidate(child["candidate"], playlist_dir)
existing.write_bytes(b"x" * 100)
print(window._output_dir_for_row(child, child["candidate"]))
print(window._existing_output_path_for_row(child, child["candidate"]))
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertTrue(lines[0].endswith("Road Mix"))
        self.assertTrue(lines[1].endswith("Channel - Episode One.mp4"))

    def test_clipflow_qt_playlist_child_rejects_smaller_title_matched_partial_file(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
window = ClipFlowWindow()
window.folder_input.setText(tempdir.name)
parent = {
    "id": "playlist-1",
    "kind": "playlist",
    "candidate": {"media_type": "playlist", "title": "Road Mix", "display_title": "Road Mix"},
}
child = {
    "id": "child-1",
    "kind": "video",
    "parent_playlist_id": "playlist-1",
    "is_playlist_child": True,
    "candidate": {
        "title": "Channel - Episode One",
        "display_title": "Channel - Episode One",
        "ext": "mp4",
        "output_ext": "mp4",
        "sort_bytes": 200 * 1024 * 1024,
    },
    "status": "준비",
}
window.rows = [parent, child]
playlist_dir = Path(tempdir.name) / "Road Mix"
playlist_dir.mkdir()
existing = playlist_dir / "Episode One.mp4"
existing.write_bytes(b"x" * 1024)
print(window._existing_output_path_for_row(child, child["candidate"]))
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "None")

    def test_clipflow_qt_streaming_playlist_events_keep_collapsed_parent_collapsed(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
source_url = "https://media.test/playlist/events"
window.url_input.setText(source_url)
window._handle_analysis_event({"type": "playlist_parent", "title": "Events", "count": 2, "source_url": source_url})
window._handle_analysis_event({"type": "playlist_entry_loading", "index": 1, "source_url": source_url})
parent = window.rows[0]
parent["expanded"] = False
window.playlist_expansion_changed(parent)
print(parent["expanded"])
print([row["render_widget"].isHidden() for row in window.rows[1:]])
window._handle_analysis_event({
    "type": "playlist_entry",
    "index": 1,
    "source_url": source_url,
    "candidates": [{
        "id": "one",
        "source": "https://media.test/watch/1",
        "url": "https://media.test/watch/1",
        "title": "One",
        "display_title": "One",
        "thumbnail": "",
        "ext": "mp4",
        "output_ext": "mp4",
        "resolution": "1080p",
        "height": 1080,
        "duration": 60,
        "sort_bytes": 10,
    }],
})
print(parent["expanded"])
print([row["render_widget"].isHidden() for row in window.rows[1:]])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "[True]", "False", "[True, True]"])

    def test_clipflow_qt_remove_playlist_parent_removes_child_rows_from_list(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, READY_STATUS

app = QApplication([])
window = ClipFlowWindow()
parent = {"id": "playlist-1", "kind": "playlist", "candidate": {"media_type": "playlist", "title": "Road Mix", "display_title": "Road Mix"}, "status": READY_STATUS, "messages": [], "expanded": True}
child = {"id": "child-1", "kind": "video", "parent_playlist_id": "playlist-1", "is_playlist_child": True, "candidate": {"title": "One", "display_title": "One"}, "status": READY_STATUS, "messages": []}
window.rows = [parent, child]
window._render_rows()
window.remove_row(parent)
print(window.rows)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "[]")

    def test_clipflow_qt_playlist_parent_delete_does_not_delete_save_folder_when_names_match(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS

app = QApplication([])
outer = tempfile.TemporaryDirectory()
save_folder = Path(outer.name) / "Road Mix"
save_folder.mkdir()
output = save_folder / "One.mp4"
output.write_bytes(b"one")
unrelated = save_folder / "Unrelated"
unrelated.mkdir()
(unrelated / "keep.txt").write_text("keep", encoding="utf-8")
window = ClipFlowWindow(confirm_delete_func=lambda path: True)
window._set_save_folder(str(save_folder))
parent = {"id": "playlist-1", "kind": "playlist", "candidate": {"media_type": "playlist", "title": "Road Mix", "display_title": "Road Mix", "output_ext": "mp4"}, "status": COMPLETED_STATUS, "messages": [], "expanded": True, "playlist_entries": []}
child = {"id": "child-1", "kind": "video", "parent_playlist_id": "playlist-1", "is_playlist_child": True, "candidate": {"title": "One", "display_title": "One", "ext": "mp4", "output_ext": "mp4"}, "status": COMPLETED_STATUS, "output_path": str(output), "messages": []}
window.rows = [parent, child]
window._render_rows()
window.delete_file_for_row(parent)
print(save_folder.exists())
print(output.exists())
print((unrelated / "keep.txt").exists())
print(window.rows)
outer.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "False", "True", "[]"])

    def test_clipflow_qt_playlist_parent_reuses_existing_playlist_rows(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/watch?v=one&list=PLROAD"
downloaded = []

def analysis(title):
    return {
        "webpage_url": url,
        "url": url,
        "title": title,
        "playlist_title": title,
        "is_playlist": True,
        "playlist_count": 2,
        "candidates": [
            {"id": "one", "source": "https://media.test/watch/1", "url": "https://media.test/watch/1", "title": "One", "display_title": "One", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 60, "sort_bytes": 10},
            {"id": "two", "source": "https://media.test/watch/2", "url": "https://media.test/watch/2", "title": "Two", "display_title": "Two", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 20},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow()
window.url_input.setText(url)
window._analysis_finished(analysis("Road Mix"))
first_ids = [row["id"] for row in window.rows]
window._analysis_finished(analysis("Road Mix"))
print(len(window.rows))
print([row["id"] for row in window.rows] == first_ids)
print([row["candidate"].get("display_title") for row in window.rows])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["3", "True", "['Road Mix', 'One', 'Two']"],
        )

    def test_clipflow_qt_playlist_dedupe_matches_legacy_rows_without_key(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/watch?v=one&list=PLROAD"
same_playlist_url = "https://media.test/watch?v=two&list=PLROAD"

app = QApplication([])
window = ClipFlowWindow()
legacy_parent = {
    "id": "legacy-playlist",
    "kind": "playlist",
    "candidate": {"url": url, "source": url, "display_title": "Road Mix", "media_type": "playlist"},
    "analysis_source_url": url,
    "source_url": url,
    "status": "완료",
    "created_order": 1,
    "expanded": True,
}
window.rows = [legacy_parent]
print(window._first_visible_analyzed_row_index_for_url(same_playlist_url))
print(window._find_playlist_parent_for_analysis({"url": same_playlist_url, "is_playlist": True}, same_playlist_url)["id"])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["0", "legacy-playlist"],
        )

    def test_clipflow_qt_playlist_child_card_frame_is_indented(self):
        script = r'''
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/playlist/road"

def fake_analysis():
    return {
        "webpage_url": url,
        "url": url,
        "title": "Road Trip Mix",
        "playlist_title": "Road Trip Mix",
        "is_playlist": True,
        "playlist_count": 1,
        "candidates": [
            {"id": "one", "source": "https://media.test/watch/1", "url": "https://media.test/watch/1", "title": "One", "display_title": "One", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 60, "sort_bytes": 10},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow()
window.resize(720, 420)
window.show()
app.processEvents()
window.url_input.setText(url)
window._analysis_finished(fake_analysis())
app.processEvents()
parent_widget = window.rows[0]["widget"]
child_widget = window.rows[1]["widget"]
parent_x = parent_widget.mapTo(window.row_container, QPoint(0, 0)).x()
child_x = child_widget.mapTo(window.row_container, QPoint(0, 0)).x()
print(child_x > parent_x)
print(18 <= child_x - parent_x <= 40)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True"])

    def test_clipflow_qt_playlist_expand_collapse_reuses_child_widgets(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/playlist/road"

app = QApplication([])
window = ClipFlowWindow()
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Road Trip Mix",
    "playlist_title": "Road Trip Mix",
    "is_playlist": True,
    "playlist_count": 2,
    "candidates": [
        {"id": "one", "source": "https://media.test/watch/1", "url": "https://media.test/watch/1", "title": "One", "display_title": "One", "thumbnail": "https://img.test/one.jpg", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 60, "sort_bytes": 10},
        {"id": "two", "source": "https://media.test/watch/2", "url": "https://media.test/watch/2", "title": "Two", "display_title": "Two", "thumbnail": "https://img.test/two.jpg", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 20},
    ],
    "warnings": [],
})
first_child_widget = window.rows[1]["widget"]
first_child_render_widget = window.rows[1]["render_widget"]
window.rows[0]["expanded"] = False
window.playlist_expansion_changed(window.rows[0])
print(window.rows[1]["widget"] is first_child_widget)
print(window.rows[1]["render_widget"] is first_child_render_widget)
print(first_child_render_widget.isHidden())
window.rows[0]["expanded"] = True
window.playlist_expansion_changed(window.rows[0])
print(window.rows[1]["widget"] is first_child_widget)
print(window.rows[1]["render_widget"] is first_child_render_widget)
print(not first_child_render_widget.isHidden())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True", "True", "True", "True"])

    def test_clipflow_qt_playlist_render_keeps_collapsed_children_in_layout(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/playlist/road"

app = QApplication([])
window = ClipFlowWindow()
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Road Trip Mix",
    "playlist_title": "Road Trip Mix",
    "is_playlist": True,
    "playlist_count": 2,
    "candidates": [
        {"id": "one", "source": "https://media.test/watch/1", "url": "https://media.test/watch/1", "title": "One", "display_title": "One", "thumbnail": "https://img.test/one.jpg", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 60, "sort_bytes": 10},
        {"id": "two", "source": "https://media.test/watch/2", "url": "https://media.test/watch/2", "title": "Two", "display_title": "Two", "thumbnail": "https://img.test/two.jpg", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 20},
    ],
    "warnings": [],
})
child_render_widgets = [row["render_widget"] for row in window.rows[1:]]
window.rows[0]["expanded"] = False
window._render_rows()
print([window.row_layout.indexOf(widget) >= 0 for widget in child_render_widgets])
print([widget.isHidden() for widget in child_render_widgets])
render_calls = []
original_render = window._render_rows
def counted_render():
    render_calls.append(True)
    original_render()
window._render_rows = counted_render
window.rows[0]["expanded"] = True
window.playlist_expansion_changed(window.rows[0])
print(len(render_calls))
print([window.row_layout.indexOf(widget) >= 0 for widget in child_render_widgets])
print([not widget.isHidden() for widget in child_render_widgets])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["[True, True]", "[True, True]", "0", "[True, True]", "[True, True]"],
        )

    def test_clipflow_qt_active_playlist_parent_hover_shows_safe_action_overlay(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, DOWNLOAD_STATUS

app = QApplication([])
window = ClipFlowWindow()
row = window._playlist_parent_loading_row("https://media.test/playlist/hover")
row["analysis_loading"] = False
row["status"] = DOWNLOAD_STATUS
row["candidate"]["title"] = "Hover Mix"
row["candidate"]["display_title"] = "Hover Mix"
window.rows = [row]
window._render_rows()
window.show()
app.processEvents()
widget = row["widget"]
widget._set_hovered(True)
print(widget.actions_widget.isVisible())
print(widget.remove_button.isEnabled())
print(widget.delete_file_button.isEnabled())
print(widget.open_folder_button.isEnabled())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "False", "False", "False"])

    def test_clipflow_qt_playlist_title_click_toggles_children(self):
        script = r'''
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/playlist/title-click"
app = QApplication([])
window = ClipFlowWindow()
window.resize(720, 420)
window.show()
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Click Mix",
    "playlist_title": "Click Mix",
    "is_playlist": True,
    "playlist_count": 1,
    "candidates": [
        {"id": "one", "source": "https://media.test/watch/1", "url": "https://media.test/watch/1", "title": "One", "display_title": "One", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 60, "sort_bytes": 10},
    ],
    "warnings": [],
})
app.processEvents()
parent = window.rows[0]
child = window.rows[1]
QTest.mouseClick(parent["widget"].title_label, Qt.LeftButton, pos=QPoint(10, parent["widget"].title_label.height() // 2))
app.processEvents()
print(parent["expanded"])
print(child["render_widget"].isHidden())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "True"])

    def test_clipflow_qt_legacy_playlist_parent_click_starts_analysis(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS

url = "https://www.youtube.com/playlist?list=PLLEGACY"
app = QApplication([])
window = ClipFlowWindow()
candidate = {
    "id": "playlist-old",
    "media_type": "playlist",
    "title": "Legacy Mix",
    "display_title": "Legacy Mix",
    "source": url,
    "url": url,
    "webpage_url": url,
    "playlist_count": 3,
    "item_count": 3,
}
parent = {
    "id": "playlist-old",
    "kind": "playlist",
    "candidate": candidate,
    "qualities": [candidate],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "analysis_source_url": url,
    "source_url": url,
    "playlist_key": "youtube.com:list:PLLEGACY",
    "status": COMPLETED_STATUS,
    "status_detail": "",
    "progress": 100,
    "progress_text": "",
    "output_path": "",
    "messages": [],
    "created_order": 1,
    "expanded": True,
}
calls = []
window.rows = [parent]
window._render_rows()
window._start_analysis = lambda auto_download=False: calls.append([window.url_input.text(), auto_download])
parent["expanded"] = False
window.playlist_expansion_changed(parent)
print(calls)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["[['https://www.youtube.com/playlist?list=PLLEGACY', False]]"],
        )

    def test_clipflow_qt_playlist_entry_events_render_children_before_complete(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, ERROR_STATUS

app = QApplication([])
window = ClipFlowWindow()
window.url_input.setText("https://media.test/playlist/events")
window._start_analysis = lambda *args, **kwargs: None
source_url = "https://media.test/playlist/events"
window._handle_analysis_event({"type": "playlist_parent", "title": "Events", "count": 3, "source_url": source_url})
window._handle_analysis_event({"type": "playlist_entry_loading", "index": 1, "title": "Video 1", "source_url": source_url})
window._handle_analysis_event({
    "type": "playlist_entry",
    "index": 1,
    "source_url": source_url,
    "candidates": [{
        "id": "one",
        "source": "https://media.test/watch/1",
        "url": "https://media.test/watch/1",
        "title": "Video 1",
        "display_title": "Video 1",
        "thumbnail": "",
        "ext": "mp4",
        "output_ext": "mp4",
        "resolution": "1080p",
        "height": 1080,
        "duration": 60,
        "sort_bytes": 10,
    }],
})
print([(row.get("kind"), row.get("child_loading"), row.get("playlist_child_index")) for row in window.rows])
window._handle_analysis_event({"type": "playlist_failed_entry", "index": 2, "title": "Video 2", "source_url": "https://media.test/watch/2", "message": "HTTP 404"})
print([(row.get("candidate", {}).get("display_title"), row.get("status")) for row in window.rows if row.get("is_playlist_child") and not row.get("child_loading")])
window._handle_analysis_event({
    "type": "playlist_entry",
    "index": 3,
    "source_url": source_url,
    "candidates": [{
        "id": "three",
        "source": "https://media.test/watch/3",
        "url": "https://media.test/watch/3",
        "title": "Video 3",
        "display_title": "Video 3",
        "thumbnail": "",
        "ext": "mp4",
        "output_ext": "mp4",
        "resolution": "720p",
        "height": 720,
        "duration": 70,
        "sort_bytes": 12,
    }],
})
window._handle_analysis_event({"type": "playlist_complete", "count": 3, "source_url": source_url})
print(any(row.get("child_loading") for row in window.rows))
print([row.get("candidate", {}).get("display_title") for row in window.rows if row.get("is_playlist_child")])
print(ERROR_STATUS in [row.get("status") for row in window.rows])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "[('playlist', None, None), ('video', None, 1), ('video', True, 2)]",
                "[('Video 1', '준비'), ('Video 2', '오류')]",
                "False",
                "['Video 1', 'Video 2', 'Video 3']",
                "True",
            ],
        )

    def test_clipflow_qt_auto_download_starts_each_playlist_child_when_entry_finishes(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
window.url_input.setText("https://media.test/playlist/events")
started = []
window.start_download_for_row = lambda row: started.append(row.get("candidate", {}).get("display_title"))
window._analysis_auto_download = True
source_url = "https://media.test/playlist/events"
window._handle_analysis_event({"type": "playlist_parent", "title": "Events", "count": 2, "source_url": source_url})
window._handle_analysis_event({"type": "playlist_entry_loading", "index": 1, "title": "Video 1", "source_url": "https://media.test/watch/1"})
window._handle_analysis_event({
    "type": "playlist_entry",
    "index": 1,
    "source_url": "https://media.test/watch/1",
    "candidates": [{
        "id": "one",
        "source": "https://media.test/watch/1",
        "url": "https://media.test/watch/1",
        "title": "Video 1",
        "display_title": "Video 1",
        "thumbnail": "",
        "ext": "mp4",
        "output_ext": "mp4",
        "resolution": "1080p",
        "height": 1080,
        "duration": 60,
        "sort_bytes": 10,
    }],
})
print(started)
print(any(row.get("child_loading") and row.get("playlist_child_index") == 2 for row in window.rows))
window._handle_analysis_event({
    "type": "playlist_entry",
    "index": 2,
    "source_url": "https://media.test/watch/2",
    "candidates": [{
        "id": "two",
        "source": "https://media.test/watch/2",
        "url": "https://media.test/watch/2",
        "title": "Video 2",
        "display_title": "Video 2",
        "thumbnail": "",
        "ext": "mp4",
        "output_ext": "mp4",
        "resolution": "1080p",
        "height": 1080,
        "duration": 120,
        "sort_bytes": 20,
    }],
})
print(started)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["['Video 1']", "True", "['Video 1', 'Video 2']"])

    def test_clipflow_qt_playlist_float_button_stays_hidden_when_parent_visible(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/playlist/visible-parent"

app = QApplication([])
window = ClipFlowWindow()
window.resize(720, 420)
window.show()
app.processEvents()
window.url_input.setText(url)
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Visible Mix",
    "playlist_title": "Visible Mix",
    "is_playlist": True,
    "playlist_count": 8,
    "candidates": [
        {"id": str(index), "source": f"https://media.test/watch/{index}", "url": f"https://media.test/watch/{index}", "title": f"Video {index}", "display_title": f"Video {index}", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 60, "sort_bytes": 10}
        for index in range(8)
    ],
    "warnings": [],
})
app.processEvents()
parent = window.rows[0]
parent["expanded"] = False
window.playlist_expansion_changed(parent)
app.processEvents()
parent["expanded"] = True
window.playlist_expansion_changed(parent)
app.processEvents()
parent_top = parent["widget"].mapTo(window.scroll_area.viewport(), parent["widget"].rect().topLeft()).y()
parent_bottom = parent_top + parent["widget"].height()
print(parent_top >= 0)
print(parent_bottom > 0)
print(window.playlist_float_button.isVisible())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "False"])

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
row_widget = row["widget"]
row_top = row_widget.mapTo(window.row_container, QPoint(0, 0)).y()
print(row["expanded"])
print(abs(bar.value() - row_top) <= 2)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True", "False", "True"])

    def test_clipflow_qt_playlist_toggle_keeps_parent_viewport_position(self):
        script = r'''
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, READY_STATUS

url = "https://media.test/playlist/steady"

def fake_analysis():
    candidates = []
    for index in range(12):
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
        "title": "Steady Mix",
        "playlist_title": "Steady Mix",
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
app.processEvents()
for index in range(8):
    candidate = {
        "id": f"filler-{index}",
        "source": f"https://media.test/filler/{index}",
        "url": f"https://media.test/filler/{index}",
        "title": f"Filler {index}",
        "display_title": f"Filler {index}",
        "thumbnail": "",
        "ext": "mp4",
        "output_ext": "mp4",
        "resolution": "1080p",
        "height": 1080,
        "duration": 60,
        "sort_bytes": 10,
    }
    window.rows.append({
        "id": f"filler-{index}",
        "kind": "video",
        "candidate": candidate,
        "qualities": [candidate],
        "quality_options": [],
        "selected_index": 0,
        "selected_format_index": 0,
        "analysis_source_url": candidate["url"],
        "source_url": candidate["url"],
        "status": READY_STATUS,
        "status_detail": "",
        "progress": 0,
        "progress_text": "",
        "output_path": "",
        "messages": [],
        "created_order": 100 + index,
    })
window._render_rows()
app.processEvents()
row = next(row for row in window.rows if row.get("kind") == "playlist")
bar = window.scroll_area.verticalScrollBar()
row_top_in_content = row["render_widget"].mapTo(window.row_container, QPoint(0, 0)).y()
bar.setValue(max(bar.minimum(), min(bar.maximum(), row_top_in_content - 90)))
app.processEvents()
before = row["render_widget"].mapTo(window.scroll_area.viewport(), QPoint(0, 0)).y()
row["expanded"] = False
window.playlist_expansion_changed(row)
app.processEvents()
after_collapse = row["render_widget"].mapTo(window.scroll_area.viewport(), QPoint(0, 0)).y()
row["expanded"] = True
window.playlist_expansion_changed(row)
app.processEvents()
after_expand = row["render_widget"].mapTo(window.scroll_area.viewport(), QPoint(0, 0)).y()
print(abs(after_collapse - before) <= 2)
print(abs(after_expand - after_collapse) <= 2)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True"])

    def test_clipflow_qt_playlist_toggle_keeps_parent_row_height_stable(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/playlist/steady-height"

def fake_analysis():
    candidates = []
    for index in range(12):
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
        "title": "Steady Height",
        "playlist_title": "Steady Height",
        "is_playlist": True,
        "playlist_count": len(candidates),
        "candidates": candidates,
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow()
window.resize(720, 760)
window.show()
app.processEvents()
window.url_input.setText(url)
window._analysis_finished(fake_analysis())
app.processEvents()
row = next(row for row in window.rows if row.get("kind") == "playlist")
height_open = row["widget"].height()
row["expanded"] = False
window.playlist_expansion_changed(row)
app.processEvents()
height_closed = row["widget"].height()
row["expanded"] = True
window.playlist_expansion_changed(row)
app.processEvents()
height_reopened = row["widget"].height()
print(height_open)
print(height_closed)
print(height_reopened)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["72", "72", "72"])

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
