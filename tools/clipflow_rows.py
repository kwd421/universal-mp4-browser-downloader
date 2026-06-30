# Auto-split from clipflow_qt.py; keep behavior changes in focused commits.
import math
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
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
ACTIVE_STATUSES = {ANALYZING_STATUS, "다운로드 중"}
COMPLETED_STATUS = "완료"
ERROR_STATUS = "오류"


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


def row_info_text(candidate):
    kind = row_kind(candidate)
    if kind == "gallery":
        count = engine.safe_int(candidate.get("item_count") or candidate.get("image_count"))
        return f"{count}장" if count else "이미지 묶음"
    if kind == "image":
        return "1장"
    seconds = engine.safe_int(candidate.get("duration"))
    if seconds:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        remaining = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{remaining:02d}"
    return engine.display_duration(candidate.get("duration"))


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
    """Hover action strip on the right of a row.

    Painted with a solid fill that exactly matches the row's current
    background (selected vs hovered), so it covers the meta columns with no
    visible seam or colour shift, leaving only the action icons on top.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Inset top/right/bottom so the fill never overlaps the row's 2px
        # painted border ring (which lives ~0.5–2.5px from the row edge). The
        # fill colour matches the hovered row background, so the inset is
        # seamless while leaving the coloured ring fully visible on hover.
        rect = QRectF(self.rect()).adjusted(0, 3, -3, -3)
        color = theme.SURFACE_SOFT
        radius = 7.0
        path = QPainterPath()
        path.moveTo(rect.left(), rect.top())
        path.lineTo(rect.right() - radius, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + radius)
        path.lineTo(rect.right(), rect.bottom() - radius)
        path.quadTo(rect.right(), rect.bottom(), rect.right() - radius, rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        path.closeSubpath()
        painter.fillPath(path, QColor(color))


class DownloadRowWidget(QFrame):
    def __init__(self, owner, row):
        super().__init__()
        self.owner = owner
        self.row = row
        self.setObjectName("DownloadRow")
        self.setProperty("selected", "false")
        self.setProperty("hovered", "false")
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFixedHeight(72)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._progress_cache_key = None
        self._progress_full_path = None
        self._progress_partial_paths = {}
        self._progress_gradient = None
        self._build()
        self.refresh()

    def _build(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(9, 9, 44, 9)
        outer.setSpacing(ROW_COLUMN_SPACING)

        self.select_checkbox = CleanCheckBox()
        self.select_checkbox.setObjectName("RowCheck")
        self.select_checkbox.setCursor(Qt.PointingHandCursor)
        self.select_checkbox.hide()
        self.select_checkbox.toggled.connect(self._on_check_toggled)
        outer.addWidget(self.select_checkbox, 0, Qt.AlignVCenter)

        self.thumbnail = ThumbnailPlaceholder()
        outer.addWidget(self.thumbnail, 0, Qt.AlignVCenter)

        self.item_widget = QWidget()
        self.item_widget.setMinimumWidth(MEDIA_MIN_WIDTH - THUMBNAIL_WIDTH - ROW_COLUMN_SPACING)
        self.item_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        item_area = QVBoxLayout(self.item_widget)
        item_area.setContentsMargins(0, 0, 0, 0)
        item_area.setSpacing(3)

        title_line = QHBoxLayout()
        title_line.setContentsMargins(0, 0, 0, 0)
        title_line.setSpacing(4)
        self.playlist_toggle_button = LucideIconButton("chevron-down", size=22, icon_size=14)
        self.playlist_toggle_button.setToolTip("펼치기/접기")
        self.playlist_toggle_button.clicked.connect(self._toggle_playlist)
        title_line.addWidget(self.playlist_toggle_button, 0, Qt.AlignVCenter)
        self.playlist_pill = QLabel("재생목록")
        self.playlist_pill.setObjectName("PlaylistPill")
        self.playlist_pill.hide()
        title_line.addWidget(self.playlist_pill, 0, Qt.AlignVCenter)
        self.title_label = MarqueeLabel()
        self.title_label.setObjectName("RowTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setTextInteractionFlags(Qt.NoTextInteraction)
        theme.apply_tracking(self.title_label, 0.1)
        title_line.addWidget(self.title_label, 1)
        item_area.addLayout(title_line)

        source_line = QHBoxLayout()
        source_line.setSpacing(6)
        self.source_link_button = SourceLinkButton()
        self.source_link_button.clicked.connect(self._open_source)
        source_line.addWidget(self.source_link_button)
        self.row_quality_label = QLabel()
        self.row_quality_label.setObjectName("MetaText")
        source_line.addWidget(self.row_quality_label, 0, Qt.AlignVCenter)
        source_line.addStretch(1)
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

        self.playlist_detail_label = QLabel("")
        self.playlist_detail_label.setObjectName("MetaText")
        self.playlist_detail_label.setWordWrap(True)
        self.playlist_detail_label.hide()
        item_area.addWidget(self.playlist_detail_label)

        outer.addWidget(self.item_widget, 1)

        self.info_widget = QWidget()
        self.info_widget.setFixedWidth(DURATION_WIDTH)
        info_layout = QHBoxLayout(self.info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)
        info_layout.setAlignment(Qt.AlignCenter)
        self.info_icon = LucideIconWidget("clock", size=18)
        info_layout.addWidget(self.info_icon)
        self.info_label = QLabel()
        self.info_label.setObjectName("MetaText")
        self.info_label.setAlignment(Qt.AlignCenter)
        info_layout.addWidget(self.info_label)
        outer.addWidget(self.info_widget, 0, Qt.AlignVCenter)

        self.size_widget = QWidget()
        self.size_widget.setFixedWidth(SIZE_WIDTH)
        size_layout = QHBoxLayout(self.size_widget)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.setSpacing(4)
        size_layout.setAlignment(Qt.AlignCenter)
        self.size_icon = LucideIconWidget("file-text", size=18)
        size_layout.addWidget(self.size_icon)
        self.size_label = QLabel()
        self.size_label.setAlignment(Qt.AlignCenter)
        size_layout.addWidget(self.size_label)
        outer.addWidget(self.size_widget, 0, Qt.AlignVCenter)

        self.actions_widget = RowActionOverlay(self)
        self.actions_widget.setObjectName("ActionOverlay")
        self.actions_widget.setMinimumWidth(ACTIONS_WIDTH)
        actions = QHBoxLayout(self.actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(4)
        actions.setAlignment(Qt.AlignCenter)

        self.open_folder_button = LucideIconButton("folder", size=38, icon_size=22)
        self.open_folder_button.setToolTip("폴더 열기")
        self.open_folder_button.clicked.connect(self._open_folder)
        actions.addWidget(self.open_folder_button)

        self.remove_button = LucideIconButton("x", size=38, icon_size=22)
        self.remove_button.setToolTip("목록에서 삭제")
        self.remove_button.clicked.connect(self._remove_row)
        actions.addWidget(self.remove_button)

        self.delete_file_button = LucideIconButton("trash-2", size=38, icon_size=22, danger=True)
        self.delete_file_button.setToolTip("파일 삭제")
        self.delete_file_button.clicked.connect(self._delete_file)
        actions.addWidget(self.delete_file_button)

        self.more_button = LucideIconButton("more-vertical", size=38, icon_size=22)
        self.more_button.setToolTip("더보기")
        self.more_button.clicked.connect(self._show_more_menu)
        actions.addWidget(self.more_button)
        self.actions_widget.hide()

        self.spinner = Spinner(30, parent=self)
        self.spinner.hide()

    def mousePressEvent(self, event):
        if getattr(self.owner, "select_mode", False):
            self.select_checkbox.setChecked(not self.select_checkbox.isChecked())
        elif self.row.get("kind") == "playlist":
            self.owner.select_row_for_widget(self)
            self._toggle_playlist()
        else:
            self.owner.select_row_for_widget(self)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_hovered(False)
        super().leaveEvent(event)

    def resizeEvent(self, event):
        self._position_actions()
        self._position_spinner()
        self._clear_progress_path_cache()
        super().resizeEvent(event)

    def _position_spinner(self):
        size = self.spinner.width()
        self.spinner.move((self.width() - size) // 2, (self.height() - size) // 2)

    def refresh(self):
        candidate = self.owner.selected_candidate_for_row_ref(self.row) or self.row["candidate"]
        title = candidate.get("display_title") or candidate.get("title") or "media"
        self.title_label.setText(str(title))
        self.title_label.setToolTip(str(title))
        self.title_label.start_marquee_if_needed()
        self.info_label.setText(row_info_text(candidate))
        self.size_label.setText(engine.display_size(candidate_size_value(candidate)))
        if self.row.get("kind") == "playlist":
            self.row_quality_label.setText("")
        else:
            self.row_quality_label.setText(f"· {quality_display_label(candidate)} · {format_display_label(candidate)}")
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
        active = self.row.get("status") in ACTIVE_STATUSES
        completed = self.row.get("status") == COMPLETED_STATUS
        output_path = Path(self.row.get("output_path") or "")
        has_output = bool(self.row.get("output_path")) and output_path.exists()
        can_resolve_output = bool(has_output or self.row.get("kind") == "playlist" or self.row.get("is_playlist_child"))
        # Finder + file delete only make sense once a file exists (completed).
        # Analysed / error rows expose only "remove from list".
        self.open_folder_button.setVisible(completed)
        self.delete_file_button.setVisible(completed)
        self.more_button.setVisible(completed)
        self.remove_button.setVisible(not active)
        self.open_folder_button.setEnabled(completed and not active)
        self.remove_button.setEnabled(not active)
        self.delete_file_button.setEnabled(completed and can_resolve_output and not active)
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
        inset = 1
        left = self.info_widget.x() if self.info_widget.x() > 0 else self.width() - self.actions_widget.width()
        width = self.width() - left - inset - 1
        self.actions_widget.setGeometry(
            max(0, left), inset, max(ACTIONS_WIDTH, width), max(0, self.height() - 2 * inset - 1)
        )
        self.actions_widget.raise_()

    def _set_hovered(self, hovered):
        self.setProperty("hovered", "true" if hovered else "false")
        active = self.row.get("status") in ACTIVE_STATUSES
        analyzing = bool(self.row.get("analysis_loading")) or self.row.get("status") == ANALYZING_STATUS
        show_actions = hovered and (not active or self.row.get("kind") == "playlist") and not analyzing
        self.actions_widget.setVisible(show_actions)
        if show_actions:
            self._position_actions()
        self._refresh_actions()
        self._repolish()

    def _open_source(self):
        self.owner.open_source_for_row(self.row)

    def _on_check_toggled(self, checked):
        self.row["checked"] = bool(checked)
        self.owner.on_row_check_changed()

    def set_select_mode(self, enabled):
        self.select_checkbox.setVisible(bool(enabled))
        self.select_checkbox.blockSignals(True)
        self.select_checkbox.setChecked(bool(enabled) and bool(self.row.get("checked")))
        self.select_checkbox.blockSignals(False)

    def _open_folder(self):
        self.owner.open_folder_for_row(self.row)

    def _remove_row(self):
        self.owner.remove_row(self.row)

    def _delete_file(self):
        self.owner.delete_file_for_row(self.row)

    def _show_more_menu(self):
        menu = QMenu(self)
        for label, fmt in (("음원 추출 (WAV)", "WAV"), ("음원 추출 (MP3)", "MP3")):
            action = menu.addAction(label)
            action.triggered.connect(lambda _checked=False, f=fmt: self.owner.extract_audio_for_row(self.row, f))
        menu.exec(self.more_button.mapToGlobal(self.more_button.rect().bottomLeft()))

    def set_selected(self, selected):
        del selected
        self.setProperty("selected", "false")
        self._repolish()

    def _repolish(self):
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_status(self, status, detail=""):
        self.row["status"] = status
        self.row["status_detail"] = detail
        self.setProperty("completed", "true" if status == COMPLETED_STATUS else "false")
        analyzing = status == "분석 중"
        if analyzing:
            self._position_spinner()
            self.spinner.raise_()
            self.spinner.start()
        else:
            self.spinner.stop()
        self.row_quality_label.setVisible(not analyzing and self.row.get("kind") != "playlist")
        self.info_widget.setVisible(not analyzing)
        self.size_widget.setVisible(not analyzing)
        self._refresh_actions()
        self.set_progress(self.row.get("progress") or 0, self.row.get("progress_text") or "")

    def set_progress(self, value, text=""):
        bounded = max(0, min(100, int(float(value or 0))))
        status = self.row.get("status")
        active = status in ACTIVE_STATUSES
        error_detail = status == ERROR_STATUS and self.row.get("status_detail")
        display_text = text if active else (self.row.get("status_detail") if error_detail else "")
        active_value = "true" if active else "false"
        progress_value = str(bounded if active else 0)
        if (
            self.row.get("progress") == bounded
            and self.row.get("progress_text") == display_text
            and self.property("progressActive") == active_value
            and self.property("progressValue") == progress_value
            and self.progress_text.text() == display_text
            and self.progress_text.isVisible() == bool(display_text)
        ):
            return
        self.row["progress"] = bounded
        self.row["progress_text"] = display_text
        self.progress_bar.setValue(bounded)
        self.progress_bar.hide()
        self.setProperty("progressActive", active_value)
        self.setProperty("progressValue", progress_value)
        self.progress_text.setVisible(bool(display_text))
        self.progress_text.setText(display_text)
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
        if self.property("progressActive") != "true" and not completed:
            return
        _rect, full, gradient = self._progress_paths()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if completed:
            # Full rounded ring at the same width as the download progress arc,
            # so a finished row reads like a "100% green" version of it.
            hovered = self.property("hovered") == "true"
            color = theme.SUCCESS_BORDER_STRONG if hovered else theme.SUCCESS_BORDER
            painter.setPen(QPen(QColor(color), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(full)
            return

        progress = max(0, min(100, int(self.property("progressValue") or 0)))
        painter.setPen(QPen(QColor(theme.ACCENT_TINT), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(full)
        if progress <= 0:
            return
        partial = self._progress_partial_path(full, progress)
        painter.setPen(QPen(QBrush(gradient), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(partial)
