# Auto-split from clipflow_qt.py; keep behavior changes in focused commits.
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from tools import downloader_engine as engine
    from tools.clipflow_icons import LucideIconButton, LucideIconWidget
    from tools.clipflow_theme import (
        ACTIONS_WIDTH,
        DURATION_WIDTH,
        MEDIA_MIN_WIDTH,
        ROW_COLUMN_SPACING,
        SIZE_WIDTH,
        THUMBNAIL_WIDTH,
    )
    from tools.clipflow_widgets import MarqueeLabel, SourceLinkButton, ThumbnailPlaceholder
except ImportError:
    import downloader_engine as engine
    from clipflow_icons import LucideIconButton, LucideIconWidget
    from clipflow_theme import (
        ACTIONS_WIDTH,
        DURATION_WIDTH,
        MEDIA_MIN_WIDTH,
        ROW_COLUMN_SPACING,
        SIZE_WIDTH,
        THUMBNAIL_WIDTH,
    )
    from clipflow_widgets import MarqueeLabel, SourceLinkButton, ThumbnailPlaceholder


ACTIVE_STATUSES = {"분석 중", "다운로드 중"}
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
    if kind == "playlist":
        count = engine.safe_int(candidate.get("item_count") or candidate.get("playlist_count"))
        return f"영상 {count}개" if count else "재생목록"
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
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._build()
        self.refresh()

    def _build(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 6, 12, 6)
        outer.setSpacing(ROW_COLUMN_SPACING)

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
        self.title_label = MarqueeLabel()
        self.title_label.setObjectName("RowTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setTextInteractionFlags(Qt.NoTextInteraction)
        title_line.addWidget(self.title_label, 1)
        item_area.addLayout(title_line)

        source_line = QHBoxLayout()
        source_line.setSpacing(6)
        self.source_link_button = SourceLinkButton()
        self.source_link_button.clicked.connect(self._open_source)
        source_line.addWidget(self.source_link_button)
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

        self.actions_widget = QFrame(self)
        self.actions_widget.setObjectName("ActionOverlay")
        self.actions_widget.setFixedWidth(ACTIONS_WIDTH + 32)
        actions = QHBoxLayout(self.actions_widget)
        actions.setContentsMargins(8, 0, 8, 0)
        actions.setSpacing(4)
        actions.setAlignment(Qt.AlignCenter)

        self.open_folder_button = LucideIconButton("folder")
        self.open_folder_button.setToolTip("폴더 열기")
        self.open_folder_button.clicked.connect(self._open_folder)
        actions.addWidget(self.open_folder_button)

        self.remove_button = LucideIconButton("x")
        self.remove_button.setToolTip("목록에서 삭제")
        self.remove_button.clicked.connect(self._remove_row)
        actions.addWidget(self.remove_button)

        self.delete_file_button = LucideIconButton("trash-2", danger=True)
        self.delete_file_button.setToolTip("파일 삭제")
        self.delete_file_button.clicked.connect(self._delete_file)
        actions.addWidget(self.delete_file_button)

        self.more_button = LucideIconButton("more-vertical")
        self.more_button.setToolTip("더보기")
        actions.addWidget(self.more_button)
        self.actions_widget.hide()

    def mousePressEvent(self, event):
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
        super().resizeEvent(event)

    def refresh(self):
        candidate = self.owner.selected_candidate_for_row_ref(self.row) or self.row["candidate"]
        title = candidate.get("display_title") or candidate.get("title") or "media"
        self.title_label.setText(str(title))
        self.title_label.setToolTip(str(title))
        self.title_label.start_marquee_if_needed()
        self.info_label.setText(row_info_text(candidate))
        self.size_label.setText(engine.display_size(candidate_size_value(candidate)))
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
        self.open_folder_button.setEnabled(completed and not active)
        self.remove_button.setEnabled(completed and not active)
        self.delete_file_button.setEnabled(completed and has_output and not active)
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
        self.playlist_toggle_button.setVisible(is_playlist)
        self.playlist_detail_label.setVisible(is_playlist and bool(self.row.get("expanded")))
        self.playlist_detail_label.setText(self._playlist_detail_text() if is_playlist else "")

    def _toggle_playlist(self):
        if self.row.get("kind") != "playlist":
            return
        self.row["expanded"] = not bool(self.row.get("expanded"))
        self._refresh_playlist_detail()
        self.updateGeometry()
        self.owner.playlist_expansion_changed(self.row)

    def _position_actions(self):
        width = self.actions_widget.width()
        self.actions_widget.setGeometry(max(0, self.width() - width - 6), 0, width, self.height())
        self.actions_widget.raise_()

    def _set_hovered(self, hovered):
        self.setProperty("hovered", "true" if hovered else "false")
        show_actions = hovered and self.row.get("status") == COMPLETED_STATUS
        self.actions_widget.setVisible(show_actions)
        if show_actions:
            self._position_actions()
        self._refresh_actions()
        self._repolish()

    def _open_source(self):
        self.owner.open_source_for_row(self.row)

    def _open_folder(self):
        self.owner.open_folder_for_row(self.row)

    def _remove_row(self):
        self.owner.remove_row(self.row)

    def _delete_file(self):
        self.owner.delete_file_for_row(self.row)

    def set_selected(self, selected):
        self.setProperty("selected", "true" if selected else "false")
        self._repolish()

    def _repolish(self):
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_status(self, status, detail=""):
        self.row["status"] = status
        self.row["status_detail"] = detail
        self._refresh_actions()
        self.set_progress(self.row.get("progress") or 0, self.row.get("progress_text") or "")

    def set_progress(self, value, text=""):
        bounded = max(0, min(100, int(float(value or 0))))
        self.row["progress"] = bounded
        status = self.row.get("status")
        active = status in ACTIVE_STATUSES
        error_detail = status == ERROR_STATUS and self.row.get("status_detail")
        display_text = text if active else (self.row.get("status_detail") if error_detail else "")
        self.row["progress_text"] = display_text
        self.progress_bar.setValue(bounded)
        self.progress_bar.hide()
        self.setProperty("progressActive", "true" if active and bounded > 0 else "false")
        self.setProperty("progressValue", str(bounded if active else 0))
        self.progress_text.setVisible(bool(display_text))
        self.progress_text.setText(display_text)
        self._repolish()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.property("progressActive") != "true":
            return
        progress = max(0, min(100, int(self.property("progressValue") or 0)))
        if progress <= 0:
            return
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        width = rect.width()
        height = rect.height()
        perimeter = max(1.0, 2 * (width + height))
        remaining = perimeter * progress / 100.0
        points = [
            (rect.left(), rect.top(), rect.right(), rect.top(), width),
            (rect.right(), rect.top(), rect.right(), rect.bottom(), height),
            (rect.right(), rect.bottom(), rect.left(), rect.bottom(), width),
            (rect.left(), rect.bottom(), rect.left(), rect.top(), height),
        ]
        path = QPainterPath()
        path.moveTo(rect.left(), rect.top())
        current_x = rect.left()
        current_y = rect.top()
        for x1, y1, x2, y2, length in points:
            if remaining <= 0:
                break
            draw = min(remaining, length)
            ratio = draw / length if length else 0
            next_x = x1 + (x2 - x1) * ratio
            next_y = y1 + (y2 - y1) * ratio
            if current_x != x1 or current_y != y1:
                path.moveTo(x1, y1)
            path.lineTo(next_x, next_y)
            current_x, current_y = next_x, next_y
            remaining -= draw

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(rect.topLeft(), rect.topRight())
        gradient.setColorAt(0.0, QColor("#2563EB"))
        gradient.setColorAt(0.45, QColor("#06B6D4"))
        gradient.setColorAt(0.75, QColor("#22C55E"))
        gradient.setColorAt(1.0, QColor("#A855F7"))
        painter.setPen(QPen(QBrush(gradient), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)
