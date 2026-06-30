import os
import sys
import time
from collections import OrderedDict, deque

from PySide6.QtCore import QSettings, QSize, Qt, QThread, QTimer, QUrl, Slot
from PySide6.QtGui import QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

try:
    from tools import candidate_presenter as presenter
    from tools import downloader_engine as engine
    from tools import clipflow_theme as theme
    from tools.clipflow_theme import (
        APP_NAME, APP_STYLE, COOKIE_DISPLAY_CHOICES, DEFAULT_OUTPUT_EXT,
        TOP_FIELD_HEIGHT, apply_tracking, configure_app_font, cookie_source_from_display, create_app_icon,
    )
    from tools.clipflow_icons import LucideIconButton, LucideIconWidget, TooltipManager, lucide_pixmap
    from tools.clipflow_widgets import CleanComboBox, ClearingUrlInput, PathDisplayInput, PrimaryActionButton
    from tools.clipflow_workers import AnalyzeWorker
    from tools.clipflow_dialogs import DeleteConfirmDialog
    from tools.clipflow_playlist import PlaylistMixin
    from tools.clipflow_downloads import DownloadMixin
    from tools.clipflow_views import RenderMixin
    from tools.clipflow_actions import ActionMixin, local_file_url
    from tools.clipflow_settings import SettingsMixin, default_save_folder
except ImportError:
    import candidate_presenter as presenter
    import downloader_engine as engine
    import clipflow_theme as theme
    from clipflow_theme import (
        APP_NAME, APP_STYLE, COOKIE_DISPLAY_CHOICES, DEFAULT_OUTPUT_EXT,
        TOP_FIELD_HEIGHT, apply_tracking, configure_app_font, cookie_source_from_display, create_app_icon,
    )
    from clipflow_icons import LucideIconButton, LucideIconWidget, TooltipManager, lucide_pixmap
    from clipflow_widgets import CleanComboBox, ClearingUrlInput, PathDisplayInput, PrimaryActionButton
    from clipflow_workers import AnalyzeWorker
    from clipflow_dialogs import DeleteConfirmDialog
    from clipflow_playlist import PlaylistMixin
    from clipflow_downloads import DownloadMixin
    from clipflow_views import RenderMixin
    from clipflow_actions import ActionMixin, local_file_url
    from clipflow_settings import SettingsMixin, default_save_folder

try:
    from tools.clipflow_theme import (
        ANALYZING_STATUS, AUTO_LABEL, COMPLETED_STATUS, DOWNLOAD_HISTORY_SETTING, DOWNLOAD_STATUS, ERROR_STATUS,
        READY_STATUS, SAVE_FOLDER_SETTING, SETTINGS_APP, SETTINGS_ORG, SORT_DESC_SETTING, SORT_KEY_SETTING,
        SORT_LABELS, WAITING_STATUS,
    )
except ImportError:
    from clipflow_theme import (
        ANALYZING_STATUS, AUTO_LABEL, COMPLETED_STATUS, DOWNLOAD_HISTORY_SETTING, DOWNLOAD_STATUS, ERROR_STATUS,
        READY_STATUS, SAVE_FOLDER_SETTING, SETTINGS_APP, SETTINGS_ORG, SORT_DESC_SETTING, SORT_KEY_SETTING,
        SORT_LABELS, WAITING_STATUS,
    )


# Names re-exported for the test-suite and external callers.
__all__ = [
    "ClipFlowWindow", "DeleteConfirmDialog", "default_save_folder", "local_file_url", "main",
    "SETTINGS_APP", "SETTINGS_ORG", "READY_STATUS", "COMPLETED_STATUS",
    "DOWNLOAD_HISTORY_SETTING", "SAVE_FOLDER_SETTING",
]


EVENT_MESSAGE_LIMIT = 500
DOWNLOAD_INFO_CACHE_LIMIT = 20
DOWNLOAD_INFO_CACHE_TTL_SECONDS = 600.0


class ClipFlowWindow(SettingsMixin, RenderMixin, ActionMixin, PlaylistMixin, DownloadMixin, QMainWindow):
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
            app.setStyleSheet(APP_STYLE)
            if not getattr(app, "_clipflow_tooltip_manager", None):
                manager = TooltipManager(app)
                app.installEventFilter(manager)
                app._clipflow_tooltip_manager = manager
        if analyze_func is engine.analyze_url:
            def analyze_with_subprocess_boundary(url, cookie_source=None, output_ext=None, on_event=None, proxy_url=None):
                return engine.analyze_url_in_subprocess(
                    url,
                    cookie_source=cookie_source,
                    output_ext=output_ext,
                    on_event=on_event,
                    proxy_url=proxy_url,
                )

            analyze_with_subprocess_boundary._clipflow_uses_analysis_worker_pool = True
            self.analyze_func = analyze_with_subprocess_boundary
        else:
            self.analyze_func = analyze_func
        if download_func is engine.download_candidate:
            def download_with_subprocess_boundary(page_url, candidate, output_dir, cookie_source=None, on_event=None, proxy_url=None):
                return engine.download_candidate_in_subprocess(
                    page_url,
                    candidate,
                    output_dir,
                    cookie_source=cookie_source,
                    on_event=on_event,
                    proxy_url=proxy_url,
                )

            download_with_subprocess_boundary._clipflow_uses_download_worker_pool = True
            self.download_func = download_with_subprocess_boundary
        else:
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
        self.active_downloads = []
        self.queued_download_rows = []
        self.selected_row_index = -1
        self.select_mode = False
        self.event_messages = deque(maxlen=EVENT_MESSAGE_LIMIT)
        self._clear_url_on_next_click = False
        self._row_sequence = 0
        self._analysis_auto_download = False
        self._analysis_url = ""
        self._queued_analysis_downloads = []
        self._download_info_cache = OrderedDict()
        self._playlist_event_candidates = []
        self._playlist_event_parent_id = ""
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
        layout.setContentsMargins(18, 16, 18, 12)
        layout.setSpacing(14)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_input_panel())
        layout.addWidget(self._build_list_panel(), 1)
        self.setCentralWidget(root)

    def _build_header(self):
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(2, 2, 2, 0)
        row.setSpacing(10)

        glyph = QLabel()
        glyph.setPixmap(create_app_icon(26).pixmap(26, 26))
        glyph.setFixedSize(26, 26)

        wordmark = QLabel(APP_NAME)
        wordmark.setObjectName("WindowTitle")
        apply_tracking(wordmark, 0.2)

        row.addWidget(glyph, 0, Qt.AlignVCenter)
        row.addWidget(wordmark, 0, Qt.AlignVCenter)
        row.addStretch(1)
        return header

    def eventFilter(self, obj, event):
        if hasattr(self, "scroll_area") and obj is self.scroll_area.viewport() and event.type() == event.Type.Resize:
            self._position_playlist_float_button()
            self._refresh_playlist_float_button()
            if hasattr(self, "empty_state"):
                self.empty_state.setGeometry(self.scroll_area.viewport().rect())
        return super().eventFilter(obj, event)

    def _panel(self):
        frame = QFrame()
        frame.setObjectName("Panel")
        return frame

    def _apply_panel_shadow(self, widget, blur=28, y_offset=8, alpha=26):
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(blur)
        shadow.setXOffset(0)
        shadow.setYOffset(y_offset)
        shadow.setColor(QColor(20, 22, 30, alpha))
        widget.setGraphicsEffect(shadow)

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
        self.url_input.pasted.connect(self._on_url_pasted)
        self.url_input.returnPressed.connect(self._handle_primary_action)

        self.paste_button = LucideIconButton("clipboard", size=30, icon_size=16)
        self.paste_button.setToolTip("붙여넣기")
        self.paste_button.clicked.connect(self._paste_and_analyze)
        self.clear_url_button = LucideIconButton("circle-x", size=30, icon_size=16)
        self.clear_url_button.setToolTip("URL 지우기")
        self.clear_url_button.clicked.connect(self._clear_url)
        url_trailing = QWidget()
        url_trailing_layout = QHBoxLayout(url_trailing)
        url_trailing_layout.setContentsMargins(0, 0, 0, 0)
        url_trailing_layout.setSpacing(0)
        url_trailing_layout.addWidget(self.paste_button)
        url_trailing_layout.addWidget(self.clear_url_button)
        url_field = self._field_box("link", self.url_input, url_trailing)

        self.primary_button = PrimaryActionButton()
        self.primary_button.setFixedSize(64, TOP_FIELD_HEIGHT)
        self.primary_button.setCursor(Qt.PointingHandCursor)
        self.primary_button.setToolTip("다운로드")
        download_icon = QIcon()
        download_icon.addPixmap(lucide_pixmap("download", 18, theme.ON_ACCENT), QIcon.Normal)
        download_icon.addPixmap(lucide_pixmap("download", 18, theme.MUTED), QIcon.Disabled)
        self.primary_button.setIcon(download_icon)
        self.primary_button.setIconSize(QSize(18, 18))
        self.primary_button.clicked.connect(self._handle_primary_action)

        self.folder_input = PathDisplayInput(self._initial_save_folder())
        self.folder_button = QPushButton("저장 위치")
        self.folder_button.setObjectName("SecondaryButton")
        self.folder_button.setFixedSize(96, TOP_FIELD_HEIGHT)
        self.folder_button.setCursor(Qt.PointingHandCursor)
        self.folder_button.setToolTip("저장 폴더 선택")
        self.folder_button.clicked.connect(self._choose_folder)
        folder_field = self._field_box("folder", self.folder_input)

        self.cookie_combo = CleanComboBox("cookie")
        self.cookie_combo.addItems(COOKIE_DISPLAY_CHOICES)
        self.cookie_combo.show_arrow = False
        self.cookie_combo.text_alignment = Qt.AlignCenter
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
        options_row.addWidget(self.folder_button)
        options_row.addWidget(self.cookie_combo)

        layout.addLayout(url_row)
        layout.addLayout(options_row)
        return panel

    def _build_list_panel(self):
        panel = QFrame()
        panel.setObjectName("ListPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.count_label = QLabel("0개")
        self.count_label.setObjectName("CountChip")
        self.count_label.setAlignment(Qt.AlignCenter)

        self.select_toggle = QPushButton("선택")
        self.select_toggle.setObjectName("GhostButton")
        self.select_toggle.setProperty("active", "false")
        self.select_toggle.setCursor(Qt.PointingHandCursor)
        self.select_toggle.setToolTip("선택 모드")
        self.select_toggle.clicked.connect(self._toggle_select_mode)

        self.select_actions = QWidget()
        select_actions_layout = QHBoxLayout(self.select_actions)
        select_actions_layout.setContentsMargins(0, 0, 0, 0)
        select_actions_layout.setSpacing(2)
        self.select_all_button = LucideIconButton("check-check", size=34, icon_size=20)
        self.select_all_button.setToolTip("전체 선택")
        self.select_all_button.clicked.connect(self._select_all_rows)
        self.remove_list_button = LucideIconButton("x", size=34, icon_size=20)
        self.remove_list_button.setToolTip("목록에서 삭제")
        self.remove_list_button.clicked.connect(self._delete_selected_from_list)
        self.remove_file_button = LucideIconButton("trash-2", size=34, icon_size=20, danger=True)
        self.remove_file_button.setToolTip("파일 삭제")
        self.remove_file_button.clicked.connect(self._delete_selected_files)
        select_actions_layout.addWidget(self.select_all_button)
        select_actions_layout.addWidget(self.remove_list_button)
        select_actions_layout.addWidget(self.remove_file_button)
        self.select_actions.hide()
        self.sort_label = QLabel("정렬:")
        self.sort_label.setObjectName("SortLabel")
        self.sort_label.setFixedHeight(TOP_FIELD_HEIGHT - 2)
        self.sort_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        self.sort_order_combo = CleanComboBox()
        self.sort_order_combo.addItems(["최신순", "이름순"])
        self.sort_order_combo.setCurrentText(SORT_LABELS.get(self.sort_key, "최신순"))
        self.sort_order_combo.currentIndexChanged.connect(self._sort_changed)
        self.sort_order_combo.show_arrow = False
        self.sort_order_combo.text_alignment = Qt.AlignCenter
        self.sort_order_combo.setMaximumWidth(120)
        self.sort_direction_button = LucideIconButton(self._sort_direction_icon(), size=40, icon_size=18, bordered=True)
        self.sort_direction_button.clicked.connect(self._toggle_sort_direction)
        self._refresh_sort_direction_button()
        self.preference_button = QPushButton("품질")
        self.preference_button.setObjectName("SecondaryButton")
        self.preference_button.setFixedSize(74, TOP_FIELD_HEIGHT - 2)
        self.preference_button.setCursor(Qt.PointingHandCursor)
        self.preference_button.setToolTip("품질/포맷/코덱/프레임 설정")
        self.preference_button.clicked.connect(self._toggle_preferences_popup)
        header.addWidget(self.select_toggle, 0, Qt.AlignVCenter)
        header.addWidget(self.select_actions, 0, Qt.AlignVCenter)
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
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._refresh_playlist_float_button)
        self.scroll_area.verticalScrollBar().rangeChanged.connect(self._refresh_scrollbar_activity)
        self.row_container = QWidget()
        self.row_container.setObjectName("RowContainer")
        self.row_layout = QVBoxLayout(self.row_container)
        self.row_layout.setContentsMargins(2, 2, 2, 2)
        self.row_layout.setSpacing(10)
        self.row_layout.addStretch(1)
        self.scroll_area.setWidget(self.row_container)
        self._refresh_scrollbar_activity()
        self.scroll_area.viewport().installEventFilter(self)
        self.playlist_float_button = QPushButton("접기", self.scroll_area.viewport())
        self.playlist_float_button.setObjectName("FloatingButton")
        self.playlist_float_button.setFixedSize(62, 30)
        self.playlist_float_button.clicked.connect(self._collapse_floating_playlist)
        self.playlist_float_button.hide()

        self.empty_state = QWidget(self.scroll_area.viewport())
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(10)
        empty_glyph = LucideIconWidget("play", size=42, color=theme.BORDER_STRONG)
        empty_title = QLabel("아직 담긴 영상이 없어요")
        empty_title.setObjectName("SectionTitle")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_sub = QLabel("위에 URL을 붙여넣으면 분석해서 카드로 보여줄게요")
        empty_sub.setObjectName("MetaText")
        empty_sub.setAlignment(Qt.AlignCenter)
        apply_tracking(empty_sub, 0.2)
        empty_layout.addWidget(empty_glyph, 0, Qt.AlignHCenter)
        empty_layout.addWidget(empty_title, 0, Qt.AlignHCenter)
        empty_layout.addWidget(empty_sub, 0, Qt.AlignHCenter)

        layout.addWidget(self.scroll_area, 1)
        return panel

    def _build_footer(self):
        footer = QWidget()
        outer = QVBoxLayout(footer)
        outer.setContentsMargins(4, 0, 4, 0)
        outer.setSpacing(9)
        divider = QFrame()
        divider.setObjectName("FooterDivider")
        outer.addWidget(divider)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel("준비됨")
        self.total_label = QLabel("총 항목: 0")
        self.concurrent_label = QLabel("동시 다운로드: 0/1")
        self.total_label.setObjectName("MetaText")
        self.concurrent_label.setObjectName("MetaText")
        apply_tracking(self.total_label, 0.2)
        apply_tracking(self.concurrent_label, 0.2)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        layout.addWidget(self.total_label)
        outer.addLayout(layout)
        return footer

    def _prepare_url_edit(self):
        return

    def _on_url_pasted(self):
        self._refresh_primary_action()

    def _clear_url(self):
        self.url_input.clear()
        self._clear_url_on_next_click = False
        self._refresh_primary_action()

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.folder_input.text())
        if folder:
            self._set_save_folder(folder)

    def _handle_primary_action(self):
        current_url = self.url_input.text().strip()
        if current_url:
            row_index = self._first_visible_analyzed_row_index_for_url(current_url)
            if row_index < 0:
                if self.analysis_thread and self.analysis_thread.isRunning():
                    self._queue_analysis_download(current_url)
                else:
                    self._start_analysis(auto_download=True)
                return
            if self._selected_row_can_download():
                self._start_download()
                return
            self.select_row(row_index)
            self._start_download()
            return
        self._start_download()

    def _paste_and_analyze(self):
        text = QApplication.clipboard().text().strip()
        if text:
            self.url_input.setText(text)
            self._refresh_primary_action()

    def _refresh_url_trailing(self):
        has_text = bool(self.url_input.text().strip())
        self.paste_button.setVisible(not has_text)
        self.clear_url_button.setVisible(has_text)

    def _queue_analysis_download(self, url):
        url = str(url or "").strip()
        if not url:
            return
        if url == self._analysis_url and self._analysis_auto_download:
            return
        if any(item.get("url") == url for item in self._queued_analysis_downloads):
            return
        self._queued_analysis_downloads.append({"url": url, "auto_download": True})
        self._set_status("Queued for analysis")
        self._refresh_primary_action()

    def _start_next_queued_analysis(self):
        if self.analysis_thread and self.analysis_thread.isRunning():
            return
        while self._queued_analysis_downloads:
            item = self._queued_analysis_downloads.pop(0)
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            self.url_input.setText(url)
            self._start_analysis(auto_download=bool(item.get("auto_download")))
            return

    def _remember_download_infos(self, analysis):
        if not isinstance(analysis, dict):
            return
        now = time.monotonic()
        self._trim_download_info_cache(now)
        infos = analysis.get("_download_infos")
        if isinstance(infos, dict):
            for key, value in infos.items():
                if isinstance(value, dict):
                    cache_key = str(key)
                    self._download_info_cache[cache_key] = (now, value)
                    self._download_info_cache.move_to_end(cache_key)
        self._trim_download_info_cache(now)

    def _trim_download_info_cache(self, now=None):
        now = time.monotonic() if now is None else now
        for key in list(self._download_info_cache.keys()):
            cached = self._download_info_cache.get(key)
            timestamp = cached[0] if isinstance(cached, tuple) and len(cached) == 2 else now
            if now - timestamp > DOWNLOAD_INFO_CACHE_TTL_SECONDS:
                self._download_info_cache.pop(key, None)
        while len(self._download_info_cache) > DOWNLOAD_INFO_CACHE_LIMIT:
            self._download_info_cache.popitem(last=False)

    def _cached_download_info(self, key):
        cached = self._download_info_cache.get(key)
        if not cached:
            return None
        if isinstance(cached, tuple) and len(cached) == 2:
            timestamp, value = cached
        else:
            timestamp, value = time.monotonic(), cached
        if time.monotonic() - timestamp > DOWNLOAD_INFO_CACHE_TTL_SECONDS:
            self._download_info_cache.pop(key, None)
            return None
        self._download_info_cache.move_to_end(key)
        return value if isinstance(value, dict) else None

    def _candidate_for_download(self, row, candidate):
        prepared = dict(candidate or {})
        key = str(prepared.get("_download_info_key") or "")
        cached_info = self._cached_download_info(key) if key else None
        if cached_info and engine.download_info_reuse_supported(prepared):
            prepared["_download_info"] = cached_info
        return prepared

    def _start_analysis(self, auto_download=False):
        if self.analysis_thread and self.analysis_thread.isRunning():
            return

        url = self.url_input.text().strip()
        if not url:
            return

        self.analysis = None
        self.selected_row_index = -1
        self._analysis_auto_download = bool(auto_download)
        self._analysis_url = url
        self._playlist_event_candidates = []
        self._playlist_event_parent_id = ""
        self._refresh_primary_action()
        self.primary_button.set_loading(False)
        self._set_status(ANALYZING_STATUS)
        if auto_download and getattr(self.download_func, "_clipflow_uses_download_worker_pool", False):
            try:
                engine.warm_download_worker()
            except Exception as exc:
                self._append_event_message(f"Download worker warmup failed: {engine.strip_ansi(exc)}")

        loading_rows = self._analysis_loading_rows(url)
        self.rows = loading_rows + [row for row in self.rows if not self._is_analysis_loading_row(row)]
        self._render_rows()

        self.analysis_thread = QThread(self)
        self.analysis_worker = AnalyzeWorker(
            url,
            cookie_source_from_display(self.cookie_combo.currentText()),
            engine.ALL_OUTPUT_EXT,
            self.analyze_func,
        )
        self.analysis_worker.moveToThread(self.analysis_thread)
        self.analysis_thread.started.connect(self.analysis_worker.run)
        self.analysis_worker.event.connect(self._handle_analysis_event)
        self.analysis_worker.finished.connect(self._analysis_finished)
        self.analysis_worker.failed.connect(self._analysis_failed)
        self.analysis_worker.finished.connect(self.analysis_thread.quit)
        self.analysis_worker.failed.connect(self.analysis_thread.quit)
        self.analysis_thread.finished.connect(self.analysis_worker.deleteLater)
        self.analysis_thread.finished.connect(self._analysis_thread_finished)
        self.analysis_thread.start()

    def _analysis_loading_rows(self, url):
        if engine.looks_like_playlist_url(url):
            parent = self._find_playlist_parent_for_url(url)
            if parent and not self._playlist_children_for_parent(parent):
                parent["analysis_loading"] = True
                parent["expanded"] = True
                parent["status"] = ANALYZING_STATUS
                parent["progress_text"] = ANALYZING_STATUS
            else:
                parent = self._playlist_parent_loading_row(url)
            child = self._playlist_child_loading_row(parent["id"], url)
            self._playlist_event_parent_id = parent["id"]
            return [parent, child]
        return [self._single_analysis_loading_row(url)]

    def _single_analysis_loading_row(self, url):
        return {
            "id": "__analyzing__",
            "kind": "video",
            "candidate": self._placeholder_candidate(url),
            "qualities": [],
            "quality_options": [],
            "selected_index": 0,
            "selected_format_index": 0,
            "analysis_source_url": url,
            "source_url": url,
            "input_url": url,
            "status": ANALYZING_STATUS,
            "status_detail": "",
            "progress": 0,
            "progress_text": ANALYZING_STATUS,
            "output_path": "",
            "messages": [],
            "created_order": self._next_row_sequence(),
            "analysis_loading": True,
        }

    def _placeholder_candidate(self, url):
        output_ext = self._preferred_output_ext()
        return {
            "id": "loading",
            "display_title": url,
            "title": url,
            "thumbnail": "",
            "duration": 0,
            "sort_bytes": 0,
            "output_ext": output_ext,
            "ext": output_ext,
            "resolution": "",
        }

    @Slot(dict)
    def _analysis_finished(self, analysis):
        self.analysis = analysis
        self._remember_download_infos(analysis)
        grouped = presenter.group_candidates(analysis.get("candidates") or [])
        source_url = analysis.get("webpage_url") or analysis.get("url") or self.url_input.text().strip()
        self._prepend_analysis_rows(analysis, grouped, source_url)
        self._clear_url_on_next_click = False
        self._set_status(f"분석 완료: {len(grouped)}개")
        self._refresh_footer()
        for warning in analysis.get("warnings") or []:
            self._append_event_message(str(warning))
        if self._analysis_auto_download and self.rows:
            self._analysis_auto_download = False
            row_index = self._first_visible_analyzed_row_index_for_url(source_url)
            target_row = self.rows[row_index] if row_index >= 0 else self.rows[0]
            self.selected_row_index = self.rows.index(target_row)
            self._refresh_row_selection()
            # Bind the resolved row object (not the shared selected index, which a
            # subsequent analysis can reset to -1 before this timer fires).
            QTimer.singleShot(0, lambda r=target_row: self.start_download_for_row(r))

    @Slot(str)
    def _analysis_failed(self, message):
        message = engine.strip_ansi(message)
        self._analysis_auto_download = False
        for row in self.rows:
            if row.get("kind") == "playlist" and row.get("analysis_loading") and not row.get("child_loading"):
                row["analysis_loading"] = False
                row["status"] = ERROR_STATUS
                row["progress_text"] = ""
        self._set_status(f"{engine.classify_error(message)}: {message}")

    @Slot()
    def _analysis_thread_finished(self):
        self.primary_button.set_loading(False)
        self.analysis_thread = None
        self.analysis_worker = None
        self._analysis_url = ""
        if any(self._is_analysis_loading_row(row) for row in self.rows):
            self.rows = [row for row in self.rows if not self._is_analysis_loading_row(row)]
            if self.selected_row_index >= len(self.rows):
                self.selected_row_index = len(self.rows) - 1
            self._render_rows()
        self._refresh_primary_action()
        if self._queued_analysis_downloads:
            QTimer.singleShot(0, self._start_next_queued_analysis)

    def _is_analysis_loading_row(self, row):
        return bool(row.get("analysis_loading")) or row.get("id") == "__analyzing__" or bool(row.get("child_loading"))

    def _prepend_analysis_rows(self, analysis, grouped_rows, source_url):
        self.rows = self._dedupe_playlist_parent_rows(self.rows)
        preserved_rows = [
            row
            for row in self.rows
            if self._should_preserve_existing_row(row)
        ]
        if analysis.get("is_playlist"):
            existing_parent = self._find_playlist_parent_for_analysis(analysis, source_url)
            if existing_parent:
                if any(not child.get("child_loading") for child in self._playlist_children_for_parent(existing_parent)):
                    self._finalize_progressive_playlist_rows(existing_parent, analysis, grouped_rows, source_url)
                    self._sort_rows()
                    self.selected_row_index = self.rows.index(existing_parent)
                    self._render_rows()
                    return
                self._update_playlist_rows(existing_parent, analysis, grouped_rows, source_url)
                self._sort_rows()
                self.selected_row_index = self.rows.index(existing_parent)
                self._render_rows()
                return
            parent = self._playlist_parent_row_from_analysis(analysis, grouped_rows, source_url)
            children = self._playlist_child_rows_from_grouped(parent, grouped_rows, analysis, source_url)
            self.rows = [parent] + children + preserved_rows
            self._sort_rows()
            self.selected_row_index = 0 if self.rows else -1
            self._render_rows()
            return
        new_rows = []
        for grouped_row in grouped_rows:
            new_rows.append(self._video_row_from_grouped(grouped_row, analysis, source_url))
        self.rows = new_rows + preserved_rows
        self._sort_rows()
        self.selected_row_index = 0 if self.rows else -1
        self._render_rows()

    def _should_preserve_existing_row(self, row):
        if self._is_analysis_loading_row(row):
            return False
        if row.get("status") in {COMPLETED_STATUS, DOWNLOAD_STATUS, WAITING_STATUS}:
            return True
        return self._row_is_downloading(row) or row in self.queued_download_rows

    def _preferred_output_ext(self):
        output_ext = self.current_preferences().output_format
        if str(output_ext).casefold() == AUTO_LABEL.casefold():
            output_ext = DEFAULT_OUTPUT_EXT
        return str(output_ext or DEFAULT_OUTPUT_EXT).lower()

    def _row_is_visible(self, row):
        if not row.get("is_playlist_child"):
            return True
        parent = self._parent_playlist_for_child(row)
        return bool(parent and parent.get("expanded"))

    @Slot(dict)
    def _handle_engine_event(self, event):
        self._handle_engine_event_for(self.active_download_row, event)

    @Slot(dict)
    def _handle_analysis_event(self, event):
        event_type = event.get("type")
        if event_type in {"playlist_parent", "playlist_entry", "playlist_entry_loading", "playlist_complete", "playlist_failed_entry"}:
            self._handle_playlist_analysis_event(event)
            return
        message = event.get("message") or event.get("path") or ""
        if event_type in {"progress", "status"}:
            if hasattr(self, "status_label"):
                self.status_label.setText(message or "분석 중")
            if message:
                self._append_event_message(message)
        elif event_type in {"log", "done", "file"} and message:
            self._append_event_message(message)

    def _find_row_by_id(self, row_id):
        if not row_id:
            return None
        for row in self.rows:
            if row.get("id") == row_id:
                return row
        return None

    # Thin signal entry points kept on the QObject window so cross-thread
    # download-worker callbacks are delivered on the UI thread (real Qt slots).
    @Slot(str, dict)
    def _handle_download_worker_event(self, row_id, event):
        self._handle_engine_event_for(self._find_row_by_id(row_id), event)

    @Slot(str, dict)
    def _download_worker_finished(self, row_id, result):
        self._download_finished_for(self._find_row_by_id(row_id), result)

    @Slot(str, str)
    def _download_worker_failed(self, row_id, message):
        self._download_failed_for(self._find_row_by_id(row_id), message)

    @Slot()
    def _on_download_thread_finished(self):
        self._handle_thread_finished(self.sender())

    def _handle_engine_event_for(self, row, event):
        event_type = event.get("type")
        message = event.get("message") or event.get("path") or ""
        widget = row.get("widget") if row else None
        if event_type == "progress":
            percent = max(0, min(100, int(float(event.get("percent") or 0))))
            text = self._progress_text(percent, event)
            if widget:
                # Avoid the heavy set_status() on every progress tick (it does
                # spinner/visibility work + a filesystem stat in _refresh_actions).
                # Status is already "다운로드 중" from _begin_download; only assert
                # it once if it somehow drifted.
                if row.get("status") != DOWNLOAD_STATUS:
                    widget.set_status(DOWNLOAD_STATUS)
                widget.set_progress(percent, text)
            if hasattr(self, "status_label") and self.status_label.text() != (text or "다운로드 중"):
                self.status_label.setText(text or "다운로드 중")
        elif event_type == "file":
            if row and event.get("path"):
                row["output_path"] = str(event["path"])
                if widget:
                    widget._refresh_actions()
        elif event_type == "status":
            if message:
                if hasattr(self, "status_label"):
                    self.status_label.setText(message)
                self._append_event_message(message)
        elif event_type in {"log", "done"}:
            if message:
                self._append_event_message(message)

    def _progress_text(self, percent, event):
        if isinstance(event, dict):
            speed = str(event.get("speed_text") or "").strip()
            if not speed:
                message = event.get("message") or ""
            else:
                return f"{percent}% · {speed}"
        else:
            message = event
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

    def _refresh_primary_action(self):
        self._refresh_url_trailing()
        has_target = 0 <= self.selected_row_index < len(self.rows) and self._row_is_visible(self.rows[self.selected_row_index])
        if has_target:
            has_target = self.rows[self.selected_row_index].get("status") != ANALYZING_STATUS
        has_url = bool(self.url_input.text().strip())
        self.primary_button.setEnabled(has_target or has_url)

    def _first_visible_analyzed_row_index_for_url(self, url):
        url = str(url or "").strip()
        if not url:
            return -1
        playlist_key = self._playlist_key(url)
        for index, row in enumerate(self.rows):
            if not self._row_is_visible(row) or self._is_analysis_loading_row(row):
                continue
            if row.get("status") == ANALYZING_STATUS:
                continue
            if playlist_key and row.get("kind") == "playlist" and self._playlist_key_for_row(row) == playlist_key:
                return index
            row_urls = {
                str(row.get("analysis_source_url") or "").strip(),
                str(row.get("source_url") or "").strip(),
                str(row.get("input_url") or "").strip(),
            }
            if url in row_urls:
                return index
        return -1

    def _selected_row_can_download(self):
        if self.selected_row_index < 0 or self.selected_row_index >= len(self.rows):
            return False
        row = self.rows[self.selected_row_index]
        return self._row_is_visible(row) and not self._is_analysis_loading_row(row) and row.get("status") != ANALYZING_STATUS

    def _selected_row_matches_current_url(self):
        if self.selected_row_index < 0 or self.selected_row_index >= len(self.rows):
            return False
        if not self._row_is_visible(self.rows[self.selected_row_index]):
            return False
        current_url = self.url_input.text().strip()
        if not current_url:
            return False
        row = self.rows[self.selected_row_index]
        row_urls = {
            str(row.get("analysis_source_url") or "").strip(),
            str(row.get("source_url") or "").strip(),
            str(row.get("input_url") or "").strip(),
        }
        return current_url in row_urls

    def _refresh_footer(self):
        return

    def _set_status(self, message):
        if hasattr(self, "status_label"):
            self.status_label.setText(message)
        self._append_event_message(message)

    def _append_event_message(self, message):
        message = str(message or "")
        if not message:
            return
        if self.event_messages and self.event_messages[-1] == message:
            return
        self.event_messages.append(message)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--clipflow-download-worker":
        try:
            from tools.clipflow_download_process import main as download_worker_main
        except ImportError:
            from clipflow_download_process import main as download_worker_main
        return download_worker_main(sys.argv[1:])
    if len(sys.argv) > 1 and sys.argv[1] == "--clipflow-analysis-worker":
        try:
            from tools.clipflow_analysis_process import main as analysis_worker_main
        except ImportError:
            from clipflow_analysis_process import main as analysis_worker_main
        return analysis_worker_main(sys.argv[1:])

    app = QApplication(sys.argv)
    configure_app_font(app)
    window = ClipFlowWindow()
    window.show()

    if os.environ.get("CLIPFLOW_QT_SMOKE") == "1":
        QTimer.singleShot(0, lambda: (print("ClipFlow smoke launch OK"), app.quit()))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
