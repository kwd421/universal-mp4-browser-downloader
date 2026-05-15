import json
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QSettings, QStandardPaths, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from tools import candidate_presenter as presenter
    from tools import downloader_engine as engine
    from tools.clipflow_rows import DownloadRowWidget, build_quality_options, row_kind, row_source_url
    from tools.clipflow_theme import (
        APP_NAME, APP_STYLE, COOKIE_CHOICES, COOKIE_DISPLAY_CHOICES, DEFAULT_OUTPUT_EXT, PRIMARY_BUTTON_WIDTH,
        TOP_FIELD_HEIGHT, configure_app_font, create_app_icon,
    )
    from tools.clipflow_icons import LucideIconButton, LucideIconWidget
    from tools.clipflow_widgets import CleanComboBox, ClearingUrlInput, PathDisplayInput, PrimaryActionButton
except ImportError:
    import candidate_presenter as presenter
    import downloader_engine as engine
    from clipflow_rows import DownloadRowWidget, build_quality_options, row_kind, row_source_url
    from clipflow_theme import (
        APP_NAME, APP_STYLE, COOKIE_CHOICES, COOKIE_DISPLAY_CHOICES, DEFAULT_OUTPUT_EXT, PRIMARY_BUTTON_WIDTH,
        TOP_FIELD_HEIGHT, configure_app_font, create_app_icon,
    )
    from clipflow_icons import LucideIconButton, LucideIconWidget
    from clipflow_widgets import CleanComboBox, ClearingUrlInput, PathDisplayInput, PrimaryActionButton


SETTINGS_ORG = os.environ.get("CLIPFLOW_SETTINGS_ORG", "ClipFlow")
SETTINGS_APP = os.environ.get("CLIPFLOW_SETTINGS_APP", "ClipFlow")
SAVE_FOLDER_SETTING = "save_folder"
COOKIE_SOURCE_SETTING = "cookie_source"
DOWNLOAD_HISTORY_SETTING = "download_history"
PREF_QUALITY_SETTING = "download_quality"
PREF_FORMAT_SETTING = "download_format"
PREF_CODEC_SETTING = "download_codec"
PREF_FRAME_SETTING = "download_frame"
SORT_KEY_SETTING = "sort_key"
SORT_DESC_SETTING = "sort_desc"

PREFERENCE_DEFAULTS = {
    "quality": "자동",
    "output_format": "자동",
    "codec": "자동",
    "frame_rate": "자동",
}
SORT_LABELS = {"latest": "최신순", "name": "이름순"}
SORT_KEYS_BY_LABEL = {label: key for key, label in SORT_LABELS.items()}
COOKIE_DISPLAY_TO_SOURCE = dict(zip(COOKIE_DISPLAY_CHOICES, COOKIE_CHOICES))
COOKIE_SOURCE_TO_DISPLAY = dict(zip(COOKIE_CHOICES, COOKIE_DISPLAY_CHOICES))


def default_save_folder():
    for location in (
        QStandardPaths.MoviesLocation,
        QStandardPaths.DownloadLocation,
        QStandardPaths.DocumentsLocation,
        QStandardPaths.HomeLocation,
    ):
        base_path = QStandardPaths.writableLocation(location)
        if base_path:
            return Path(base_path) / APP_NAME
    return Path(".").resolve() / APP_NAME


def local_file_url(path):
    return QUrl.fromLocalFile(str(Path(path).expanduser().resolve()))


def cookie_source_from_display(display_text):
    text = str(display_text or "").strip()
    if text in COOKIE_DISPLAY_TO_SOURCE:
        return COOKIE_DISPLAY_TO_SOURCE[text]
    if text.startswith("쿠키:"):
        text = text.split(":", 1)[1].strip()
    return text or "없음"


def _combo_text(combo):
    return str(combo.currentText()).strip()


class AnalyzeWorker(QObject):
    event = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, url, cookie_source, output_ext, analyze_func):
        super().__init__()
        self.url = url
        self.cookie_source = cookie_source
        self.output_ext = output_ext
        self.analyze_func = analyze_func

    @Slot()
    def run(self):
        try:
            analysis = self.analyze_func(
                self.url,
                cookie_source=self.cookie_source,
                output_ext=self.output_ext,
                on_event=self.event.emit,
            )
            self.finished.emit(analysis)
        except Exception as exc:
            self.failed.emit(str(exc))


class DownloadWorker(QObject):
    event = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, page_url, candidate, output_dir, cookie_source, download_func):
        super().__init__()
        self.page_url = page_url
        self.candidate = candidate
        self.output_dir = output_dir
        self.cookie_source = cookie_source
        self.download_func = download_func

    @Slot()
    def run(self):
        try:
            result = self.download_func(
                self.page_url,
                self.candidate,
                self.output_dir,
                cookie_source=self.cookie_source,
                on_event=self.event.emit,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class PreferencesDialog(QDialog):
    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.setWindowTitle("품질 설정")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)

        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.quality_combo = CleanComboBox()
        self.quality_combo.addItems(["자동", "2160p", "1440p", "1080p", "720p", "480p", "360p"])
        self.format_combo = CleanComboBox()
        self.format_combo.addItems(["자동", "MP4", "WEBM", "MP3", "WAV", "AAC"])
        self.codec_combo = CleanComboBox()
        self.codec_combo.addItems(["자동", "H264", "H265", "AV1", "VP9"])
        self.frame_combo = CleanComboBox()
        self.frame_combo.addItems(["자동", "60fps", "30fps"])

        self.quality_combo.setCurrentText(preferences.quality)
        self.format_combo.setCurrentText(preferences.output_format)
        self.codec_combo.setCurrentText(preferences.codec)
        self.frame_combo.setCurrentText(preferences.frame_rate)
        self.format_combo.currentIndexChanged.connect(self.refresh_controls)

        for row, (label, combo) in enumerate(
            (
                ("품질", self.quality_combo),
                ("포맷", self.format_combo),
                ("코덱", self.codec_combo),
                ("프레임", self.frame_combo),
            )
        ):
            label_widget = QLabel(label)
            label_widget.setObjectName("MetaText")
            form.addWidget(label_widget, row, 0)
            form.addWidget(combo, row, 1)

        layout.addLayout(form)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("취소")
        self.cancel_button.setObjectName("SecondaryButton")
        self.ok_button = QPushButton("확인")
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button.clicked.connect(self.accept)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.ok_button)
        layout.addLayout(buttons)
        self.refresh_controls()

    def refresh_controls(self):
        audio_format = self.format_combo.currentText().strip().lower() in presenter.AUDIO_FORMATS
        self.codec_combo.setEnabled(not audio_format)
        self.frame_combo.setEnabled(not audio_format)

    def preferences(self):
        return presenter.DownloadPreferences(
            quality=_combo_text(self.quality_combo),
            output_format=_combo_text(self.format_combo),
            codec=_combo_text(self.codec_combo),
            frame_rate=_combo_text(self.frame_combo),
        )


class DeleteConfirmDialog(QDialog):
    def __init__(self, output_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("파일 삭제")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)

        title = QLabel("파일을 삭제하시겠습니까?")
        title.setObjectName("SectionTitle")
        detail = QLabel(str(output_path))
        detail.setObjectName("MetaText")
        detail.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(detail)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("취소")
        self.cancel_button.setObjectName("SecondaryButton")
        self.ok_button = QPushButton("확인")
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button.clicked.connect(self.accept)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.ok_button)
        layout.addLayout(buttons)


class ClipFlowWindow(QMainWindow):
    def __init__(
        self,
        analyze_func=engine.analyze_url,
        download_func=engine.download_candidate,
        open_url_func=None,
        confirm_delete_func=None,
    ):
        super().__init__()
        app = QApplication.instance()
        if app:
            configure_app_font(app)
        self.analyze_func = analyze_func
        self.download_func = download_func
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.preference_values = self._initial_preferences()
        self.sort_key = self.settings.value(SORT_KEY_SETTING, "latest", str) or "latest"
        if self.sort_key not in SORT_LABELS:
            self.sort_key = "latest"
        self.sort_desc = str(self.settings.value(SORT_DESC_SETTING, "true", str)).lower() != "false"
        self.open_url_func = open_url_func or (lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.confirm_delete_func = confirm_delete_func
        self.analysis = None
        self.rows = []
        self.analysis_thread = None
        self.analysis_worker = None
        self.download_thread = None
        self.download_worker = None
        self.active_download_row = None
        self.selected_row_index = -1
        self.event_messages = []
        self._clear_url_on_next_click = False
        self._row_sequence = 0
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(create_app_icon())
        self.resize(720, 760)
        self.setMinimumSize(560, 420)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        self._load_completed_history()
        self._refresh_primary_action()

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 12)
        layout.setSpacing(14)

        layout.addWidget(self._build_input_panel())
        layout.addWidget(self._build_list_panel(), 1)
        layout.addWidget(self._build_footer())
        self.setCentralWidget(root)

    def eventFilter(self, obj, event):
        if hasattr(self, "scroll_area") and obj is self.scroll_area.viewport() and event.type() == event.Type.Resize:
            self._position_playlist_float_button()
            self._refresh_playlist_float_button()
        return super().eventFilter(obj, event)

    def _panel(self):
        frame = QFrame()
        frame.setObjectName("Panel")
        return frame

    def _field_box(self, icon_kind, line_edit, trailing_widget=None):
        frame = QFrame()
        frame.setObjectName("FieldBox")
        frame.setFixedHeight(TOP_FIELD_HEIGHT)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 0, 6 if trailing_widget else 12, 0)
        layout.setSpacing(10)
        icon = LucideIconWidget(icon_kind)
        line_edit.setObjectName("BareInput")
        layout.addWidget(icon)
        layout.addWidget(line_edit, 1)
        if trailing_widget:
            layout.addWidget(trailing_widget)
        return frame

    def _build_input_panel(self):
        panel = self._panel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        self.url_input = ClearingUrlInput()
        self.url_input.setPlaceholderText("URL을 입력하세요")
        self.url_input.textChanged.connect(self._refresh_primary_action)
        self.url_input.clicked_for_edit.connect(self._prepare_url_edit)
        self.clear_url_button = LucideIconButton("circle-x", size=30, icon_size=16)
        self.clear_url_button.setToolTip("URL 지우기")
        self.clear_url_button.clicked.connect(self._clear_url)
        url_field = self._field_box("link", self.url_input, self.clear_url_button)

        self.primary_button = PrimaryActionButton()
        self.primary_button.setFixedSize(PRIMARY_BUTTON_WIDTH, TOP_FIELD_HEIGHT)
        self.primary_button.clicked.connect(self._handle_primary_action)

        self.folder_input = PathDisplayInput(self._initial_save_folder())
        self.folder_button = QPushButton("저장 위치")
        self.folder_button.setObjectName("SecondaryButton")
        self.folder_button.setFixedSize(104, TOP_FIELD_HEIGHT - 8)
        self.folder_button.setToolTip("저장 폴더 선택")
        self.folder_button.clicked.connect(self._choose_folder)
        folder_field = self._field_box("folder", self.folder_input, self.folder_button)

        self.cookie_combo = CleanComboBox("cookie")
        self.cookie_combo.addItems(COOKIE_DISPLAY_CHOICES)
        self.cookie_combo.setFixedHeight(TOP_FIELD_HEIGHT)
        self.cookie_combo.setMinimumWidth(132)
        self.cookie_combo.setMaximumWidth(142)
        self.cookie_combo.setToolTip(
            "로그인한 사이트의 영상이 안 보일 때만 사용하세요.\n"
            "선택한 브라우저의 로그인 세션을 읽어 접근 가능한 항목인지 확인합니다.\n"
            "비밀번호는 저장하지 않으며 권한 우회 기능은 제공하지 않습니다."
        )
        self._restore_cookie_source()
        self.cookie_combo.currentIndexChanged.connect(self._save_cookie_source)

        url_row = QHBoxLayout()
        url_row.setContentsMargins(0, 0, 0, 0)
        url_row.setSpacing(12)
        url_row.addWidget(url_field, 1)
        url_row.addWidget(self.primary_button)

        options_row = QHBoxLayout()
        options_row.setContentsMargins(0, 0, 0, 0)
        options_row.setSpacing(12)
        options_row.addWidget(folder_field, 1)
        options_row.addWidget(self.cookie_combo)

        layout.addLayout(url_row)
        layout.addLayout(options_row)
        return panel

    def _build_list_panel(self):
        panel = self._panel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("다운로드 목록")
        title.setObjectName("SectionTitle")
        self.count_label = QLabel("0개")
        self.count_label.setObjectName("MetaText")
        self.sort_label = QLabel("정렬:")
        self.sort_label.setObjectName("MetaText")
        self.sort_label.setFixedHeight(TOP_FIELD_HEIGHT - 2)
        self.sort_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        self.sort_order_combo = CleanComboBox()
        self.sort_order_combo.addItems(["최신순", "이름순"])
        self.sort_order_combo.setCurrentText(SORT_LABELS.get(self.sort_key, "최신순"))
        self.sort_order_combo.currentIndexChanged.connect(self._sort_changed)
        self.sort_order_combo.setMaximumWidth(120)
        self.sort_direction_button = LucideIconButton(self._sort_direction_icon(), size=40, icon_size=18)
        self.sort_direction_button.clicked.connect(self._toggle_sort_direction)
        self._refresh_sort_direction_button()
        self.preference_button = QPushButton("품질")
        self.preference_button.setObjectName("SecondaryButton")
        self.preference_button.setFixedSize(74, TOP_FIELD_HEIGHT - 2)
        self.preference_button.setToolTip("품질/포맷/코덱/프레임 설정")
        self.preference_button.clicked.connect(self._open_preferences_dialog)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.sort_label, 0, Qt.AlignVCenter)
        header.addWidget(self.sort_order_combo, 0, Qt.AlignVCenter)
        header.addWidget(self.sort_direction_button, 0, Qt.AlignVCenter)
        header.addWidget(self.preference_button, 0, Qt.AlignVCenter)
        layout.addLayout(header)

        self.header_labels = []

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._refresh_playlist_float_button)
        self.row_container = QWidget()
        self.row_container.setObjectName("RowContainer")
        self.row_layout = QVBoxLayout(self.row_container)
        self.row_layout.setContentsMargins(0, 0, 0, 0)
        self.row_layout.setSpacing(0)
        self.row_layout.addStretch(1)
        self.scroll_area.setWidget(self.row_container)
        self.scroll_area.viewport().installEventFilter(self)
        self.playlist_float_button = QPushButton("접기", self.scroll_area.viewport())
        self.playlist_float_button.setObjectName("FloatingButton")
        self.playlist_float_button.setFixedSize(62, 30)
        self.playlist_float_button.clicked.connect(self._collapse_floating_playlist)
        self.playlist_float_button.hide()
        layout.addWidget(self.scroll_area, 1)
        return panel

    def _build_footer(self):
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(4, 0, 4, 0)
        self.status_label = QLabel("준비됨")
        self.total_label = QLabel("총 항목: 0")
        self.concurrent_label = QLabel("동시 다운로드: 0/1")
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        layout.addWidget(self.total_label)
        layout.addSpacing(24)
        layout.addWidget(self.concurrent_label)
        return footer

    def _prepare_url_edit(self):
        return

    def _clear_url(self):
        self.url_input.clear()
        self._clear_url_on_next_click = False
        self._refresh_primary_action()

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.folder_input.text())
        if folder:
            self._set_save_folder(folder)

    def current_preferences(self):
        return presenter.DownloadPreferences(**self.preference_values)

    def _preferences_changed(self):
        for row in self.rows:
            candidate = self.selected_candidate_for_row_ref(row)
            if candidate:
                row["candidate"] = candidate
                widget = row.get("widget")
                if widget:
                    widget.refresh()

    def _initial_preferences(self):
        return {
            "quality": self.settings.value(PREF_QUALITY_SETTING, PREFERENCE_DEFAULTS["quality"], str),
            "output_format": self.settings.value(PREF_FORMAT_SETTING, PREFERENCE_DEFAULTS["output_format"], str),
            "codec": self.settings.value(PREF_CODEC_SETTING, PREFERENCE_DEFAULTS["codec"], str),
            "frame_rate": self.settings.value(PREF_FRAME_SETTING, PREFERENCE_DEFAULTS["frame_rate"], str),
        }

    def _set_preferences(self, quality=None, output_format=None, codec=None, frame_rate=None):
        values = {
            "quality": quality or self.preference_values.get("quality") or PREFERENCE_DEFAULTS["quality"],
            "output_format": output_format or self.preference_values.get("output_format") or PREFERENCE_DEFAULTS["output_format"],
            "codec": codec or self.preference_values.get("codec") or PREFERENCE_DEFAULTS["codec"],
            "frame_rate": frame_rate or self.preference_values.get("frame_rate") or PREFERENCE_DEFAULTS["frame_rate"],
        }
        self.preference_values = values
        self.settings.setValue(PREF_QUALITY_SETTING, values["quality"])
        self.settings.setValue(PREF_FORMAT_SETTING, values["output_format"])
        self.settings.setValue(PREF_CODEC_SETTING, values["codec"])
        self.settings.setValue(PREF_FRAME_SETTING, values["frame_rate"])
        self._preferences_changed()

    def _create_preferences_dialog(self):
        return PreferencesDialog(self.current_preferences(), self)

    def _open_preferences_dialog(self):
        dialog = self._create_preferences_dialog()
        if dialog.exec() == QDialog.Accepted:
            preferences = dialog.preferences()
            self._set_preferences(
                quality=preferences.quality,
                output_format=preferences.output_format,
                codec=preferences.codec,
                frame_rate=preferences.frame_rate,
            )

    def _initial_save_folder(self):
        saved = self.settings.value(SAVE_FOLDER_SETTING, "", str)
        if saved:
            return str(Path(saved).expanduser())
        return str(default_save_folder())

    def _set_save_folder(self, folder):
        folder_text = str(Path(folder).expanduser())
        self.folder_input.setText(folder_text)
        self.settings.setValue(SAVE_FOLDER_SETTING, folder_text)

    def _restore_cookie_source(self):
        saved = self.settings.value(COOKIE_SOURCE_SETTING, COOKIE_CHOICES[0], str) or COOKIE_CHOICES[0]
        display = COOKIE_SOURCE_TO_DISPLAY.get(saved, COOKIE_DISPLAY_CHOICES[0])
        index = self.cookie_combo.findText(display)
        self.cookie_combo.setCurrentIndex(index if index >= 0 else 0)

    def _save_cookie_source(self, *_args):
        self.settings.setValue(COOKIE_SOURCE_SETTING, cookie_source_from_display(self.cookie_combo.currentText()))
        self.settings.sync()

    def _json_ready(self, value):
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    def _completed_history_payload(self):
        payload = []
        for row in self.rows:
            if row.get("status") != "완료":
                continue
            candidate = row.get("candidate") or {}
            payload.append(
                {
                    "candidate": self._json_ready(candidate),
                    "source_url": row.get("source_url") or "",
                    "analysis_source_url": row.get("analysis_source_url") or "",
                    "output_path": row.get("output_path") or "",
                    "created_order": int(row.get("created_order") or 0),
                    "messages": self._json_ready(row.get("messages") or []),
                }
            )
        return payload

    def _save_completed_history(self):
        self.settings.setValue(
            DOWNLOAD_HISTORY_SETTING,
            json.dumps(self._completed_history_payload(), ensure_ascii=False, default=str),
        )
        self.settings.sync()

    def _load_completed_history(self):
        raw = self.settings.value(DOWNLOAD_HISTORY_SETTING, "", str) or ""
        if not raw:
            return
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            return
        restored = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("candidate"), dict):
                continue
            candidate = item["candidate"]
            created_order = engine.safe_int(item.get("created_order")) or self._next_row_sequence()
            self._row_sequence = max(self._row_sequence, created_order)
            source_url = item.get("source_url") or item.get("analysis_source_url") or candidate.get("source") or candidate.get("url") or ""
            restored.append(
                {
                    "id": candidate.get("id") or f"history-{created_order}",
                    "kind": row_kind(candidate),
                    "candidate": candidate,
                    "qualities": [candidate],
                    "quality_options": build_quality_options([candidate]),
                    "selected_index": 0,
                    "selected_format_index": 0,
                    "analysis_source_url": item.get("analysis_source_url") or source_url,
                    "source_url": source_url,
                    "status": "완료",
                    "status_detail": "",
                    "progress": 100,
                    "progress_text": "",
                    "output_path": item.get("output_path") or "",
                    "messages": item.get("messages") or [],
                    "created_order": created_order,
                }
            )
        if restored:
            self.rows = restored + self.rows
            self._render_rows()

    def _handle_primary_action(self):
        if not self.url_input.text().strip():
            text = QApplication.clipboard().text().strip()
            if text:
                self.url_input.setText(text)
            return
        if self._selected_row_matches_current_url():
            self._start_download()
            return
        self._start_analysis()

    def _start_analysis(self):
        if self.analysis_thread and self.analysis_thread.isRunning():
            return

        url = self.url_input.text().strip()
        if not url:
            return

        self.analysis = None
        self.selected_row_index = -1
        self.primary_button.setEnabled(False)
        self.primary_button.setText("분석 중")
        self.primary_button.set_loading(True)
        self._set_status("분석 중")

        self.analysis_thread = QThread(self)
        self.analysis_worker = AnalyzeWorker(
            url,
            cookie_source_from_display(self.cookie_combo.currentText()),
            engine.ALL_OUTPUT_EXT,
            self.analyze_func,
        )
        self.analysis_worker.moveToThread(self.analysis_thread)
        self.analysis_thread.started.connect(self.analysis_worker.run)
        self.analysis_worker.event.connect(self._handle_engine_event)
        self.analysis_worker.finished.connect(self._analysis_finished)
        self.analysis_worker.failed.connect(self._analysis_failed)
        self.analysis_worker.finished.connect(self.analysis_thread.quit)
        self.analysis_worker.failed.connect(self.analysis_thread.quit)
        self.analysis_thread.finished.connect(self.analysis_worker.deleteLater)
        self.analysis_thread.finished.connect(self._analysis_thread_finished)
        self.analysis_thread.start()

    @Slot(dict)
    def _analysis_finished(self, analysis):
        self.analysis = analysis
        grouped = presenter.group_candidates(analysis.get("candidates") or [])
        source_url = analysis.get("webpage_url") or analysis.get("url") or self.url_input.text().strip()
        self._prepend_analysis_rows(analysis, grouped, source_url)
        self._clear_url_on_next_click = False
        self._set_status(f"분석 완료: {len(grouped)}개")
        self._refresh_footer()
        for warning in analysis.get("warnings") or []:
            self.event_messages.append(str(warning))

    @Slot(str)
    def _analysis_failed(self, message):
        self._set_status(f"{engine.classify_error(message)}: {message}")

    @Slot()
    def _analysis_thread_finished(self):
        self.primary_button.setEnabled(True)
        self.primary_button.set_loading(False)
        self.analysis_thread = None
        self.analysis_worker = None
        self._refresh_primary_action()

    def _prepend_analysis_rows(self, analysis, grouped_rows, source_url):
        preserved_rows = [
            row
            for row in self.rows
            if row.get("status") == "완료"
        ]
        if analysis.get("is_playlist"):
            playlist_candidate = self._playlist_candidate_from_analysis(analysis, grouped_rows, source_url)
            self.rows = [
                {
                    "id": "playlist",
                    "kind": "playlist",
                    "candidate": playlist_candidate,
                    "qualities": [playlist_candidate],
                    "quality_options": build_quality_options([playlist_candidate]),
                    "selected_index": 0,
                    "selected_format_index": 0,
                    "analysis_source_url": source_url,
                    "source_url": source_url,
                    "status": "준비",
                    "status_detail": "",
                    "progress": 0,
                    "progress_text": "",
                    "output_path": "",
                    "messages": [],
                    "created_order": self._next_row_sequence(),
                    "playlist_entries": grouped_rows,
                    "expanded": False,
                }
            ] + preserved_rows
            self._sort_rows()
            self.selected_row_index = 0 if self.rows else -1
            self._render_rows()
            return
        new_rows = []
        for grouped_row in grouped_rows:
            candidate = grouped_row["candidate"]
            row = {
                "id": grouped_row.get("id"),
                "kind": row_kind(candidate),
                "candidate": candidate,
                "qualities": grouped_row["qualities"],
                "quality_options": build_quality_options(grouped_row["qualities"]),
                "selected_index": 0,
                "selected_format_index": 0,
                "analysis_source_url": source_url,
                "source_url": source_url or row_source_url(analysis, candidate),
                "status": "준비",
                "status_detail": "",
                "progress": 0,
                "progress_text": "",
                "output_path": "",
                "messages": [],
                "created_order": self._next_row_sequence(),
            }
            new_rows.append(row)
        self.rows = new_rows + preserved_rows
        self._sort_rows()
        self.selected_row_index = 0 if self.rows else -1
        self._render_rows()

    def _playlist_candidate_from_analysis(self, analysis, grouped_rows, source_url):
        first_candidate = (grouped_rows[0].get("candidate") if grouped_rows else {}) or {}
        candidates = [row.get("candidate") or {} for row in grouped_rows]
        title = (
            analysis.get("playlist_title")
            or analysis.get("title")
            or first_candidate.get("display_title")
            or first_candidate.get("title")
            or "Playlist"
        )
        return {
            "id": "playlist",
            "media_type": "playlist",
            "format_selector": "bestvideo*+bestaudio/best",
            "title": title,
            "display_title": title,
            "thumbnail": first_candidate.get("thumbnail") or "",
            "duration": sum(engine.safe_int(candidate.get("duration")) for candidate in candidates),
            "sort_bytes": sum(engine.safe_int(candidate.get("sort_bytes")) for candidate in candidates),
            "item_count": engine.safe_int(analysis.get("playlist_count")) or len(grouped_rows),
            "playlist_count": engine.safe_int(analysis.get("playlist_count")) or len(grouped_rows),
            "source": source_url,
            "url": source_url,
            "webpage_url": source_url,
            "output_ext": self.current_preferences().output_format if self.current_preferences().output_format != "자동" else DEFAULT_OUTPUT_EXT.lower(),
            "ext": self.current_preferences().output_format if self.current_preferences().output_format != "자동" else DEFAULT_OUTPUT_EXT.lower(),
        }

    def _render_rows(self):
        self._sort_rows()
        while self.row_layout.count() > 1:
            item = self.row_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for row in self.rows:
            widget = DownloadRowWidget(self, row)
            row["widget"] = widget
            self.row_layout.insertWidget(self.row_layout.count() - 1, widget)
        self.count_label.setText(f"{len(self.rows)}개")
        self._refresh_footer()
        self._refresh_row_selection()
        self._refresh_primary_action()
        self._refresh_playlist_float_button()

    def playlist_expansion_changed(self, row):
        widget = row.get("widget") if isinstance(row, dict) else None
        if widget:
            widget.updateGeometry()
        QTimer.singleShot(0, self._refresh_playlist_float_button)

    def _expanded_playlist_row(self):
        for row in self.rows:
            if row.get("kind") == "playlist" and row.get("expanded"):
                return row
        return None

    def _position_playlist_float_button(self):
        if not hasattr(self, "playlist_float_button"):
            return
        viewport = self.scroll_area.viewport()
        x = max(8, viewport.width() - self.playlist_float_button.width() - 12)
        self.playlist_float_button.move(x, 10)
        self.playlist_float_button.raise_()

    def _refresh_playlist_float_button(self):
        if not hasattr(self, "playlist_float_button"):
            return
        row = self._expanded_playlist_row()
        widget = row.get("widget") if row else None
        visible = False
        if widget:
            top = widget.mapTo(self.scroll_area.viewport(), QPoint(0, 0)).y()
            bottom = top + widget.height()
            visible = top < 4 and bottom > 0
        self.playlist_float_button.setVisible(visible)
        if visible:
            self._position_playlist_float_button()

    def _scroll_row_to_top(self, row):
        widget = row.get("widget") if isinstance(row, dict) else None
        if not widget:
            return
        top = widget.mapTo(self.row_container, QPoint(0, 0)).y()
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(max(bar.minimum(), min(bar.maximum(), top)))

    def _collapse_floating_playlist(self):
        row = self._expanded_playlist_row()
        if not row:
            return
        row["expanded"] = False
        widget = row.get("widget")
        if widget:
            widget._refresh_playlist_detail()
            widget.updateGeometry()
        self._scroll_row_to_top(row)
        self._refresh_playlist_float_button()

    def _next_row_sequence(self):
        self._row_sequence += 1
        return self._row_sequence

    def _sort_rows(self):
        reverse = bool(self.sort_desc)
        if self.sort_key == "name":
            self.rows.sort(key=lambda row: self._row_sort_name(row), reverse=reverse)
        else:
            self.rows.sort(key=lambda row: int(row.get("created_order") or 0), reverse=reverse)

    def _row_sort_name(self, row):
        candidate = self.selected_candidate_for_row_ref(row) or row.get("candidate") or {}
        return str(candidate.get("display_title") or candidate.get("title") or "").casefold()

    def _sort_changed(self):
        self.sort_key = SORT_KEYS_BY_LABEL.get(self.sort_order_combo.currentText(), "latest")
        self.settings.setValue(SORT_KEY_SETTING, self.sort_key)
        self._render_rows()

    def _sort_direction_icon(self):
        return "arrow-down-wide-narrow" if self.sort_desc else "arrow-up-narrow-wide"

    def _refresh_sort_direction_button(self):
        if not hasattr(self, "sort_direction_button"):
            return
        self.sort_direction_button.icon_name = self._sort_direction_icon()
        self.sort_direction_button.setToolTip("내림차순" if self.sort_desc else "오름차순")
        self.sort_direction_button.update()

    def _toggle_sort_direction(self):
        self.sort_desc = not self.sort_desc
        self.settings.setValue(SORT_DESC_SETTING, "true" if self.sort_desc else "false")
        self._refresh_sort_direction_button()
        self._render_rows()

    def select_row(self, index):
        if index < 0 or index >= len(self.rows):
            self.selected_row_index = -1
        else:
            self.selected_row_index = index
        self._refresh_row_selection()
        self._refresh_primary_action()

    def select_row_for_widget(self, widget):
        for index, row in enumerate(self.rows):
            if row.get("widget") is widget:
                self.select_row(index)
                return

    def _refresh_row_selection(self):
        for index, row in enumerate(self.rows):
            widget = row.get("widget")
            if widget:
                widget.set_selected(index == self.selected_row_index)

    def quality_changed_for_row(self, row, quality_index):
        if row not in self.rows:
            return
        options = row.get("quality_options") or []
        row["selected_index"] = max(0, min(int(quality_index), len(options) - 1)) if options else 0
        row["selected_format_index"] = 0
        candidate = self.selected_candidate_for_row_ref(row)
        if candidate:
            row["candidate"] = candidate
            widget = row.get("widget")
            if widget:
                widget.refresh()

    def format_changed_for_row(self, row, format_index):
        if row not in self.rows:
            return
        option = self.selected_quality_option_for_row_ref(row)
        formats = option.get("formats") if option else []
        row["selected_format_index"] = max(0, min(int(format_index), len(formats) - 1)) if formats else 0
        candidate = self.selected_candidate_for_row_ref(row)
        if candidate:
            row["candidate"] = candidate
            widget = row.get("widget")
            if widget:
                widget.refresh()

    def selected_quality_option_for_row_ref(self, row):
        if not row:
            return None
        options = row.get("quality_options")
        if options is None:
            options = build_quality_options(row.get("qualities") or [])
            row["quality_options"] = options
        if not options:
            return None
        selected_index = max(0, min(int(row.get("selected_index") or 0), len(options) - 1))
        row["selected_index"] = selected_index
        return options[selected_index]

    def selected_candidate_for_row_ref(self, row):
        if row and row.get("kind") == "playlist":
            candidate = dict(row.get("candidate") or {})
            preferences = self.current_preferences()
            output_format = preferences.output_format
            if str(output_format).casefold() == "자동".casefold():
                output_format = DEFAULT_OUTPUT_EXT
            candidate["output_ext"] = str(output_format).lower()
            candidate["ext"] = str(output_format).lower()
            return candidate
        if row and row.get("status") == "완료":
            return row.get("candidate")
        selected = presenter.select_candidate_for_preferences(row.get("qualities") or [], self.current_preferences())
        if selected:
            return selected
        option = self.selected_quality_option_for_row_ref(row)
        if not option:
            return None
        formats = option.get("formats") or []
        if not formats:
            return None
        selected_format_index = max(0, min(int(row.get("selected_format_index") or 0), len(formats) - 1))
        row["selected_format_index"] = selected_format_index
        return formats[selected_format_index]["candidate"]

    def selected_candidate_for_row(self, row_index):
        if row_index < 0 or row_index >= len(self.rows):
            return None
        return self.selected_candidate_for_row_ref(self.rows[row_index])

    def _start_download(self):
        if self.download_thread and self.download_thread.isRunning():
            return
        if self.selected_row_index < 0 or self.selected_row_index >= len(self.rows):
            self._set_status("다운로드할 항목을 선택하세요")
            return

        row = self.rows[self.selected_row_index]
        candidate = self.selected_candidate_for_row_ref(row)
        if not candidate:
            self._set_status("다운로드할 항목을 선택하세요")
            return

        self.active_download_row = row
        row["download_started_at"] = time.time()
        row["widget"].set_status("다운로드 중")
        row["widget"].set_progress(0, "0%")
        self.primary_button.setEnabled(False)
        self._set_status("다운로드 중")

        page_url = row.get("source_url") or (self.analysis or {}).get("webpage_url") or self.url_input.text().strip()
        self.download_thread = QThread(self)
        self.download_worker = DownloadWorker(
            page_url,
            candidate,
            engine.output_dir_for_candidate(candidate, self.folder_input.text()),
            cookie_source_from_display(self.cookie_combo.currentText()),
            self.download_func,
        )
        self.download_worker.moveToThread(self.download_thread)
        self.download_thread.started.connect(self.download_worker.run)
        self.download_worker.event.connect(self._handle_engine_event)
        self.download_worker.finished.connect(self._download_finished)
        self.download_worker.failed.connect(self._download_failed)
        self.download_worker.finished.connect(self.download_thread.quit)
        self.download_worker.failed.connect(self.download_thread.quit)
        self.download_thread.finished.connect(self.download_worker.deleteLater)
        self.download_thread.finished.connect(self._download_thread_finished)
        self.download_thread.start()

    @Slot(dict)
    def _download_finished(self, result):
        if self.active_download_row:
            selected = self.selected_candidate_for_row_ref(self.active_download_row)
            if selected:
                self.active_download_row["candidate"] = selected
                self.active_download_row["qualities"] = [selected]
                self.active_download_row["quality_options"] = build_quality_options([selected])
            self._resolve_finished_output_path(self.active_download_row, result)
            widget = self.active_download_row.get("widget")
            if widget:
                widget.set_status("완료")
                widget.set_progress(100, "완료")
                widget._refresh_actions()
            self._save_completed_history()
        self._set_status("완료")
        output_dir = result.get("output_dir") if isinstance(result, dict) else None
        if output_dir:
            self.event_messages.append(str(output_dir))

    def _resolve_finished_output_path(self, row, result):
        if not row:
            return
        known_value = row.get("output_path")
        if known_value:
            known_path = Path(known_value)
            if known_path.exists():
                row["output_path"] = str(known_path)
                return

        result = result if isinstance(result, dict) else {}
        for key in ("output_path", "filepath", "filename", "path"):
            value = result.get(key)
            if value and Path(value).exists():
                row["output_path"] = str(Path(value))
                return

        output_dir = Path(result.get("output_dir") or self.folder_input.text()).expanduser()
        if not output_dir.exists():
            return

        selected = self.selected_candidate_for_row_ref(row) or {}
        preferred_ext = (selected.get("output_ext") or selected.get("ext") or "mp4").lower()
        extensions = [preferred_ext, "mp4", "webm", "wav"]
        try:
            since = max(0, float(row.get("download_started_at") or 0) - 1)
        except (TypeError, ValueError):
            since = 0
        for ext in dict.fromkeys(extensions):
            found = engine.newest_file(output_dir, ext, since=since)
            if found and found.exists():
                row["output_path"] = str(found)
                return

    @Slot(str)
    def _download_failed(self, message):
        if self.active_download_row:
            widget = self.active_download_row.get("widget")
            self.active_download_row["messages"].append(message)
            if widget:
                widget.set_status("오류", message)
                widget.set_progress(0, "")
        self._set_status(f"{engine.classify_error(message)}: {message}")

    @Slot()
    def _download_thread_finished(self):
        self.primary_button.setEnabled(True)
        self.download_thread = None
        self.download_worker = None
        self.active_download_row = None
        self._refresh_primary_action()

    @Slot(dict)
    def _handle_engine_event(self, event):
        event_type = event.get("type")
        message = event.get("message") or event.get("path") or ""
        row = self.active_download_row
        widget = row.get("widget") if row else None
        if event_type == "progress":
            percent = max(0, min(100, int(float(event.get("percent") or 0))))
            text = self._progress_text(percent, message)
            if widget:
                widget.set_status("다운로드 중")
                widget.set_progress(percent, text)
            self.status_label.setText(text or "다운로드 중")
        elif event_type == "file":
            if row and event.get("path"):
                row["output_path"] = str(event["path"])
                if widget:
                    widget._refresh_actions()
        elif event_type == "status":
            if message:
                self.status_label.setText(message)
                self.event_messages.append(message)
        elif event_type in {"log", "done"}:
            if message:
                self.event_messages.append(message)

    def _progress_text(self, percent, message):
        parts = str(message or "").split()
        speed = ""
        for index, part in enumerate(parts):
            if "/s" in part:
                if index > 0 and parts[index - 1].replace(".", "", 1).isdigit():
                    speed = f"{parts[index - 1]} {part}"
                else:
                    speed = part
                break
        return f"{percent}% · {speed}" if speed else f"{percent}%"

    def open_source_for_row(self, row):
        source_url = row.get("source_url") or ""
        if source_url:
            self.open_url_func(source_url)

    def open_folder_for_row(self, row):
        output_path = Path(row.get("output_path") or "")
        if output_path.exists():
            target = output_path.parent
        else:
            target = Path(self.folder_input.text()).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        self._open_path(target)

    def _open_path(self, path):
        return QDesktopServices.openUrl(local_file_url(path))

    def remove_row(self, row):
        if row.get("status") in {"분석 중", "다운로드 중"}:
            return
        if row in self.rows:
            index = self.rows.index(row)
            self.rows.pop(index)
            if self.selected_row_index >= len(self.rows):
                self.selected_row_index = len(self.rows) - 1
            self._render_rows()
            self._save_completed_history()

    def delete_file_for_row(self, row):
        output_path = Path(row.get("output_path") or "")
        if not output_path.exists() or row.get("status") == "다운로드 중":
            return
        confirmed = (
            self.confirm_delete_func(output_path)
            if self.confirm_delete_func
            else self._confirm_file_delete(output_path)
        )
        if not confirmed:
            return
        try:
            output_path.unlink()
        except OSError as exc:
            QMessageBox.warning(self, "파일 삭제 실패", str(exc))
            return
        row["output_path"] = ""
        widget = row.get("widget")
        if widget:
            widget._refresh_actions()
        self._save_completed_history()

    def _create_delete_confirm_dialog(self, output_path):
        return DeleteConfirmDialog(output_path, self)

    def _confirm_file_delete(self, output_path):
        dialog = self._create_delete_confirm_dialog(output_path)
        return dialog.exec() == QDialog.Accepted

    def _refresh_primary_action(self):
        has_url = bool(self.url_input.text().strip())
        if not has_url:
            self.primary_button.setText("붙여넣기")
        elif self._selected_row_matches_current_url():
            self.primary_button.setText("다운로드")
        else:
            self.primary_button.setText("분석")

    def _selected_row_matches_current_url(self):
        if self.selected_row_index < 0 or self.selected_row_index >= len(self.rows):
            return False
        current_url = self.url_input.text().strip()
        if not current_url:
            return False
        row = self.rows[self.selected_row_index]
        row_urls = {
            str(row.get("analysis_source_url") or "").strip(),
            str(row.get("source_url") or "").strip(),
        }
        return current_url in row_urls

    def _refresh_footer(self):
        self.total_label.setText(f"총 항목: {len(self.rows)}")
        active = 1 if self.download_thread and self.download_thread.isRunning() else 0
        self.concurrent_label.setText(f"동시 다운로드: {active}/1")

    def _set_status(self, message):
        self.status_label.setText(message)
        self.event_messages.append(message)


def main():
    app = QApplication(sys.argv)
    configure_app_font(app)
    window = ClipFlowWindow()
    window.show()

    if os.environ.get("CLIPFLOW_QT_SMOKE") == "1":
        QTimer.singleShot(0, lambda: (print("ClipFlow smoke launch OK"), app.quit()))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
