import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QSettings, QSize, QStandardPaths, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
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
    from tools import clipflow_theme as theme
    from tools.clipflow_rows import DownloadRowWidget, build_quality_options, row_kind, row_source_url
    from tools.clipflow_theme import (
        APP_NAME, APP_STYLE, COOKIE_CHOICES, COOKIE_DISPLAY_CHOICES, DEFAULT_OUTPUT_EXT, PRIMARY_BUTTON_WIDTH,
        TOP_FIELD_HEIGHT, apply_tracking, configure_app_font, cookie_source_from_display, create_app_icon,
    )
    from tools.clipflow_icons import LucideIconButton, LucideIconWidget, TooltipManager, lucide_pixmap
    from tools.clipflow_widgets import CleanCheckBox, CleanComboBox, ClearingUrlInput, ComboPopup, PathDisplayInput, PrimaryActionButton
    from tools.clipflow_workers import AnalyzeWorker, DownloadWorker
    from tools.clipflow_dialogs import DeleteConfirmDialog, PreferencesDialog, _combo_text
    from tools.clipflow_playlist import PlaylistMixin
    from tools.clipflow_downloads import DownloadMixin
except ImportError:
    import candidate_presenter as presenter
    import downloader_engine as engine
    import clipflow_theme as theme
    from clipflow_rows import DownloadRowWidget, build_quality_options, row_kind, row_source_url
    from clipflow_theme import (
        APP_NAME, APP_STYLE, COOKIE_CHOICES, COOKIE_DISPLAY_CHOICES, DEFAULT_OUTPUT_EXT, PRIMARY_BUTTON_WIDTH,
        TOP_FIELD_HEIGHT, apply_tracking, configure_app_font, cookie_source_from_display, create_app_icon,
    )
    from clipflow_icons import LucideIconButton, LucideIconWidget, TooltipManager, lucide_pixmap
    from clipflow_widgets import CleanCheckBox, CleanComboBox, ClearingUrlInput, ComboPopup, PathDisplayInput, PrimaryActionButton
    from clipflow_workers import AnalyzeWorker, DownloadWorker
    from clipflow_dialogs import DeleteConfirmDialog, PreferencesDialog, _combo_text
    from clipflow_playlist import PlaylistMixin
    from clipflow_downloads import DownloadMixin

try:
    from tools.clipflow_theme import (
        ANALYZING_STATUS, AUTO_LABEL, COMPLETED_STATUS, COOKIE_DISPLAY_TO_SOURCE, COOKIE_SOURCE_TO_DISPLAY,
        DOWNLOAD_CONCURRENCY, DOWNLOAD_HISTORY_SETTING, DOWNLOAD_STATUS, ERROR_STATUS, PREF_CODEC_SETTING,
        PREF_FORMAT_SETTING, PREF_FRAME_SETTING, PREF_QUALITY_SETTING, PREFERENCE_DEFAULTS, READY_STATUS,
        SAVE_FOLDER_SETTING, SETTINGS_APP, SETTINGS_ORG, SORT_DESC_SETTING, SORT_KEY_SETTING, SORT_KEYS_BY_LABEL,
        SORT_LABELS, COOKIE_SOURCE_SETTING, WAITING_STATUS,
    )
except ImportError:
    from clipflow_theme import (
        ANALYZING_STATUS, AUTO_LABEL, COMPLETED_STATUS, COOKIE_DISPLAY_TO_SOURCE, COOKIE_SOURCE_TO_DISPLAY,
        DOWNLOAD_CONCURRENCY, DOWNLOAD_HISTORY_SETTING, DOWNLOAD_STATUS, ERROR_STATUS, PREF_CODEC_SETTING,
        PREF_FORMAT_SETTING, PREF_FRAME_SETTING, PREF_QUALITY_SETTING, PREFERENCE_DEFAULTS, READY_STATUS,
        SAVE_FOLDER_SETTING, SETTINGS_APP, SETTINGS_ORG, SORT_DESC_SETTING, SORT_KEY_SETTING, SORT_KEYS_BY_LABEL,
        SORT_LABELS, COOKIE_SOURCE_SETTING, WAITING_STATUS,
    )


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


class ClipFlowWindow(PlaylistMixin, DownloadMixin, QMainWindow):
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
        self.active_downloads = []
        self.queued_download_rows = []
        self.selected_row_index = -1
        self.select_mode = False
        self.event_messages = []
        self._clear_url_on_next_click = False
        self._row_sequence = 0
        self._analysis_auto_download = False
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
        self.primary_button.setIcon(QIcon(lucide_pixmap("download", 18, theme.ON_ACCENT)))
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
        title = QLabel("다운로드 목록")
        title.setObjectName("SectionTitle")
        apply_tracking(title, -0.2)
        self.count_label = QLabel("0개")
        self.count_label.setObjectName("CountChip")
        self.count_label.setAlignment(Qt.AlignCenter)

        self.select_checkbox = CleanCheckBox()
        self.select_checkbox.setObjectName("SelectToggle")
        self.select_checkbox.setCursor(Qt.PointingHandCursor)
        self.select_checkbox.setToolTip("선택 모드")
        self.select_checkbox.toggled.connect(self._toggle_select_mode)

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
        self.sort_label.setObjectName("MetaText")
        self.sort_label.setFixedHeight(TOP_FIELD_HEIGHT - 2)
        self.sort_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        self.sort_order_combo = CleanComboBox()
        self.sort_order_combo.addItems(["최신순", "이름순"])
        self.sort_order_combo.setCurrentText(SORT_LABELS.get(self.sort_key, "최신순"))
        self.sort_order_combo.currentIndexChanged.connect(self._sort_changed)
        self.sort_order_combo.show_arrow = False
        self.sort_order_combo.text_alignment = Qt.AlignCenter
        self.sort_order_combo.setMaximumWidth(120)
        self.sort_direction_button = LucideIconButton(self._sort_direction_icon(), size=40, icon_size=18)
        self.sort_direction_button.clicked.connect(self._toggle_sort_direction)
        self._refresh_sort_direction_button()
        self.preference_button = QPushButton("품질")
        self.preference_button.setObjectName("SecondaryButton")
        self.preference_button.setFixedSize(74, TOP_FIELD_HEIGHT - 2)
        self.preference_button.setCursor(Qt.PointingHandCursor)
        self.preference_button.setToolTip("품질/포맷/코덱/프레임 설정")
        self.preference_button.clicked.connect(self._toggle_preferences_popup)
        header.addWidget(title)
        header.addWidget(self.select_checkbox, 0, Qt.AlignVCenter)
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

    def _toggle_preferences_popup(self):
        popup = getattr(self, "preferences_popup", None)
        if popup and popup.isVisible():
            popup.close()
            popup.deleteLater()
            self.preferences_popup = None
            return
        preferences = self.current_preferences()
        popup = ComboPopup(self.preference_button)
        popup.setStyleSheet(
            f"QLabel#PreferencePopupLabel {{ color: {theme.MUTED}; font-size: 12px; font-weight: 600; }}"
        )
        layout = QGridLayout(popup)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        quality_combo = CleanComboBox()
        quality_combo.addItems(["자동", "2160p", "1440p", "1080p", "720p", "480p", "360p"])
        format_combo = CleanComboBox()
        format_combo.addItems(["자동", "MP4", "WEBM", "MP3", "WAV", "AAC"])
        codec_combo = CleanComboBox()
        codec_combo.addItems(["자동", "H264", "H265", "AV1", "VP9"])
        frame_combo = CleanComboBox()
        frame_combo.addItems(["자동", "60fps", "30fps"])
        quality_combo.setCurrentText(preferences.quality)
        format_combo.setCurrentText(preferences.output_format)
        codec_combo.setCurrentText(preferences.codec)
        frame_combo.setCurrentText(preferences.frame_rate)

        def refresh_controls():
            audio_format = format_combo.currentText().strip().lower() in presenter.AUDIO_FORMATS
            codec_combo.setEnabled(not audio_format)
            frame_combo.setEnabled(not audio_format)

        def apply_preferences(*_args):
            refresh_controls()
            self._set_preferences(
                quality=_combo_text(quality_combo),
                output_format=_combo_text(format_combo),
                codec=_combo_text(codec_combo),
                frame_rate=_combo_text(frame_combo),
            )

        for row, (label_text, combo) in enumerate(
            (
                ("품질", quality_combo),
                ("포맷", format_combo),
                ("코덱", codec_combo),
                ("프레임", frame_combo),
            )
        ):
            label = QLabel(label_text)
            label.setObjectName("PreferencePopupLabel")
            layout.addWidget(label, row, 0)
            layout.addWidget(combo, row, 1)
            combo.currentIndexChanged.connect(apply_preferences)

        refresh_controls()
        popup.adjustSize()
        popup.setFixedWidth(max(260, popup.sizeHint().width()))
        popup.adjustSize()
        anchor = self.preference_button.mapToGlobal(QPoint(self.preference_button.width(), self.preference_button.height() + 6))
        x = anchor.x() - popup.width()
        y = anchor.y()
        screen = QApplication.screenAt(anchor) or self.screen()
        if screen:
            available = screen.availableGeometry()
            x = max(available.left() + 6, min(x, available.right() - popup.width() + 1))
            y = max(available.top() + 6, min(y, available.bottom() - popup.height() + 1))
        popup.move(QPoint(x, y))
        popup.destroyed.connect(lambda *_args: setattr(self, "preferences_popup", None))
        self.preferences_popup = popup
        popup.show()

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
        rows = self._dedupe_playlist_parent_rows(list(self.rows))
        for row in rows:
            include_playlist_parent = False
            if row.get("kind") == "playlist":
                children = [child for child in rows if child.get("parent_playlist_id") == row.get("id")]
                include_playlist_parent = any(child.get("status") == COMPLETED_STATUS for child in children)
                if include_playlist_parent:
                    self._refresh_playlist_parent_metadata(row)
            if row.get("status") != COMPLETED_STATUS and not include_playlist_parent:
                continue
            candidate = row.get("candidate") or {}
            payload.append(
                {
                    "candidate": self._json_ready(candidate),
                    "source_url": row.get("source_url") or "",
                    "analysis_source_url": row.get("analysis_source_url") or "",
                    "playlist_key": self._playlist_group_key_for_row(row) if row.get("kind") == "playlist" else row.get("playlist_key") or "",
                    "parent_playlist_id": row.get("parent_playlist_id") or "",
                    "is_playlist_child": bool(row.get("is_playlist_child")),
                    "playlist_child_index": int(row.get("playlist_child_index") or 0),
                    "expanded": bool(row.get("expanded", True)),
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
            playlist_key = item.get("playlist_key") or self._playlist_key(
                item.get("analysis_source_url") or source_url
            )
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
                    "playlist_key": playlist_key,
                    "parent_playlist_id": item.get("parent_playlist_id") or "",
                    "is_playlist_child": bool(item.get("is_playlist_child")),
                    "playlist_child_index": engine.safe_int(item.get("playlist_child_index")),
                    "expanded": bool(item.get("expanded", True)),
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
            repaired_missing_parents = self._restore_missing_playlist_parents(restored)
            restored = self._dedupe_playlist_parent_rows(restored)
            self._attach_restored_playlist_children(restored)
            restored = self._dedupe_playlist_parent_rows(restored)
            self.rows = restored + self.rows
            self._render_rows()
            if repaired_missing_parents:
                self._save_completed_history()

    def _restore_missing_playlist_parents(self, rows):
        existing_ids = {row.get("id") for row in rows if row.get("kind") == "playlist"}
        missing_groups = {}
        for row in rows:
            parent_id = row.get("parent_playlist_id")
            if not row.get("is_playlist_child") or not parent_id or parent_id in existing_ids:
                continue
            missing_groups.setdefault(parent_id, []).append(row)
        repaired = False
        for parent_id, children in missing_groups.items():
            key = next((child.get("playlist_key") for child in children if child.get("playlist_key")), "")
            output_dirs = []
            for child in children:
                output_path = child.get("output_path") or ""
                if output_path:
                    output_dirs.append(Path(output_path).expanduser().parent)
            common_dir = output_dirs[0] if output_dirs and all(path == output_dirs[0] for path in output_dirs) else None
            title = common_dir.name if common_dir else "재생목록"
            source_url = key if str(key).startswith(("http://", "https://")) else ""
            preferred_ext = self._preferred_output_ext()
            candidate = {
                "id": parent_id,
                "media_type": "playlist",
                "format_selector": "bestvideo*+bestaudio/best",
                "title": title,
                "display_title": title,
                "thumbnail": (children[0].get("candidate") or {}).get("thumbnail") or "",
                "duration": sum(engine.safe_int((child.get("candidate") or {}).get("duration")) for child in children),
                "sort_bytes": sum(engine.safe_int((child.get("candidate") or {}).get("sort_bytes")) for child in children),
                "item_count": len(children),
                "playlist_count": len(children),
                "source": source_url,
                "url": source_url,
                "webpage_url": source_url,
                "output_ext": preferred_ext,
                "ext": preferred_ext,
            }
            created_orders = [engine.safe_int(child.get("created_order")) for child in children]
            created_order = max(0, min(order for order in created_orders if order) - 1) if any(created_orders) else self._next_row_sequence()
            rows.append(
                {
                    "id": parent_id,
                    "kind": "playlist",
                    "candidate": candidate,
                    "qualities": [candidate],
                    "quality_options": build_quality_options([candidate]),
                    "selected_index": 0,
                    "selected_format_index": 0,
                    "analysis_source_url": source_url,
                    "source_url": source_url,
                    "playlist_key": key,
                    "parent_playlist_id": "",
                    "is_playlist_child": False,
                    "playlist_child_index": 0,
                    "expanded": True,
                    "status": COMPLETED_STATUS,
                    "status_detail": "",
                    "progress": 100,
                    "progress_text": "",
                    "output_path": "",
                    "messages": [],
                    "created_order": created_order,
                    "playlist_entries": [
                        {"candidate": child.get("candidate") or {}, "qualities": child.get("qualities") or []}
                        for child in children
                    ],
                }
            )
            repaired = True
        return repaired

    def _attach_restored_playlist_children(self, rows):
        parents_by_key = {}
        for row in rows:
            if row.get("kind") != "playlist":
                continue
            key = self._playlist_key_for_row(row)
            if key and key not in parents_by_key:
                parents_by_key[key] = row
        child_counts = {}
        for row in rows:
            if row.get("kind") == "playlist" or row.get("is_playlist_child"):
                continue
            key = self._playlist_key_for_row(row)
            parent = parents_by_key.get(key)
            if not parent:
                continue
            parent_id = parent.get("id")
            child_counts[parent_id] = child_counts.get(parent_id, 0) + 1
            row["parent_playlist_id"] = parent_id
            row["is_playlist_child"] = True
            row["playlist_child_index"] = child_counts[parent_id]
            row["playlist_key"] = key

    def _handle_primary_action(self):
        if self.analysis_thread and self.analysis_thread.isRunning():
            return
        current_url = self.url_input.text().strip()
        if current_url:
            row_index = self._first_visible_analyzed_row_index_for_url(current_url)
            if row_index < 0:
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

    def _start_analysis(self, auto_download=False):
        if self.analysis_thread and self.analysis_thread.isRunning():
            return

        url = self.url_input.text().strip()
        if not url:
            return

        self.analysis = None
        self.selected_row_index = -1
        self._analysis_auto_download = bool(auto_download)
        self._playlist_event_candidates = []
        self._playlist_event_parent_id = ""
        self.primary_button.setEnabled(False)
        self.primary_button.set_loading(False)
        self._set_status(ANALYZING_STATUS)

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

    def _playlist_parent_loading_row(self, url):
        created_order = self._next_row_sequence()
        parent_id = f"playlist-loading-{created_order}"
        candidate = self._placeholder_candidate(url)
        candidate.update(
            {
                "id": parent_id,
                "media_type": "playlist",
                "format_selector": "bestvideo*+bestaudio/best",
                "item_count": 0,
                "playlist_count": 0,
                "source": url,
                "webpage_url": url,
            }
        )
        return {
            "id": parent_id,
            "kind": "playlist",
            "candidate": candidate,
            "qualities": [candidate],
            "quality_options": build_quality_options([candidate]),
            "selected_index": 0,
            "selected_format_index": 0,
            "analysis_source_url": url,
            "source_url": url,
            "input_url": url,
            "status": READY_STATUS,
            "status_detail": "",
            "progress": 0,
            "progress_text": "",
            "output_path": "",
            "messages": [],
            "created_order": created_order,
            "playlist_entries": [],
            "expanded": True,
            "analysis_loading": True,
        }

    def _playlist_child_loading_row(self, parent_id, url):
        return {
            "id": f"{parent_id}-loading",
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
            "parent_playlist_id": parent_id,
            "is_playlist_child": True,
            "child_loading": True,
            "analysis_loading": True,
            "playlist_child_index": 0,
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
        grouped = presenter.group_candidates(analysis.get("candidates") or [])
        source_url = analysis.get("webpage_url") or analysis.get("url") or self.url_input.text().strip()
        self._prepend_analysis_rows(analysis, grouped, source_url)
        self._clear_url_on_next_click = False
        self._set_status(f"분석 완료: {len(grouped)}개")
        self._refresh_footer()
        for warning in analysis.get("warnings") or []:
            self.event_messages.append(str(warning))
        if self._analysis_auto_download and self.rows:
            self._analysis_auto_download = False
            row_index = self._first_visible_analyzed_row_index_for_url(source_url)
            self.selected_row_index = row_index if row_index >= 0 else 0
            self._refresh_row_selection()
            QTimer.singleShot(0, self._start_download)

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
        if any(self._is_analysis_loading_row(row) for row in self.rows):
            self.rows = [row for row in self.rows if not self._is_analysis_loading_row(row)]
            if self.selected_row_index >= len(self.rows):
                self.selected_row_index = len(self.rows) - 1
            self._render_rows()
        self._refresh_primary_action()

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

    def _playlist_parent_row_from_analysis(self, analysis, grouped_rows, source_url, parent_id=None):
        created_order = self._next_row_sequence()
        parent_id = parent_id or f"playlist-{created_order}"
        playlist_candidate = self._playlist_candidate_from_analysis(analysis, grouped_rows, source_url)
        playlist_candidate["id"] = parent_id
        return {
            "id": parent_id,
            "kind": "playlist",
            "candidate": playlist_candidate,
            "qualities": [playlist_candidate],
            "quality_options": build_quality_options([playlist_candidate]),
            "selected_index": 0,
            "selected_format_index": 0,
            "analysis_source_url": source_url,
            "source_url": source_url,
            "input_url": analysis.get("url") or source_url,
            "status": READY_STATUS,
            "status_detail": "",
            "progress": 0,
            "progress_text": "",
            "output_path": "",
            "messages": [],
            "created_order": created_order,
            "playlist_entries": grouped_rows,
            "expanded": True,
            "playlist_key": self._playlist_key(analysis.get("url") or source_url),
        }

    def _playlist_child_rows_from_grouped(self, parent, grouped_rows, analysis, source_url):
        children = []
        for index, grouped_row in enumerate(grouped_rows, start=1):
            child = self._video_row_from_grouped(grouped_row, analysis, source_url)
            child["id"] = f"{parent['id']}-child-{index}"
            child["parent_playlist_id"] = parent["id"]
            child["is_playlist_child"] = True
            child["playlist_child_index"] = index
            child["playlist_key"] = parent.get("playlist_key")
            child["source_url"] = row_source_url(analysis, child.get("candidate") or {}) or child.get("source_url") or source_url
            children.append(child)
        return children

    def _find_playlist_parent_for_analysis(self, analysis, source_url):
        return self._find_playlist_parent_for_url(analysis.get("url") or source_url)

    def _find_playlist_parent_for_url(self, url):
        key = self._playlist_key(url)
        if not key:
            return None
        for row in self.rows:
            if row.get("kind") == "playlist" and self._playlist_key_for_row(row) == key:
                return row
        return None

    def _update_playlist_rows(self, parent, analysis, grouped_rows, source_url):
        parent_id = parent.get("id")
        if not parent_id:
            return
        replacement = self._playlist_parent_row_from_analysis(analysis, grouped_rows, source_url, parent_id=parent_id)
        replacement["created_order"] = parent.get("created_order") or replacement.get("created_order")
        replacement["expanded"] = parent.get("expanded", True)
        parent.clear()
        parent.update(replacement)
        existing_children = {
            self._row_media_identity(row): row
            for row in self.rows
            if row.get("parent_playlist_id") == parent_id
        }
        children = []
        for child in self._playlist_child_rows_from_grouped(parent, grouped_rows, analysis, source_url):
            existing = existing_children.get(self._row_media_identity(child))
            if existing:
                child["id"] = existing.get("id") or child.get("id")
                child["created_order"] = existing.get("created_order") or child.get("created_order")
                if existing.get("status") in {COMPLETED_STATUS, DOWNLOAD_STATUS, WAITING_STATUS}:
                    for key in ("status", "status_detail", "progress", "progress_text", "output_path", "messages", "download_started_at"):
                        child[key] = existing.get(key, child.get(key))
                child["widget"] = existing.get("widget")
            children.append(child)
        self.rows = [row for row in self.rows if row.get("parent_playlist_id") != parent_id]
        insert_index = self.rows.index(parent) + 1 if parent in self.rows else 0
        for child in reversed(children):
            self.rows.insert(insert_index, child)

    def _finalize_progressive_playlist_rows(self, parent, analysis, grouped_rows, source_url):
        parent_id = parent.get("id")
        if not parent_id:
            return
        replacement = self._playlist_parent_row_from_analysis(analysis, grouped_rows, source_url, parent_id=parent_id)
        replacement["created_order"] = parent.get("created_order") or replacement.get("created_order")
        replacement["expanded"] = parent.get("expanded", True)
        replacement["widget"] = parent.get("widget")
        replacement["render_widget"] = parent.get("render_widget")
        parent.clear()
        parent.update(replacement)
        parent["analysis_loading"] = False
        self.rows = [
            row
            for row in self.rows
            if not (row.get("parent_playlist_id") == parent_id and row.get("child_loading"))
        ]
        self._refresh_playlist_parent_status(parent)

    def _row_media_identity(self, row):
        candidate = row.get("candidate") or {}
        return (
            candidate.get("source")
            or candidate.get("webpage_url")
            or candidate.get("url")
            or row.get("source_url")
            or row.get("id")
            or ""
        )

    def _video_row_from_grouped(self, grouped_row, analysis, source_url):
        candidate = grouped_row["candidate"]
        return {
            "id": grouped_row.get("id"),
            "kind": row_kind(candidate),
            "candidate": candidate,
            "qualities": grouped_row["qualities"],
            "quality_options": build_quality_options(grouped_row["qualities"]),
            "selected_index": 0,
            "selected_format_index": 0,
            "analysis_source_url": source_url,
            "source_url": source_url or row_source_url(analysis, candidate),
            "input_url": analysis.get("url") or source_url,
            "status": READY_STATUS,
            "status_detail": "",
            "progress": 0,
            "progress_text": "",
            "output_path": "",
            "messages": [],
            "created_order": self._next_row_sequence(),
        }

    def _should_preserve_existing_row(self, row):
        if self._is_analysis_loading_row(row):
            return False
        if row.get("status") in {COMPLETED_STATUS, DOWNLOAD_STATUS, WAITING_STATUS}:
            return True
        return self._row_is_downloading(row) or row in self.queued_download_rows

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
            "output_ext": self._preferred_output_ext(),
            "ext": self._preferred_output_ext(),
        }

    def _refresh_playlist_parent_metadata(self, parent):
        if not parent or parent.get("kind") != "playlist":
            return
        candidate = parent.get("candidate") or {}
        children = [
            row
            for row in self._playlist_children_for_parent(parent)
            if not row.get("child_loading")
        ]
        count = len(children)
        if parent.get("analysis_loading"):
            expected = engine.safe_int(candidate.get("playlist_count") or candidate.get("item_count"))
            count = max(count, expected)
        candidate["duration"] = sum(engine.safe_int((child.get("candidate") or {}).get("duration")) for child in children)
        candidate["sort_bytes"] = sum(engine.safe_int((child.get("candidate") or {}).get("sort_bytes")) for child in children)
        candidate["item_count"] = count
        candidate["playlist_count"] = count
        parent["playlist_entries"] = [
            {"candidate": child.get("candidate") or {}, "qualities": child.get("qualities") or []}
            for child in children
        ]

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

    def _parent_playlist_for_child(self, child_row):
        parent_id = child_row.get("parent_playlist_id")
        if not parent_id:
            return None
        for row in self.rows:
            if row.get("id") == parent_id:
                return row
        return None

    def _visible_rows(self):
        return [row for row in self.rows if self._row_is_visible(row)]

    def _render_rows(self):
        self._sort_rows()
        row_widgets = []
        for row in self.rows:
            widget = row.get("widget")
            if widget is None:
                widget = DownloadRowWidget(self, row)
                row["widget"] = widget
            else:
                widget.refresh()
            widget.set_select_mode(self.select_mode)
            render_widget = self._row_render_widget(row, widget)
            row_widgets.append((row, widget, render_widget))

        expected_widgets = {render_widget for _row, _widget, render_widget in row_widgets}
        existing_widgets = []
        for index in range(self.row_layout.count() - 1):
            item = self.row_layout.itemAt(index)
            widget = item.widget() if item else None
            if widget:
                existing_widgets.append(widget)
        for widget in existing_widgets:
            if widget in expected_widgets:
                continue
            self.row_layout.removeWidget(widget)
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()

        for index, (row, widget, render_widget) in enumerate(row_widgets):
            current_index = self.row_layout.indexOf(render_widget)
            if current_index != index:
                if current_index >= 0:
                    self.row_layout.removeWidget(render_widget)
                self.row_layout.insertWidget(index, render_widget)
            visible = self._row_is_visible(row)
            render_widget.setVisible(visible)
            widget.setVisible(visible)
        visible_rows = self._visible_rows()
        self.count_label.setText(f"{len(self.rows)}개")
        if hasattr(self, "empty_state"):
            self.empty_state.setGeometry(self.scroll_area.viewport().rect())
            self.empty_state.setVisible(not visible_rows)
            if not visible_rows:
                self.empty_state.raise_()
        self._refresh_footer()
        self._refresh_row_selection()
        self._refresh_primary_action()
        self._refresh_playlist_float_button()
        self._refresh_scrollbar_activity()

    def _refresh_scrollbar_activity(self, *_args):
        if not hasattr(self, "scroll_area"):
            return
        bar = self.scroll_area.verticalScrollBar()
        scrollable = "true" if bar.maximum() > bar.minimum() else "false"
        if bar.property("scrollable") == scrollable:
            return
        bar.setProperty("scrollable", scrollable)
        bar.style().unpolish(bar)
        bar.style().polish(bar)
        bar.update()

    def _row_render_widget(self, row, widget):
        if not row.get("is_playlist_child"):
            row["render_widget"] = widget
            return widget
        container = row.get("render_widget")
        if container is None or container is widget:
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(28, 0, 0, 0)
            layout.setSpacing(0)
            layout.addWidget(widget)
            row["render_widget"] = container
        return container

    def playlist_expansion_changed(self, row):
        self._sync_row_layout_geometry()
        before_top = self._row_viewport_top(row)
        if isinstance(row, dict) and not row.get("expanded"):
            selected = self.rows[self.selected_row_index] if 0 <= self.selected_row_index < len(self.rows) else None
            if selected and selected.get("parent_playlist_id") == row.get("id"):
                self.selected_row_index = self.rows.index(row)
        if self._playlist_parent_needs_child_analysis(row):
            source_url = self._playlist_source_url(row)
            row["expanded"] = True
            self.url_input.setText(source_url)
            self._start_analysis(auto_download=False)
            return
        if self._set_playlist_child_visibility(row):
            self._sync_row_layout_geometry()
            self._refresh_footer()
            self._refresh_row_selection()
            self._refresh_primary_action()
            self._refresh_playlist_float_button()
        else:
            self._render_rows()
        self._restore_row_viewport_top(row, before_top)
        QTimer.singleShot(0, self._refresh_playlist_float_button)

    def _playlist_parent_needs_child_analysis(self, row):
        if not isinstance(row, dict) or row.get("kind") != "playlist":
            return False
        if row.get("analysis_loading") or self.analysis_thread:
            return False
        if self._playlist_children_for_parent(row):
            return False
        return bool(self._playlist_source_url(row))

    def _playlist_source_url(self, row):
        if not isinstance(row, dict):
            return ""
        candidate = row.get("candidate") or {}
        return str(
            row.get("analysis_source_url")
            or row.get("source_url")
            or row.get("input_url")
            or candidate.get("webpage_url")
            or candidate.get("url")
            or candidate.get("source")
            or ""
        ).strip()

    def _set_playlist_child_visibility(self, row):
        if not isinstance(row, dict) or row.get("kind") != "playlist":
            return False
        children = self._playlist_children_for_parent(row)
        if not children:
            return True
        render_widgets = []
        for child in children:
            render_widget = child.get("render_widget") or child.get("widget")
            if render_widget is None or self.row_layout.indexOf(render_widget) < 0:
                return False
            render_widgets.append(render_widget)
        visible = bool(row.get("expanded"))
        for child, render_widget in zip(children, render_widgets):
            render_widget.setVisible(visible)
            widget = child.get("widget")
            if widget and widget is not render_widget:
                widget.setVisible(visible)
        return True

    def _sync_row_layout_geometry(self):
        if not hasattr(self, "row_layout") or not hasattr(self, "row_container"):
            return
        self.row_layout.activate()
        self.row_container.adjustSize()
        self.row_container.updateGeometry()

    def _row_viewport_top(self, row):
        widget = (row.get("render_widget") or row.get("widget")) if isinstance(row, dict) else None
        if not widget:
            return None
        return widget.mapTo(self.scroll_area.viewport(), QPoint(0, 0)).y()

    def _restore_row_viewport_top(self, row, before_top):
        if before_top is None:
            return
        after_top = self._row_viewport_top(row)
        if after_top is None:
            return
        delta = after_top - before_top
        if not delta:
            return
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(max(bar.minimum(), min(bar.maximum(), bar.value() + delta)))

    def _expanded_playlist_row(self):
        for row in self.rows:
            if row.get("kind") == "playlist" and row.get("expanded") and row.get("widget"):
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
            parent_bottom = top + widget.height()
            bottom = parent_bottom
            child_widgets = [
                child.get("widget")
                for child in self.rows
                if child.get("parent_playlist_id") == row.get("id") and child.get("widget")
            ]
            for child_widget in child_widgets:
                child_top = child_widget.mapTo(self.scroll_area.viewport(), QPoint(0, 0)).y()
                bottom = max(bottom, child_top + child_widget.height())
            visible = parent_bottom <= 0 and bottom > 0
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
        self._render_rows()
        self._scroll_row_to_top(row)
        self._refresh_playlist_float_button()

    def _next_row_sequence(self):
        self._row_sequence += 1
        return self._row_sequence

    def _sort_rows(self):
        reverse = bool(self.sort_desc)
        top_rows = []
        child_rows = []
        parent_ids = set()
        for row in self.rows:
            if row.get("is_playlist_child"):
                child_rows.append(row)
            else:
                top_rows.append(row)
                parent_ids.add(row.get("id"))
        attached_children = {parent_id: [] for parent_id in parent_ids}
        orphan_children = []
        for row in child_rows:
            parent_id = row.get("parent_playlist_id")
            if parent_id in attached_children:
                attached_children[parent_id].append(row)
            else:
                orphan_children.append(row)
        top_rows.extend(orphan_children)
        if self.sort_key == "name":
            top_rows.sort(key=lambda row: self._row_sort_name(row), reverse=reverse)
        else:
            top_rows.sort(key=lambda row: int(row.get("created_order") or 0), reverse=reverse)
        sorted_rows = []
        for row in top_rows:
            sorted_rows.append(row)
            children = attached_children.get(row.get("id")) or []
            children.sort(key=lambda child: (int(child.get("playlist_child_index") or 0), int(child.get("created_order") or 0)))
            sorted_rows.extend(children)
        self.rows = sorted_rows

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
            if str(output_format).casefold() == AUTO_LABEL.casefold():
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
                self.event_messages.append(message)
        elif event_type in {"log", "done", "file"} and message:
            self.event_messages.append(message)

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
            text = self._progress_text(percent, message)
            if widget:
                widget.set_status("다운로드 중")
                widget.set_progress(percent, text)
            if hasattr(self, "status_label"):
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
        reveal_target = None
        open_target = None
        if row.get("kind") == "playlist":
            candidate = row.get("candidate") or {}
            playlist_folder = engine.output_dir_for_candidate(candidate, self.folder_input.text())
            if playlist_folder.exists():
                reveal_target = playlist_folder
            else:
                open_target = self._first_playlist_output_parent(row) or Path(self.folder_input.text()).expanduser()
        else:
            saved_output = row.get("output_path") or ""
            output_path = Path(saved_output)
            if saved_output and output_path.exists():
                reveal_target = output_path
            else:
                candidate = self.selected_candidate_for_row_ref(row) or row.get("candidate") or {}
                existing_output = self._existing_output_path_for_row(row, candidate)
                reveal_target = existing_output if existing_output and existing_output.exists() else None
                open_target = Path(self.folder_input.text()).expanduser()
        if reveal_target:
            self._reveal_in_file_manager(reveal_target)
            return
        open_target = open_target or Path(self.folder_input.text()).expanduser()
        open_target.mkdir(parents=True, exist_ok=True)
        self._open_path(open_target)

    def _reveal_in_file_manager(self, path):
        path = Path(path)
        if sys.platform == "darwin":
            try:
                subprocess.run(["open", "-R", str(path)], check=False)
                return
            except Exception:
                pass
        if sys.platform.startswith("win") and path.exists():
            try:
                subprocess.Popen(["explorer.exe", f"/select,{path.resolve()}"])
                return
            except Exception:
                pass
        self._open_path(path.parent if path.is_file() else path)

    def _open_path(self, path):
        return QDesktopServices.openUrl(local_file_url(path))

    def _first_playlist_output_parent(self, row):
        for entry in row.get("playlist_entries") or []:
            child = entry if isinstance(entry, dict) else {}
            saved_output = child.get("output_path") or ""
            output_path = Path(saved_output)
            if saved_output and output_path.exists():
                return output_path.parent
            candidate = child.get("candidate") if isinstance(child.get("candidate"), dict) else None
            expected = engine.existing_output_path_for_candidate(candidate or {}, self.folder_input.text())
            if expected:
                return expected.parent
        return None

    def remove_row(self, row):
        if row.get("status") in {"분석 중", "다운로드 중"}:
            return
        if row in self.rows:
            index = self.rows.index(row)
            if row.get("kind") == "playlist":
                parent_id = row.get("id")
                self.rows = [
                    item for item in self.rows
                    if item is not row and item.get("parent_playlist_id") != parent_id
                ]
            else:
                self.rows.pop(index)
            if self.selected_row_index >= len(self.rows):
                self.selected_row_index = len(self.rows) - 1
            self._render_rows()
            self._save_completed_history()

    def _toggle_select_mode(self, checked):
        self.select_mode = bool(checked)
        self.select_actions.setVisible(self.select_mode)
        if not self.select_mode:
            for row in self.rows:
                row["checked"] = False
        for row in self.rows:
            widget = row.get("widget")
            if widget:
                widget.set_select_mode(self.select_mode)

    def on_row_check_changed(self):
        return

    def _select_all_rows(self):
        for row in self.rows:
            row["checked"] = True
            widget = row.get("widget")
            if widget:
                widget.set_select_mode(True)

    def _delete_selected_from_list(self):
        self._remove_selected(delete_files=False)

    def _delete_selected_files(self):
        self._remove_selected(delete_files=True)

    def _remove_selected(self, delete_files):
        removable = [
            row
            for row in self.rows
            if row.get("checked") and row.get("status") not in {"분석 중", "다운로드 중"}
        ]
        if not removable:
            self._set_status("선택된 항목이 없습니다")
            return
        if not self._confirm_selected(len(removable), delete_files):
            return
        if delete_files:
            for row in removable:
                output_path = Path(row.get("output_path") or "")
                if output_path.exists() and output_path.is_file():
                    try:
                        output_path.unlink()
                    except OSError:
                        pass
        keep = [row for row in self.rows if row not in removable]
        self.rows = keep
        if self.selected_row_index >= len(self.rows):
            self.selected_row_index = len(self.rows) - 1
        self._render_rows()
        self._save_completed_history()

    def _confirm_selected(self, count, delete_files):
        dialog = QDialog(self)
        dialog.setWindowTitle("파일 삭제" if delete_files else "목록에서 삭제")
        dialog.setModal(True)
        dialog.setMinimumWidth(360)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        if delete_files:
            message = f"선택한 {count}개 항목의 파일을 삭제할까요?"
            detail = "다운로드된 파일이 실제로 삭제되고 목록에서도 제거됩니다."
        else:
            message = f"선택한 {count}개 항목을 목록에서 삭제할까요?"
            detail = "파일은 삭제되지 않고 목록에서만 제거됩니다."
        title = QLabel(message)
        title.setObjectName("SectionTitle")
        title.setWordWrap(True)
        detail_label = QLabel(detail)
        detail_label.setObjectName("MetaText")
        detail_label.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(detail_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("취소")
        cancel.setObjectName("SecondaryButton")
        confirm = QPushButton("삭제")
        confirm.setObjectName("DangerButton" if delete_files else "")
        cancel.clicked.connect(dialog.reject)
        confirm.clicked.connect(dialog.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)
        return dialog.exec() == QDialog.Accepted

    def delete_file_for_row(self, row):
        if row.get("status") == "다운로드 중":
            return
        output_path = self._delete_target_for_row(row)
        if output_path is None:
            return
        if not output_path.exists():
            return
        confirmed = (
            self.confirm_delete_func(output_path)
            if self.confirm_delete_func
            else self._confirm_file_delete(output_path, row)
        )
        if not confirmed:
            return
        try:
            if row.get("kind") == "playlist":
                self._delete_playlist_output_files(row, output_path)
            elif output_path.is_dir():
                output_path.rmdir()
            else:
                output_path.unlink()
        except OSError as exc:
            QMessageBox.warning(self, "파일 삭제 실패", str(exc))
            return
        self._remove_rows_after_file_delete(row)
        self._save_completed_history()

    def _delete_target_for_row(self, row):
        if row.get("kind") == "playlist":
            return engine.output_dir_for_candidate(row.get("candidate") or {}, self.folder_input.text())
        saved_output = row.get("output_path") or ""
        if saved_output:
            return Path(saved_output)
        candidate = self.selected_candidate_for_row_ref(row) or row.get("candidate") or {}
        return self._existing_output_path_for_row(row, candidate)

    def _delete_playlist_output_files(self, row, playlist_dir):
        playlist_dir = Path(playlist_dir).expanduser()
        paths = []
        for child in self._playlist_children_for_parent(row):
            saved_output = child.get("output_path") or ""
            if saved_output:
                path = Path(saved_output).expanduser()
            else:
                path = engine.existing_output_path_for_candidate(child.get("candidate") or {}, playlist_dir)
            if path and path.exists() and path.is_file():
                try:
                    path.relative_to(playlist_dir)
                except ValueError:
                    continue
                paths.append(path)
        for path in dict.fromkeys(paths):
            path.unlink()
        save_folder = Path(self.folder_input.text()).expanduser().resolve()
        if playlist_dir.exists() and playlist_dir.resolve() != save_folder:
            try:
                playlist_dir.rmdir()
            except OSError:
                pass

    def _remove_rows_after_file_delete(self, row):
        if row.get("kind") == "playlist":
            parent_id = row.get("id")
            self.rows = [
                item for item in self.rows
                if item is not row and item.get("parent_playlist_id") != parent_id
            ]
        else:
            parent = self._parent_playlist_for_child(row)
            if row in self.rows:
                self.rows.remove(row)
            if parent:
                parent["playlist_entries"] = [
                    {"candidate": child.get("candidate") or {}, "qualities": child.get("qualities") or []}
                    for child in self._playlist_children_for_parent(parent)
                    if child is not row and not child.get("child_loading")
                ]
                self._refresh_playlist_parent_status(parent)
        if self.selected_row_index >= len(self.rows):
            self.selected_row_index = len(self.rows) - 1
        self._render_rows()

    def _create_delete_confirm_dialog(self, output_path, row=None):
        if row and row.get("kind") == "playlist":
            child_count = len([
                child
                for child in self._playlist_children_for_parent(row)
                if not child.get("child_loading")
            ])
            return DeleteConfirmDialog(
                output_path,
                self,
                title_text="재생목록을 삭제하시겠습니까?",
                detail_text=f"{output_path}\n하위 파일 {child_count}개도 함께 삭제됩니다.",
                window_title="재생목록 삭제",
            )
        return DeleteConfirmDialog(output_path, self)

    def _confirm_file_delete(self, output_path, row=None):
        dialog = self._create_delete_confirm_dialog(output_path, row)
        return dialog.exec() == QDialog.Accepted

    def _refresh_primary_action(self):
        self._refresh_url_trailing()
        has_target = 0 <= self.selected_row_index < len(self.rows) and self._row_is_visible(self.rows[self.selected_row_index])
        if has_target:
            has_target = self.rows[self.selected_row_index].get("status") != ANALYZING_STATUS
        has_url = bool(self.url_input.text().strip())
        analyzing = bool(self.analysis_thread and self.analysis_thread.isRunning())
        self.primary_button.setEnabled((has_target or has_url) and not analyzing)

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
