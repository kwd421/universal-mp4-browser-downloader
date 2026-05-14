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
from PySide6.QtWidgets import QApplication
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
print("|".join(label.text() for label in window.header_labels))
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
                "영상|품질|포맷|길이|크기|상태|작업",
            ],
        )

    def test_clipflow_qt_analysis_prepends_and_deduplicates_rows(self):
        script = r'''
from PySide6.QtCore import QTimer
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
steps = ["one", "two", "one"]
started = False

def row_titles():
    return [row["widget"].title_label.text() for row in window.rows]

def drive():
    global started
    if not started:
        started = True
        window.url_input.setText("https://media.test/" + steps.pop(0))
        window._start_analysis()
        return
    if window.analysis_thread:
        return
    if steps:
        window.url_input.setText("https://media.test/" + steps.pop(0))
        window._start_analysis()
        return
    if len(window.rows) == 2:
        print("|".join(row_titles()))
        print(window.count_label.text())
        app.quit()

timer = QTimer()
timer.timeout.connect(drive)
timer.start(20)
QTimer.singleShot(5000, app.quit)
app.exec()
'''
        result = run_qt_script(script)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["one|two", "2개"])

    def test_clipflow_qt_download_uses_selected_quality_and_row_local_progress(self):
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
            {"id": "720", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "720p", "height": 720, "duration": 120, "sort_bytes": 20},
            {"id": "1080", "source": url, "url": url, "title": "Video", "display_title": "Video", "thumbnail": "", "ext": "mp4", "output_ext": "mp4", "resolution": "1080p", "height": 1080, "duration": 120, "sort_bytes": 30},
        ],
        "warnings": [],
    }

def fake_download(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
    downloaded.append(candidate["id"])
    if on_event:
        on_event({"type": "progress", "percent": 42, "message": "42.0% 7.0 MB/s ETA 00:10"})
        on_event({"type": "file", "path": output_dir + "/Video.mp4"})
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
        print(row_widget.quality_combo.itemText(0))
        print(row_widget.format_combo.currentText())
        print(row_widget.format_combo.isHidden())
        print(row_widget.format_label.isHidden())
        print(row_widget.info_label.text())
        print(row_widget.size_label.text())
        print(row_widget.quality_combo.isHidden())
        row_widget.quality_combo.setCurrentIndex(1)
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
        print(row_widget.status_label.text())
        print(row_widget.quality_combo.isHidden())
        print(row_widget.quality_combo.isEnabled())
        print(row_widget.format_combo.isHidden())
        print(row_widget.format_combo.isEnabled())
        print(hasattr(row_widget, "quality_value_label"))
        if hasattr(row_widget, "quality_value_label"):
            print(row_widget.quality_value_label.isHidden())
            print(row_widget.quality_value_label.text())
            print(row_widget.quality_value_label.property("locked"))
        print(row_widget.format_label.isHidden())
        print(row_widget.format_label.text())
        print(row_widget.format_label.property("locked"))
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
                "1080p",
                "MP4",
                "False",
                "True",
                "00:02:00",
                "30 B",
                "False",
                "720",
                "100",
                "",
                "True",
                "True",
                "완료",
                "True",
                "True",
                "True",
                "True",
                "True",
                "False",
                "720p",
                "true",
                "False",
                "MP4",
                "true",
                "False",
            ],
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


if __name__ == "__main__":
    unittest.main()
