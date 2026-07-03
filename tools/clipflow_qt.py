import os
import sys
import time
from collections import OrderedDict, deque

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, QSettings, QSize, Qt, QThread, QTimer, QUrl, Slot, qInstallMessageHandler
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
    from tools.clipflow_widgets import CleanComboBox, ClearingUrlInput, ComboPopup, OutlinedButton, PathDisplayInput, PrimaryActionButton, RoundedFrame, TimecodeInput
    from tools.clipflow_rows import build_quality_options
    from tools.clipflow_workers import AnalyzeWorker
    from tools.clipflow_dialogs import DeleteConfirmDialog
    from tools.clipflow_playlist import PlaylistMixin
    from tools.clipflow_downloads import DownloadMixin
    from tools.clipflow_views import RenderMixin
    from tools.clipflow_actions import ActionMixin, local_file_url
    from tools.clipflow_settings import SettingsMixin, default_save_folder
    from tools.clipflow_updater import start_sparkle_updater
except ImportError:
    import candidate_presenter as presenter
    import downloader_engine as engine
    import clipflow_theme as theme
    from clipflow_theme import (
        APP_NAME, APP_STYLE, COOKIE_DISPLAY_CHOICES, DEFAULT_OUTPUT_EXT,
        TOP_FIELD_HEIGHT, apply_tracking, configure_app_font, cookie_source_from_display, create_app_icon,
    )
    from clipflow_icons import LucideIconButton, LucideIconWidget, TooltipManager, lucide_pixmap
    from clipflow_widgets import CleanComboBox, ClearingUrlInput, ComboPopup, OutlinedButton, PathDisplayInput, PrimaryActionButton, RoundedFrame, TimecodeInput
    from clipflow_rows import build_quality_options
    from clipflow_workers import AnalyzeWorker
    from clipflow_dialogs import DeleteConfirmDialog
    from clipflow_playlist import PlaylistMixin
    from clipflow_downloads import DownloadMixin
    from clipflow_views import RenderMixin
    from clipflow_actions import ActionMixin, local_file_url
    from clipflow_settings import SettingsMixin, default_save_folder
    from clipflow_updater import start_sparkle_updater

try:
    from tools.clipflow_theme import (
        ANALYZING_STATUS, AUTO_LABEL, COMPLETED_STATUS, DOWNLOAD_HISTORY_SETTING, DOWNLOAD_STATUS, ERROR_STATUS,
        PAUSED_STATUS, READY_STATUS, SAVE_FOLDER_SETTING, SETTINGS_APP, SETTINGS_ORG, SORT_DESC_SETTING, SORT_KEY_SETTING,
        SORT_LABELS, WAITING_STATUS, WINDOW_SIZE_SETTING,
    )
except ImportError:
    from clipflow_theme import (
        ANALYZING_STATUS, AUTO_LABEL, COMPLETED_STATUS, DOWNLOAD_HISTORY_SETTING, DOWNLOAD_STATUS, ERROR_STATUS,
        PAUSED_STATUS, READY_STATUS, SAVE_FOLDER_SETTING, SETTINGS_APP, SETTINGS_ORG, SORT_DESC_SETTING, SORT_KEY_SETTING,
        SORT_LABELS, WAITING_STATUS, WINDOW_SIZE_SETTING,
    )


# Names re-exported for the test-suite and external callers.
__all__ = [
    "ClipFlowWindow", "DeleteConfirmDialog", "default_save_folder", "local_file_url", "main",
    "SETTINGS_APP", "SETTINGS_ORG", "READY_STATUS", "COMPLETED_STATUS",
    "DOWNLOAD_HISTORY_SETTING", "SAVE_FOLDER_SETTING", "WINDOW_SIZE_SETTING",
]


EVENT_MESSAGE_LIMIT = 500
_QT_WARNING_FILTER_INSTALLED = False


def _should_suppress_qt_message(message):
    text = str(message or "")
    return (
        "QFont::setPointSize: Point size <= 0 (-1)" in text
        or "QIODevice::read (QSslSocket): device not open" in text
    )


def install_qt_warning_filter():
    global _QT_WARNING_FILTER_INSTALLED
    if _QT_WARNING_FILTER_INSTALLED:
        return

    def handler(mode, context, message):
        del mode, context
        if _should_suppress_qt_message(message):
            return
        sys.stderr.write(f"{message}\n")

    qInstallMessageHandler(handler)
    _QT_WARNING_FILTER_INSTALLED = True


def checkbox_outline_pixmap(size, color, checked=False):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    pen = QPen(QColor(color))
    pen.setWidthF(1.4)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    inset = pen.widthF() / 2 + 0.5
    painter.drawRoundedRect(QRectF(inset, inset, size - inset * 2, size - inset * 2), 3, 3)
    if checked:
        check_size = max(10, size - 5)
        offset = (size - check_size) // 2
        painter.drawPixmap(offset, offset, check_size, check_size, lucide_pixmap("check", check_size, color))
    painter.end()
    return pixmap
DOWNLOAD_INFO_CACHE_LIMIT = 20
DOWNLOAD_INFO_CACHE_TTL_SECONDS = 600.0
LIST_TOOL_HEIGHT = 36
LIST_TOOL_WIDTH = 64
SORT_TOOL_WIDTH = 96
SEARCH_INPUT_WIDTH = 180
WINDOW_DEFAULT_SIZE = QSize(720, 760)
WINDOW_MINIMUM_SIZE = QSize(560, 420)


class ClipFlowWindow(SettingsMixin, RenderMixin, ActionMixin, PlaylistMixin, DownloadMixin, QMainWindow):
    def __init__(
        self,
        analyze_func=engine.analyze_url,
        download_func=engine.download_candidate,
        open_url_func=None,
        confirm_delete_func=None,
        playlist_choice_func=None,
    ):
        super().__init__()
        install_qt_warning_filter()
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
        self.download_concurrency = self._initial_download_concurrency()
        self.sort_key = self.settings.value(SORT_KEY_SETTING, "latest", str) or "latest"
        if self.sort_key not in SORT_LABELS:
            self.sort_key = "latest"
        self.sort_desc = str(self.settings.value(SORT_DESC_SETTING, "true", str)).lower() != "false"
        self.open_url_func = open_url_func or (lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.confirm_delete_func = confirm_delete_func
        self.playlist_choice_func = playlist_choice_func
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
        self.setMinimumSize(WINDOW_MINIMUM_SIZE)
        self.resize(self._initial_window_size())
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        self._load_completed_history()
        self._refresh_primary_action()

    def _initial_window_size(self):
        size = self.settings.value(WINDOW_SIZE_SETTING, WINDOW_DEFAULT_SIZE, QSize)
        if isinstance(size, QSize) and size.isValid():
            return size.expandedTo(WINDOW_MINIMUM_SIZE)
        return WINDOW_DEFAULT_SIZE

    def closeEvent(self, event):
        self.settings.setValue(WINDOW_SIZE_SETTING, self.size())
        super().closeEvent(event)

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

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

    def _refresh_select_toggle_icon(self):
        checked = bool(getattr(self, "select_mode", False))
        color = theme.GRAPHITE
        self.select_toggle.setIcon(QIcon(checkbox_outline_pixmap(20, color, checked=checked)))

    def eventFilter(self, obj, event):
        if hasattr(self, "search_input") and obj is self.search_input and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key_Escape:
                self._set_search_expanded(False)
                return True
        if getattr(self, "clip_range_popup", None) is obj and event.type() == event.Type.Hide:
            self._restore_clip_range_draft_from_applied()
        if getattr(self, "clip_range_popup", None) is obj and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._apply_clip_range_popup()
                return True
            if event.key() == Qt.Key_Escape:
                obj.close()
                return True
        if hasattr(self, "scroll_area") and obj is self.scroll_area.viewport() and event.type() == event.Type.Resize:
            self._position_playlist_float_button()
            self._refresh_playlist_float_button()
            if hasattr(self, "empty_state"):
                self.empty_state.setGeometry(self.scroll_area.viewport().rect())
        return super().eventFilter(obj, event)

    def _panel(self):
        frame = RoundedFrame(radius=12, border_width=1.4, background=theme.SURFACE, border=theme.GRAPHITE)
        frame.setObjectName("Panel")
        frame.setStyleSheet("QFrame#Panel { background: transparent; border: none; }")
        return frame

    def _apply_panel_shadow(self, widget, blur=28, y_offset=8, alpha=26):
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(blur)
        shadow.setXOffset(0)
        shadow.setYOffset(y_offset)
        shadow.setColor(QColor(20, 22, 30, alpha))
        widget.setGraphicsEffect(shadow)

    def _field_box(self, icon_kind, line_edit, trailing_widget=None):
        frame = RoundedFrame(radius=8, border_width=1.4, background=theme.SURFACE, border=theme.GRAPHITE)
        frame.setObjectName("FieldBox")
        frame.setStyleSheet("QFrame#FieldBox { background: transparent; border: none; }")
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

    def _time_field_box(self, line_edit, height=TOP_FIELD_HEIGHT):
        frame = RoundedFrame(radius=9, border_width=1.4, background=theme.SURFACE_SOFT, border=theme.GRAPHITE)
        frame.setObjectName("FieldBox")
        frame.setProperty("timeField", "true")
        frame.setStyleSheet("QFrame#FieldBox { background: transparent; border: none; }")
        frame.setFixedHeight(height)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(0)
        line_edit.setObjectName("BareInput")
        layout.addWidget(line_edit, 1)
        return frame

    def _build_clip_popup_time_row(self, label_text, line_edit):
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        label = QLabel(label_text)
        label.setObjectName("ClipRangeLabel")
        label.setFixedWidth(74)
        label.setFixedHeight(36)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        line_edit.setFixedSize(164, 36)
        row.addWidget(label)
        row.addWidget(line_edit)
        return row_widget, label

    def _build_input_panel(self):
        panel = self._panel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.url_input = ClearingUrlInput()
        self.url_input.setPlaceholderText("URL을 입력하세요")
        self._clip_range_url_text = ""
        self.url_input.textChanged.connect(self._refresh_primary_action)
        self.url_input.textChanged.connect(self._reset_clip_range_on_url_change)
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

        self.clip_range_button = OutlinedButton("구간선택")
        self.clip_range_button.setObjectName("SecondaryButton")
        self.clip_range_button.setFixedSize(88, TOP_FIELD_HEIGHT)
        self.clip_range_button.setCursor(Qt.PointingHandCursor)
        self.clip_range_button.setToolTip("시작/종료 시간을 지정해서 구간만 다운로드")
        self.clip_range_button.clicked.connect(self._toggle_clip_range_popup)

        self.clip_start_input = TimecodeInput("미설정")
        start_tooltip = "시작시간이 --이면 처음부터 다운로드합니다."
        end_tooltip = "종료시간이 --이면 끝까지 다운로드합니다."
        self.clip_start_input.setToolTip(start_tooltip)
        self.clip_end_input = TimecodeInput("미설정")
        self.clip_end_input.setToolTip(end_tooltip)
        self.clip_start_input.editingComplete.connect(self._focus_clip_end_input)
        self.clip_start_input.textChanged.connect(self._clear_zero_zero_clip_range)
        self.clip_end_input.textChanged.connect(self._clear_zero_zero_clip_range)
        self.clip_start_input.textChanged.connect(self._clear_clip_range_apply_error)
        self.clip_end_input.textChanged.connect(self._clear_clip_range_apply_error)
        self._applied_clip_start_text = ""
        self._applied_clip_end_text = ""
        self._applied_clip_cut_mode = "fast"
        self._clip_range_apply_error = ""
        self.clip_cut_fast = OutlinedButton("빠른 컷")
        self.clip_cut_fast.setObjectName("CutModeButton")
        self.clip_cut_fast.setCheckable(True)
        self.clip_cut_fast.setChecked(True)
        self.clip_cut_fast.setCursor(Qt.PointingHandCursor)
        self.clip_cut_fast.setToolTip("재인코딩 없이 빠르게 저장합니다. 키프레임 간격에 따라 시작/종료 지점이 몇 초 정도 어긋날 수 있습니다.")
        self.clip_cut_accurate = OutlinedButton("정확 컷")
        self.clip_cut_accurate.setObjectName("CutModeButton")
        self.clip_cut_accurate.setCheckable(True)
        self.clip_cut_accurate.setCursor(Qt.PointingHandCursor)
        self.clip_cut_accurate.setToolTip("시작/종료 지점을 정확하게 맞춥니다. 재인코딩 때문에 느리고 CPU를 더 사용할 수 있습니다.")
        self.clip_cut_fast.clicked.connect(lambda: self._set_clip_cut_mode("fast"))
        self.clip_cut_accurate.clicked.connect(lambda: self._set_clip_cut_mode("accurate"))
        self._refresh_clip_cut_buttons()

        self.folder_input = PathDisplayInput(self._initial_save_folder())
        self.folder_input.editingFinished.connect(self._save_folder_from_input)
        self.folder_button = OutlinedButton("저장 위치")
        self.folder_button.setObjectName("SecondaryButton")
        self.folder_button.setFixedSize(88, TOP_FIELD_HEIGHT)
        self.folder_button.setCursor(Qt.PointingHandCursor)
        self.folder_button.setToolTip("저장 폴더 선택")
        self.folder_button.clicked.connect(self._choose_folder)
        folder_field = self._field_box("folder", self.folder_input)

        self.cookie_combo = CleanComboBox("cookie")
        self.cookie_combo.addItems(COOKIE_DISPLAY_CHOICES)
        self.cookie_combo.show_arrow = False
        self.cookie_combo.text_alignment = Qt.AlignCenter
        self.cookie_combo.setFixedHeight(TOP_FIELD_HEIGHT)
        self.cookie_combo.setMinimumWidth(126)
        self.cookie_combo.setMaximumWidth(132)
        self.cookie_combo.setToolTip(
            "로그인한 사이트의 영상이 안 보일 때만 사용하세요.\n"
            "선택한 브라우저의 로그인 세션을 읽어 접근 가능한 항목인지 확인합니다.\n"
            "비밀번호는 저장하지 않으며 권한 우회 기능은 제공하지 않습니다."
        )
        self._restore_cookie_source()
        self.cookie_combo.currentIndexChanged.connect(self._save_cookie_source)

        url_row = QHBoxLayout()
        url_row.setContentsMargins(0, 0, 0, 0)
        url_row.setSpacing(10)
        url_row.addWidget(url_field, 1)
        url_row.addWidget(self.clip_range_button)
        url_row.addWidget(self.primary_button)

        options_row = QHBoxLayout()
        options_row.setContentsMargins(0, 0, 0, 0)
        options_row.setSpacing(10)
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
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.count_label = QLabel("0개")
        self.count_label.setObjectName("CountChip")
        self.count_label.setAlignment(Qt.AlignCenter)

        self.select_toggle = QPushButton("")
        self.select_toggle.setObjectName("IconButton")
        self.select_toggle.setProperty("active", "false")
        self.select_toggle.setFixedSize(LIST_TOOL_HEIGHT, LIST_TOOL_HEIGHT)
        self.select_toggle.setIconSize(QSize(20, 20))
        self._refresh_select_toggle_icon()
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
        self.search_button = LucideIconButton("search", size=LIST_TOOL_HEIGHT, icon_size=20)
        self.search_button.setToolTip("제목 검색")
        self.search_button.clicked.connect(self._toggle_search)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("SearchInput")
        self.search_input.setPlaceholderText("제목 검색")
        self.search_input.setObjectName("BareInput")
        self.search_input_frame = RoundedFrame(radius=8, border_width=1.4, background=theme.SURFACE, border=theme.GRAPHITE)
        self.search_input_frame.setFixedHeight(LIST_TOOL_HEIGHT)
        self.search_input_frame.setMaximumWidth(0)
        self.search_input_frame.hide()
        search_frame_layout = QHBoxLayout(self.search_input_frame)
        search_frame_layout.setContentsMargins(10, 0, 10, 0)
        search_frame_layout.setSpacing(0)
        search_frame_layout.addWidget(self.search_input)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_input.installEventFilter(self)
        self.search_animation = QPropertyAnimation(self.search_input_frame, b"maximumWidth", self)
        self.search_animation.setDuration(180)
        self.search_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.sort_order_combo = CleanComboBox()
        self.sort_order_combo.setObjectName("CompactComboBox")
        self.sort_order_combo.setStyleSheet(
            "QComboBox#CompactComboBox { min-height: 36px; max-height: 36px; padding: 0px; border: none; }"
        )
        self.sort_order_combo.addItems(["다운로드순", "이름순"])
        self.sort_order_combo.setCurrentText(SORT_LABELS.get(self.sort_key, "다운로드순"))
        self.sort_order_combo.currentIndexChanged.connect(self._sort_changed)
        self.sort_order_combo.show_arrow = False
        self.sort_order_combo.text_alignment = Qt.AlignCenter
        self.sort_order_combo.setFixedSize(SORT_TOOL_WIDTH, LIST_TOOL_HEIGHT)
        self.sort_order_combo.setMinimumSize(SORT_TOOL_WIDTH, LIST_TOOL_HEIGHT)
        self.sort_order_combo.setMaximumSize(SORT_TOOL_WIDTH, LIST_TOOL_HEIGHT)
        self.sort_direction_button = LucideIconButton(self._sort_direction_icon(), size=LIST_TOOL_HEIGHT, icon_size=20)
        self.sort_direction_button.clicked.connect(self._toggle_sort_direction)
        self._refresh_sort_direction_button()
        self.preference_button = OutlinedButton("옵션")
        self.preference_button.setObjectName("SecondaryButton")
        self.preference_button.setFixedSize(LIST_TOOL_WIDTH, LIST_TOOL_HEIGHT)
        self.preference_button.setCursor(Qt.PointingHandCursor)
        self.preference_button.setToolTip("품질/포맷/코덱/병렬 설정")
        self.preference_button.clicked.connect(self._toggle_preferences_popup)
        header.addWidget(self.select_toggle, 0, Qt.AlignVCenter)
        header.addWidget(self.select_actions, 0, Qt.AlignVCenter)
        header.addStretch(1)
        header.addWidget(self.search_input_frame, 0, Qt.AlignVCenter)
        header.addWidget(self.search_button, 0, Qt.AlignVCenter)
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
        self.row_layout.setContentsMargins(0, 2, 0, 2)
        self.row_layout.setSpacing(5)
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

    def _save_folder_from_input(self):
        text = self.folder_input.text().strip()
        if text:
            self._set_save_folder(text)

    def _toggle_search(self):
        self._set_search_expanded(not self.search_input_frame.isVisible())

    def _set_search_expanded(self, expanded):
        expanded = bool(expanded)
        self.search_animation.stop()
        if expanded:
            self.search_input_frame.show()
            self.search_animation.setStartValue(self.search_input_frame.maximumWidth())
            self.search_animation.setEndValue(SEARCH_INPUT_WIDTH)
            self.search_animation.start()
            self.search_input.setFocus(Qt.MouseFocusReason)
            return
        self.search_input.clear()
        self.search_animation.setStartValue(self.search_input_frame.maximumWidth())
        self.search_animation.setEndValue(0)
        self.search_animation.finished.connect(self._hide_collapsed_search)
        self.search_animation.start()

    def _hide_collapsed_search(self):
        try:
            self.search_animation.finished.disconnect(self._hide_collapsed_search)
        except RuntimeError:
            pass
        if self.search_input_frame.maximumWidth() <= 0:
            self.search_input_frame.hide()

    def _on_search_text_changed(self, *_args):
        self._render_rows()

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
        fixed_has_clip_range = bool(row and row.get("fixed_candidate") and (candidate or {}).get("clip_range"))
        if row and not fixed_has_clip_range and row.get("download_base_candidate"):
            prepared = dict(row.get("download_base_candidate") or {})
        else:
            prepared = dict(candidate or {})
        key = str(prepared.get("_download_info_key") or "")
        cached_info = self._cached_download_info(key) if key else None
        if cached_info and engine.download_info_reuse_supported(prepared):
            prepared["_download_info"] = cached_info
        if not fixed_has_clip_range:
            prepared.pop("clip_range", None)
            prepared.pop("clip_cut_mode", None)
            clip_range = self.current_clip_range()
            if clip_range:
                prepared["clip_range"] = clip_range
                prepared["clip_cut_mode"] = self.clip_cut_mode()
        if prepared.get("clip_range"):
            if not prepared.get("clip_cut_mode"):
                prepared["clip_cut_mode"] = self.clip_cut_mode()
            self._validate_clip_range_against_duration(prepared)
            prepared = engine.candidate_with_clip_range_metadata(prepared)
        return prepared

    def _validate_clip_range_against_duration(self, candidate):
        clip_range = (candidate or {}).get("clip_range")
        if not isinstance(clip_range, dict):
            return
        duration = float(engine.safe_int((candidate or {}).get("source_duration") or (candidate or {}).get("duration")))
        if duration <= 0:
            return
        try:
            start = float(clip_range.get("start") or 0)
        except (TypeError, ValueError):
            return
        if start >= duration:
            raise ValueError(
                f"시작 시간이 영상 길이를 벗어났습니다: "
                f"시작 {engine.display_duration(start)} / 길이 {engine.display_duration(duration)}"
            )
        end = clip_range.get("end")
        if end is None:
            return
        try:
            end = float(end)
        except (TypeError, ValueError):
            return
        if end > duration:
            raise ValueError(
                f"종료 시간이 영상 길이를 벗어났습니다: "
                f"종료 {engine.display_duration(end)} / 길이 {engine.display_duration(duration)}"
            )

    def _apply_download_candidate_to_row(self, row, candidate):
        if not row or not candidate:
            return
        if not row.get("fixed_candidate") and not row.get("download_base_candidate"):
            existing = dict(row.get("candidate") or {})
            if not existing.get("clip_range"):
                row["download_base_candidate"] = existing
                row["download_base_qualities"] = list(row.get("qualities") or [])
                row["download_base_quality_options"] = list(row.get("quality_options") or [])
        prepared = dict(candidate)
        row["candidate"] = prepared
        row["qualities"] = [prepared]
        row["quality_options"] = build_quality_options([prepared])
        row["selected_index"] = 0
        row["selected_format_index"] = 0
        widget = row.get("widget")
        if widget:
            widget.refresh()

    def _time_input_text(self, widget):
        if hasattr(widget, "normalize_text"):
            widget.normalize_text()
        text = widget.text().strip().replace("_", "") if widget else ""
        return "" if not text.replace(":", "") else text

    def _set_clip_input_texts(self, start_text, end_text):
        self.clip_start_input.blockSignals(True)
        self.clip_end_input.blockSignals(True)
        try:
            self.clip_start_input.setText(start_text or "")
            self.clip_end_input.setText(end_text or "")
        finally:
            self.clip_start_input.blockSignals(False)
            self.clip_end_input.blockSignals(False)

    def _position_clip_range_popup(self, popup):
        popup.adjustSize()
        popup.setFixedWidth(max(252, popup.sizeHint().width()))
        popup.adjustSize()
        anchor = self.clip_range_button.mapToGlobal(QPoint(self.clip_range_button.width(), self.clip_range_button.height() + 6))
        x = anchor.x() - popup.width()
        y = anchor.y()
        screen = QApplication.screenAt(anchor) or self.screen()
        if screen:
            available = screen.availableGeometry()
            x = max(available.left() + 6, min(x, available.right() - popup.width() + 1))
            y = max(available.top() + 6, min(y, available.bottom() - popup.height() + 1))
        popup.move(QPoint(x, y))

    def _create_clip_range_popup(self):
        popup = ComboPopup(self.clip_range_button)
        popup.setStyleSheet(
            f"QLabel#ClipRangeLabel {{ color: {theme.GRAPHITE}; font-size: 16px; font-weight: 700; }}"
            f"QPushButton#SecondaryButton {{"
            f" background: {theme.SURFACE}; color: {theme.INK}; border: 1px solid {theme.GRAPHITE};"
            " border-radius: 8px; padding: 7px 12px; font-size: 13px; font-weight: 600;"
            f"}}"
            f"QPushButton#SecondaryButton:hover {{ background: {theme.SURFACE_SOFT}; border-color: {theme.GRAPHITE}; }}"
            f"QPushButton#CutModeButton {{"
            f" background: {theme.SURFACE}; color: {theme.INK}; border: 1px solid {theme.GRAPHITE};"
            " border-radius: 8px; padding: 7px 10px; font-size: 13px; font-weight: 700;"
            f"}}"
            f"QPushButton#CutModeButton:hover {{ background: {theme.SURFACE_SOFT}; border-color: {theme.GRAPHITE}; }}"
            f"QPushButton#CutModeButton[selected='true'] {{ background: {theme.INK}; color: {theme.ON_ACCENT}; border-color: {theme.INK}; }}"
        )
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        start_row, self.clip_start_label = self._build_clip_popup_time_row("시작시간", self.clip_start_input)
        end_row, self.clip_end_label = self._build_clip_popup_time_row("종료시간", self.clip_end_input)
        self.clip_start_label.setToolTip(self.clip_start_input.toolTip())
        self.clip_end_label.setToolTip(self.clip_end_input.toolTip())
        layout.addWidget(start_row)
        layout.addWidget(end_row)
        cut_row = QWidget()
        cut_layout = QHBoxLayout(cut_row)
        cut_layout.setContentsMargins(0, 0, 0, 0)
        cut_layout.setSpacing(10)
        cut_label = QLabel("컷 방식")
        cut_label.setObjectName("ClipRangeLabel")
        cut_label.setFixedWidth(74)
        cut_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.clip_cut_fast.setFixedSize(77, 34)
        self.clip_cut_accurate.setFixedSize(77, 34)
        cut_layout.addWidget(cut_label)
        cut_layout.addWidget(self.clip_cut_fast)
        cut_layout.addWidget(self.clip_cut_accurate)
        layout.addWidget(cut_row)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(10)
        reset_button = OutlinedButton("초기화")
        reset_button.setObjectName("SecondaryButton")
        reset_button.setFixedSize(77, 34)
        reset_button.setCursor(Qt.PointingHandCursor)
        reset_button.clicked.connect(self._reset_clip_range_inputs)
        apply_button = OutlinedButton("적용")
        apply_button.setObjectName("PrimaryPopupButton")
        apply_button.setFixedSize(77, 34)
        apply_button.setCursor(Qt.PointingHandCursor)
        apply_button.setDefault(True)
        apply_button.setAutoDefault(True)
        apply_button.clicked.connect(self._apply_clip_range_popup)
        buttons.addStretch(1)
        buttons.addWidget(reset_button)
        buttons.addWidget(apply_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        popup.installEventFilter(self)
        return popup

    def _refresh_clip_cut_buttons(self):
        if not hasattr(self, "clip_cut_fast"):
            return
        for button in (self.clip_cut_fast, self.clip_cut_accurate):
            button.setProperty("selected", "true" if button.isChecked() else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    def _set_clip_cut_mode(self, mode):
        accurate = str(mode or "").lower() == "accurate"
        self.clip_cut_fast.blockSignals(True)
        self.clip_cut_accurate.blockSignals(True)
        try:
            self.clip_cut_fast.setChecked(not accurate)
            self.clip_cut_accurate.setChecked(accurate)
        finally:
            self.clip_cut_fast.blockSignals(False)
            self.clip_cut_accurate.blockSignals(False)
        self._refresh_clip_cut_buttons()

    def _draft_clip_cut_mode(self):
        return "accurate" if getattr(self, "clip_cut_accurate", None) and self.clip_cut_accurate.isChecked() else "fast"

    def clip_cut_mode(self):
        return "accurate" if getattr(self, "_applied_clip_cut_mode", "fast") == "accurate" else "fast"

    def _toggle_clip_range_popup(self):
        if getattr(self.clip_range_button, "_ignore_next_popup", False):
            self.clip_range_button._ignore_next_popup = False
            return
        popup = getattr(self, "clip_range_popup", None)
        if popup and popup.isVisible():
            popup.close()
            return
        if popup is None:
            popup = self._create_clip_range_popup()
            self.clip_range_popup = popup
        self._set_clip_input_texts(self._applied_clip_start_text, self._applied_clip_end_text)
        self._set_clip_cut_mode(self.clip_cut_mode())
        self._position_clip_range_popup(popup)
        popup.show()

    def _reset_clip_range_inputs(self):
        self.clip_start_input.clear()
        self.clip_end_input.clear()

    def _restore_clip_range_draft_from_applied(self):
        self._set_clip_input_texts(self._applied_clip_start_text, self._applied_clip_end_text)

    def _focus_clip_end_input(self):
        def focus_end():
            self.clip_start_input.clearFocus()
            self.clip_end_input.setFocus(Qt.TabFocusReason)
            self.clip_end_input.set_selected_segment(0)

        QTimer.singleShot(0, focus_end)

    def _clear_clip_range_apply_error(self):
        self._clip_range_apply_error = ""

    def _apply_clip_range_popup(self):
        start_text = self._time_input_text(self.clip_start_input)
        end_text = self._time_input_text(self.clip_end_input)
        try:
            self._clip_range_from_texts(start_text, end_text)
        except ValueError as exc:
            self._clip_range_apply_error = str(exc)
            self._set_status(self._clip_range_apply_error)
            return
        self._clip_range_apply_error = ""
        if start_text and end_text and self._time_text_is_zero(start_text) and self._time_text_is_zero(end_text):
            start_text = ""
            end_text = ""
            self._set_clip_input_texts("", "")
        self._applied_clip_start_text = start_text
        self._applied_clip_end_text = end_text
        self._applied_clip_cut_mode = self._draft_clip_cut_mode()
        popup = getattr(self, "clip_range_popup", None)
        if popup:
            popup.close()

    def _reset_clip_range_on_url_change(self, text):
        current = str(text or "").strip()
        if current == self._clip_range_url_text:
            return
        self._clip_range_url_text = current
        if not (self.clip_start_input.text() or self.clip_end_input.text()):
            self._applied_clip_start_text = ""
            self._applied_clip_end_text = ""
            self._clip_range_apply_error = ""
            return
        self._applied_clip_start_text = ""
        self._applied_clip_end_text = ""
        self._clip_range_apply_error = ""
        self.clip_start_input.blockSignals(True)
        self.clip_end_input.blockSignals(True)
        try:
            self.clip_start_input.clear()
            self.clip_end_input.clear()
        finally:
            self.clip_start_input.blockSignals(False)
            self.clip_end_input.blockSignals(False)

    def _time_text_is_zero(self, text):
        text = (text or "").strip().replace("_", "")
        if not text or not text.replace(":", ""):
            return False
        try:
            return engine.parse_timecode(text) == 0
        except ValueError:
            return False

    def _clear_zero_zero_clip_range(self):
        start_text = self._time_input_text(getattr(self, "clip_start_input", None))
        end_text = self._time_input_text(getattr(self, "clip_end_input", None))
        if not (start_text and end_text):
            return
        if not (self._time_text_is_zero(start_text) and self._time_text_is_zero(end_text)):
            return
        self.clip_start_input.blockSignals(True)
        self.clip_end_input.blockSignals(True)
        try:
            self.clip_start_input.clear()
            self.clip_end_input.clear()
        finally:
            self.clip_start_input.blockSignals(False)
            self.clip_end_input.blockSignals(False)

    def _validate_time_input_bounds(self, text):
        if not text:
            return
        parts = text.split(":")
        if len(parts) == 3:
            try:
                hours, minutes, seconds = (int(part or 0) for part in parts)
            except ValueError as exc:
                raise ValueError("구간 시간은 숫자로 입력하세요.") from exc
            if hours > 99 or minutes > 59 or seconds > 59:
                raise ValueError("구간 시간은 시 99, 분 59, 초 59 이하로 입력하세요.")

    def _clip_range_from_texts(self, start_text, end_text):
        self._validate_time_input_bounds(start_text)
        self._validate_time_input_bounds(end_text)
        if self._time_text_is_zero(start_text) and not end_text:
            return None
        if start_text and end_text and self._time_text_is_zero(start_text) and self._time_text_is_zero(end_text):
            return None
        return engine.normalize_clip_range(start_text, end_text)

    def current_clip_range(self):
        if self._clip_range_apply_error:
            raise ValueError(self._clip_range_apply_error)
        return self._clip_range_from_texts(self._applied_clip_start_text, self._applied_clip_end_text)

    def _show_clip_range_dialog(self, initial=None):
        dialog = QDialog(self)
        dialog.setWindowTitle("구간 다운로드")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        start = TimecodeInput("시작시간")
        end = TimecodeInput("종료시간")
        initial = initial or {}
        if initial.get("start") is not None:
            start_seconds = int(float(initial.get("start") or 0))
            start.set_time_parts(start_seconds // 3600, (start_seconds % 3600) // 60, start_seconds % 60)
        if initial.get("end") is not None:
            end_seconds = int(float(initial.get("end") or 0))
            end.set_time_parts(end_seconds // 3600, (end_seconds % 3600) // 60, end_seconds % 60)
        fields = QHBoxLayout()
        fields.addWidget(self._time_field_box(start))
        fields.addWidget(self._time_field_box(end))
        layout.addLayout(fields)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = OutlinedButton("취소")
        cancel.setObjectName("SecondaryButton")
        apply_button = OutlinedButton("다운로드")
        apply_button.setObjectName("PrimaryPopupButton")
        apply_button.setDefault(True)
        apply_button.setAutoDefault(True)
        buttons.addWidget(cancel)
        buttons.addWidget(apply_button)
        layout.addLayout(buttons)
        cancel.clicked.connect(dialog.reject)
        apply_button.clicked.connect(dialog.accept)
        if dialog.exec() != QDialog.Accepted:
            return None
        return engine.normalize_clip_range(self._time_input_text(start), self._time_input_text(end))

    def download_segment_for_row(self, row, clip_range=None):
        if row not in self.rows:
            return
        if row.get("kind") == "playlist" and not row.get("is_playlist_child"):
            self._set_status("재생목록 부모는 하위 항목에서 구간 추출을 선택하세요")
            return
        source_path = self._segment_extract_source_path(row) if hasattr(self, "_segment_extract_source_path") else None
        if not source_path:
            self._set_status("구간 추출할 로컬 파일이 없습니다")
            return
        candidate = self.selected_candidate_for_row_ref(row)
        if not candidate:
            self._set_status("구간 추출할 항목을 선택하세요")
            return
        if clip_range is None:
            try:
                clip_range = self._show_clip_range_dialog(self.current_clip_range())
            except ValueError as exc:
                self._set_status(str(exc))
                return
        if not clip_range:
            return
        prepared = dict(candidate)
        prepared["clip_range"] = engine.normalize_clip_range(clip_range.get("start"), clip_range.get("end"))
        prepared["clip_cut_mode"] = self.clip_cut_mode()
        prepared = engine.candidate_with_clip_range_metadata(prepared)
        created_order = self._next_row_sequence()
        new_row = {
            "id": f"{row.get('id') or 'row'}-segment-{created_order}",
            "kind": row.get("kind") or "video",
            "candidate": prepared,
            "qualities": [prepared],
            "quality_options": build_quality_options([prepared]),
            "selected_index": 0,
            "selected_format_index": 0,
            "analysis_source_url": row.get("analysis_source_url") or row.get("source_url") or prepared.get("source") or "",
            "source_url": row.get("source_url") or prepared.get("source") or prepared.get("url") or "",
            "input_url": row.get("input_url") or row.get("source_url") or "",
            "status": READY_STATUS,
            "status_detail": "",
            "progress": 0,
            "progress_text": "",
            "output_path": "",
            "messages": [],
            "created_order": created_order,
            "fixed_candidate": True,
            "parent_playlist_id": row.get("parent_playlist_id") or "",
            "is_playlist_child": bool(row.get("is_playlist_child")),
            "playlist_child_index": row.get("playlist_child_index") or 0,
            "playlist_key": row.get("playlist_key") or "",
        }
        new_row["local_segment_source_path"] = str(source_path)
        insert_at = self.rows.index(row) + 1
        self.rows.insert(insert_at, new_row)
        self._render_rows()
        self.start_download_for_row(new_row)

    def _start_analysis(self, auto_download=False):
        if self.analysis_thread and self.analysis_thread.isRunning():
            return

        url = self.url_input.text().strip()
        if not url:
            return
        url = self._resolve_playlist_choice_url(url)
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

    def _resolve_playlist_choice_url(self, url):
        url = str(url or "").strip()
        if not engine.needs_youtube_playlist_choice(url):
            return url
        chooser = self.playlist_choice_func or self._show_playlist_choice_dialog
        choice = chooser(url)
        if choice == "single":
            return engine.youtube_single_video_url(url)
        if choice == "playlist":
            return engine.youtube_playlist_url(url)
        return None

    def _show_playlist_choice_dialog(self, url):
        dialog = QDialog(self)
        dialog.setWindowTitle("다운로드 방식 선택")
        dialog.setModal(True)
        dialog.setMinimumWidth(380)
        choice = {"value": None}
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        title = QLabel("이 링크는 영상과 재생목록을 함께 가리켜요")
        title.setObjectName("SectionTitle")
        title.setWordWrap(True)
        detail = QLabel(str(url))
        detail.setObjectName("MetaText")
        detail.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(detail)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = OutlinedButton("취소")
        cancel.setObjectName("SecondaryButton")
        single = OutlinedButton("단일 영상")
        single.setObjectName("PrimaryPopupButton")
        playlist = OutlinedButton("재생목록")
        single.setDefault(True)
        single.setAutoDefault(True)

        def choose(value):
            choice["value"] = value
            dialog.accept()

        cancel.clicked.connect(dialog.reject)
        single.clicked.connect(lambda: choose("single"))
        playlist.clicked.connect(lambda: choose("playlist"))
        buttons.addWidget(cancel)
        buttons.addWidget(single)
        buttons.addWidget(playlist)
        layout.addLayout(buttons)
        if dialog.exec() != QDialog.Accepted:
            return None
        return choice["value"]

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
                row["status_detail"] = message
                row["progress_text"] = message
        self._set_status(f"{engine.classify_error(message)}: {message}")
        self._maybe_prompt_macos_cookie_permission(message)

    def _maybe_prompt_macos_cookie_permission(self, message):
        """On macOS, if a browser-cookie read failed (typically because the app
        lacks Full Disk Access), explain why and offer to open the settings pane."""
        if sys.platform != "darwin":
            return
        if getattr(self, "_cookie_permission_prompt_shown", False):
            return
        source = cookie_source_from_display(self.cookie_combo.currentText())
        if not engine.cookie_spec(source):
            return
        text = str(message or "").lower()
        if "cookie" not in text:
            return
        if not any(token in text for token in (
            "could not find", "database", "permission", "permitted", "decrypt",
            "blocked", "denied", "access", "errno", "could not copy", "operation not",
        )):
            return
        self._cookie_permission_prompt_shown = True
        self._show_macos_cookie_permission_dialog()

    def _show_macos_cookie_permission_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("쿠키 접근 권한 필요")
        dialog.setModal(True)
        dialog.setMinimumWidth(440)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        title = QLabel("로그인이 필요한 항목이에요")
        title.setObjectName("SectionTitle")
        title.setWordWrap(True)
        detail = QLabel(
            "비공개·로그인 전용 영상이나 재생목록은 브라우저의 로그인 쿠키가 필요해요.\n"
            "macOS에서는 ClipFlow가 브라우저 쿠키를 읽으려면 ‘전체 디스크 접근’ 권한이 있어야 합니다.\n\n"
            "‘전체 디스크 접근 열기’를 누르면 이 앱(터미널에서 실행했다면 ‘터미널’)이 목록에 자동으로 추가돼요. "
            "옆의 스위치만 켜고 다시 다운로드를 시도하세요."
        )
        detail.setObjectName("MetaText")
        detail.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(detail)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        later = OutlinedButton("나중에")
        later.setObjectName("SecondaryButton")
        later.setCursor(Qt.PointingHandCursor)
        open_button = OutlinedButton("전체 디스크 접근 열기")
        open_button.setObjectName("PrimaryPopupButton")
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.setDefault(True)
        open_button.setAutoDefault(True)
        later.clicked.connect(dialog.reject)
        open_button.clicked.connect(lambda: (self._open_full_disk_access_settings(), dialog.accept()))
        buttons.addWidget(later)
        buttons.addWidget(open_button)
        layout.addLayout(buttons)
        dialog.exec()

    def _open_full_disk_access_settings(self):
        # Touch Full-Disk-Access-protected paths first so macOS registers the
        # responsible app (this app, or the launching Terminal) in the Full Disk
        # Access list automatically — the user then only flips the switch.
        self._provoke_full_disk_access_registration()
        QDesktopServices.openUrl(QUrl("x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"))

    def _provoke_full_disk_access_registration(self):
        if sys.platform != "darwin":
            return
        home = os.path.expanduser("~")
        protected_paths = [
            os.path.join(home, "Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies"),
            os.path.join(home, "Library/Cookies/Cookies.binarycookies"),
            os.path.join(home, "Library/Safari/Bookmarks.plist"),
        ]
        for path in protected_paths:
            try:
                with open(path, "rb") as handle:
                    handle.read(1)
            except Exception:
                # A PermissionError here is exactly what makes macOS list this
                # app under Full Disk Access; other errors are harmless to ignore.
                continue

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
                    self.selected_row_index = -1
                    self._render_rows()
                    return
                self._update_playlist_rows(existing_parent, analysis, grouped_rows, source_url)
                self._sort_rows()
                self.selected_row_index = -1
                self._render_rows()
                return
            parent = self._playlist_parent_row_from_analysis(analysis, grouped_rows, source_url)
            children = self._playlist_child_rows_from_grouped(parent, grouped_rows, analysis, source_url)
            self.rows = [parent] + children + preserved_rows
            self._sort_rows()
            self.selected_row_index = -1
            self._render_rows()
            return
        new_rows = []
        for grouped_row in grouped_rows:
            new_row = self._video_row_from_grouped(grouped_row, analysis, source_url)
            existing = self._find_existing_video_row_for_analysis(new_row, source_url)
            if existing:
                self._refresh_existing_video_row_for_analysis(existing, new_row)
                if hasattr(self, "_next_row_sequence"):
                    existing["created_order"] = self._next_row_sequence()
                new_rows.append(existing)
            else:
                new_rows.append(new_row)
        reused_ids = {id(row) for row in new_rows}
        self.rows = new_rows + [row for row in preserved_rows if id(row) not in reused_ids]
        self._sort_rows()
        self.selected_row_index = -1
        self._render_rows()

    def _find_existing_video_row_for_analysis(self, new_row, source_url):
        target_key = self._video_duplicate_key(new_row, source_url, include_current_clip_range=True)
        if not target_key:
            return None
        for row in self.rows:
            if self._is_analysis_loading_row(row):
                continue
            if row.get("kind") == "playlist" and not row.get("is_playlist_child"):
                continue
            if self._video_duplicate_key(row, source_url, include_current_clip_range=False) == target_key:
                return row
        return None

    def _refresh_existing_video_row_for_analysis(self, existing, new_row):
        for key in ("analysis_source_url", "source_url", "input_url"):
            if new_row.get(key):
                existing[key] = new_row.get(key)
        if existing.get("status") in {COMPLETED_STATUS, DOWNLOAD_STATUS, WAITING_STATUS, PAUSED_STATUS}:
            return
        for key in ("candidate", "qualities", "quality_options", "selected_index", "selected_format_index"):
            existing[key] = new_row.get(key)
        existing["status"] = new_row.get("status", READY_STATUS)
        existing["status_detail"] = ""
        existing["progress"] = 0
        existing["progress_text"] = ""
        existing["messages"] = list(new_row.get("messages") or [])

    def _video_duplicate_key(self, row, source_url="", include_current_clip_range=False):
        candidate = dict(row.get("candidate") or {})
        if not candidate:
            return None
        if include_current_clip_range and not candidate.get("clip_range"):
            try:
                clip_range = self.current_clip_range()
            except ValueError:
                clip_range = None
            if clip_range:
                candidate["clip_range"] = clip_range
                candidate["clip_cut_mode"] = self.clip_cut_mode()
        url_key = self._video_duplicate_url_key(row, candidate, source_url)
        if not url_key:
            return None
        ext = str(candidate.get("output_ext") or candidate.get("ext") or self._preferred_output_ext()).strip().lower()
        clip_suffix = engine.clip_range_suffix(candidate.get("clip_range"))
        return (url_key, ext, clip_suffix)

    def _video_duplicate_url_key(self, row, candidate, source_url=""):
        values = [
            row.get("analysis_source_url"),
            row.get("source_url"),
            row.get("input_url"),
            source_url,
            candidate.get("webpage_url"),
            candidate.get("page_url"),
            candidate.get("source_url"),
            candidate.get("source"),
            candidate.get("url"),
        ]
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            if engine.is_youtube_url(text):
                return engine.youtube_single_video_url(text).strip()
            return text
        return ""

    def _should_preserve_existing_row(self, row):
        if self._is_analysis_loading_row(row):
            return False
        if row.get("status") in {COMPLETED_STATUS, DOWNLOAD_STATUS, WAITING_STATUS, PAUSED_STATUS}:
            return True
        return self._row_is_downloading(row) or row in self.queued_download_rows

    def _preferred_output_ext(self):
        output_ext = self.current_preferences().output_format
        if str(output_ext).casefold() == AUTO_LABEL.casefold():
            output_ext = DEFAULT_OUTPUT_EXT
        return str(output_ext or DEFAULT_OUTPUT_EXT).lower()

    def _row_is_visible(self, row):
        if not self._row_matches_search(row):
            return False
        if not row.get("is_playlist_child"):
            return True
        parent = self._parent_playlist_for_child(row)
        return bool(parent and parent.get("expanded"))

    def _row_matches_search(self, row):
        if not hasattr(self, "search_input"):
            return True
        query = self.search_input.text().strip().casefold()
        if not query:
            return True
        candidate = self.selected_candidate_for_row_ref(row) or row.get("candidate") or {}
        text_parts = [
            candidate.get("display_title"),
            candidate.get("title"),
            row.get("title"),
            row.get("playlist_title"),
        ]
        return query in " ".join(str(part or "") for part in text_parts).casefold()

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
            if row and (row.get("download_cancel_requested") or row.get("status") == PAUSED_STATUS):
                return
            percent = max(0, min(100, int(float(event.get("percent") or 0))))
            text = self._progress_text(percent, event)
            if row and row.get("download_starting"):
                row["download_starting"] = False
                if widget:
                    widget.set_status(DOWNLOAD_STATUS)
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
                if row and row.get("download_starting") and widget:
                    widget.set_progress(0, engine.compact_text(message, 48))
                self._append_event_message(message)
        elif event_type in {"log", "done"}:
            if message:
                if row and row.get("download_starting") and event_type == "log" and widget:
                    widget.set_progress(0, engine.compact_text(message, 48))
                self._append_event_message(message)

    def _progress_text(self, percent, event):
        if isinstance(event, dict):
            message = str(event.get("message") or "").strip()
            if "/s" in message:
                return self._progress_text_from_message(percent, message, event.get("eta_text") or "")
            speed = str(event.get("speed_text") or "").strip()
            eta = str(event.get("eta_text") or "").strip()
            if not speed:
                message = event.get("message") or ""
            else:
                text = f"{percent}% · {speed}"
                return f"{text} · ETA {eta}" if eta else text
        else:
            message = event
        return self._progress_text_from_message(percent, message, "")

    def _progress_text_from_message(self, percent, message, eta_text=""):
        parts = str(message or "").split()
        speed = ""
        for index, part in enumerate(parts):
            if "/s" in part:
                if index > 0 and parts[index - 1].replace(".", "", 1).isdigit():
                    speed = f"{parts[index - 1]} {part}"
                else:
                    speed = part
        text = f"{percent}%"
        if speed:
            text = f"{text} · {speed}"
        eta = str(eta_text or "").strip()
        if not eta and "ETA" in parts:
            eta_index = parts.index("ETA")
            if eta_index + 1 < len(parts):
                eta = parts[eta_index + 1]
        return f"{text} · ETA {eta}" if eta else text

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
    app._clipflow_sparkle_updater = start_sparkle_updater()
    window = ClipFlowWindow()
    window.show()

    if os.environ.get("CLIPFLOW_QT_SMOKE") == "1":
        QTimer.singleShot(0, lambda: (print("ClipFlow smoke launch OK"), app.quit()))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
