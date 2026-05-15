import os
import subprocess
import sys
import unittest


def run_qt_script(script, timeout=10):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    return subprocess.run(
        [sys.executable, "-c", script],
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
required = ["link", "folder", "x", "trash-2", "more-vertical", "clock", "file-text", "circle-help", "chevron-down", "play", "video", "cookie"]
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
                "붙여넣기",
                "쿠키: 없음",
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
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

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
window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
window.format_pref_combo.setCurrentText("WEBM")
window.url_input.setText("https://media.test/video")
window._start_analysis()

def drive():
    if window.analysis_thread or window.download_thread:
        return
    if window.rows and not started_download:
        started_download.append(True)
        row_widget = window.rows[0]["widget"]
        print(analyze_exts)
        print(window.quality_pref_combo.currentText())
        print(window.codec_pref_combo.currentText())
        print(window.frame_pref_combo.currentText())
        print(window.selected_candidate_for_row_ref(window.rows[0])["id"])
        print(row_widget.size_label.text())
        print(row_widget.info_label.text())
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
            ["['all']", "자동", "자동", "자동", "webm-1080", "40 B", "00:02:00", "webm-1080"],
        )

    def test_clipflow_qt_audio_format_disables_codec_and_frame_preferences(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
window.format_pref_combo.setCurrentText("MP3")
window._refresh_preference_controls()

print(window.codec_pref_combo.isEnabled())
print(window.frame_pref_combo.isEnabled())
window.format_pref_combo.setCurrentText("MP4")
window._refresh_preference_controls()
print(window.codec_pref_combo.isEnabled())
print(window.frame_pref_combo.isEnabled())
print(window.cookie_combo.maximumWidth() <= 190)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "False", "True", "True", "True"])

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
        print(row_widget.size_label.text())
        window.format_pref_combo.setCurrentText("WEBM")
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
            ["30 B", "40 B", "webm-1080"],
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
row_widget._set_hovered(False)
print(row_widget.actions_widget.isHidden())
print(row_widget.delete_file_button.property("danger"))
row_widget.site_button.click()
row_widget.domain_label.click()
print(opened)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["False", "False", "False", "True", "False", "True", "true", "['https://media.test/video', 'https://media.test/video']"],
        )

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
            ["0", "True", "84,92,160", "560x420", "True", "720x760"],
        )

    def test_clipflow_qt_sort_label_aligns_with_sort_dropdowns(self):
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
print(window.sort_label.height())
print(window.sort_order_combo.height())
print(abs(label_top - combo_top) <= 1)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["40", "40", "True"])

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
help_top = window.cookie_help_button.mapTo(window, QPoint(0, 0)).y()
primary_right = window.primary_button.mapTo(window, QPoint(0, 0)).x() + window.primary_button.width()
help_right = window.cookie_help_button.mapTo(window, QPoint(0, 0)).x() + window.cookie_help_button.width()

print(folder_box.height())
print(window.cookie_combo.height())
print(window.cookie_help_button.height())
print(abs(folder_top - cookie_top) <= 1)
print(abs(folder_top - help_top) <= 1)
print(abs(primary_right - help_right) <= 1)
print(window.primary_button.width())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["42", "42", "42", "True", "True", "True", "150"],
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
        row_widget.site_button.click()
        print(opened[0])
        print("media.test" in row_widget.site_button.toolTip())
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

    def test_clipflow_qt_url_click_clears_input_without_clearing_rows(self):
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
        app.quit()

timer = QTimer()
timer.timeout.connect(drive)
timer.start(20)
QTimer.singleShot(5000, app.quit)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["", "1", "붙여넣기"])


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
print(window.primary_button.text() == "분석")
window._handle_primary_action()

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


if __name__ == "__main__":
    unittest.main()
