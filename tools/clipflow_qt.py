import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QStandardPaths, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
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
    from tools.clipflow_widgets import CleanComboBox, ClearingUrlInput, PathDisplayInput
except ImportError:
    import candidate_presenter as presenter
    import downloader_engine as engine
    from clipflow_rows import DownloadRowWidget, build_quality_options, row_kind, row_source_url
    from clipflow_theme import (
        APP_NAME, APP_STYLE, COOKIE_CHOICES, COOKIE_DISPLAY_CHOICES, DEFAULT_OUTPUT_EXT, PRIMARY_BUTTON_WIDTH,
        TOP_FIELD_HEIGHT, configure_app_font, create_app_icon,
    )
    from clipflow_icons import LucideIconButton, LucideIconWidget
    from clipflow_widgets import CleanComboBox, ClearingUrlInput, PathDisplayInput


SETTINGS_ORG = "ClipFlow"
SETTINGS_APP = "ClipFlow"
SAVE_FOLDER_SETTING = "save_folder"


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
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(create_app_icon())
        self.resize(720, 760)
        self.setMinimumSize(560, 420)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
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

    def _panel(self):
        frame = QFrame()
        frame.setObjectName("Panel")
        return frame

    def _field_box(self, icon_kind, line_edit, trailing_widget=None):
        frame = QFrame()
        frame.setObjectName("FieldBox")
        frame.setFixedHeight(TOP_FIELD_HEIGHT)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 0, 12, 0)
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
        url_field = self._field_box("link", self.url_input)

        self.primary_button = QPushButton()
        self.primary_button.setFixedSize(PRIMARY_BUTTON_WIDTH, TOP_FIELD_HEIGHT)
        self.primary_button.clicked.connect(self._handle_primary_action)

        self.folder_input = PathDisplayInput(self._initial_save_folder())
        self.folder_button = LucideIconButton("folder")
        self.folder_button.setToolTip("저장 폴더 선택")
        self.folder_button.clicked.connect(self._choose_folder)
        folder_field = self._field_box("folder", self.folder_input, self.folder_button)

        self.cookie_combo = CleanComboBox("cookie")
        self.cookie_combo.addItems(COOKIE_DISPLAY_CHOICES)
        self.cookie_combo.setFixedHeight(TOP_FIELD_HEIGHT)
        self.cookie_combo.setMinimumWidth(168)
        self.cookie_combo.setMaximumWidth(184)

        self.cookie_help_button = QToolButton()
        self.cookie_help_button.setObjectName("HelpButton")
        self.cookie_help_button.setText("?")
        self.cookie_help_button.setFixedSize(TOP_FIELD_HEIGHT, TOP_FIELD_HEIGHT)
        self.cookie_help_button.setToolTip(
            "로그인한 사이트의 영상이 안 보일 때만 사용하세요.\n"
            "선택한 브라우저의 로그인 세션을 읽어 접근 가능한 항목인지 확인합니다.\n"
            "비밀번호는 저장하지 않으며 권한 우회 기능은 제공하지 않습니다."
        )

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
        options_row.addWidget(self.cookie_help_button, 0, Qt.AlignVCenter)

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
        self.sort_order_combo.addItems(["최신순"])
        self.sort_order_combo.setMaximumWidth(120)
        self.sort_direction_combo = CleanComboBox()
        self.sort_direction_combo.addItems(["내림차순"])
        self.sort_direction_combo.setMaximumWidth(120)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.sort_label, 0, Qt.AlignVCenter)
        header.addWidget(self.sort_order_combo, 0, Qt.AlignVCenter)
        header.addWidget(self.sort_direction_combo, 0, Qt.AlignVCenter)
        layout.addLayout(header)

        preferences = QHBoxLayout()
        preferences.setContentsMargins(0, 0, 0, 0)
        preferences.setSpacing(8)
        self.quality_pref_combo = CleanComboBox()
        self.quality_pref_combo.addItems(["자동", "2160p", "1440p", "1080p", "720p", "480p", "360p"])
        self.quality_pref_combo.setFixedWidth(96)
        self.format_pref_combo = CleanComboBox()
        self.format_pref_combo.addItems(["MP4", "WEBM", "MP3", "WAV", "AAC"])
        self.format_pref_combo.setFixedWidth(86)
        self.codec_pref_combo = CleanComboBox()
        self.codec_pref_combo.addItems(["자동", "H264", "H265", "AV1", "VP9"])
        self.codec_pref_combo.setFixedWidth(96)
        self.frame_pref_combo = CleanComboBox()
        self.frame_pref_combo.addItems(["자동", "60fps", "30fps"])
        self.frame_pref_combo.setFixedWidth(96)
        for combo in (self.quality_pref_combo, self.format_pref_combo, self.codec_pref_combo, self.frame_pref_combo):
            combo.currentIndexChanged.connect(self._preferences_changed)
        preferences.addWidget(QLabel("품질"))
        preferences.addWidget(self.quality_pref_combo)
        preferences.addWidget(QLabel("포맷"))
        preferences.addWidget(self.format_pref_combo)
        preferences.addWidget(QLabel("코덱"))
        preferences.addWidget(self.codec_pref_combo)
        preferences.addWidget(QLabel("프레임"))
        preferences.addWidget(self.frame_pref_combo)
        preferences.addStretch(1)
        layout.addLayout(preferences)
        self._refresh_preference_controls()

        self.header_labels = []

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.row_container = QWidget()
        self.row_container.setObjectName("RowContainer")
        self.row_layout = QVBoxLayout(self.row_container)
        self.row_layout.setContentsMargins(0, 0, 0, 0)
        self.row_layout.setSpacing(0)
        self.row_layout.addStretch(1)
        self.scroll_area.setWidget(self.row_container)
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
        if self._clear_url_on_next_click and self.url_input.text().strip():
            self.url_input.clear()
            self.analysis = None
            self.selected_row_index = -1
            self._clear_url_on_next_click = False
            self._refresh_row_selection()
            self._refresh_primary_action()

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.folder_input.text())
        if folder:
            self._set_save_folder(folder)

    def current_preferences(self):
        return presenter.DownloadPreferences(
            quality=_combo_text(self.quality_pref_combo),
            output_format=_combo_text(self.format_pref_combo),
            codec=_combo_text(self.codec_pref_combo),
            frame_rate=_combo_text(self.frame_pref_combo),
        )

    def _refresh_preference_controls(self):
        audio_format = _combo_text(self.format_pref_combo).lower() in presenter.AUDIO_FORMATS
        self.codec_pref_combo.setEnabled(not audio_format)
        self.frame_pref_combo.setEnabled(not audio_format)

    def _preferences_changed(self):
        self._refresh_preference_controls()
        for row in self.rows:
            candidate = self.selected_candidate_for_row_ref(row)
            if candidate:
                row["candidate"] = candidate
                widget = row.get("widget")
                if widget:
                    widget.refresh()

    def _initial_save_folder(self):
        saved = self.settings.value(SAVE_FOLDER_SETTING, "", str)
        if saved:
            return str(Path(saved).expanduser())
        return str(default_save_folder())

    def _set_save_folder(self, folder):
        folder_text = str(Path(folder).expanduser())
        self.folder_input.setText(folder_text)
        self.settings.setValue(SAVE_FOLDER_SETTING, folder_text)

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
        self._clear_url_on_next_click = True
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
        self.analysis_thread = None
        self.analysis_worker = None
        self._refresh_primary_action()

    def _prepend_analysis_rows(self, analysis, grouped_rows, source_url):
        preserved_rows = [
            row
            for row in self.rows
            if row.get("status") == "완료" and row.get("analysis_source_url") != source_url
        ]
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
            }
            new_rows.append(row)
        self.rows = new_rows + preserved_rows
        self.selected_row_index = 0 if self.rows else -1
        self._render_rows()

    def _render_rows(self):
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
            self.folder_input.text(),
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
            self._resolve_finished_output_path(self.active_download_row, result)
            widget = self.active_download_row.get("widget")
            if widget:
                widget.set_status("완료")
                widget.set_progress(100, "완료")
                widget._refresh_actions()
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

    def _confirm_file_delete(self, output_path):
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("파일 삭제")
        dialog.setText("파일을 삭제하시겠습니까?")
        dialog.setInformativeText(str(output_path))
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        dialog.setDefaultButton(QMessageBox.No)
        yes_button = dialog.button(QMessageBox.Yes)
        no_button = dialog.button(QMessageBox.No)
        if yes_button:
            yes_button.setText("예")
        if no_button:
            no_button.setText("아니오")
        return dialog.exec() == QMessageBox.Yes

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
