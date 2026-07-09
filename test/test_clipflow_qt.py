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
from tools.clipflow_qt import ClipFlowWindow, _should_suppress_qt_message

print(APP_NAME)
print(bool(APP_STYLE))
print(callable(configure_app_font))
print(callable(create_app_icon))
print(CleanComboBox.__name__)
print(PathDisplayInput.__name__)
print(DownloadRowWidget.__name__)
print(callable(build_quality_options))
print(ClipFlowWindow.__name__)
print(_should_suppress_qt_message("QFont::setPointSize: Point size <= 0 (-1), must be greater than 0"))
print(_should_suppress_qt_message("QIODevice::read (QSslSocket): device not open"))
print(_should_suppress_qt_message("other warning"))
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
                "True",
                "True",
                "False",
            ],
        )

    def test_clipflow_entry_dispatches_analysis_worker_before_gui_import(self):
        script = r'''
import sys
import types
from tools import clipflow_entry

called = []

analysis_module = types.ModuleType("tools.clipflow_analysis_process")
analysis_module.main = lambda argv=None: called.append(list(argv or [])) or 17
gui_module = types.ModuleType("tools.clipflow_qt")
gui_module.main = lambda: (_ for _ in ()).throw(AssertionError("GUI should not import for analysis worker"))
sys.modules["tools.clipflow_analysis_process"] = analysis_module
sys.modules["tools.clipflow_qt"] = gui_module
sys.argv = ["ClipFlow.exe", "--clipflow-analysis-worker", "--persistent"]

print(clipflow_entry.main())
print(called)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["17", "[['--clipflow-analysis-worker', '--persistent']]"])

    def test_clipflow_spec_includes_analysis_worker_hidden_import(self):
        from pathlib import Path

        text = Path("build-helper/ClipFlow.spec").read_text(encoding="utf-8")
        self.assertIn("tools.clipflow_analysis_process", text)
        self.assertIn("tools.clipflow_download_process", text)
        self.assertIn("tools.clipflow_qt", text)

    def test_clipflow_qt_uses_bundled_lucide_icons(self):
        script = r'''
import tools.clipflow_widgets as widgets
from PySide6.QtWidgets import QApplication, QLabel
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
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel
from tools.clipflow_widgets import CleanComboBox, ComboPopup

app = QApplication([])
combo = CleanComboBox()
combo.addItems(["최신순", "이름순"])
popup_surface = ComboPopup(combo)
print(popup_surface.testAttribute(Qt.WA_TranslucentBackground))
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
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True", "True", "True", "True"])

    def test_clipflow_qt_clean_combo_popup_respects_center_alignment(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import CleanComboBox

app = QApplication([])
combo = CleanComboBox()
combo.addItems(["1", "2", "3"])
combo.text_alignment = Qt.AlignCenter
combo.show()
combo.showPopup()
app.processEvents()
print(combo._active_popup.styleSheet())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("text-align: center", result.stdout)

    def test_clipflow_qt_clean_switch_animates_knob_between_states(self):
        script = r'''
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import CleanSwitch

app = QApplication([])
switch = CleanSwitch()
switch.show()
app.processEvents()
print(switch.cursor().shape() == Qt.PointingHandCursor)
print(switch.knob_progress())
QTest.mouseClick(switch, Qt.LeftButton)
app.processEvents()
print(switch._knob_animation.state() == QAbstractAnimation.Running)
QTest.qWait(switch._knob_animation.duration() + 30)
print(switch.knob_progress())
print(switch.isChecked())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "0.0", "True", "1.0", "True"])

    def test_clipflow_qt_sort_combo_hides_inline_arrow(self):
        script = r'''
from PySide6.QtCore import Qt
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
        self.assertEqual(result.stdout.splitlines(), ["False", "True", "False"])

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

    def test_clipflow_qt_app_icon_uses_transparent_canvas(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_theme import create_app_icon

app = QApplication([])
image = create_app_icon(128).pixmap(128, 128).toImage()
corners = [
    image.pixelColor(0, 0).alpha(),
    image.pixelColor(127, 0).alpha(),
    image.pixelColor(0, 127).alpha(),
    image.pixelColor(127, 127).alpha(),
]
xs = []
ys = []
for y in range(128):
    for x in range(128):
        if image.pixelColor(x, y).alpha() > 0:
            xs.append(x)
            ys.append(y)
print(corners)
print(bool(xs))
edge = image.pixelColor(64, 10)
print(edge.alpha() > 0)
print(max(edge.red(), edge.green(), edge.blue()) < 40)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["[0, 0, 0, 0]", "True", "True", "True"])

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

    def test_primary_action_uses_plain_video_row_when_stale_segment_row_is_selected(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, READY_STATUS, COMPLETED_STATUS

app = QApplication([])
window = ClipFlowWindow()
url = "https://chzzk.naver.com/video/14056968"
base_candidate = {"id": "hls", "title": "Video", "display_title": "Video", "url": "https://media.test/master.m3u8", "ext": "mp4"}
segment_candidate = dict(base_candidate)
segment_candidate["clip_range"] = {"start": 18000, "end": 18960}
window.rows = [
    {"id": "base", "status": READY_STATUS, "source_url": url, "input_url": url, "candidate": base_candidate, "quality_options": [base_candidate], "selected_index": 0},
    {"id": "old-segment", "status": COMPLETED_STATUS, "source_url": url, "input_url": url, "candidate": segment_candidate, "quality_options": [segment_candidate], "selected_index": 0, "fixed_candidate": True, "output_path": "C:/missing/old-segment.mp4"},
]
window.url_input.setText(url)
window.selected_row_index = 1
started = []
window._start_download = lambda: started.append(window.rows[window.selected_row_index]["id"])
window._handle_primary_action()
print(started)
print(window.selected_row_index)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["['base']", "0"])

    def test_direct_download_from_clip_locked_row_preserves_saved_segment_when_clip_inputs_are_empty(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS

app = QApplication([])
window = ClipFlowWindow()
url = "https://chzzk.naver.com/video/14056968"
base_candidate = {"id": "hls", "title": "Video", "display_title": "Video", "url": "https://media.test/master.m3u8", "ext": "mp4", "output_ext": "mp4", "duration": 600}
clip_candidate = dict(base_candidate)
clip_candidate["clip_range"] = {"start": 120, "end": 480}
clip_candidate["display_title"] = "Video [02m00s-08m00s]"
row = {
    "id": "row",
    "status": COMPLETED_STATUS,
    "source_url": url,
    "input_url": url,
    "candidate": clip_candidate,
    "download_base_candidate": base_candidate,
    "quality_options": [clip_candidate],
    "selected_index": 0,
    "fixed_candidate": True,
    "output_path": "C:/Downloads/Video [02m00s-08m00s].mp4",
}
window.rows = [row]
window.url_input.setText(url)
prepared = window._candidate_for_download(row, row["candidate"])
print(prepared["display_title"])
print("clip_range" in prepared)
print(prepared["duration"])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["Video [02m00s-08m00s]", "True", "360"])

    def test_primary_action_does_not_treat_restored_clip_history_row_as_plain_download(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
url = "https://chzzk.naver.com/video/14056968"
restored_candidate = {
    "id": "hls",
    "title": "Video [02m00s-08m00s]",
    "display_title": "Video [02m00s-08m00s]",
    "source": url,
    "ext": "mp4",
    "output_ext": "mp4",
    "duration": 360,
    "source_duration": 600,
    "sort_bytes": 352500000,
    "source_filesize": 1000000000,
    "clip_range": {"start": 120, "end": 480},
}
row = window._history_row_from_item({
    "candidate": restored_candidate,
    "source_url": url,
    "output_path": "C:/Downloads/Video [02m00s-08m00s].mp4",
    "created_order": 1,
})
window.rows = [row]
window.url_input.setText(url)
window.selected_row_index = 0
calls = []
window._start_download = lambda: calls.append("download")
window._start_analysis = lambda auto_download=False: calls.append(["analyze", auto_download])
window._handle_primary_action()
print(bool(row.get("fixed_candidate")))
print(calls)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "[['analyze', True]]"])

    def test_different_clip_from_clip_locked_row_uses_new_clip_range_not_saved_segment(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS

app = QApplication([])
window = ClipFlowWindow()
url = "https://chzzk.naver.com/video/14056968"
base_candidate = {"id": "hls", "title": "Video", "display_title": "Video", "url": "https://media.test/master.m3u8", "ext": "mp4", "output_ext": "mp4", "duration": 600}
clip_candidate = dict(base_candidate)
clip_candidate["clip_range"] = {"start": 120, "end": 480}
clip_candidate["display_title"] = "Video [02m00s-08m00s]"
row = {
    "id": "row",
    "status": COMPLETED_STATUS,
    "source_url": url,
    "input_url": url,
    "candidate": clip_candidate,
    "download_base_candidate": base_candidate,
    "quality_options": [clip_candidate],
    "selected_index": 0,
    "fixed_candidate": True,
    "output_path": "C:/Downloads/Video [02m00s-08m00s].mp4",
}
window.rows = [row]
window.url_input.setText(url)
window._applied_clip_start_text = "00:09:00"
window._applied_clip_end_text = "00:10:00"
prepared = window._candidate_for_download(row, row["candidate"])
print(prepared["clip_range"])
print(prepared["display_title"])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["{'start': 540.0, 'end': 600.0}", "Video [09m00s-10m00s]"])

    def test_finishing_progress_event_keeps_finishing_state_without_percent_text(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, DOWNLOAD_STATUS
from tools.clipflow_rows import DownloadRowWidget

app = QApplication([])
window = ClipFlowWindow()
row = {"id": "row", "status": DOWNLOAD_STATUS, "candidate": {"title": "Video", "display_title": "Video"}}
widget = DownloadRowWidget(window, row)
row["widget"] = widget
window.rows = [row]
window._handle_engine_event_for(row, {"type": "progress", "percent": 100, "phase": "finishing", "message": "마무리 중", "eta_text": "01:20"})
print(row.get("download_finishing"))
print(row.get("progress_text"))
print(widget.property("finishing"))
print("%" in row.get("progress_text", ""))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "마무리 중 · ETA 01:20", "true", "False"])

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
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel
from tools.clipflow_qt import ClipFlowWindow, READY_STATUS
from tools.clipflow_widgets import CleanComboBox, CleanSwitch

app = QApplication([])
window = ClipFlowWindow()
window.resize(720, 520)
window.show()
window._create_preferences_dialog = lambda: (_ for _ in ()).throw(RuntimeError("dialog should not open"))
window.preference_button.click()
popup = window.preferences_popup
combos = popup.findChildren(CleanComboBox)
labels = [label.text() for label in popup.findChildren(QLabel)]
print(bool(popup and popup.isVisible()))
print(len(combos))
print(all(not combo.show_arrow for combo in combos))
print(window.preference_button.text())
print("병렬" in window.preference_button.toolTip())
print("병렬" in labels)
print("HDR" in labels)
print("프레임" in labels)
print(all(combo.toolTip() for combo in combos))
print(all(label.toolTip() for label in popup.findChildren(QLabel) if label.text() in {"화질", "포맷", "코덱", "HDR", "병렬"}))
print(popup.findChild(CleanSwitch).cursor().shape() == Qt.PointingHandCursor)
print(combos[-1].currentText())
button_right = window.preference_button.mapToGlobal(QPoint(window.preference_button.width(), 0)).x()
print(abs(popup.geometry().right() - button_right) <= 1)
combos[0].setCurrentText("720p")
combos[1].setCurrentText("WEBM")
combos[-1].setCurrentText("2")
print(window.current_preferences().quality)
print(window.current_preferences().output_format)
print(window.download_concurrency)
QTest.mouseClick(window.preference_button, Qt.LeftButton)
app.processEvents()
print(window.preferences_popup is None)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["True", "4", "True", "옵션", "True", "True", "True", "False", "True", "True", "True", "3", "True", "720p", "WEBM", "2", "True"],
        )

    def test_clipflow_qt_audio_format_disables_video_preferences(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
dialog = window._create_preferences_dialog()
dialog.format_combo.setCurrentText("MP3")
dialog.refresh_controls()
print(dialog.quality_combo.isEnabled())
print(dialog.codec_combo.isEnabled())
print(dialog.hdr_switch.isEnabled())
print(hasattr(dialog, "frame_combo"))
print(bool(dialog.quality_combo.toolTip()))
print(bool(dialog.format_combo.toolTip()))
print(bool(dialog.codec_combo.toolTip()))
print(bool(dialog.hdr_switch.toolTip()))
dialog.format_combo.setCurrentText("MP4")
dialog.refresh_controls()
print(dialog.quality_combo.isEnabled())
print(dialog.codec_combo.isEnabled())
print(dialog.hdr_switch.isEnabled())
print(dialog.preferences().frame_rate)
print(window.cookie_combo.maximumWidth() <= 142)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "False", "False", "False", "True", "True", "True", "True", "True", "True", "True", "자동", "True"])

    def test_clipflow_qt_extract_audio_converts_existing_file_without_redownloading(self):
        script = r'''
import tempfile
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools import downloader_engine as engine
from tools.clipflow_qt import ClipFlowWindow

tempdir = tempfile.TemporaryDirectory()
source = Path(tempdir.name) / "Already Downloaded.mp4"
source.write_bytes(b"video")
calls = {"download": 0, "convert": []}

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    calls["download"] += 1
    raise AssertionError("network download should not run for existing audio extraction")

def fake_convert(input_path, output_ext, output_dir=None, on_event=None, ffmpeg_exe=None, runner=None):
    output = Path(output_dir or Path(input_path).parent) / (Path(input_path).stem + "." + str(output_ext).lower())
    calls["convert"].append((str(input_path), str(output_ext).lower(), str(output_dir)))
    output.write_bytes(b"audio")
    if on_event:
        on_event({"type": "file", "path": str(output)})
    return {"ok": True, "output_dir": str(output.parent), "output_path": str(output)}

original_convert = getattr(engine, "convert_existing_media_to_audio", None)
engine.convert_existing_media_to_audio = fake_convert

try:
    app = QApplication([])
    window = ClipFlowWindow(download_func=fake_download)
    window.folder_input.setText(tempdir.name)
    row = {
        "id": "row-1",
        "kind": "video",
        "candidate": {
            "id": "row-1",
            "source": "https://media.test/watch/1",
            "url": "https://media.test/watch/1",
            "title": "Already Downloaded",
            "display_title": "Already Downloaded",
            "thumbnail": "",
            "ext": "mp4",
            "output_ext": "mp4",
            "duration": 1,
        },
        "qualities": [],
        "quality_options": [],
        "selected_index": 0,
        "selected_format_index": 0,
        "source_url": "https://media.test/watch/1",
        "input_url": "https://media.test/watch/1",
        "status": "완료",
        "messages": [],
        "progress": 100,
        "progress_text": "",
        "output_path": str(source),
        "created_order": 1,
    }
    window.rows = [row]
    window._render_rows()
    window.extract_audio_for_row(row, "MP3")

    def drive():
        if window.active_downloads:
            return
        audio_row = window.rows[1]
        print(calls["download"])
        print(calls["convert"][0][0] == str(source))
        print(calls["convert"][0][1])
        print(Path(audio_row["output_path"]).name)
        print(audio_row["status"])
        tempdir.cleanup()
        app.quit()

    timer = QTimer()
    timer.timeout.connect(drive)
    timer.start(20)
    QTimer.singleShot(3000, app.quit)
    app.exec()
finally:
    if original_convert is None:
        delattr(engine, "convert_existing_media_to_audio")
    else:
        engine.convert_existing_media_to_audio = original_convert
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["0", "True", "mp3", "Already Downloaded.mp3", "완료"])

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

    def test_clipflow_qt_progress_prefers_engine_message_speed_over_raw_ffmpeg_x(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
print(window._progress_text(37, {"message": "37.0% 28.5 MB/s 처리 29.4x ETA 1:54", "speed_text": "29.4x", "eta_text": "1:54"}))
print(window._progress_text(61, {"message": "61.3% 3.3 MB/s 정확 컷 처리 2.08x ETA 0:04", "speed_text": "2.08x", "eta_text": "0:04"}))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "37% · 28.5 MB/s · ETA 1:54",
                "61% · 3.3 MB/s · ETA 0:04",
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
print(row_widget.row_quality_label.isHidden())
print(row_widget.row_quality_label.text())
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
            ["False", "False", "False", "True", "False", "False", "True", "true", "False", "False", "False", "", "['https://media.test/video']"],
        )

    def test_clipflow_qt_hover_actions_sit_above_time_and_size_columns(self):
        script = r'''
from PySide6.QtCore import QRect
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
info_top_left = row_widget.info_widget.mapTo(row_widget, row_widget.info_widget.rect().topLeft())
size_top_left = row_widget.size_widget.mapTo(row_widget, row_widget.size_widget.rect().topLeft())
info_rect = QRect(info_top_left, row_widget.info_widget.size())
size_rect = QRect(size_top_left, row_widget.size_widget.size())
print(actions.y() < info_rect.y())
print(not actions.intersects(info_rect))
print(not actions.intersects(size_rect))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True"])

    def test_clipflow_qt_hover_actions_use_compact_stable_title_slot(self):
        script = r'''
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/video"

app = QApplication([])
window = ClipFlowWindow()
window.resize(760, 420)
window.show()
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Video",
    "candidates": [
        {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
    ],
    "warnings": [],
})
app.processEvents()
row_widget = window.rows[0]["widget"]
row_widget.set_status("완료")
row_widget._set_hovered(True)
app.processEvents()
actions = row_widget.actions_widget.geometry()
title_top = row_widget.title_label.mapTo(row_widget, QPoint(0, 0)).y()
title_center = title_top + row_widget.title_label.height() / 2
action_center = actions.y() + actions.height() / 2
meta_top = row_widget.info_widget.mapTo(row_widget, QPoint(0, 0)).y()

print(actions.height())
print(row_widget.open_folder_button.width(), row_widget.open_folder_button.icon_size)
print(abs(action_center - title_center) <= 1)
print(actions.y() + actions.height() < meta_top)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["28", "28 18", "True", "True"])

    def test_clipflow_qt_row_title_has_no_hover_tooltip_but_action_icons_do(self):
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
app.processEvents()
row_widget = window.rows[0]["widget"]
print(row_widget.title_label.toolTip())
print(row_widget.open_folder_button.toolTip())
print(row_widget.more_button.toolTip())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["", "폴더 열기", "더보기"])

    def test_clipflow_qt_row_meta_text_uses_icon_height_for_vertical_centering(self):
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
app.processEvents()
row_widget = window.rows[0]["widget"]
print(row_widget.info_label.height(), row_widget.info_icon.height())
print(row_widget.size_label.height(), row_widget.size_icon.height())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["14 14", "14 14"])

    def test_clipflow_qt_row_title_uses_two_line_area_with_dynamic_vertical_alignment(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/video"
long_title = "This is a long title that should wrap when the hover actions reserve the right title slot"

app = QApplication([])
window = ClipFlowWindow()
window.resize(560, 420)
window.show()
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Video",
    "candidates": [
        {"id": "short", "source": url, "url": url, "title": "Short", "display_title": "Short", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        {"id": "long", "source": url + "/2", "url": url + "/2", "title": long_title, "display_title": long_title, "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
    ],
    "warnings": [],
})
app.processEvents()
short_row = next(row["widget"] for row in window.rows if row["candidate"].get("id") == "short")
long_row = next(row["widget"] for row in window.rows if row["candidate"].get("id") == "long")
print(short_row.title_label.height())
print(bool(short_row.title_label.alignment() & Qt.AlignVCenter))

long_row.set_status("완료")
long_row._set_hovered(True)
app.processEvents()
print(long_row.title_label.height())
print(bool(long_row.title_label.alignment() & Qt.AlignTop))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["34", "True", "34", "True"])

    def test_clipflow_qt_row_keeps_hover_background_while_more_menu_is_open(self):
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
app.processEvents()
row_widget = window.rows[0]["widget"]
row_widget.set_status("완료")
row_widget._actions_menu_open = True
row_widget._set_hovered(False)
print(row_widget.property("hovered"))
print(not row_widget.actions_widget.isHidden())
row_widget._actions_menu_open = False
row_widget._set_hovered(False)
print(row_widget.property("hovered"))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["true", "True", "false"])

    def test_clipflow_qt_row_uses_same_inner_inset_for_thumbnail_meta_and_hover_actions(self):
        script = r'''
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/video"
border = 1
inset = 5

app = QApplication([])
window = ClipFlowWindow()
window.resize(760, 420)
window.show()
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Video",
    "candidates": [
        {"id": "best", "source": url, "url": url, "title": "Kenshi Yonezu 米津玄師 - Sayonara, Mata Itsuka ! 75th", "display_title": "Kenshi Yonezu 米津玄師 - Sayonara, Mata Itsuka ! 75th", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 285, "sort_bytes": 87600000},
    ],
    "warnings": [],
})
app.processEvents()
row_widget = window.rows[0]["widget"]
row_widget._set_hovered(True)
app.processEvents()

def mapped_rect(widget):
    return QRect(widget.mapTo(row_widget, widget.rect().topLeft()), widget.size())

thumb = row_widget.thumbnail.geometry()
title = mapped_rect(row_widget.title_label)
favicon = mapped_rect(row_widget.source_link_button)
favicon_icon = row_widget.source_link_button._icon_target_rect().translated(favicon.topLeft())
info_icon = mapped_rect(row_widget.info_icon)
info_label = mapped_rect(row_widget.info_label)
size_icon = mapped_rect(row_widget.size_icon)
size_label = mapped_rect(row_widget.size_label)
info_widget = mapped_rect(row_widget.info_widget)
actions = row_widget.actions_widget.geometry()

print(thumb.x() - border)
print(thumb.y() - border)
print(row_widget.height() - border - (thumb.y() + thumb.height()))
print(title.x() - (thumb.x() + thumb.width()))
print(favicon.x() - (thumb.x() + thumb.width()))
print(row_widget.height() - border - (favicon.y() + favicon.height()))
print(favicon_icon.x() - (thumb.x() + thumb.width()))
print(row_widget.height() - border - (favicon_icon.y() + favicon_icon.height()))
print(row_widget.height() - border - (info_widget.y() + info_widget.height()))
print(row_widget.width() - border - (size_label.x() + size_label.width()))
print(size_icon.x() - (info_label.x() + info_label.width()))
print(abs((info_icon.y() + info_icon.height() / 2) - (info_label.y() + info_label.height() / 2)) <= 1)
print(abs((size_icon.y() + size_icon.height() / 2) - (size_label.y() + size_label.height() / 2)) <= 1)
print(actions.y() - border)
print(info_widget.y() - (actions.y() + actions.height()))
print(row_widget.width() - border - (actions.x() + actions.width()))
print(row_widget.open_folder_button.icon_size)
print(hasattr(row_widget.open_folder_button, "hover_preview"))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["5"] * 8 + ["8", "8", "8", "True", "True", "8", "4", "5", "18", "False"],
        )

    def test_clipflow_qt_thumbnail_hover_preview_tracks_cursor_and_flips_at_edges(self):
        script = r'''
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import ThumbnailPlaceholder

app = QApplication([])
size = QSize(384, 216)
screen = QRect(0, 0, 600, 420)

normal = ThumbnailPlaceholder.preview_geometry(QPoint(80, 300), size, screen)
right_edge = ThumbnailPlaceholder.preview_geometry(QPoint(590, 300), size, screen)
top_edge = ThumbnailPlaceholder.preview_geometry(QPoint(80, 40), size, screen)
corner = ThumbnailPlaceholder.preview_geometry(QPoint(590, 40), size, screen)

print(normal.left(), normal.bottom(), normal.width(), normal.height())
print(right_edge.right() <= screen.right())
print(right_edge.right() == 580)
print(top_edge.top() == 50)
print(corner.right() == 580)
print(corner.top() == 50)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["90 290 384 216", "True", "True", "True", "True", "True"])

    def test_clipflow_qt_row_thumbnail_and_favicon_alignment(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow
from tools.clipflow_rows import ROW_INSET, ROW_LEADING_INSET

url = "https://media.test/video"

app = QApplication([])
window = ClipFlowWindow()
window.resize(760, 420)
window.show()
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Video",
    "candidates": [
        {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
    ],
    "warnings": [],
})
app.processEvents()
row_widget = window.rows[0]["widget"]
thumb_pos = row_widget.thumbnail.pos()
favicon_pos = row_widget.source_link_button.mapTo(row_widget, row_widget.source_link_button.rect().topLeft())
title_pos = row_widget.title_label.mapTo(row_widget, row_widget.title_label.rect().topLeft())
border = 1
print(thumb_pos.x() - border == ROW_LEADING_INSET and thumb_pos.y() - border == ROW_INSET)
print(favicon_pos.x() == title_pos.x())
print(favicon_pos.y() + row_widget.source_link_button.height() == thumb_pos.y() + row_widget.thumbnail.height())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True"])

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
print(bool(thumbnail._preview.windowFlags() & Qt.WindowTransparentForInput))
print(thumbnail._preview_label.width(), thumbnail._preview_label.height())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "324 216"])

    def test_clipflow_qt_thumbnail_inline_draw_centers_with_device_pixel_ratio(self):
        script = r'''
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import ThumbnailPlaceholder, _pixmap_logical_size

app = QApplication([])
thumbnail = ThumbnailPlaceholder()
thumbnail._set_pixmap(QPixmap(80, 120))
scaled = thumbnail._scaled_thumbnail_pixmap()
logical = _pixmap_logical_size(scaled)
x = round((thumbnail.width() - logical.width()) / 2)
y = round((thumbnail.height() - logical.height()) / 2)
print(x, y)
print(round(logical.width()), round(logical.height()))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["30 0", "36 54"])

    def test_clipflow_qt_rounded_pixmap_portrait_rounds_image_bounds(self):
        script = r'''
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import _rounded_pixmap

app = QApplication([])
portrait = QPixmap.fromImage(QImage(268, 394, QImage.Format_RGB32))
portrait.fill(0x336699)
rounded = _rounded_pixmap(portrait, 216, 317, 12, 1.0)
image = rounded.toImage()
print(image.pixelColor(0, 0).alpha())
print(image.pixelColor(rounded.width() - 1, 0).alpha())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "0")
        self.assertEqual(lines[1], "0")

    def test_clipflow_qt_thumbnail_preview_portrait_uses_rotated_landscape_frame(self):
        script = r'''
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import ThumbnailPlaceholder

app = QApplication([])
thumbnail = ThumbnailPlaceholder()
thumbnail._set_pixmap(QPixmap(268, 394))
print(thumbnail._preview_size().width(), thumbnail._preview_size().height())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["216 317"])

    def test_clipflow_qt_thumbnail_preview_moves_from_mouse_event_global_position(self):
        script = r'''
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import ThumbnailPlaceholder

app = QApplication([])
thumbnail = ThumbnailPlaceholder()
positions = []

def record_move(cursor_pos=None):
    positions.append((cursor_pos.x(), cursor_pos.y()) if cursor_pos is not None else None)

thumbnail._move_preview = record_move
event = QMouseEvent(
    QEvent.MouseMove,
    QPointF(5, 5),
    QPointF(5, 5),
    QPointF(123, 456),
    Qt.NoButton,
    Qt.NoButton,
    Qt.NoModifier,
)
thumbnail.mouseMoveEvent(event)
print(positions[0])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["(123, 456)"])

    def test_clipflow_qt_thumbnail_preview_keeps_only_one_active_preview(self):
        script = r'''
from PySide6.QtCore import QPoint
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import ThumbnailPlaceholder

app = QApplication([])
first = ThumbnailPlaceholder()
second = ThumbnailPlaceholder()
first._set_pixmap(QPixmap(120, 80))
second._set_pixmap(QPixmap(120, 80))

first._show_preview(QPoint(120, 300))
app.processEvents()
print(first._preview.isVisible())

second._show_preview(QPoint(140, 330))
app.processEvents()
print(first._preview.isVisible())
print(second._preview.isVisible())

second._hide_preview()
print(ThumbnailPlaceholder._active_preview_owner is None)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "False", "True", "True"])

    def test_clipflow_qt_thumbnail_preview_leave_does_not_hide_while_cursor_still_inside_thumbnail(self):
        script = r'''
from PySide6.QtCore import QPoint
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import ThumbnailPlaceholder

app = QApplication([])
thumbnail = ThumbnailPlaceholder()
thumbnail.show()
thumbnail._set_pixmap(QPixmap(120, 80))
thumbnail._show_preview()
inside = thumbnail.mapToGlobal(QPoint(10, 10))
outside = thumbnail.mapToGlobal(QPoint(-10, -10))
thumbnail._hide_preview_if_cursor_left(inside)
print(thumbnail._preview.isVisible())
thumbnail._hide_preview_if_cursor_left(outside)
print(thumbnail._preview.isVisible())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "False"])

    def test_clipflow_qt_thumbnail_preview_hides_when_app_deactivates(self):
        script = r'''
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import ThumbnailPlaceholder

app = QApplication([])
thumbnail = ThumbnailPlaceholder()
thumbnail._set_pixmap(QPixmap(120, 80))
thumbnail._show_preview(QPoint(120, 300))
app.processEvents()
print(thumbnail._preview.isVisible())
app.sendEvent(app, QEvent(QEvent.ApplicationDeactivate))
app.processEvents()
print(thumbnail._preview.isVisible())
print(ThumbnailPlaceholder._active_preview_owner is None)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "False", "True"])

    def test_clipflow_qt_source_link_button_centers_icon_without_edge_crop(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import SourceLinkButton

app = QApplication([])
button = SourceLinkButton()
rect = button._icon_target_rect()
print(button.width(), button.height())
print(button.iconSize().width(), button.iconSize().height())
print(rect.x(), rect.y(), rect.width(), rect.height())
print(rect.left() == 0)
print(rect.top() == 0)
print(rect.right() == button.width() - 1)
print(rect.bottom() == button.height() - 1)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["20 20", "20 20", "0 0 20 20", "True", "True", "True", "True"])

    def test_clipflow_qt_list_toolbar_uses_compact_buttons_without_sort_label(self):
        script = r'''
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, READY_STATUS

app = QApplication([])
window = ClipFlowWindow()
window.resize(1500, 1100)
window.show()
app.processEvents()

select_top = window.select_toggle.mapTo(window, QPoint(0, 0)).y()
combo_top = window.sort_order_combo.mapTo(window, QPoint(0, 0)).y()
button_top = window.sort_direction_button.mapTo(window, QPoint(0, 0)).y()
preference_top = window.preference_button.mapTo(window, QPoint(0, 0)).y()
select_center = select_top + window.select_toggle.height() // 2
combo_center = combo_top + window.sort_order_combo.height() // 2
button_center = button_top + window.sort_direction_button.height() // 2
preference_center = preference_top + window.preference_button.height() // 2
QTest.mouseClick(window.sort_order_combo, Qt.LeftButton)
app.processEvents()
popup_width = window.sort_order_combo._active_popup.width()
window.sort_order_combo._active_popup.close()
app.processEvents()

print(hasattr(window, "sort_label"))
print(window.select_toggle.objectName())
print(window.select_toggle.text())
print(window.select_toggle.iconSize().width())
print(window.select_toggle.height())
print(window.select_toggle.width())
print(window.select_toggle.width() == window.select_toggle.height())
print("border: none" in window.select_toggle.styleSheet() or window.select_toggle.objectName() == "IconButton")
QTest.mouseClick(window.select_toggle, Qt.LeftButton)
app.processEvents()
print(window.select_toggle.text())
print(window.select_toggle.property("active"))
print(window.sort_order_combo.height())
print(window.sort_order_combo.width())
print(window.preference_button.height())
print(window.preference_button.width())
print(window.sort_direction_button.bordered)
print(window.sort_order_combo.currentText())
print(abs(select_center - combo_center) <= 1)
print(abs(select_center - button_center) <= 1)
print(abs(select_center - preference_center) <= 1)
print(popup_width <= window.sort_order_combo.width() + 6)
print(hasattr(window, "sort_direction_combo"))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "False", "IconButton", "", "20", "36", "36", "True", "True", "", "true",
                "36", "96", "36", "64", "False", "다운로드순", "True", "True", "True", "True", "False",
            ],
        )

    def test_clipflow_qt_list_toolbar_search_filters_titles_without_mutating_rows(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
window.resize(760, 420)
window.show()
window._analysis_finished({
    "webpage_url": "https://media.test/video",
    "url": "https://media.test/video",
    "title": "Video",
    "candidates": [
        {"id": "alpha", "source": "https://media.test/a", "url": "https://media.test/a", "title": "Alpha One", "display_title": "Alpha One", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        {"id": "beta", "source": "https://media.test/b", "url": "https://media.test/b", "title": "Beta Two", "display_title": "Beta Two", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
    ],
    "warnings": [],
})
app.processEvents()

print(window.search_input_frame.maximumWidth())
button_x_before = window.search_button.mapTo(window, window.search_button.rect().topLeft()).x()
QTest.mouseClick(window.search_button, Qt.LeftButton)
app.processEvents()
window.search_animation.setCurrentTime(window.search_animation.duration())
button_x_after = window.search_button.mapTo(window, window.search_button.rect().topLeft()).x()
print(window.search_input_frame.isVisible())
print(window.search_input_frame.maximumWidth())
print(window.search_input_frame.height())
print(button_x_before == button_x_after)
print(window.search_input_frame.mapTo(window, window.search_input_frame.rect().topLeft()).x() < button_x_after)

window.search_input.setText("alpha")
app.processEvents()
visible_titles = [
    row["widget"].title_label.text()
    for row in window.rows
    if row["widget"].isVisible()
]
print(visible_titles)
print(len(window.rows))

QTest.mouseClick(window.select_toggle, Qt.LeftButton)
app.processEvents()
QTest.mouseClick(window.select_all_button, Qt.LeftButton)
app.processEvents()
print(sorted((row["candidate"].get("id"), row.get("checked", False)) for row in window.rows))

alpha_row = next(row for row in window.rows if row["candidate"].get("id") == "alpha")
window.remove_row(alpha_row)
app.processEvents()
print([row["candidate"].get("id") for row in window.rows])
window.search_input.clear()
app.processEvents()
print([row["widget"].title_label.text() for row in window.rows if row["widget"].isVisible()])

window.search_input.setText("beta")
app.processEvents()
QTest.keyClick(window.search_input, Qt.Key_Escape)
app.processEvents()
window.search_animation.setCurrentTime(window.search_animation.duration())
print(window.search_input.text())
print(window.search_input_frame.isVisible())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "0", "True", "180", "36", "True", "True", "['Alpha One']", "2",
                "[('alpha', True), ('beta', False)]", "['beta']", "['Beta Two']", "", "False",
            ],
        )

    def test_clipflow_qt_list_rows_use_five_pixel_spacing(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
print(window.row_layout.spacing())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["5"])

    def test_clipflow_qt_restores_and_saves_window_size(self):
        script = r'''
from PySide6.QtCore import QSize, QSettings
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, SETTINGS_APP, SETTINGS_ORG, WINDOW_SIZE_SETTING

app = QApplication([])
settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
settings.setValue(WINDOW_SIZE_SETTING, QSize(640, 690))

window = ClipFlowWindow()
window.show()
app.processEvents()
print(window.size().width(), window.size().height())

window.resize(670, 710)
app.processEvents()
window.close()
app.processEvents()

restored = ClipFlowWindow()
print(restored.size().width(), restored.size().height())
restored.close()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["640 690", "670 710"])

    def test_clipflow_qt_list_header_and_rows_share_left_edge(self):
        script = r'''
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/video"

app = QApplication([])
window = ClipFlowWindow()
window.resize(760, 420)
window.show()
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Video",
    "candidates": [
        {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
    ],
    "warnings": [],
})
app.processEvents()
row_widget = window.rows[0]["widget"]
select_x = window.select_toggle.mapTo(window, QPoint(0, 0)).x()
scroll_x = window.scroll_area.mapTo(window, QPoint(0, 0)).x()
row_x = row_widget.mapTo(window, QPoint(0, 0)).x()
print(select_x == scroll_x)
print(select_x == row_x)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True"])

    def test_clipflow_qt_shell_omits_brand_header_to_reclaim_space(self):
        script = r'''
from PySide6.QtWidgets import QApplication, QLabel
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
window.show()
app.processEvents()

print(bool(window.findChildren(QLabel, "WindowTitle")))
print(hasattr(window, "brand_header"))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "False"])

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

folder_box = window.folder_input.parent()
url_box = window.url_input.parent()
segment_button = window.clip_range_button
folder_top = folder_box.mapTo(window, QPoint(0, 0)).y()
cookie_top = window.cookie_combo.mapTo(window, QPoint(0, 0)).y()
segment_top = segment_button.mapTo(window, QPoint(0, 0)).y()
primary_top = window.primary_button.mapTo(window, QPoint(0, 0)).y()
primary_right = window.primary_button.mapTo(window, QPoint(0, 0)).x() + window.primary_button.width()
cookie_right = window.cookie_combo.mapTo(window, QPoint(0, 0)).x() + window.cookie_combo.width()

print(folder_box.height())
print(window.cookie_combo.height())
print(window.folder_button.text())
print(url_box.width() >= folder_box.width())
print(abs(folder_top - cookie_top) <= 1)
print(abs(segment_top - primary_top) <= 1)
print(abs(primary_right - cookie_right) <= 1)
print(segment_button.text())
print(segment_button.width())
print(hasattr(window, "clip_range_panel"))
print(window.primary_button.width())
print(hasattr(window, "cookie_help_button"))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["42", "42", "저장 위치", "True", "True", "True", "True", "구간선택", "88", "False", "64", "False"],
        )

    def test_clipflow_qt_folder_path_is_editable_and_persisted_on_enter(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, SAVE_FOLDER_SETTING, SETTINGS_APP, SETTINGS_ORG
from PySide6.QtCore import QSettings

app = QApplication([])
window = ClipFlowWindow()
window.show()
app.processEvents()
QTest.mouseClick(window.folder_input, Qt.LeftButton)
app.processEvents()
window.folder_input.selectAll()
QTest.keyClicks(window.folder_input, "C:/ClipFlow/Typed")
QTest.keyClick(window.folder_input, Qt.Key_Return)
app.processEvents()

print(window.folder_input.isReadOnly())
print(int(window.folder_input.focusPolicy()) == int(Qt.StrongFocus))
print(window.folder_input.hasFocus())
print(window.folder_input.text())
print(QSettings(SETTINGS_ORG, SETTINGS_APP).value(SAVE_FOLDER_SETTING))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        typed_path = "C:\\ClipFlow\\Typed" if os.name == "nt" else "C:/ClipFlow/Typed"
        self.assertEqual(result.stdout.splitlines(), ["False", "True", "True", typed_path, typed_path])

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

    def test_clipflow_qt_play_button_opens_completed_file_with_default_app(self):
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
output = Path(tempdir.name) / "Video.mp4"
output.write_bytes(b"video")
row = {
    "id": "row-1",
    "kind": "video",
    "candidate": {"title": "Video", "display_title": "Video", "source": "https://media.test/video", "url": "https://media.test/video", "ext": "mp4", "output_ext": "mp4"},
    "qualities": [],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "source_url": "https://media.test/video",
    "output_path": str(output),
    "status": "완료",
    "status_detail": "",
    "progress": 100,
    "progress_text": "",
    "messages": [],
    "created_order": 1,
}
window.rows = [row]
window._render_rows()
widget = row["widget"]
print(not widget.play_file_button.isHidden())
print(widget.play_file_button.isEnabled())
window.play_file_for_row(row)
print(opened == [output])
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True"])

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

    def test_clipflow_qt_close_event_detaches_running_analysis_thread(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThread
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
thread = QThread()
thread.start()
window.analysis_thread = thread
window.close()
print(window.analysis_thread is None)
print(thread.parent() is None)
app.quit()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["True", "True"],
        )

    def test_clipflow_qt_error_row_reanalyzes_when_same_url_submitted_again(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, ERROR_STATUS

url = "https://www.instagram.com/stories/user/123/"
calls = []

app = QApplication([])
window = ClipFlowWindow()
window.rows = [window._single_analysis_loading_row(url)]
window._analysis_failed("ERROR: could not find chrome cookies database")
print(window.rows[0]["status"])
print(window.rows[0]["status_detail"])

window._start_analysis = lambda auto_download=False: calls.append(["analyze", auto_download])
window.url_input.setText(url)
window._handle_primary_action()
print(calls)
print(sum(1 for row in window.rows if row.get("status") == ERROR_STATUS))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        import sys

        expected_detail = (
            "브라우저 쿠키를 읽을 수 없어요. 설정 → 전체 디스크 접근에서 ClipFlow 허용"
            if sys.platform == "darwin"
            else "ERROR: could not find chrome cookies database"
        )
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "오류",
                expected_detail,
                "[['analyze', True]]",
                "1",
            ],
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
print(delete_dialog.cancel_button.width() >= 64)
print(delete_dialog.ok_button.width() >= 64)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True", "True", "True", "True"])

    def test_clipflow_qt_spinner_advances_clockwise_and_row_uses_border_progress(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ANALYZING_STATUS, ClipFlowWindow, DOWNLOAD_STATUS
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
row_widget.set_status(DOWNLOAD_STATUS)
row_widget.set_progress(42, "42% · 7.0 MB/s")

print(button._angle == 332)
print("border-radius: 8px" in APP_STYLE)
print(row_widget.progress_bar.isHidden())
print(row_widget.property("progressActive"))
print(row_widget.property("progressValue"))
print(row_widget.row_quality_label.isHidden())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True", "true", "42", "False"])

    def test_clipflow_qt_analysis_row_uses_animated_border_not_center_spinner(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ANALYZING_STATUS, ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
window._analysis_finished({
    "webpage_url": "https://media.test/watch/analyzing",
    "url": "https://media.test/watch/analyzing",
    "title": "Analyzing",
    "candidates": [{"id": "analysis", "source": "https://media.test/watch/analyzing", "url": "https://media.test/watch/analyzing", "title": "Analyzing", "display_title": "Analyzing", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 1}],
    "warnings": [],
})
row_widget = window.rows[0]["widget"]
row_widget.set_status(ANALYZING_STATUS)
row_widget.set_progress(0, "")
print(row_widget.property("analyzing"))
print(row_widget._analysis_ring_timer.isActive())
print(row_widget.spinner.isHidden())
print(row_widget.property("progressActive"))
print(row_widget.property("progressValue"))
print(row_widget._analysis_ring_timer.interval() <= 16)
rect, _full, _gradient = row_widget._progress_paths()
row_widget._analysis_ring_offset = 0.25
print(len(row_widget._analysis_dash_path(rect).toSubpathPolygons()))
row_widget._analysis_ring_offset = 3.98
row_widget._analysis_ring_elapsed.invalidate()
row_widget._advance_analysis_ring()
print(0.0 <= row_widget._analysis_ring_offset < 0.1)
row_widget.set_status("준비")
print(row_widget.property("analyzing"))
print(row_widget._analysis_ring_timer.isActive())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["true", "True", "True", "true", "0", "True", "1", "True", "false", "False"])

    def test_clipflow_qt_download_starting_does_not_show_center_spinner(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import DOWNLOAD_STATUS, ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
window._analysis_finished({
    "webpage_url": "https://media.test/watch/starting",
    "url": "https://media.test/watch/starting",
    "title": "Starting",
    "candidates": [{"id": "starting", "source": "https://media.test/watch/starting", "url": "https://media.test/watch/starting", "title": "Starting", "display_title": "Starting", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 1}],
    "warnings": [],
})
row = window.rows[0]
widget = row["widget"]
row["download_starting"] = True
widget.set_status(DOWNLOAD_STATUS)
widget.set_progress(0, "다운로드 준비 중")
print(widget.spinner.isHidden())
print(not widget.spinner._timer.isActive())
print(not widget.row_quality_label.isHidden())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True"])

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

    def test_clipflow_qt_row_resize_repositions_actions_spinner_and_clears_progress_cache(self):
        script = r'''
from PySide6.QtCore import QSize
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
row = {
    "id": "row",
    "kind": "video",
    "candidate": {"id": "best", "source": "https://media.test/watch", "url": "https://media.test/watch", "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 1},
    "qualities": [],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "analysis_source_url": "https://media.test/watch",
    "source_url": "https://media.test/watch",
    "status": "준비",
    "status_detail": "",
    "progress": 0,
    "progress_text": "",
    "output_path": "",
    "messages": [],
    "created_order": 1,
}
window.rows = [row]
window._render_rows()
widget = row["widget"]
calls = []
widget._position_actions = lambda: calls.append("actions")
widget._position_spinner = lambda: calls.append("spinner")
widget._clear_progress_path_cache = lambda: calls.append("cache")
widget.resizeEvent(QResizeEvent(QSize(700, 72), QSize(680, 72)))
print(",".join(calls))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "actions,spinner,cache")

    def test_clipflow_qt_row_action_overlay_stays_transparent_behind_icons(self):
        script = r'''
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from tools.clipflow_rows import RowActionOverlay

app = QApplication([])
parent = QWidget()
parent.setProperty("selected", "false")
overlay = RowActionOverlay(parent)
overlay.resize(160, 70)
pixmap = QPixmap(160, 70)
pixmap.fill(QColor(0, 0, 0, 0))
overlay.render(pixmap, QPoint(0, 0))
print(pixmap.toImage().pixelColor(0, 35).alpha())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["0"])

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

    def test_clipflow_qt_download_concurrency_setting_limits_active_downloads(self):
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
window.download_concurrency = 2
window.url_input.setText(base + "0")
window._analysis_finished({
    "webpage_url": base + "0",
    "url": base + "0",
    "title": "Batch",
    "candidates": [
        {"id": str(i), "source": base + str(i), "url": base + str(i), "title": f"Video {i}", "display_title": f"Video {i}", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": i + 1}
        for i in range(3)
    ],
    "warnings": [],
})
for index in range(3):
    window.select_row(index)
    window._start_download()
printed = {"done": False}

def check():
    if not printed["done"]:
        print(len(getattr(window, "active_downloads", [])))
        print(len(getattr(window, "queued_download_rows", [])))
        printed["done"] = True
    if not window.active_downloads and not window.queued_download_rows:
        app.quit()

timer = QTimer()
timer.timeout.connect(check)
timer.start(50)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["2", "1"])

    def test_clipflow_qt_pauses_resumes_and_deletes_partial_download_files(self):
        script = r'''
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow
from tools.clipflow_theme import DOWNLOAD_STATUS, PAUSED_STATUS

class FakeThread:
    def __init__(self):
        self.calls = []

    def requestInterruption(self):
        self.calls.append("requestInterruption")

    def quit(self):
        self.calls.append("quit")

    def wait(self, timeout):
        self.calls.append(f"wait:{timeout}")
        return True

    def terminate(self):
        self.calls.append("terminate")

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
window = ClipFlowWindow(confirm_delete_func=lambda path: True)
window.folder_input.setText(tempdir.name)
candidate = {
    "id": "one",
    "source": "https://media.test/video",
    "url": "https://media.test/video",
    "title": "Video",
    "display_title": "Video",
    "thumbnail": "",
    "ext": "mp4",
    "output_ext": "mp4",
    "duration": 120,
    "sort_bytes": 30,
}
row = {
    "id": "row-1",
    "kind": "video",
    "candidate": candidate,
    "qualities": [candidate],
    "quality_options": [],
    "selected_index": 0,
    "selected_format_index": 0,
    "analysis_source_url": candidate["url"],
    "source_url": candidate["url"],
    "input_url": candidate["url"],
    "status": DOWNLOAD_STATUS,
    "status_detail": "",
    "progress": 43,
    "progress_text": "43%",
    "output_path": "",
    "messages": [],
    "created_order": 1,
}
window.rows = [row]
window._render_rows()
thread = FakeThread()
window.active_downloads = [{"thread": thread, "worker": None, "row": row}]

window.pause_download_for_row(row)
window._handle_engine_event_for(row, {"type": "progress", "percent": 0, "message": "0.0%"})
print(row["status"])
print(row["progress"])
print(row["progress_text"])
print(len(window.active_downloads))
print(thread.calls)

started = []
window.start_download_for_row = lambda resumed: started.append(resumed is row)
window.resume_download_for_row(row)
print(started)

row["status"] = PAUSED_STATUS
for suffix in ("Video.mp4.part", "Video.mp4.ytdl", "Video.mp4.part-Frag3.part"):
    (Path(tempdir.name) / suffix).write_text("partial", encoding="utf-8")
window.delete_file_for_row(row)
print([(Path(tempdir.name) / suffix).exists() for suffix in ("Video.mp4.part", "Video.mp4.ytdl", "Video.mp4.part-Frag3.part")])
print(row in window.rows)
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "일시정지",
                "43",
                "43%",
                "0",
                "['requestInterruption', 'quit', 'wait:800']",
                "[True]",
                "[False, False, False]",
                "False",
            ],
        )

    def test_clipflow_qt_resume_keeps_paused_progress_until_new_progress_event(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow
from tools.clipflow_theme import PAUSED_STATUS

app = QApplication([])
url = "https://media.test/video"

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    return {"ok": True, "output_dir": output_dir}

window = ClipFlowWindow(download_func=fake_download)
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Video",
    "candidates": [
        {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 120, "sort_bytes": 30},
    ],
    "warnings": [],
})
row = window.rows[0]
row["status"] = PAUSED_STATUS
row["progress"] = 43
row["progress_text"] = "43% · 5.0 MB/s"
widget = row["widget"]
widget.set_status(PAUSED_STATUS)
widget.set_progress(43, row["progress_text"])
window.resume_download_for_row(row)
app.processEvents()
print(row["progress"])
print(row["progress_text"])
print(widget.property("progressValue"))
while window.active_downloads:
    app.processEvents()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["43", "43% · 5.0 MB/s", "43"])

    def test_clipflow_qt_download_rows_swap_hover_actions_for_pause_and_resume(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow
from tools.clipflow_theme import DOWNLOAD_STATUS, PAUSED_STATUS

url = "https://media.test/video"

app = QApplication([])
window = ClipFlowWindow()
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Video",
    "candidates": [
        {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 120, "sort_bytes": 30},
    ],
    "warnings": [],
})
row = window.rows[0]
widget = row["widget"]
widget.set_status(DOWNLOAD_STATUS)
widget._set_hovered(True)
app.processEvents()
print(not widget.pause_download_button.isHidden())
print(not widget.resume_download_button.isHidden())
print(not widget.delete_file_button.isHidden())

widget.set_status(PAUSED_STATUS)
widget._set_hovered(True)
app.processEvents()
print(not widget.pause_download_button.isHidden())
print(not widget.resume_download_button.isHidden())
print(not widget.delete_file_button.isHidden())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "False", "False", "False", "True", "False"])

    def test_clipflow_qt_progress_text_includes_eta_when_available(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
print(window._progress_text(12, {"speed_text": "4.0 MB/s", "eta_text": "1:23"}))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["12% · 4.0 MB/s · ETA 1:23"])

    def test_clipflow_qt_concurrent_downloads_keep_progress_on_distinct_repeated_analysis_rows(self):
        script = r'''
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS

urls = ["https://media.test/watch/one", "https://media.test/watch/two"]

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    title = candidate.get("display_title")
    time.sleep(0.15 if title == "One" else 0.25)
    if on_event:
        on_event({"type": "progress", "percent": 41 if title == "One" else 82, "message": f"{title} progress"})
    time.sleep(0.05)
    return {"ok": True, "output_dir": str(output_dir)}

def analyze(window, url, title):
    window.url_input.setText(url)
    window._analysis_finished({
        "webpage_url": url,
        "url": url,
        "title": title,
        "candidates": [{"id": title.lower(), "source": url, "url": url, "title": title, "display_title": title, "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 1}],
        "warnings": [],
    })
    return next(row for row in window.rows if (row.get("candidate") or {}).get("display_title") == title)

app = QApplication([])
window = ClipFlowWindow(download_func=fake_download)
first = analyze(window, urls[0], "One")
window.start_download_for_row(first)
second = analyze(window, urls[1], "Two")
window.start_download_for_row(second)

def done():
    if not window.active_downloads and not window.queued_download_rows:
        app.quit()

timer = QTimer()
timer.timeout.connect(done)
timer.start(50)
QTimer.singleShot(3000, app.quit)
app.exec()

rows_by_title = {
    (row.get("candidate") or {}).get("display_title"): row
    for row in window.rows
    if (row.get("candidate") or {}).get("display_title") in {"One", "Two"}
}
print(rows_by_title["One"]["id"] != rows_by_title["Two"]["id"])
print(rows_by_title["One"]["status"] == COMPLETED_STATUS)
print(rows_by_title["Two"]["status"] == COMPLETED_STATUS)
print(rows_by_title["One"]["progress"])
print(rows_by_title["Two"]["progress"])
'''
        result = run_qt_script(script, timeout=8)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True", "100", "100"])

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

    def test_clipflow_qt_reanalyzing_same_video_reuses_existing_row(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS

url = "https://media.test/watch/reuse"

def analysis():
    return {
        "webpage_url": url,
        "url": url,
        "title": "Reuse",
        "candidates": [
            {"id": "reuse", "source": url, "url": url, "title": "Reuse", "display_title": "Reuse", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 15, "sort_bytes": 10},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow()
window._analysis_finished(analysis())
row = window.rows[0]
row_id = row["id"]
row["status"] = COMPLETED_STATUS
row["progress"] = 100
row["output_path"] = "C:/Downloads/Reuse.mp4"
old_order = row["created_order"]
window._analysis_finished(analysis())
print(len(window.rows))
print(window.rows[0]["id"] == row_id)
print(window.rows[0]["created_order"] > old_order)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["1", "True", "True"])

    def test_clipflow_qt_reanalyzing_with_different_clip_range_creates_distinct_row(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS

url = "https://media.test/watch/reuse-segment"

def analysis():
    return {
        "webpage_url": url,
        "url": url,
        "title": "Reuse Segment",
        "candidates": [
            {"id": "reuse", "source": url, "url": url, "title": "Reuse Segment", "display_title": "Reuse Segment", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 60, "sort_bytes": 60},
        ],
        "warnings": [],
    }

app = QApplication([])
window = ClipFlowWindow()
window._applied_clip_start_text = "00:00:10"
window._applied_clip_end_text = "00:00:20"
window._analysis_finished(analysis())
row = window.rows[0]
prepared = window._candidate_for_download(row, row["candidate"])
window._apply_download_candidate_to_row(row, prepared)
row["status"] = COMPLETED_STATUS
row["progress"] = 100
window._applied_clip_start_text = "00:00:30"
window._applied_clip_end_text = "00:00:40"
window._analysis_finished(analysis())
new_row = window.rows[0]
prepared_new = window._candidate_for_download(new_row, new_row["candidate"])
window._apply_download_candidate_to_row(new_row, prepared_new)
titles = [(row.get("candidate") or {}).get("display_title") for row in window.rows]
print(len(window.rows))
print(any("[00m10s-00m20s]" in title for title in titles))
print(any("[00m30s-00m40s]" in title for title in titles))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["2", "True", "True"])

    def test_clipflow_qt_reanalyzing_during_clip_download_keeps_downloading_row(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/watch/active-segment"

def analysis():
    return {
        "webpage_url": url,
        "url": url,
        "title": "Active Segment",
        "candidates": [
            {"id": "active", "source": url, "url": url, "title": "Active Segment", "display_title": "Active Segment", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 120, "sort_bytes": 120},
        ],
        "warnings": [],
    }

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    import time
    if on_event:
        on_event({"type": "progress", "percent": 10, "message": "10.0% 12.0 MB/s", "speed_text": "12.0 MB/s"})
    while not getattr(fake_download, "release", False):
        time.sleep(0.01)
    return {"ok": True, "output_dir": output_dir, "output_path": str(output_dir) + "/out.mp4", "target_url": page_url}

fake_download.release = False

app = QApplication([])
window = ClipFlowWindow(analyze_func=analysis, download_func=fake_download)
window.folder_input.setText("C:/Temp")
window._analysis_finished(analysis())
row = window.rows[0]
window.clip_start_input.setText("00:00:10")
window.clip_end_input.setText("00:00:20")
window._apply_clip_range_popup()
window.start_download_for_row(row)
while not window.active_downloads:
    app.processEvents()
window.clip_start_input.setText("00:00:30")
window.clip_end_input.setText("00:00:40")
window._apply_clip_range_popup()
window._analysis_finished(analysis())
titles = [(item.get("candidate") or {}).get("display_title") for item in window.rows]
print(len(window.rows))
print(sum("[00m10s-00m20s]" in title for title in titles))
print(bool(row.get("fixed_candidate")))
print(row is window.rows[0] or row in window.rows)
fake_download.release = True
while window.active_downloads:
    app.processEvents()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "2",
                "1",
                "True",
                "True",
            ],
        )

    def test_clipflow_qt_clip_download_from_completed_row_keeps_original_card(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS

url = "https://media.test/watch/completed-clip"

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    return {"ok": True, "output_dir": output_dir, "output_path": str(output_dir) + "/out.mp4", "target_url": page_url}

app = QApplication([])
window = ClipFlowWindow(download_func=fake_download)
window.folder_input.setText("C:/Temp")
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Completed Clip",
    "candidates": [
        {"id": "completed", "source": url, "url": url, "title": "Completed Clip", "display_title": "Completed Clip", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 1440, "sort_bytes": 1440},
    ],
    "warnings": [],
})
row = window.rows[0]
row["status"] = COMPLETED_STATUS
row["progress"] = 100
window.clip_start_input.setText("00:02:00")
window.clip_end_input.setText("00:24:00")
window._apply_clip_range_popup()
window.start_download_for_row(row)
while window.active_downloads:
    app.processEvents()
titles = [(item.get("candidate") or {}).get("display_title") for item in window.rows]
print(row["candidate"]["display_title"])
print(len(window.rows))
print(sum("[02m00s-24m00s]" in title for title in titles))
print(bool(row.get("fixed_candidate")))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["Completed Clip", "2", "1", "False"])

    def test_clipflow_qt_different_clip_range_during_download_spawns_sibling_row(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/watch/sibling-clip"

def analysis():
    return {
        "webpage_url": url,
        "url": url,
        "title": "Sibling Clip",
        "candidates": [
            {"id": "sibling", "source": url, "url": url, "title": "Sibling Clip", "display_title": "Sibling Clip", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 120, "sort_bytes": 120},
        ],
        "warnings": [],
    }

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    import time
    if on_event:
        on_event({"type": "progress", "percent": 5, "message": "5.0% 10.0 MB/s", "speed_text": "10.0 MB/s"})
    while not getattr(fake_download, "release", False):
        time.sleep(0.01)
    return {"ok": True, "output_dir": output_dir, "output_path": str(output_dir) + "/out.mp4", "target_url": page_url}

fake_download.release = False

app = QApplication([])
window = ClipFlowWindow(analyze_func=analysis, download_func=fake_download)
window.folder_input.setText("C:/Temp")
window._analysis_finished(analysis())
row = window.rows[0]
window.clip_start_input.setText("00:00:10")
window.clip_end_input.setText("00:00:20")
window._apply_clip_range_popup()
window.start_download_for_row(row)
while not window.active_downloads:
    app.processEvents()
window.clip_start_input.setText("00:00:30")
window.clip_end_input.setText("00:00:40")
window._apply_clip_range_popup()
window.start_download_for_row(row)
while len(window.active_downloads) < 2:
    app.processEvents()
titles = [(item.get("candidate") or {}).get("display_title") for item in window.rows]
print(len(window.rows))
print(len(window.active_downloads))
print(sum("[00m10s-00m20s]" in title for title in titles))
print(sum("[00m30s-00m40s]" in title for title in titles))
fake_download.release = True
while window.active_downloads:
    app.processEvents()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["2", "2", "1", "1"])

    def test_clipflow_qt_auto_download_freezes_full_clip_intent_during_analysis(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow
import time

url = "https://media.test/watch/freeze-clip"

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    while not getattr(fake_download, "release", False):
        time.sleep(0.01)
    title = (candidate or {}).get("display_title") or "out"
    return {"ok": True, "output_dir": output_dir, "output_path": str(output_dir) + f"/{title}.mp4", "target_url": page_url}

fake_download.release = False
app = QApplication([])
window = ClipFlowWindow(download_func=fake_download)
window.folder_input.setText("C:/Temp")
window.url_input.setText(url)
# Simulate download click with no clip: auto_download freezes full intent.
window._analysis_auto_download = True
window._analysis_download_clip_frozen = True
window._analysis_download_clip_range = None
window._analysis_download_clip_cut_mode = None
# User sets clip while "analysis" is still in flight.
window._applied_clip_start_text = "00:01:00"
window._applied_clip_end_text = "00:12:00"
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Freeze Clip",
    "candidates": [
        {"id": "full", "source": url, "url": url, "title": "Freeze Clip", "display_title": "Freeze Clip", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 3600, "sort_bytes": 600},
    ],
    "warnings": [],
})
for _ in range(50):
    app.processEvents()
    time.sleep(0.01)
    if window.active_downloads:
        break
print(len(window.active_downloads))
active = window.active_downloads[0]["candidate"] if window.active_downloads else {}
print(bool(active.get("clip_range")))
print((active.get("display_title") or ""))
row = next((item for item in window.rows if window._row_is_downloading(item)), window.rows[0])
window.start_download_for_row(row)
for _ in range(50):
    app.processEvents()
    time.sleep(0.01)
    if len(window.active_downloads) >= 2:
        break
print(len(window.rows))
print(len(window.active_downloads))
print(sum(1 for item in window.rows if (item.get("candidate") or {}).get("clip_range")))
fake_download.release = True
while window.active_downloads:
    app.processEvents()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["1", "False", "Freeze Clip", "2", "2", "1"])

    def test_clipflow_qt_full_download_then_clip_spawns_sibling_without_mutating_full_row(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://www.youtube.com/watch?v=xAxh-dEHcTk"

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    import time
    if on_event:
        on_event({"type": "progress", "percent": 3, "message": "3.0%"})
    while not getattr(fake_download, "release", False):
        time.sleep(0.01)
    title = (candidate or {}).get("display_title") or (candidate or {}).get("title") or "out"
    return {"ok": True, "output_dir": output_dir, "output_path": str(output_dir) + f"/{title}.mp4", "target_url": page_url}

fake_download.release = False

app = QApplication([])
window = ClipFlowWindow(download_func=fake_download)
window.folder_input.setText("C:/Temp")
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "Full Then Clip",
    "candidates": [
        {"id": "full", "source": url, "url": url, "title": "Full Then Clip", "display_title": "Full Then Clip", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 600, "sort_bytes": 600},
    ],
    "warnings": [],
})
row = window.rows[0]
window.start_download_for_row(row)
while not window.active_downloads:
    app.processEvents()
window.clip_start_input.setText("00:01:00")
window.clip_end_input.setText("00:02:00")
window._apply_clip_range_popup()
window.start_download_for_row(row)
while len(window.active_downloads) < 2:
    app.processEvents()
titles = [(item.get("candidate") or {}).get("display_title") for item in window.rows]
full_rows = [item for item in window.rows if not (item.get("candidate") or {}).get("clip_range")]
clip_rows = [item for item in window.rows if (item.get("candidate") or {}).get("clip_range")]
print(len(window.rows))
print(len(window.active_downloads))
print(len(full_rows))
print(len(clip_rows))
print((full_rows[0].get("candidate") or {}).get("display_title") if full_rows else "")
print(bool((full_rows[0].get("candidate") or {}).get("clip_range")) if full_rows else "missing")
print(sum("[01m00s-02m00s]" in str(title) for title in titles))
fake_download.release = True
while window.active_downloads:
    app.processEvents()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["2", "2", "1", "1", "Full Then Clip", "False", "1"])

    def test_clipflow_qt_first_clip_download_does_not_spawn_full_video_row(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://media.test/watch/first-clip"

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    import time
    while not getattr(fake_download, "release", False):
        time.sleep(0.01)
    return {"ok": True, "output_dir": output_dir, "output_path": str(output_dir) + "/out.mp4", "target_url": page_url}

fake_download.release = False

app = QApplication([])
window = ClipFlowWindow(download_func=fake_download)
window.folder_input.setText("C:/Temp")
window._analysis_finished({
    "webpage_url": url,
    "url": url,
    "title": "First Clip",
    "candidates": [
        {"id": "first", "source": url, "url": url, "title": "First Clip", "display_title": "First Clip", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 1200, "sort_bytes": 1200},
    ],
    "warnings": [],
})
row = window.rows[0]
window.clip_start_input.setText("00:02:00")
window.clip_end_input.setText("00:12:00")
window._apply_clip_range_popup()
window.start_download_for_row(row)
while not window.active_downloads:
    app.processEvents()
titles = [(item.get("candidate") or {}).get("display_title") for item in window.rows]
print(len(window.rows))
print(sum("[02m00s-12m00s]" in title for title in titles))
print(sum(title == "First Clip" for title in titles))
fake_download.release = True
while window.active_downloads:
    app.processEvents()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["1", "1", "0"])

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
print(row["widget"].row_quality_label.text())
print(row["widget"].row_quality_label.isHidden())
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["완료", "Already Here.mp4", "False", "이미 있는 파일", "False"])

    def test_clipflow_qt_existing_output_keeps_row_order_and_flashes_existing_card(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, READY_STATUS

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
existing = Path(tempdir.name) / "Older Existing.mp4"
existing.write_bytes(b"done")
window = ClipFlowWindow()
window._set_save_folder(tempdir.name)
window._row_sequence = 2
older_candidate = {"id": "older", "source": "https://media.test/older", "url": "https://media.test/older", "title": "Older Existing", "display_title": "Older Existing", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 1}
newer_candidate = {"id": "newer", "source": "https://media.test/newer", "url": "https://media.test/newer", "title": "Newer", "display_title": "Newer", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 1}
window.rows = [
    {"id": "newer", "kind": "video", "candidate": newer_candidate, "qualities": [newer_candidate], "quality_options": [newer_candidate], "selected_index": 0, "selected_format_index": 0, "source_url": "https://media.test/newer", "input_url": "https://media.test/newer", "status": READY_STATUS, "progress": 0, "progress_text": "", "output_path": "", "messages": [], "created_order": 2},
    {"id": "older", "kind": "video", "candidate": older_candidate, "qualities": [older_candidate], "quality_options": [older_candidate], "selected_index": 0, "selected_format_index": 0, "source_url": "https://media.test/older", "input_url": "https://media.test/older", "status": READY_STATUS, "progress": 0, "progress_text": "", "output_path": "", "messages": [], "created_order": 1},
]
window._render_rows()
older = window.rows[1]
window._mark_existing_output(older, existing)
print([row["id"] for row in window.rows])
print(older["created_order"])
print(older["widget"].property("existingFlash"))
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["['newer', 'older']", "1", "true"])

    def test_clipflow_qt_existing_output_redirects_notice_to_original_completed_card(self):
        script = r'''
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow, READY_STATUS, COMPLETED_STATUS

url = "https://media.test/watch/already-owned"
app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
existing = Path(tempdir.name) / "Owned Video.mp4"
existing.write_bytes(b"done-file")
window = ClipFlowWindow(download_func=lambda *a, **k: (_ for _ in ()).throw(AssertionError("download should not run")))
window._set_save_folder(tempdir.name)
candidate = {"id": "owned", "source": url, "url": url, "title": "Owned Video", "display_title": "Owned Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "duration": 10, "sort_bytes": 10}
original = {
    "id": "original",
    "kind": "video",
    "candidate": dict(candidate),
    "qualities": [dict(candidate)],
    "quality_options": [dict(candidate)],
    "selected_index": 0,
    "selected_format_index": 0,
    "source_url": url,
    "input_url": url,
    "status": COMPLETED_STATUS,
    "status_detail": "",
    "progress": 100,
    "progress_text": "완료",
    "output_path": str(existing),
    "messages": [],
    "created_order": 1,
    "fixed_candidate": False,
}
fresh = {
    "id": "fresh",
    "kind": "video",
    "candidate": dict(candidate),
    "qualities": [dict(candidate)],
    "quality_options": [dict(candidate)],
    "selected_index": 0,
    "selected_format_index": 0,
    "source_url": url,
    "input_url": url,
    "status": READY_STATUS,
    "progress": 0,
    "progress_text": "",
    "output_path": "",
    "messages": [],
    "created_order": 2,
}
window.rows = [fresh, original]
window._render_rows()
window.selected_row_index = 0
window.start_download_for_row(fresh)
ids = [row["id"] for row in window.rows]
owner = next(row for row in window.rows if row["id"] == "original")
print(ids)
print(owner.get("status_detail"))
print(owner["widget"].property("existingFlash"))
print(any(row["id"] == "fresh" for row in window.rows))
tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["['original']", "이미 있는 파일", "true", "False"])

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

    def test_clipflow_qt_delete_confirm_dialog_accepts_enter(self):
        script = r'''
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import DeleteConfirmDialog

app = QApplication([])
dialog = DeleteConfirmDialog(Path("Video.mp4"))
dialog.show()
app.processEvents()
print(dialog.ok_button.isDefault())
QTimer.singleShot(0, lambda: QTest.keyClick(dialog, Qt.Key_Return))
print(dialog.exec())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "1"])

    def test_clipflow_qt_outlined_button_keeps_stable_popup_size(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import OutlinedButton

app = QApplication([])
button = OutlinedButton("단일 영상")
button.show()
app.processEvents()
print(button.sizeHint().height() >= 34)
print(button.height() >= 34)
print(button.sizeHint().width() > button.sizeHint().height())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True"])

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
print(child_widget.row_quality_label.isHidden())
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

    def test_clipflow_qt_default_engine_does_not_preload_ytdlp_or_ffmpeg_on_startup(self):
        script = r'''
import sys
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
print("yt_dlp" in sys.modules)
print("imageio_ffmpeg" in sys.modules)
print(hasattr(window.analyze_func, "_clipflow_uses_analysis_worker_pool"))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "False", "True"])

    def test_clipflow_qt_default_analysis_uses_subprocess_boundary(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools import clipflow_qt

app = QApplication([])
calls = []
events = []
original = clipflow_qt.engine.analyze_url_in_subprocess

def fake_process(url, cookie_source=None, output_ext=None, on_event=None, proxy_url=None):
    calls.append([url, cookie_source, output_ext, proxy_url])
    if on_event:
        on_event({"type": "status", "message": "URL 분석 중"})
    return {"webpage_url": url, "url": url, "candidates": [], "warnings": []}

clipflow_qt.engine.analyze_url_in_subprocess = fake_process
try:
    window = clipflow_qt.ClipFlowWindow()
    result = window.analyze_func(
        "https://media.test/watch",
        cookie_source="Firefox",
        output_ext="MP4",
        proxy_url="http://127.0.0.1:8080",
        on_event=events.append,
    )
finally:
    clipflow_qt.engine.analyze_url_in_subprocess = original

print(calls)
print(events)
print(result["webpage_url"])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "[['https://media.test/watch', 'Firefox', 'MP4', 'http://127.0.0.1:8080']]",
                "[{'type': 'status', 'message': 'URL 분석 중'}]",
                "https://media.test/watch",
            ],
        )

    def test_clipflow_qt_resolves_ambiguous_youtube_playlist_choice(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

url = "https://youtu.be/7DAFS8sga2k?list=PL5cMV8jURyS9R5ideqDxaIguOnbby9MVs"

app = QApplication([])
single = ClipFlowWindow(playlist_choice_func=lambda value: "single")
playlist = ClipFlowWindow(playlist_choice_func=lambda value: "playlist")
cancelled = ClipFlowWindow(playlist_choice_func=lambda value: None)
plain = ClipFlowWindow(playlist_choice_func=lambda value: (_ for _ in ()).throw(AssertionError("should not ask")))

print(single._resolve_playlist_choice_url(url))
print(playlist._resolve_playlist_choice_url(url))
print(cancelled._resolve_playlist_choice_url(url))
print(plain._resolve_playlist_choice_url("https://youtu.be/Kc-JF2eSmt8"))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "https://youtu.be/7DAFS8sga2k",
                "https://www.youtube.com/playlist?list=PL5cMV8jURyS9R5ideqDxaIguOnbby9MVs",
                "None",
                "https://youtu.be/Kc-JF2eSmt8",
            ],
        )

    def test_clipflow_qt_custom_analysis_function_bypasses_subprocess_boundary(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools import clipflow_qt

app = QApplication([])
calls = []
original = clipflow_qt.engine.analyze_url_in_subprocess

def forbidden_process(*_args, **_kwargs):
    raise AssertionError("default analysis subprocess should not be used")

def fake_analyze(url, cookie_source=None, output_ext=None, on_event=None, proxy_url=None):
    calls.append([url, cookie_source, output_ext, proxy_url])
    return {"webpage_url": url, "url": url, "candidates": [], "warnings": []}

clipflow_qt.engine.analyze_url_in_subprocess = forbidden_process
try:
    window = clipflow_qt.ClipFlowWindow(analyze_func=fake_analyze)
    result = window.analyze_func("https://media.test/custom", cookie_source="None", output_ext="WEBM", proxy_url="proxy")
finally:
    clipflow_qt.engine.analyze_url_in_subprocess = original

print(calls)
print(result["webpage_url"])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "[['https://media.test/custom', 'None', 'WEBM', 'proxy']]",
                "https://media.test/custom",
            ],
        )

    def test_clipflow_qt_default_download_uses_subprocess_boundary(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools import clipflow_qt

app = QApplication([])
calls = []
events = []
original = clipflow_qt.engine.download_candidate_in_subprocess

def fake_process(page_url, candidate, output_dir, cookie_source=None, on_event=None, proxy_url=None):
    calls.append([page_url, candidate.get("format_selector"), str(output_dir), cookie_source, proxy_url])
    if on_event:
        on_event({"type": "progress", "percent": 12, "message": "12%"})
    return {"ok": True, "output_dir": str(output_dir), "target_url": page_url}

clipflow_qt.engine.download_candidate_in_subprocess = fake_process
try:
    window = clipflow_qt.ClipFlowWindow()
    result = window.download_func(
        "https://media.test/watch",
        {"format_selector": "best", "output_ext": "mp4"},
        "C:/Out",
        cookie_source="Firefox",
        proxy_url="http://127.0.0.1:8080",
        on_event=events.append,
    )
finally:
    clipflow_qt.engine.download_candidate_in_subprocess = original

print(calls)
print(events)
print(result["target_url"])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "[['https://media.test/watch', 'best', 'C:/Out', 'Firefox', 'http://127.0.0.1:8080']]",
                "[{'type': 'progress', 'percent': 12, 'message': '12%'}]",
                "https://media.test/watch",
            ],
        )

    def test_clipflow_qt_auto_download_warms_default_download_worker(self):
        script = r'''
from PySide6.QtCore import QTimer, QThread
from PySide6.QtWidgets import QApplication
from tools import clipflow_qt

app = QApplication([])
warm_calls = []
download_calls = []

original_warm = getattr(clipflow_qt.engine, "warm_download_worker", None)
original_download = clipflow_qt.engine.download_candidate_in_subprocess

def fake_warm():
    warm_calls.append(QThread.currentThread() is app.thread())

def fake_download(page_url, candidate, output_dir, cookie_source=None, on_event=None, proxy_url=None):
    download_calls.append([page_url, candidate.get("id")])
    return {"ok": True, "output_dir": output_dir, "target_url": page_url}

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

clipflow_qt.engine.warm_download_worker = fake_warm
clipflow_qt.engine.download_candidate_in_subprocess = fake_download
try:
    window = clipflow_qt.ClipFlowWindow(analyze_func=fake_analyze)
    window.url_input.setText("https://media.test/video")
    window._start_analysis(auto_download=True)

    def drive():
        if window.analysis_thread or window.download_thread or window.active_downloads:
            return
        app.quit()

    timer = QTimer()
    timer.timeout.connect(drive)
    timer.start(20)
    QTimer.singleShot(5000, app.quit)
    app.exec()
finally:
    if original_warm is None:
        delattr(clipflow_qt.engine, "warm_download_worker")
    else:
        clipflow_qt.engine.warm_download_worker = original_warm
    clipflow_qt.engine.download_candidate_in_subprocess = original_download

print(warm_calls)
print(download_calls)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["[True]", "[['https://media.test/video', 'best']]"])

    def test_clipflow_qt_download_button_queues_url_while_analysis_is_running(self):
        script = r'''
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
analyzed = []
downloaded = []

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    analyzed.append(url)
    time.sleep(0.15)
    return {
        "webpage_url": url,
        "url": url,
        "title": url.rsplit("/", 1)[-1],
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": url, "display_title": url, "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    downloaded.append(page_url)
    return {"ok": True, "output_dir": output_dir, "target_url": page_url}

window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
window.url_input.setText("https://media.test/one")
window._start_analysis(auto_download=True)
window.url_input.setText("https://media.test/two")
window._refresh_primary_action()
print(window.primary_button.isEnabled())
window._handle_primary_action()

def drive():
    if window.analysis_thread or window.download_thread or window.active_downloads or window.queued_download_rows:
        return
    if len(downloaded) < 2:
        return
    print(analyzed)
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
                "True",
                "['https://media.test/one', 'https://media.test/two']",
                "['https://media.test/one', 'https://media.test/two']",
            ],
        )

    def test_clipflow_qt_attaches_cached_analysis_info_only_to_download_candidate(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
download_infos = []

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    download_infos.append(candidate.get("_download_info"))
    return {"ok": True, "output_dir": output_dir, "target_url": page_url}

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "_download_infos": {
            "info-key": {"id": "video-id", "title": "Video", "formats": [{"format_id": "18", "url": "https://media.test/video.mp4"}]},
        },
        "candidates": [
            {"id": "best", "_download_info_key": "info-key", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
url = "https://media.test/video"
analysis = fake_analyze(url)
window._analysis_finished(analysis)
row = window.rows[0]
print("_download_info" in row["candidate"])
window.start_download_for_row(row)
while window.active_downloads:
    app.processEvents()
print(download_infos)
print("_download_info" in row["candidate"])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "False",
                "[{'id': 'video-id', 'title': 'Video', 'formats': [{'format_id': '18', 'url': 'https://media.test/video.mp4'}]}]",
                "False",
            ],
        )

    def test_clipflow_qt_top_clip_inputs_attach_range_only_when_set(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
print(window.clip_range_button.text())
print(getattr(window, "clip_range_popup", None))
print(window.current_clip_range())
print("clip_range" in window._candidate_for_download({"id": "row"}, {"title": "Video"}))
window.clip_start_input.setText("00:00:10")
window.clip_end_input.setText("00:00:20")
print(window.current_clip_range())
print("clip_range" in window._candidate_for_download({"id": "row"}, {"title": "Video"}))
window._apply_clip_range_popup()
print(window.current_clip_range())
print(window._candidate_for_download({"id": "row"}, {"title": "Video"}).get("clip_range"))
window.clip_start_input.setText("00:00:00")
window.clip_end_input.setText("00:00:00")
window._apply_clip_range_popup()
print(window.current_clip_range())
print("clip_range" in window._candidate_for_download({"id": "row"}, {"title": "Video"}))
window.clip_start_input.setText("00:12:12")
window.clip_end_input.setText("00:13:00")
window._apply_clip_range_popup()
window.url_input.setText("https://media.test/changed")
print(window.clip_start_input.text())
print(window.clip_end_input.text())
print(window.current_clip_range())
window.clip_start_input.setText("00:10:00")
window.clip_end_input.setText("00:20:00")
window._apply_clip_range_popup()
window._toggle_clip_range_popup()
window.clip_start_input.setText("00:30:00")
window.clip_range_popup.close()
app.processEvents()
print(window.clip_start_input.text())
print(window.clip_end_input.text())
print(window.current_clip_range())
print(window.clip_cut_mode())
print(window._candidate_for_download({"id": "row"}, {"title": "Video"}).get("clip_cut_mode"))
row = {"id": "row", "candidate": {"title": "Video", "display_title": "Video", "output_ext": "mp4", "duration": 3600, "sort_bytes": 3600}}
first = window._candidate_for_download(row, row["candidate"])
window._apply_download_candidate_to_row(row, first)
window.clip_start_input.setText("00:00:30")
window.clip_end_input.setText("00:00:40")
window._apply_clip_range_popup()
second = window._candidate_for_download(row, row["candidate"])
print(first["clip_range"])
print(second["clip_range"])
print(second["display_title"])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "구간선택",
                "None",
                "None",
                "False",
                "None",
                "False",
                "{'start': 10.0, 'end': 20.0}",
                "{'start': 10.0, 'end': 20.0}",
                "None",
                "False",
                "",
                "",
                "None",
                "00:10:00",
                "00:20:00",
                "{'start': 600.0, 'end': 1200.0}",
                "fast",
                "fast",
                "{'start': 600.0, 'end': 1200.0}",
                "{'start': 30.0, 'end': 40.0}",
                "Video [00m30s-00m40s]",
            ],
        )

    def test_clipflow_qt_clip_range_button_reveals_options_popup(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QComboBox
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
window.show()
app.processEvents()
print(getattr(window, "clip_range_popup", None))
QTest.mouseClick(window.clip_range_button, Qt.LeftButton)
app.processEvents()
print(window.clip_range_popup.isVisible())
print(window.clip_start_label.text())
print(window.clip_end_label.text())
print(window.clip_start_input.display_text())
print(window.clip_end_input.display_text())
print(len(window.clip_range_popup.findChildren(QComboBox)))
print([button.text() for button in window.clip_range_popup.findChildren(QPushButton)])
start_rects = window.clip_start_input._segment_rects
print(start_rects[0].left() > 0)
window.clip_start_input._update_hover_cursor(start_rects[0].center())
print(window.clip_start_input.cursor().shape() == Qt.PointingHandCursor)
print(all(button.cursor().shape() == Qt.PointingHandCursor for button in window.clip_range_popup.findChildren(QPushButton)))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["None", "True", "시작시간", "종료시간", "HH:MM:SS", "HH:MM:SS", "0", "['초기화', '적용']", "True", "True", "True"],
        )

    def test_clipflow_qt_clip_range_popup_enter_applies(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
window.show()
app.processEvents()
QTest.mouseClick(window.clip_range_button, Qt.LeftButton)
app.processEvents()
window.clip_start_input.setText("00:00:10")
window.clip_end_input.setText("00:00:20")
QTest.keyClick(window.clip_range_popup, Qt.Key_Return)
app.processEvents()
print(window.clip_range_popup.isVisible())
print(window.current_clip_range())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "{'start': 10.0, 'end': 20.0}"])

    def test_clipflow_qt_invalid_clip_range_does_not_start_download(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
calls = []

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    calls.append(candidate)
    return {"ok": True, "output_dir": output_dir, "target_url": page_url}

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

window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
window._analysis_finished(fake_analyze("https://media.test/video"))
window.clip_start_input.setText("00:00:20")
window.clip_end_input.setText("00:00:10")
window._apply_clip_range_popup()
print(window.clip_start_input.text())
window.clip_start_input.setText("00:60:00")
window.clip_end_input.setText("01:00:00")
window._apply_clip_range_popup()
window.start_download_for_row(window.rows[0])
while window.active_downloads:
    app.processEvents()
print(len(calls))
print(any("종료구간" in message for message in window.event_messages))
print(any("59 이하" in message for message in window.event_messages))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["00:00:20", "0", "True", "True"])

    def test_clipflow_qt_clip_range_start_past_duration_does_not_start_download(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
calls = []

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    calls.append(candidate)
    return {"ok": True, "output_dir": output_dir, "target_url": page_url}

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 120},
        ],
        "warnings": [],
    }

window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
window._analysis_finished(fake_analyze("https://media.test/video"))
row = window.rows[0]
window.clip_start_input.setText("00:03:00")
window._apply_clip_range_popup()
window.start_download_for_row(row)
while window.active_downloads:
    app.processEvents()
print(len(calls))
print(row["status"])
print(any("영상 길이" in message for message in window.event_messages))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["0", "오류", "True"])

    def test_clipflow_qt_clip_range_end_past_duration_does_not_start_download(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
calls = []

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    calls.append(candidate)
    return {"ok": True, "output_dir": output_dir, "target_url": page_url}

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 120},
        ],
        "warnings": [],
    }

window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
window._analysis_finished(fake_analyze("https://media.test/video"))
row = window.rows[0]
window.clip_start_input.setText("00:01:00")
window.clip_end_input.setText("00:03:00")
window._apply_clip_range_popup()
window.start_download_for_row(row)
while window.active_downloads:
    app.processEvents()
print(len(calls))
print(row["status"])
print(any("종료 시간이 영상 길이를 벗어났습니다" in message for message in window.event_messages))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["0", "오류", "True"])

    def test_clipflow_qt_global_clip_download_updates_visible_row_metadata(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
downloads = []

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    downloads.append(candidate)
    return {"ok": True, "output_dir": output_dir, "output_path": output_dir + "/Video [12m12s-12m15s].mp4", "target_url": page_url}

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 7200, "sort_bytes": 7200},
        ],
        "warnings": [],
    }

window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
window._analysis_finished(fake_analyze("https://media.test/video"))
row = window.rows[0]
window.clip_start_input.setText("00:12:12")
window.clip_end_input.setText("00:12:15")
window._apply_clip_range_popup()
window.start_download_for_row(row)
while window.active_downloads:
    app.processEvents()
print(row["candidate"]["display_title"])
print(row["candidate"]["duration"])
print(row["candidate"]["sort_bytes"])
print(downloads[0]["display_title"])
print(len(window.rows))
clip_row = next(item for item in window.rows if item.get("fixed_candidate"))
print(clip_row["candidate"]["display_title"])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["Video [12m12s-12m15s]", "3", "3", "Video [12m12s-12m15s]", "1", "Video [12m12s-12m15s]"],
        )

    def test_clipflow_qt_global_clip_download_does_not_skip_when_full_file_exists(self):
        script = r'''
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
Path(tempdir.name, "Video.mp4").write_bytes(b"full")
downloads = []

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    downloads.append(candidate)
    output = Path(output_dir) / "Video [00m10s-00m20s].mp4"
    output.write_bytes(b"segment")
    if on_event:
        on_event({"type": "file", "path": str(output)})
    return {"ok": True, "output_dir": output_dir, "output_path": str(output), "target_url": page_url}

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 120},
        ],
        "warnings": [],
    }

try:
    window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
    window.folder_input.setText(tempdir.name)
    window._analysis_finished(fake_analyze("https://media.test/video"))
    row = window.rows[0]
    window.clip_start_input.setText("00:00:10")
    window.clip_end_input.setText("00:00:20")
    window._apply_clip_range_popup()
    window.start_download_for_row(row)
    while window.active_downloads:
        app.processEvents()
    clip_row = next(item for item in window.rows if item.get("fixed_candidate"))
    print(len(downloads))
    print(row["candidate"]["display_title"])
    print(clip_row["candidate"]["display_title"])
    print(Path(clip_row["output_path"]).name)
finally:
    tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["1", "Video [00m10s-00m20s]", "Video [00m10s-00m20s]", "Video [00m10s-00m20s].mp4"],
        )

    def test_clipflow_qt_global_clip_download_does_not_skip_different_saved_segment(self):
        script = r'''
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
downloads = []

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    downloads.append((candidate["clip_range"], candidate["display_title"]))
    output = Path(output_dir) / f"{candidate['display_title']}.mp4"
    output.write_bytes(b"segment")
    if on_event:
        on_event({"type": "progress", "percent": 50, "message": "50.0% 12.0 MB/s 처리 20x ETA 0:01", "speed_text": "20x", "eta_text": "0:01"})
        on_event({"type": "file", "path": str(output)})
    return {"ok": True, "output_dir": output_dir, "output_path": str(output), "target_url": page_url}

def fake_analyze(url, cookie_source=None, proxy_url=None, output_ext=None, on_event=None):
    return {
        "webpage_url": url,
        "url": url,
        "title": "Video",
        "candidates": [
            {"id": "best", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 120},
        ],
        "warnings": [],
    }

try:
    window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
    window.folder_input.setText(tempdir.name)
    window._analysis_finished(fake_analyze("https://media.test/video"))
    row = window.rows[0]
    window.clip_start_input.setText("00:00:10")
    window.clip_end_input.setText("00:00:20")
    window._apply_clip_range_popup()
    window.start_download_for_row(row)
    while window.active_downloads:
        app.processEvents()
    window.clip_start_input.setText("00:00:30")
    window.clip_end_input.setText("00:00:40")
    window._apply_clip_range_popup()
    window.start_download_for_row(row)
    while window.active_downloads:
        app.processEvents()
    print(downloads)
    print(row["widget"].row_quality_label.text())
finally:
    tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(
            lines[0],
            "[({'start': 10.0, 'end': 20.0}, 'Video [00m10s-00m20s]'), ({'start': 30.0, 'end': 40.0}, 'Video [00m30s-00m40s]')]",
        )

    def test_clipflow_qt_timecode_input_supports_parts_and_direct_text(self):
        script = r'''
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tools.clipflow_widgets import TimecodeInput

app = QApplication([])
field = TimecodeInput()
field.resize(172, 36)
field.show()
app.processEvents()
print(field.display_text())
print(field.sizeHint().width() >= 160)
field.set_time_parts(1, 2, 3)
print(field.text())
field.setText("00:10:05")
print(field.time_seconds())
field.set_selected_segment(0)
QTest.keyClicks(field, "121212")
print(field.text())
print(field.time_seconds())
field.clear()
field.set_selected_segment(1)
QTest.keyClicks(field, "1212")
print(field.text())
field.setText("12:12:12")
field.set_selected_segment(1)
QTest.keyClicks(field, "31")
print(field.text())
print(field.selected_segment())
print(field.has_selected_segment())
field.clear()
field.set_selected_segment(0)
QTest.keyClicks(field, "1")
QTest.keyClick(field, Qt.Key_Tab)
print(field.text())
print(field.selected_segment())
field.clear()
field.set_selected_segment(1)
QTest.keyClicks(field, "5")
print(field.text())
field.clear()
field.set_selected_segment(2)
QTest.keyClicks(field, "7")
print(field.text())
field.setText("12:31:12")
field.set_selected_segment(2)
QTest.keyClicks(field, "45")
print(field.text())
print(field.selected_segment())
field.set_selected_segment(1)
QTest.keyClicks(field, "99")
print(field.display_text())
print(field.selected_segment())
field.set_selected_segment(2)
QTest.keyClicks(field, "99")
print(field.display_text())
print(field.selected_segment())
completed = []
field.editingComplete.connect(lambda: completed.append(field.text()))
field.clear()
field.set_selected_segment(2)
QTest.keyClicks(field, "1")
QTest.keyClick(field, Qt.Key_Tab)
print(completed[-1])
print(field.selected_segment())
print(len(field._segment_rects))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["HH:MM:SS", "True", "01:02:03", "605.0", "12:12:12", "43932.0", "00:12:12", "12:31:12", "2", "True", "01:00:00", "1", "00:05:00", "00:00:07", "12:31:45", "2", "12:MM:45", "1", "12:00:SS", "2", "00:00:01", "2", "3"])

    def test_clipflow_qt_start_seconds_advances_to_end_time(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
window.show()
app.processEvents()
window.clip_start_input.set_selected_segment(2)
QTest.keyClicks(window.clip_start_input, "45")
app.processEvents()
print(window.clip_start_input.text())
print(window.clip_end_input.has_selected_segment())
print(window.clip_end_input.selected_segment())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["00:00:45", "True", "0"])

    def test_clipflow_qt_row_level_segment_action_requires_local_file(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
downloads = []

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    downloads.append(candidate)
    if on_event:
        on_event({"type": "file", "path": output_dir + "/Video [00m10s-00m20s].mp4"})
    return {"ok": True, "output_dir": output_dir, "output_path": output_dir + "/Video [00m10s-00m20s].mp4", "target_url": page_url}

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

window = ClipFlowWindow(analyze_func=fake_analyze, download_func=fake_download)
window._analysis_finished(fake_analyze("https://media.test/video"))
source = window.rows[0]
window.download_segment_for_row(source, {"start": 10.0, "end": 20.0})
while window.active_downloads:
    app.processEvents()
print(len(window.rows))
print(len(downloads))
print(any("로컬 파일" in message for message in window.event_messages))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "1",
                "0",
                "True",
            ],
        )

    def test_clipflow_qt_completed_row_segment_action_extracts_from_local_file(self):
        script = r'''
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from tools import downloader_engine as engine
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
tempdir = tempfile.TemporaryDirectory()
source = Path(tempdir.name) / "Already Downloaded.mp4"
source.write_bytes(b"video")
calls = {"download": 0, "extract": []}

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    calls["download"] += 1
    raise AssertionError("network download should not run for local segment extraction")

def fake_extract(input_path, candidate, output_dir=None, on_event=None, ffmpeg_exe=None, runner=None):
    output = Path(output_dir) / (candidate["display_title"] + ".mp4")
    output.write_bytes(b"segment")
    calls["extract"].append((str(input_path), candidate["display_title"], candidate["duration"]))
    if on_event:
        on_event({"type": "file", "path": str(output)})
    return {"ok": True, "output_dir": str(output.parent), "output_path": str(output)}

original_extract = getattr(engine, "extract_existing_media_segment", None)
engine.extract_existing_media_segment = fake_extract

try:
    window = ClipFlowWindow(download_func=fake_download)
    window.folder_input.setText(tempdir.name)
    row = {
        "id": "row-1",
        "kind": "video",
        "candidate": {
            "id": "best",
            "source": "https://media.test/watch",
            "url": "https://media.test/watch",
            "title": "Already Downloaded",
            "display_title": "Already Downloaded",
            "thumbnail": "",
            "ext": "mp4",
            "output_ext": "mp4",
            "duration": 120,
            "sort_bytes": 120,
        },
        "qualities": [],
        "quality_options": [],
        "selected_index": 0,
        "selected_format_index": 0,
        "source_url": "https://media.test/watch",
        "input_url": "https://media.test/watch",
        "status": "완료",
        "messages": [],
        "progress": 100,
        "progress_text": "",
        "output_path": str(source),
        "created_order": 1,
    }
    window.rows = [row]
    window._render_rows()
    window.download_segment_for_row(row, {"start": 10.0, "end": 20.0})
    while window.active_downloads:
        app.processEvents()
    fixed = next(item for item in window.rows if item.get("fixed_candidate"))
    print(calls["download"])
    print(calls["extract"][0][0] == str(source))
    print(calls["extract"][0][1])
    print(calls["extract"][0][2])
    print(Path(fixed["output_path"]).name)
finally:
    if original_extract is None:
        delattr(engine, "extract_existing_media_segment")
    else:
        engine.extract_existing_media_segment = original_extract
    tempdir.cleanup()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["0", "True", "Already Downloaded [00m10s-00m20s]", "10", "Already Downloaded [00m10s-00m20s].mp4"],
        )

    def test_clipflow_qt_completed_history_preserves_clip_range_without_signed_cdn_url(self):
        script = r'''
from tools.clipflow_qt import ClipFlowWindow, COMPLETED_STATUS
from PySide6.QtWidgets import QApplication

app = QApplication([])
window = ClipFlowWindow()
window.rows = [
    {
        "id": "row-1",
        "kind": "video",
        "candidate": {
            "id": "best",
            "title": "Video",
            "display_title": "Video",
            "url": "https://cdn.example.test/signed.mp4?token=secret",
            "source": "https://chzzk.naver.com/video/1",
            "output_ext": "mp4",
            "clip_range": {"start": 10.0, "end": 20.0},
        },
        "status": COMPLETED_STATUS,
        "source_url": "https://chzzk.naver.com/video/1",
        "analysis_source_url": "https://chzzk.naver.com/video/1",
        "output_path": "C:/Out/Video [00m10s-00m20s].mp4",
        "messages": [],
    }
]
payload = window._completed_history_payload()
candidate = payload[0]["candidate"]
print(candidate["clip_range"])
print(candidate.get("url", ""))
print(candidate["source"])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "{'start': 10.0, 'end': 20.0}",
                "",
                "https://chzzk.naver.com/video/1",
            ],
        )

    def test_clipflow_qt_playlist_entry_event_attaches_cached_analysis_info_to_child_download(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
download_infos = []

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    download_infos.append(candidate.get("_download_info"))
    return {"ok": True, "output_dir": output_dir, "target_url": page_url}

window = ClipFlowWindow(download_func=fake_download)
playlist_url = "https://youtube.test/playlist?list=abc"
parent = window._playlist_parent_loading_row(playlist_url)
window.rows = [parent]
window._playlist_event_parent_id = parent["id"]
candidate = {"id": "child", "_download_info_key": "child-key", "source": "https://youtube.test/watch?v=child", "url": "https://youtube.test/watch?v=child", "title": "Child", "display_title": "Child", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30}
window._handle_playlist_analysis_event({
    "type": "playlist_entry",
    "parent_id": parent["id"],
    "index": 1,
    "title": "Child",
    "source_url": "https://youtube.test/watch?v=child",
    "url": "https://youtube.test/watch?v=child",
    "analysis": {"_download_infos": {"child-key": {"id": "child-id", "title": "Child", "formats": [{"format_id": "18", "url": "https://media.test/child.mp4"}]}}},
    "candidates": [candidate],
    "candidate": candidate,
})
child = next(row for row in window.rows if row.get("is_playlist_child") and not row.get("child_loading"))
window.start_download_for_row(child)
while window.active_downloads:
    app.processEvents()
print(download_infos)
print("_download_info" in child["candidate"])
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "[{'id': 'child-id', 'title': 'Child', 'formats': [{'format_id': '18', 'url': 'https://media.test/child.mp4'}]}]",
                "False",
            ],
        )

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
        self.assertEqual(result.stdout.splitlines(), ["2", "[None, 'playlist']", "True", "True"])

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

    def test_clipflow_qt_paused_analysis_row_remove_deletes_from_list(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
window.show()
app.processEvents()
parent = window._playlist_parent_loading_row("https://media.test/playlist/paused-remove")
parent["analysis_loading"] = True
parent["status"] = "일시정지"
window.rows = [parent]
window._render_rows()
app.processEvents()
widget = parent["widget"]
widget._set_hovered(True)
app.processEvents()
print(widget.remove_button.isVisible())
print(widget.delete_file_button.isVisible())
print(widget.remove_button.isEnabled())
window.remove_row(parent)
print(len(window.rows))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "False", "True", "0"])

    def test_clipflow_qt_paused_streaming_playlist_stops_future_auto_downloads(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_qt import ClipFlowWindow

app = QApplication([])
window = ClipFlowWindow()
started = []
window.start_download_for_row = lambda row: started.append((row.get("candidate") or {}).get("display_title"))
window._analysis_auto_download = True
source_url = "https://media.test/playlist/events"
window._handle_analysis_event({"type": "playlist_parent", "title": "Events", "count": 3, "source_url": source_url})
parent = window.rows[0]
window.pause_download_for_row(parent)
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
        "thumbnail": "https://img.test/one.jpg",
        "ext": "mp4",
        "output_ext": "mp4",
        "duration": 60,
        "sort_bytes": 10,
    }],
})
print(started)
print(parent["_playlist_auto_download_paused"])
print(parent["status"])
print(parent["candidate"]["thumbnail"])
print(any(row.get("child_loading") for row in window.rows))
widget = parent["widget"]
widget.set_status(parent["status"], parent.get("status_detail", ""))
print(widget.property("analyzing"))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["[]", "True", "일시정지", "https://img.test/one.jpg", "False", "false"],
        )

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
for index in range(14):
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
        "created_order": -100 - index,
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
        self.assertEqual(result.stdout.splitlines(), ["66", "66", "66"])

    def test_clipflow_qt_long_titles_wrap_to_two_lines(self):
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
window.resize(360, 420)
window.show()
window._analysis_finished(fake_analyze(url))
app.processEvents()
row_widget = window.rows[0]["widget"]
label = row_widget.title_label
print(type(label).__name__)
print(label.wordWrap())
print(label.maximumHeight())
print(label.text().count("\n") + 1)
print(label.text().endswith("..."))
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["QLabel", "False", "34", "2", "True"])

    def test_clipflow_qt_tooltips_are_styled_and_positioned_above_icon_buttons(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from tools.clipflow_icons import CustomTooltip, LucideIconButton
from tools.clipflow_theme import APP_STYLE

app = QApplication([])
button = LucideIconButton("folder", size=32, icon_size=18)
button.setToolTip("Folder")
button.show()
app.processEvents()
position = button.tooltip_position()
global_top = button.mapToGlobal(button.rect().topLeft()).y()
tooltip = CustomTooltip.instance()
tooltip.setText("폴더 열기")
tooltip.adjustSize()
pixmap = QPixmap(tooltip.size())
pixmap.fill(Qt.transparent)
tooltip.render(pixmap)
bubble = tooltip.bubble_geometry()
print("QToolTip" in APP_STYLE)
print(position.y() < global_top)
print("background: #FFFFFF" in tooltip.styleSheet())
print(tooltip.windowFlags() & Qt.NoDropShadowWindowHint == Qt.NoDropShadowWindowHint)
print(not bool(tooltip.windowFlags() & Qt.WindowStaysOnTopHint))
print(tooltip.graphicsEffect() is None)
print(tooltip.size() == bubble.size())
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True", "True", "True", "True", "True"])

    def test_clipflow_qt_tooltip_sits_close_to_hovered_icon(self):
        script = r'''
from PySide6.QtWidgets import QApplication
from tools.clipflow_icons import CustomTooltip, LucideIconButton, show_tooltip_above

app = QApplication([])
button = LucideIconButton("folder", size=32, icon_size=18)
button.move(400, 400)
button.show()
app.processEvents()
show_tooltip_above(button, "폴더 열기")
app.processEvents()
tooltip = CustomTooltip.instance()
bubble = tooltip.bubble_geometry().translated(tooltip.geometry().topLeft())
button_top = button.mapToGlobal(button.rect().topLeft()).y()
gap = button_top - bubble.bottom()
print(gap)
print(2 <= gap <= 6)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], "True")

    def test_clipflow_qt_download_row_pointer_cursor_only_on_favicon_and_hover_actions(self):
        script = r'''
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from tools.clipflow_rows import DownloadRowWidget

class RowOwner:
    select_mode = False

    def selected_candidate_for_row_ref(self, row):
        return row.get("candidate")

    def row_has_deletable_output(self, row):
        return False

app = QApplication([])
row = {"id": "row-1", "candidate": {"title": "Test", "display_title": "Test", "output_ext": "mp4"}}
widget = DownloadRowWidget(RowOwner(), row)
pointer = Qt.PointingHandCursor
arrow = Qt.ArrowCursor
checks = [
    widget.cursor().shape() == arrow,
    widget.thumbnail.cursor().shape() == arrow,
    widget.thumbnail.icon.cursor().shape() == arrow,
    widget.title_label.cursor().shape() == arrow,
    widget.info_icon.cursor().shape() == arrow,
    widget.size_icon.cursor().shape() == arrow,
    widget.source_link_button.cursor().shape() == pointer,
    widget.pause_download_button.cursor().shape() == pointer,
    widget.resume_download_button.cursor().shape() == pointer,
    widget.play_file_button.cursor().shape() == pointer,
    widget.open_folder_button.cursor().shape() == pointer,
    widget.remove_button.cursor().shape() == pointer,
    widget.delete_file_button.cursor().shape() == pointer,
    widget.more_button.cursor().shape() == pointer,
    widget.playlist_toggle_button.cursor().shape() == arrow,
    widget.select_checkbox.cursor().shape() == arrow,
    widget.actions_widget.cursor().shape() == arrow,
]
for ok in checks:
    print(ok)
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True"] * 17)


if __name__ == "__main__":
    unittest.main()
