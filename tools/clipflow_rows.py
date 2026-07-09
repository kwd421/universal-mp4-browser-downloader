# Auto-split from clipflow_qt.py; keep behavior changes in focused commits.
import math
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from tools import downloader_engine as engine
    from tools import clipflow_theme as theme
    from tools.clipflow_icons import LucideIconButton, LucideIconWidget
    from tools.clipflow_theme import (
        ACTIONS_WIDTH,
        DURATION_WIDTH,
        MEDIA_MIN_WIDTH,
        ROW_COLUMN_SPACING,
        SIZE_WIDTH,
        THUMBNAIL_WIDTH,
    )
    from tools.clipflow_widgets import CleanCheckBox, MarqueeLabel, SourceLinkButton, Spinner, ThumbnailPlaceholder
except ImportError:
    import downloader_engine as engine
    import clipflow_theme as theme
    from clipflow_icons import LucideIconButton, LucideIconWidget
    from clipflow_theme import (
        ACTIONS_WIDTH,
        DURATION_WIDTH,
        MEDIA_MIN_WIDTH,
        ROW_COLUMN_SPACING,
        SIZE_WIDTH,
        THUMBNAIL_WIDTH,
    )
    from clipflow_widgets import CleanCheckBox, MarqueeLabel, SourceLinkButton, Spinner, ThumbnailPlaceholder


ANALYZING_STATUS = "분석 중"
DOWNLOAD_STATUS = "다운로드 중"
WAITING_STATUS = "대기"
PAUSED_STATUS = "일시정지"
ACTIVE_STATUSES = {ANALYZING_STATUS, DOWNLOAD_STATUS}
COMPLETED_STATUS = "완료"
ERROR_STATUS = "오류"
ROW_BORDER_WIDTH = 1
ROW_INSET = 5
ROW_LEADING_INSET = 5
ROW_CHECK_COLUMN_WIDTH = 20
ROW_META_INSET = 8
ROW_META_GAP = 8
META_ICON_SIZE = 14
META_TEXT_HEIGHT = META_ICON_SIZE
ROW_HEIGHT = 66
TITLE_BLOCK_HEIGHT = 34
ACTION_BUTTON_SIZE = 28
ACTION_ICON_SIZE = 18
ACTION_SPACING = 5
ACTION_STRIP_WIDTH = ACTION_BUTTON_SIZE * 5 + ACTION_SPACING * 4


def row_source_url(analysis, candidate):
    return (
        candidate.get("webpage_url")
        or candidate.get("page_url")
        or candidate.get("source_url")
        or candidate.get("source")
        or candidate.get("url")
        or (analysis or {}).get("webpage_url")
        or (analysis or {}).get("url")
        or ""
    )


def row_kind(candidate):
    media_type = str(candidate.get("media_type") or "video").lower()
    if media_type in {"image", "gallery", "playlist"}:
        return media_type
    return "video"


def row_clip_range_for_display(candidate):
    raw = (candidate or {}).get("clip_range")
    if not isinstance(raw, dict):
        return None
    start = raw.get("start")
    end = raw.get("end")
    if start is None and end is None:
        return None
    source_duration = engine.safe_int((candidate or {}).get("source_duration"))
    try:
        if source_duration:
            return engine.normalize_clip_range(start, end, duration=source_duration)
        if end is None:
            return {"start": float(start or 0), "end": None}
        start_val = float(start or 0)
        end_val = float(end)
        if end_val <= start_val:
            return None
        return {"start": start_val, "end": end_val}
    except (TypeError, ValueError):
        return None


def row_display_title(candidate):
    title = str((candidate or {}).get("display_title") or (candidate or {}).get("title") or "media")
    clip_range = row_clip_range_for_display(candidate)
    if not clip_range:
        return title
    suffix = engine.clip_range_suffix(clip_range)
    if not suffix:
        return title
    if title.endswith(suffix):
        return title
    return f"{title} {suffix}".strip()


def format_title_label_text(text, font, width, max_lines=2, ellipsis="..."):
    text = str(text or "").strip()
    if not text:
        return ""
    width = max(1, int(width))
    metrics = QFontMetrics(font)
    ellipsis_width = metrics.horizontalAdvance(ellipsis)

    def fits(segment, reserve_ellipsis=False):
        limit = width - (ellipsis_width if reserve_ellipsis else 0)
        return metrics.horizontalAdvance(segment) <= limit

    lines = []
    index = 0
    length = len(text)
    while index < length and len(lines) < max_lines:
        line = ""
        is_last_line = len(lines) == max_lines - 1
        while index < length:
            char = text[index]
            trial = line + char
            reserve = is_last_line and index + 1 < length
            if not fits(trial, reserve_ellipsis=reserve) and line:
                break
            if not fits(trial, reserve_ellipsis=False) and not line:
                line = char
                index += 1
                break
            line = trial
            index += 1
        lines.append(line)

    if index < length:
        last = lines[-1] if lines else ""
        while last and metrics.horizontalAdvance(last + ellipsis) > width:
            last = last[:-1]
        lines[-1] = (last + ellipsis) if last or ellipsis else ellipsis

    return "\n".join(lines)


def row_info_text(candidate):
    kind = row_kind(candidate)
    if kind == "gallery":
        count = engine.safe_int(candidate.get("item_count") or candidate.get("image_count"))
        return f"{count}장" if count else "이미지 묶음"
    if kind == "image":
        return "1장"
    seconds = engine.safe_int(candidate.get("duration"))
    duration_text = ""
    if seconds:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        remaining = seconds % 60
        duration_text = f"{hours:02d}:{minutes:02d}:{remaining:02d}"
    else:
        duration_text = engine.display_duration(candidate.get("duration"))
    return duration_text


def quality_display_label(candidate):
    if candidate.get("media_type") == "audio":
        return "오디오"
    resolution = str(candidate.get("resolution") or "").strip()
    if resolution and resolution.lower() != "unknown":
        if "x" in resolution:
            height = resolution.split("x")[-1]
            return f"{height}p" if height.isdigit() else resolution
        return resolution
    height = engine.safe_int(candidate.get("height"))
    return f"{height}p" if height else "원본"


def format_display_label(candidate):
    return str(candidate.get("output_ext") or candidate.get("ext") or "").upper() or "MP4"


def format_sort_rank(label):
    normalized = str(label or "").upper()
    ranks = {"MP4": 0, "WEBM": 1, "MP3": 2, "WAV": 3, "AAC": 4}
    return ranks.get(normalized, 10)


def candidate_size_value(candidate):
    return (
        engine.safe_int(candidate.get("sort_bytes"))
        or engine.safe_int(candidate.get("filesize"))
        or engine.safe_int(candidate.get("filesize_approx"))
        or 0
    )


def candidate_size_label(candidate):
    return engine.display_size(candidate_size_value(candidate))


def build_quality_options(qualities):
    grouped = {}
    for candidate in qualities or []:
        quality_label = quality_display_label(candidate)
        format_label = format_display_label(candidate)
        option = grouped.setdefault(quality_label, {"label": quality_label, "formats": {}})
        existing = option["formats"].get(format_label)
        if not existing or candidate_size_value(candidate) > candidate_size_value(existing):
            option["formats"][format_label] = candidate

    options = []
    for option in grouped.values():
        formats = [
            {"label": label, "candidate": candidate}
            for label, candidate in option["formats"].items()
        ]
        formats.sort(key=lambda item: (format_sort_rank(item["label"]), -candidate_size_value(item["candidate"])))
        options.append({"label": option["label"], "formats": formats})
    return options


class RowActionOverlay(QFrame):
    """Hover action strip on the right of a row."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setCursor(Qt.ArrowCursor)

    def paintEvent(self, event):
        del event


class DownloadRowWidget(QFrame):
    def __init__(self, owner, row):
        super().__init__()
        self.owner = owner
        self.row = row
        self.setObjectName("DownloadRow")
        self.setProperty("selected", "false")
        self.setProperty("hovered", "false")
        self.setCursor(Qt.ArrowCursor)
        self.setMouseTracking(True)
        self.setFixedHeight(ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._progress_cache_key = None
        self._progress_full_path = None
        self._progress_partial_paths = {}
        self._progress_gradient = None
        self._analysis_ring_offset = 0.0
        self._analysis_ring_duration_ms = 2200
        self._analysis_ring_elapsed = QElapsedTimer()
        self._analysis_ring_timer = QTimer(self)
        self._analysis_ring_timer.setTimerType(Qt.PreciseTimer)
        self._analysis_ring_timer.setInterval(16)
        self._analysis_ring_timer.timeout.connect(self._advance_analysis_ring)
        self._existing_flash_step = 0
        self._existing_flash_elapsed = QElapsedTimer()
        self._existing_flash_duration_ms = 2000
        self._existing_flash_timer = QTimer(self)
        self._existing_flash_timer.setTimerType(Qt.PreciseTimer)
        self._existing_flash_timer.setInterval(16)
        self._existing_flash_timer.timeout.connect(self._advance_existing_flash)
        self._build()
        self.refresh()

    def _build(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(ROW_LEADING_INSET, ROW_INSET, ROW_INSET, ROW_INSET)
        outer.setSpacing(ROW_INSET)

        self.select_checkbox = CleanCheckBox()
        self.select_checkbox.setObjectName("RowCheck")
        self.select_checkbox.hide()
        self.select_checkbox.toggled.connect(self._on_check_toggled)
        self.select_slot = QWidget()
        self.select_slot.setFixedWidth(ROW_CHECK_COLUMN_WIDTH)
        self.select_slot.hide()
        select_layout = QHBoxLayout(self.select_slot)
        select_layout.setContentsMargins(0, 0, 0, 0)
        select_layout.setSpacing(0)
        select_layout.addWidget(self.select_checkbox, 0, Qt.AlignCenter)
        outer.addWidget(self.select_slot, 0, Qt.AlignVCenter)

        self.thumbnail = ThumbnailPlaceholder()
        outer.addWidget(self.thumbnail, 0, Qt.AlignVCenter)

        self.item_widget = QWidget()
        self.item_widget.setMinimumWidth(MEDIA_MIN_WIDTH - THUMBNAIL_WIDTH - ROW_COLUMN_SPACING)
        self.item_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.item_widget.setFixedHeight(54)
        item_area = QVBoxLayout(self.item_widget)
        item_area.setContentsMargins(0, 0, 0, 0)
        item_area.setSpacing(0)

        title_line = QHBoxLayout()
        title_line.setContentsMargins(0, 0, 0, 0)
        title_line.setSpacing(4)
        self.playlist_toggle_button = LucideIconButton("chevron-down", size=22, icon_size=14, pointer_cursor=False)
        self.playlist_toggle_button.setToolTip("펼치기/접기")
        self.playlist_toggle_button.clicked.connect(self._toggle_playlist)
        title_line.addWidget(self.playlist_toggle_button, 0, Qt.AlignVCenter)
        self.playlist_pill = QLabel("재생목록")
        self.playlist_pill.setObjectName("PlaylistPill")
        self.playlist_pill.hide()
        title_line.addWidget(self.playlist_pill, 0, Qt.AlignVCenter)
        self.title_label = QLabel()
        self.title_label.setObjectName("RowTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setFixedHeight(TITLE_BLOCK_HEIGHT)
        self._title_source_text = ""
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.title_label.setTextInteractionFlags(Qt.NoTextInteraction)
        theme.apply_tracking(self.title_label, 0.1)
        title_line.addWidget(self.title_label, 1)
        self.title_action_spacer = QWidget()
        self.title_action_spacer.setFixedWidth(ACTION_STRIP_WIDTH + ROW_INSET)
        self.title_action_spacer.hide()
        title_line.addWidget(self.title_action_spacer, 0)
        item_area.addLayout(title_line)

        source_line = QHBoxLayout()
        source_line.setContentsMargins(0, 0, 0, 0)
        source_line.setSpacing(6)
        self.source_link_button = SourceLinkButton()
        self.source_link_button.clicked.connect(self._open_source)
        source_line.addWidget(self.source_link_button)
        self.source_status_slot = QWidget()
        self.source_status_slot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        source_status_layout = QHBoxLayout(self.source_status_slot)
        source_status_layout.setContentsMargins(0, 0, 0, 0)
        source_status_layout.setSpacing(0)
        self.row_quality_label = MarqueeLabel()
        self.row_quality_label.setObjectName("MetaText")
        self.row_quality_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.row_quality_label.hide()
        source_status_layout.addWidget(self.row_quality_label, 1)
        source_line.addWidget(self.source_status_slot, 1)

        self.meta_widget = QWidget()
        self.meta_widget.setFixedHeight(16 + max(0, ROW_META_INSET - ROW_INSET))
        self.meta_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        meta_layout = QHBoxLayout(self.meta_widget)
        meta_layout.setContentsMargins(0, 0, max(0, ROW_META_INSET - ROW_INSET), max(0, ROW_META_INSET - ROW_INSET))
        meta_layout.setSpacing(ROW_META_GAP)
        meta_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.info_widget = QWidget()
        self.info_widget.setFixedHeight(16)
        self.info_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        info_layout = QHBoxLayout(self.info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)
        info_layout.setAlignment(Qt.AlignCenter)
        self.info_icon = LucideIconWidget("clock", size=META_ICON_SIZE)
        info_layout.addWidget(self.info_icon, 0, Qt.AlignVCenter)
        self.info_label = QLabel()
        self.info_label.setObjectName("MetaText")
        self.info_label.setFixedHeight(META_TEXT_HEIGHT)
        self.info_label.setAlignment(Qt.AlignCenter)
        self._info_source_text = ""
        info_layout.addWidget(self.info_label, 0, Qt.AlignVCenter)
        meta_layout.addWidget(self.info_widget)

        self.size_widget = QWidget()
        self.size_widget.setFixedHeight(16)
        self.size_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        size_layout = QHBoxLayout(self.size_widget)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.setSpacing(4)
        size_layout.setAlignment(Qt.AlignCenter)
        self.size_icon = LucideIconWidget("download", size=META_ICON_SIZE)
        size_layout.addWidget(self.size_icon, 0, Qt.AlignVCenter)
        self.size_label = QLabel()
        self.size_label.setObjectName("MetaText")
        self.size_label.setFixedHeight(META_TEXT_HEIGHT)
        self.size_label.setAlignment(Qt.AlignCenter)
        size_layout.addWidget(self.size_label, 0, Qt.AlignVCenter)
        meta_layout.addWidget(self.size_widget)
        source_line.addWidget(self.meta_widget, 0, Qt.AlignBottom)

        item_area.addStretch(1)
        item_area.addLayout(source_line)

        progress_line = QHBoxLayout()
        progress_line.setContentsMargins(0, 0, 0, 0)
        progress_line.setSpacing(8)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.progress_bar.hide()
        self.progress_text = QLabel("")
        self.progress_text.setObjectName("MetaText")
        progress_line.addWidget(self.progress_bar, 1)
        progress_line.addWidget(self.progress_text, 0)
        item_area.addLayout(progress_line)
        self.progress_text.hide()

        self.playlist_detail_label = QLabel("")
        self.playlist_detail_label.setObjectName("MetaText")
        self.playlist_detail_label.setWordWrap(True)
        self.playlist_detail_label.hide()
        item_area.addWidget(self.playlist_detail_label)

        outer.addWidget(self.item_widget, 1, Qt.AlignTop)

        self.actions_widget = RowActionOverlay(self)
        self.actions_widget.setObjectName("ActionOverlay")
        self.actions_widget.setMinimumWidth(ACTION_STRIP_WIDTH)
        actions = QHBoxLayout(self.actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(ACTION_SPACING)
        actions.setAlignment(Qt.AlignCenter)

        self.pause_download_button = LucideIconButton(
            "pause",
            size=ACTION_BUTTON_SIZE,
            icon_size=ACTION_ICON_SIZE,
        )
        self.pause_download_button.setToolTip("일시정지")
        self.pause_download_button.clicked.connect(self._pause_download)
        actions.addWidget(self.pause_download_button)

        self.resume_download_button = LucideIconButton(
            "play",
            size=ACTION_BUTTON_SIZE,
            icon_size=ACTION_ICON_SIZE,
        )
        self.resume_download_button.setToolTip("재시작")
        self.resume_download_button.clicked.connect(self._resume_download)
        actions.addWidget(self.resume_download_button)

        self.play_file_button = LucideIconButton(
            "play",
            size=ACTION_BUTTON_SIZE,
            icon_size=ACTION_ICON_SIZE,
        )
        self.play_file_button.setToolTip("재생")
        self.play_file_button.clicked.connect(self._play_file)
        actions.addWidget(self.play_file_button)

        self.open_folder_button = LucideIconButton(
            "folder",
            size=ACTION_BUTTON_SIZE,
            icon_size=ACTION_ICON_SIZE,
        )
        self.open_folder_button.setToolTip("폴더 열기")
        self.open_folder_button.clicked.connect(self._open_folder)
        actions.addWidget(self.open_folder_button)

        self.remove_button = LucideIconButton(
            "x",
            size=ACTION_BUTTON_SIZE,
            icon_size=ACTION_ICON_SIZE,
        )
        self.remove_button.setToolTip("목록에서 삭제")
        self.remove_button.clicked.connect(self._remove_row)
        actions.addWidget(self.remove_button)

        self.delete_file_button = LucideIconButton(
            "trash-2",
            size=ACTION_BUTTON_SIZE,
            icon_size=ACTION_ICON_SIZE,
            danger=True,
        )
        self.delete_file_button.setToolTip("파일 삭제")
        self.delete_file_button.clicked.connect(self._delete_file)
        actions.addWidget(self.delete_file_button)

        self.more_button = LucideIconButton(
            "more-vertical",
            size=ACTION_BUTTON_SIZE,
            icon_size=ACTION_ICON_SIZE,
        )
        self.more_button.setToolTip("더보기")
        self.more_button.clicked.connect(self._show_more_menu)
        actions.addWidget(self.more_button)
        self.actions_widget.hide()

        self.spinner = Spinner(30, parent=self)
        self.spinner.hide()
        self._actions_menu_open = False
        self._apply_row_arrow_cursors()

    def _apply_row_arrow_cursors(self):
        for widget in (
            self,
            self.select_slot,
            self.item_widget,
            self.playlist_pill,
            self.title_label,
            self.title_action_spacer,
            self.source_status_slot,
            self.row_quality_label,
            self.meta_widget,
            self.info_widget,
            self.info_icon,
            self.info_label,
            self.size_widget,
            self.size_icon,
            self.size_label,
            self.progress_bar,
            self.progress_text,
            self.playlist_detail_label,
            self.actions_widget,
            self.thumbnail,
            self.select_checkbox,
            self.playlist_toggle_button,
        ):
            widget.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, event):
        if getattr(self.owner, "select_mode", False):
            self.select_checkbox.setChecked(not self.select_checkbox.isChecked())
        elif self.row.get("kind") == "playlist":
            self._toggle_playlist()
        event.accept()

    def enterEvent(self, event):
        self._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_hovered(False)
        super().leaveEvent(event)

    def resizeEvent(self, event):
        self._position_actions()
        self._position_spinner()
        self._refresh_title_display()
        self._refresh_title_alignment()
        self._refresh_info_display()
        self._clear_progress_path_cache()
        super().resizeEvent(event)

    def _position_spinner(self):
        size = self.spinner.width()
        self.spinner.move((self.width() - size) // 2, (self.height() - size) // 2)

    def refresh(self):
        candidate = self.owner.selected_candidate_for_row_ref(self.row) or self.row["candidate"]
        self._title_source_text = row_display_title(candidate)
        self._refresh_title_display()
        self.title_label.setToolTip("")
        self._refresh_title_alignment()
        self._info_source_text = row_info_text(candidate)
        self._refresh_info_display()
        self.size_label.setText(candidate_size_label(candidate))
        self.row_quality_label.setText("")
        self.thumbnail.set_thumbnail_url(candidate.get("thumbnail") or "", self.row.get("source_url") or "")
        self._refresh_source_button()
        self._refresh_playlist_detail()
        self.set_status(self.row.get("status") or "준비", self.row.get("status_detail") or "")
        self.set_progress(self.row.get("progress") or 0, self.row.get("progress_text") or "")
        self._refresh_actions()

    def _refresh_source_button(self):
        source_url = self.row.get("source_url") or ""
        self.source_link_button.set_source_url(source_url)

    def _refresh_actions(self):
        status = self.row.get("status")
        active = status in ACTIVE_STATUSES
        pauseable = status in {DOWNLOAD_STATUS, WAITING_STATUS}
        paused = status == PAUSED_STATUS
        completed = self.row.get("status") == COMPLETED_STATUS
        has_deletable_output = self.owner.row_has_deletable_output(self.row)
        has_output = has_deletable_output
        remove_paused = paused and not has_deletable_output
        # Finder + file delete only make sense once a file exists (completed).
        # Paused analysis rows without files should expose list removal instead.
        self.pause_download_button.setVisible(pauseable)
        self.resume_download_button.setVisible(paused)
        self.play_file_button.setVisible(completed and has_output and self.row.get("kind") != "playlist")
        self.open_folder_button.setVisible(completed)
        self.delete_file_button.setVisible(completed or (paused and has_deletable_output))
        self.more_button.setVisible(completed)
        self.remove_button.setVisible((not active and not paused) or remove_paused)
        self.pause_download_button.setEnabled(pauseable)
        self.resume_download_button.setEnabled(paused)
        self.play_file_button.setEnabled(completed and has_output and not active)
        self.open_folder_button.setEnabled(completed and not active)
        self.remove_button.setEnabled(not pauseable and ((not active and not paused) or remove_paused))
        self.delete_file_button.setEnabled((completed or paused) and has_deletable_output and not active)
        self.more_button.setEnabled(completed)

    def _playlist_detail_text(self):
        entries = self.row.get("playlist_entries") or []
        lines = []
        for index, item in enumerate(entries[:20], start=1):
            candidate = item.get("candidate") if isinstance(item, dict) else item
            title = (candidate or {}).get("display_title") or (candidate or {}).get("title") or f"Video {index}"
            lines.append(f"{index}. {title}")
        if len(entries) > 20:
            lines.append(f"... +{len(entries) - 20}")
        return "\n".join(lines)

    def _refresh_playlist_detail(self):
        is_playlist = self.row.get("kind") == "playlist"
        self.playlist_toggle_button.hide()
        if is_playlist:
            candidate = self.row.get("candidate") or {}
            count = engine.safe_int(candidate.get("item_count") or candidate.get("playlist_count"))
            self.playlist_pill.setText(f"재생목록 · {count}개" if count else "재생목록")
        self.playlist_pill.setVisible(is_playlist)
        self.playlist_detail_label.hide()
        self.playlist_detail_label.setText("")

    def _toggle_playlist(self):
        if self.row.get("kind") != "playlist":
            return
        self.row["expanded"] = not bool(self.row.get("expanded"))
        self._refresh_playlist_detail()
        self.updateGeometry()
        self.owner.playlist_expansion_changed(self.row)

    def _position_actions(self):
        actual_width = ACTION_STRIP_WIDTH
        title_top = self.title_label.mapTo(self, self.title_label.rect().topLeft()).y()
        if title_top <= 0:
            title_top = ROW_BORDER_WIDTH + ROW_INSET
        top = title_top + max(0, (TITLE_BLOCK_HEIGHT - ACTION_BUTTON_SIZE) // 2)
        height = ACTION_BUTTON_SIZE
        left = self.width() - ROW_BORDER_WIDTH - ROW_INSET - actual_width
        self.actions_widget.setGeometry(max(0, left), top, actual_width, height)
        self.actions_widget.raise_()

    def _set_hovered(self, hovered):
        force_actions = bool(getattr(self, "_actions_menu_open", False))
        visual_hovered = bool(hovered or force_actions)
        self.setProperty("hovered", "true" if visual_hovered else "false")
        active = self.row.get("status") in ACTIVE_STATUSES
        analyzing = self.row.get("status") == ANALYZING_STATUS or (
            bool(self.row.get("analysis_loading"))
            and self.row.get("status") not in {DOWNLOAD_STATUS, WAITING_STATUS, PAUSED_STATUS, COMPLETED_STATUS, ERROR_STATUS}
        )
        show_actions = visual_hovered and not analyzing
        self.actions_widget.setVisible(show_actions)
        action_width = ACTION_STRIP_WIDTH
        self.title_action_spacer.setFixedWidth(action_width + ROW_INSET)
        self.title_action_spacer.setVisible(show_actions)
        self.title_label.setContentsMargins(0, 0, 0, 0)
        self.item_widget.layout().activate()
        self._refresh_title_display()
        self._refresh_title_alignment()
        self._refresh_info_display()
        if show_actions:
            self._position_actions()
        self._refresh_actions()
        self._repolish()

    def _refresh_title_display(self):
        source = str(getattr(self, "_title_source_text", "") or "")
        width = max(1, self.title_label.width())
        self.title_label.setText(format_title_label_text(source, self.title_label.font(), width))

    def _refresh_info_display(self):
        self.info_label.setText(str(getattr(self, "_info_source_text", "") or ""))

    def _title_uses_multiple_lines(self):
        return "\n" in (self.title_label.text() or "")

    def _refresh_title_alignment(self):
        self.title_label.setFixedHeight(TITLE_BLOCK_HEIGHT)
        vertical_alignment = Qt.AlignTop if self._title_uses_multiple_lines() else Qt.AlignVCenter
        self.title_label.setAlignment(Qt.AlignLeft | vertical_alignment)

    def _open_source(self):
        self.owner.open_source_for_row(self.row)

    def _on_check_toggled(self, checked):
        self.row["checked"] = bool(checked)
        self.owner.on_row_check_changed()

    def set_select_mode(self, enabled):
        self.select_slot.setVisible(bool(enabled))
        self.select_checkbox.setVisible(bool(enabled))
        self.select_checkbox.blockSignals(True)
        self.select_checkbox.setChecked(bool(enabled) and bool(self.row.get("checked")))
        self.select_checkbox.blockSignals(False)

    def _open_folder(self):
        self.owner.open_folder_for_row(self.row)

    def _remove_row(self):
        self.owner.remove_row(self.row)

    def _pause_download(self):
        self.owner.pause_download_for_row(self.row)

    def _resume_download(self):
        self.owner.resume_download_for_row(self.row)

    def _play_file(self):
        self.owner.play_file_for_row(self.row)

    def _delete_file(self):
        self.owner.delete_file_for_row(self.row)

    def _show_more_menu(self):
        menu = QMenu(self)
        if self.row.get("kind") != "playlist" or self.row.get("is_playlist_child"):
            segment_action = menu.addAction("구간 추출...")
            segment_action.triggered.connect(lambda _checked=False: self.owner.download_segment_for_row(self.row))
        for label, fmt in (("음원 추출 (WAV)", "WAV"), ("음원 추출 (MP3)", "MP3")):
            action = menu.addAction(label)
            action.triggered.connect(lambda _checked=False, f=fmt: self.owner.extract_audio_for_row(self.row, f))
        self._actions_menu_open = True
        self._set_hovered(True)
        try:
            menu.exec(self.more_button.mapToGlobal(self.more_button.rect().bottomLeft()))
        finally:
            self._actions_menu_open = False
            self._set_hovered(self.underMouse())

    def set_selected(self, selected):
        del selected
        self.setProperty("selected", "false")
        self._repolish()

    def _repolish(self):
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _sync_ring_timer(self):
        # The rotating ring animates in indeterminate phases: analysis, download
        # prep (download_starting), and post-download finalize (download_finishing).
        # Only (re)start when idle so phase handoffs keep the animation continuous.
        spinning = (
            self.property("analyzing") == "true"
            or self.property("starting") == "true"
            or self.property("finishing") == "true"
        )
        if spinning:
            if not self._analysis_ring_timer.isActive():
                self._analysis_ring_elapsed.restart()
                self._analysis_ring_timer.start()
        elif self._analysis_ring_timer.isActive():
            self._analysis_ring_timer.stop()
            self._analysis_ring_elapsed.invalidate()

    def _advance_analysis_ring(self):
        if self._analysis_ring_elapsed.isValid():
            elapsed = self._analysis_ring_elapsed.elapsed() % self._analysis_ring_duration_ms
            self._analysis_ring_offset = 4.0 * elapsed / self._analysis_ring_duration_ms
        else:
            self._analysis_ring_offset = (self._analysis_ring_offset + 0.08) % 4.0
        self.update()

    def flash_existing_output_notice(self):
        self._existing_flash_step = 0
        self._existing_flash_elapsed.restart()
        self.setProperty("existingFlash", "true")
        self._existing_flash_timer.stop()
        self._existing_flash_timer.start()
        self.update()

    def _existing_flash_t(self):
        duration = max(1, int(self._existing_flash_duration_ms or 2000))
        return max(0.0, min(1.0, float(self._existing_flash_elapsed.elapsed()) / duration))

    def _existing_flash_smoothstep(self, edge0, edge1, x):
        if edge1 <= edge0:
            return 0.0 if x < edge0 else 1.0
        t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
        return t * t * (3.0 - 2.0 * t)

    def _existing_flash_blink_amount(self, t):
        """Two clear blinks over 0→1. Peak = 1 (flash moment), valley = 0 (original)."""
        def blink(center, width):
            half = width * 0.5
            start = center - half
            end = center + half
            if t < start or t > end:
                return 0.0
            local = (t - start) / max(0.001, width)
            # Slightly snappier than pure sine so peaks read as distinct beats.
            return math.sin(local * math.pi) ** 0.85

        # Shorter humps + wider rest between → easier to count as two blinks.
        return max(blink(0.26, 0.28), blink(0.72, 0.28))

    def _existing_flash_ring_opacity(self, t):
        # Black completed ring: fully fade out then restore, twice.
        removed = self._existing_flash_blink_amount(t)
        return 1.0 - removed

    def _existing_flash_bg_alpha(self, t):
        # Same beat as the ring. Stronger wash so the card itself is readable.
        return 0.14 * self._existing_flash_blink_amount(t)

    def _advance_existing_flash(self):
        if not self._existing_flash_elapsed.isValid() or self._existing_flash_elapsed.elapsed() >= self._existing_flash_duration_ms:
            self._existing_flash_timer.stop()
            self.setProperty("existingFlash", "false")
            self.update()
            return
        self._existing_flash_step += 1
        self.update()

    def _analysis_ring_point(self, rect, phase):
        phase = float(phase or 0.0) % 4.0
        side = int(phase)
        t = phase - side
        radius = min(10.0, rect.width() / 2.0, rect.height() / 2.0)
        straight_fraction = 0.82
        corner_t = 0.0 if t < straight_fraction else (t - straight_fraction) / (1.0 - straight_fraction)

        left, right = rect.left(), rect.right()
        top, bottom = rect.top(), rect.bottom()
        if side == 0:
            if t < straight_fraction:
                x = (left + radius) + (right - 2 * radius - left) * (t / straight_fraction)
                return QPointF(x, top)
            angle = math.radians(-90.0 + 90.0 * corner_t)
            return QPointF(right - radius + radius * math.cos(angle), top + radius + radius * math.sin(angle))
        if side == 1:
            if t < straight_fraction:
                y = (top + radius) + (bottom - 2 * radius - top) * (t / straight_fraction)
                return QPointF(right, y)
            angle = math.radians(90.0 * corner_t)
            return QPointF(right - radius + radius * math.cos(angle), bottom - radius + radius * math.sin(angle))
        if side == 2:
            if t < straight_fraction:
                x = (right - radius) - (right - 2 * radius - left) * (t / straight_fraction)
                return QPointF(x, bottom)
            angle = math.radians(90.0 + 90.0 * corner_t)
            return QPointF(left + radius + radius * math.cos(angle), bottom - radius + radius * math.sin(angle))
        if t < straight_fraction:
            y = (bottom - radius) - (bottom - 2 * radius - top) * (t / straight_fraction)
            return QPointF(left, y)
        angle = math.radians(180.0 + 90.0 * corner_t)
        return QPointF(left + radius + radius * math.cos(angle), top + radius + radius * math.sin(angle))

    def _analysis_dash_path(self, rect):
        return self._ring_segment_path(rect, float(self._analysis_ring_offset or 0.0), 0.46)

    def _ring_segment_path(self, rect, start_phase, length_phase):
        # Exact perimeter segment: straight edges as lines, corners as true
        # arcs, and no subpath break when the phase wraps 4.0 -> 0.0 (the
        # top-left corner) — the ring is continuous there.
        path = QPainterPath()
        length_phase = max(0.0, min(4.0, float(length_phase or 0.0)))
        if length_phase <= 0.0:
            return path
        radius = min(10.0, rect.width() / 2.0, rect.height() / 2.0)
        straight_fraction = 0.82
        corner_span = 1.0 - straight_fraction
        diameter = 2.0 * radius
        corner_rects = (
            QRectF(rect.right() - diameter, rect.top(), diameter, diameter),
            QRectF(rect.right() - diameter, rect.bottom() - diameter, diameter, diameter),
            QRectF(rect.left(), rect.bottom() - diameter, diameter, diameter),
            QRectF(rect.left(), rect.top(), diameter, diameter),
        )
        corner_start_angles = (90.0, 0.0, 270.0, 180.0)
        start = float(start_phase or 0.0) % 4.0
        end = start + length_phase
        path.moveTo(self._analysis_ring_point(rect, start))
        phase = start
        while phase < end - 1e-6:
            base = math.floor(phase + 1e-9)
            side = int(base) % 4
            t = phase - base
            if t < straight_fraction - 1e-9:
                piece_end = min(end, base + straight_fraction)
                path.lineTo(self._analysis_ring_point(rect, piece_end % 4.0))
            else:
                piece_end = min(end, base + 1.0)
                from_t = max(0.0, (t - straight_fraction) / corner_span)
                to_t = min(1.0, (piece_end - base - straight_fraction) / corner_span)
                path.arcTo(
                    corner_rects[side],
                    corner_start_angles[side] - 90.0 * from_t,
                    -90.0 * (to_t - from_t),
                )
            phase = piece_end
        return path

    def _show_row_quality_text(self, text, tooltip=""):
        text = str(text or "")
        self.row_quality_label.setText(text)
        self.row_quality_label.setToolTip(str(tooltip or text))
        if text:
            self.row_quality_label.show()
            self.row_quality_label.start_marquee_if_needed()
        else:
            self.row_quality_label.stop_marquee()
            self.row_quality_label.hide()

    def set_status(self, status, detail=""):
        self.row["status"] = status
        self.row["status_detail"] = detail
        self.setProperty("completed", "true" if status == COMPLETED_STATUS else "false")
        self.setProperty("errored", "true" if status == ERROR_STATUS else "false")
        analyzing = status == ANALYZING_STATUS or (
            bool(self.row.get("analysis_loading"))
            and status not in {DOWNLOAD_STATUS, WAITING_STATUS, PAUSED_STATUS, COMPLETED_STATUS, ERROR_STATUS}
        )
        if status == DOWNLOAD_STATUS:
            analyzing = False
        self.setProperty("analyzing", "true" if analyzing else "false")
        starting = bool(self.row.get("download_starting"))
        self.setProperty("starting", "true" if starting else "false")
        finishing = bool(self.row.get("download_finishing"))
        self.setProperty("finishing", "true" if finishing else "false")
        self._sync_ring_timer()
        self.spinner.stop()
        if analyzing or starting or finishing or (status == COMPLETED_STATUS and detail):
            self._show_row_quality_text(detail or status)
        else:
            self._show_row_quality_text("")
        self.info_widget.show()
        self.size_widget.show()
        self._refresh_actions()
        if self.row.get("download_finishing"):
            self.set_finishing(self.row.get("progress_text") or "마무리 중")
        else:
            self.set_progress(self.row.get("progress") or 0, self.row.get("progress_text") or "")

    def set_finishing(self, text="마무리 중"):
        detail = str(text or "마무리 중").strip() or "마무리 중"
        self.row["download_finishing"] = True
        self.row["download_starting"] = False
        self.row["progress"] = 100
        self.row["progress_text"] = detail
        self.setProperty("starting", "false")
        self.setProperty("finishing", "true")
        self.setProperty("progressActive", "true")
        self.setProperty("progressValue", "100")
        self._sync_ring_timer()
        self._show_row_quality_text(detail)
        self.update()

    def set_progress(self, value, text=""):
        self.row.pop("download_finishing", None)
        self.setProperty("finishing", "false")
        bounded = max(0, min(100, int(float(value or 0))))
        status = self.row.get("status")
        active = status in ACTIVE_STATUSES
        paused = status == PAUSED_STATUS
        error_detail = status == ERROR_STATUS and self.row.get("status_detail")
        completed_detail = status == COMPLETED_STATUS and self.row.get("status_detail")
        display_text = text if active or paused else (self.row.get("status_detail") if error_detail or completed_detail else "")
        active_value = "true" if active or paused else "false"
        progress_value = str(bounded if active or paused else 0)
        if (
            self.row.get("progress") == bounded
            and self.row.get("progress_text") == display_text
            and self.property("progressActive") == active_value
            and self.property("progressValue") == progress_value
            and self.row_quality_label.text() == display_text
            and self.row_quality_label.isVisible() == bool(display_text)
        ):
            return
        self.row["progress"] = bounded
        self.row["progress_text"] = display_text
        self.progress_bar.setValue(bounded)
        self.progress_bar.hide()
        self.setProperty("progressActive", active_value)
        self.setProperty("progressValue", progress_value)
        if (active or paused) and display_text:
            self._show_row_quality_text(display_text)
        elif status in {ERROR_STATUS, COMPLETED_STATUS} and display_text:
            self._show_row_quality_text(display_text)
        elif status not in ACTIVE_STATUSES:
            self._show_row_quality_text("")
        self.progress_text.hide()
        self.progress_text.setText("")
        self.progress_text.setStyleSheet(
            f"color: {theme.DANGER};" if status == ERROR_STATUS and display_text else ""
        )
        # A repaint is enough for the painted progress ring; avoid a full style
        # unpolish/polish on every progress tick (called dozens of times/sec).
        self.update()

    def _clear_progress_path_cache(self):
        self._progress_cache_key = None
        self._progress_full_path = None
        self._progress_partial_paths.clear()
        self._progress_gradient = None

    def _progress_paths(self):
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        key = (round(rect.width(), 2), round(rect.height(), 2))
        if self._progress_cache_key != key:
            self._progress_cache_key = key
            self._progress_full_path = QPainterPath()
            self._progress_full_path.addRoundedRect(rect, 10.0, 10.0)
            self._progress_gradient = QLinearGradient(rect.topLeft(), rect.topRight())
            self._progress_gradient.setColorAt(0.0, QColor(theme.ACCENT))
            self._progress_gradient.setColorAt(1.0, QColor(theme.ACCENT_SOFT))
            self._progress_partial_paths.clear()
        return rect, self._progress_full_path, self._progress_gradient

    def _progress_partial_path(self, full, progress):
        progress = max(0, min(100, int(progress)))
        cached = self._progress_partial_paths.get(progress)
        if cached is not None:
            return cached
        partial = QPainterPath()
        polygons = full.toSubpathPolygons()
        points = list(polygons[0]) if polygons else []
        if len(points) < 2:
            self._progress_partial_paths[progress] = partial
            return partial
        lengths = []
        total_length = 0.0
        for start, end in zip(points, points[1:]):
            segment_length = math.hypot(end.x() - start.x(), end.y() - start.y())
            lengths.append(segment_length)
            total_length += segment_length
        if total_length <= 0:
            self._progress_partial_paths[progress] = partial
            return partial
        target_length = total_length * progress / 100.0
        traversed = 0.0
        partial.moveTo(points[0])
        for index, segment_length in enumerate(lengths):
            start = points[index]
            end = points[index + 1]
            if traversed + segment_length <= target_length:
                partial.lineTo(end)
                traversed += segment_length
                continue
            if segment_length > 0:
                ratio = max(0.0, min(1.0, (target_length - traversed) / segment_length))
                partial.lineTo(
                    start.x() + (end.x() - start.x()) * ratio,
                    start.y() + (end.y() - start.y()) * ratio,
                )
            break
        self._progress_partial_paths[progress] = partial
        return partial

    def paintEvent(self, event):
        super().paintEvent(event)
        completed = self.property("completed") == "true"
        errored = self.property("errored") == "true"
        analyzing = self.property("analyzing") == "true"
        starting = self.property("starting") == "true"
        finishing = self.property("finishing") == "true"
        flashing = self.property("existingFlash") == "true"
        if (
            self.property("progressActive") != "true"
            and not analyzing
            and not completed
            and not errored
            and not starting
            and not finishing
            and not flashing
        ):
            return
        _rect, full, gradient = self._progress_paths()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if flashing:
            t = self._existing_flash_t()
            # Same beat: bg wash up when ring goes away (easier to see on white cards).
            bg_alpha = self._existing_flash_bg_alpha(t)
            if bg_alpha > 0.001:
                wash = QColor(theme.ACCENT)
                wash.setAlphaF(bg_alpha)
                card = QPainterPath()
                card.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10.0, 10.0)
                painter.fillPath(card, wash)
            # Black completed ring: fully out → restore, twice.
            ring = QColor(theme.GRAPHITE)
            ring.setAlphaF(self._existing_flash_ring_opacity(t))
            painter.setPen(QPen(ring, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(full)
            return

        if errored:
            # Full red ring so a failed row is obvious at a glance.
            painter.setPen(QPen(QColor(theme.DANGER), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(full)
            return

        if analyzing:
            painter.setPen(QPen(QColor(theme.ACCENT_TINT), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(full)
            pen = QPen(QColor(theme.ACCENT_SOFT if self.property("hovered") == "true" else theme.ACCENT), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(self._analysis_dash_path(_rect))
            return

        if completed:
            hovered = self.property("hovered") == "true"
            color = theme.GRAPHITE_HOVER if hovered else theme.GRAPHITE
            painter.setPen(QPen(QColor(color), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(full)
            return

        if starting:
            painter.setPen(QPen(QColor(theme.ACCENT_TINT), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(full)
            pen = QPen(QColor(theme.ACCENT_SOFT if self.property("hovered") == "true" else theme.ACCENT), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(self._analysis_dash_path(_rect))
            return

        if finishing:
            painter.setPen(QPen(QColor(theme.ACCENT_TINT), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(full)
            rainbow = QLinearGradient(_rect.topLeft(), _rect.topRight())
            rainbow.setColorAt(0.00, QColor("#2F80ED"))
            rainbow.setColorAt(0.25, QColor("#9B51E0"))
            rainbow.setColorAt(0.50, QColor("#EB5757"))
            rainbow.setColorAt(0.75, QColor("#F2C94C"))
            rainbow.setColorAt(1.00, QColor("#27AE60"))
            pen = QPen(QBrush(rainbow), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(self._analysis_dash_path(_rect))
            return

        progress = max(0, min(100, int(self.property("progressValue") or 0)))
        painter.setPen(QPen(QColor(theme.ACCENT_TINT), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(full)
        if progress <= 0:
            return
        partial = self._ring_segment_path(_rect, 3.82, 4.0 * progress / 100.0)
        painter.setPen(QPen(QBrush(gradient), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(partial)
