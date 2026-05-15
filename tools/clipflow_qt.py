import os
import sys
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
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
except ImportError:
    import candidate_presenter as presenter
    import downloader_engine as engine


APP_NAME = "ClipFlow"
DEFAULT_OUTPUT_EXT = "MP4"
COOKIE_CHOICES = ["없음", "Chrome", "Edge", "Firefox"]
COOKIE_DISPLAY_CHOICES = [f"쿠키: {choice}" for choice in COOKIE_CHOICES]
TOP_FIELD_HEIGHT = 42
PRIMARY_BUTTON_WIDTH = 150
THUMBNAIL_WIDTH = 96
MEDIA_MIN_WIDTH = 354
QUALITY_WIDTH = 88
FORMAT_WIDTH = 78
DURATION_WIDTH = 84
SIZE_WIDTH = 92
STATUS_WIDTH = 112
ACTIONS_WIDTH = 116
ROW_COLUMN_SPACING = 10
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\NotoSansKR-Regular.ttf",
    r"C:\Windows\Fonts\malgun.ttf",
]
_FONT_CONFIGURED = False

APP_STYLE = """
QMainWindow {
    background: #f5f9ff;
    font-family: "Noto Sans KR", "Malgun Gothic", "NanumGothic", "Segoe UI";
}
QFrame#Panel {
    background: #ffffff;
    border: 1px solid #dce6f4;
    border-radius: 12px;
}
QFrame#FieldBox {
    background: #ffffff;
    border: 1px solid #cad7e8;
    border-radius: 8px;
}
QFrame#DownloadRow {
    background: #ffffff;
    border: 1px solid #e1e8f3;
    border-radius: 0px;
}
QFrame#DownloadRow[selected="true"] {
    background: #ffffff;
    border-color: #e1e8f3;
}
QFrame#DownloadRow[hovered="true"] {
    background: #f8fbff;
    border-color: #c8d9f2;
}
QFrame#DownloadRow[selected="true"][hovered="true"] {
    background: #f8fbff;
    border-color: #c8d9f2;
}
QWidget#RowContainer {
    background: #ffffff;
}
QFrame#ThumbBox {
    background: #e9eff7;
    border: 1px solid #d8e2ef;
    border-radius: 6px;
}
QToolButton#SourceButton {
    background: #ef4444;
    color: #ffffff;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 700;
    padding: 0px;
}
QToolButton#SourceButton:hover {
    background: #dc2626;
}
QToolButton#HelpButton {
    background: #ffffff;
    border: 1px solid #9eb1ca;
    border-radius: 21px;
    color: #1f3b70;
    font-weight: 700;
}
QToolButton#HelpButton:hover {
    background: #edf4ff;
}
QToolButton#ActionButton {
    color: #243b5a;
    font-size: 15px;
}
QLabel {
    color: #1f2937;
    font-size: 13px;
}
QLabel#WindowTitle {
    font-size: 22px;
    font-weight: 700;
    color: #111827;
}
QLabel#SectionTitle {
    font-size: 17px;
    font-weight: 700;
    color: #111827;
}
QLabel#RowTitle {
    font-size: 14px;
    font-weight: 700;
    color: #111827;
}
QLabel#MetaText {
    color: #52627a;
    font-size: 12px;
}
QLabel#FieldIcon {
    color: #52627a;
    font-size: 16px;
}
QLabel#FormatValue {
    background: #ffffff;
    border: 1px solid #d5dfec;
    border-radius: 7px;
    padding: 7px 10px;
    color: #1f2937;
}
QLabel#QualityValue {
    background: #ffffff;
    border: 1px solid #d5dfec;
    border-radius: 7px;
    padding: 7px 10px;
    color: #1f2937;
}
QLabel#QualityValue[locked="true"], QLabel#FormatValue[locked="true"] {
    background: transparent;
    border: none;
    padding: 0px;
}
QLabel#StatusPill {
    border-radius: 12px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 700;
}
QLineEdit, QComboBox {
    background: #ffffff;
    border: 1px solid #cad7e8;
    border-radius: 8px;
    padding: 8px 10px;
    min-height: 22px;
}
QLineEdit#BareInput {
    background: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px;
}
QPushButton {
    background: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 9px 18px;
    font-weight: 700;
}
QPushButton:hover {
    background: #1d4ed8;
}
QPushButton:pressed {
    background: #1e40af;
}
QPushButton:disabled {
    background: #9db7e8;
}
QPushButton#SecondaryButton {
    background: #eef4ff;
    color: #1f3b70;
    border: 1px solid #cbdaf1;
}
QPushButton#SecondaryButton:hover {
    background: #e0ecff;
}
QToolButton {
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px;
}
QToolButton:hover {
    background: #edf4ff;
}
QToolButton:disabled {
    color: #aeb8c7;
}
QProgressBar {
    border: none;
    border-radius: 3px;
    background: #e7edf6;
    height: 6px;
    max-height: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background: #2563eb;
    border-radius: 3px;
}
QScrollArea {
    border: none;
    background: transparent;
}
"""

STATUS_STYLES = {
    "준비": "background: #eef2f7; color: #344054;",
    "대기": "background: #eef2f7; color: #344054;",
    "분석 중": "background: #e7f0ff; color: #1d4ed8;",
    "다운로드 중": "background: #e7f0ff; color: #1d4ed8;",
    "완료": "background: #dcfce7; color: #15803d;",
    "오류": "background: #fee2e2; color: #dc2626;",
}


def configure_app_font(app):
    global _FONT_CONFIGURED
    if _FONT_CONFIGURED:
        return
    selected_family = ""
    for font_path in FONT_CANDIDATES:
        if Path(font_path).exists():
            font_id = QFontDatabase.addApplicationFont(font_path)
            families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
            if families and not selected_family:
                selected_family = families[0]
    if not selected_family:
        selected_family = "Malgun Gothic"
    app.setFont(QFont(selected_family, 10))
    _FONT_CONFIGURED = True


def create_app_icon(size=64):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    rect = QRectF(4, 4, size - 8, size - 8)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, QColor("#38bdf8"))
    gradient.setColorAt(1.0, QColor("#2563eb"))
    painter.setPen(Qt.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(rect, 14, 14)

    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Noto Sans KR", max(12, int(size * 0.34)), QFont.Bold))
    painter.drawText(rect, Qt.AlignCenter, "Cf")
    painter.end()
    return QIcon(pixmap)


def source_domain(url):
    host = urlparse(url or "").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or "source"


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
    ranks = {"MP4": 0, "WEBM": 1, "WAV": 2}
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


def cookie_source_from_display(display_text):
    text = str(display_text or "").strip()
    if text.startswith("쿠키:"):
        text = text.split(":", 1)[1].strip()
    return text or "없음"


class ClearingUrlInput(QLineEdit):
    clicked_for_edit = Signal()

    def mousePressEvent(self, event):
        self.clicked_for_edit.emit()
        super().mousePressEvent(event)


class PathDisplayInput(QLineEdit):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, event):
        self.deselect()
        self.clearFocus()
        event.accept()

    def mouseMoveEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.deselect()
        event.accept()

    def keyPressEvent(self, event):
        event.ignore()


class LineIcon(QWidget):
    def __init__(self, icon_kind, parent=None):
        super().__init__(parent)
        self.icon_kind = icon_kind
        self.setFixedSize(22, 22)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor("#52627a")
        pen = QPen(color, 1.7)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        if self.icon_kind == "link":
            painter.drawArc(QRectF(4, 8, 9, 9), 35 * 16, 240 * 16)
            painter.drawArc(QRectF(9, 5, 9, 9), 215 * 16, 240 * 16)
            painter.drawLine(QPointF(9, 12), QPointF(13, 8))
        elif self.icon_kind == "folder":
            painter.drawLine(QPointF(4, 8), QPointF(9, 8))
            painter.drawLine(QPointF(9, 8), QPointF(11, 10))
            painter.drawLine(QPointF(11, 10), QPointF(18, 10))
            painter.drawRoundedRect(QRectF(3, 10, 16, 9), 2, 2)
        elif self.icon_kind == "cookie":
            painter.drawEllipse(QPointF(11, 11), 7, 7)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(8, 9), 1.1, 1.1)
            painter.drawEllipse(QPointF(12, 13), 1.0, 1.0)
            painter.drawEllipse(QPointF(14, 8), 0.9, 0.9)
        elif self.icon_kind == "clock":
            painter.drawEllipse(QPointF(11, 11), 7, 7)
            painter.drawLine(QPointF(11, 11), QPointF(11, 7))
            painter.drawLine(QPointF(11, 11), QPointF(14, 13))
        elif self.icon_kind == "file":
            painter.drawRoundedRect(QRectF(6, 4, 11, 15), 1.5, 1.5)
            painter.drawLine(QPointF(13, 4), QPointF(17, 8))
            painter.drawLine(QPointF(13, 4), QPointF(13, 8))
            painter.drawLine(QPointF(13, 8), QPointF(17, 8))
            painter.drawLine(QPointF(8, 12), QPointF(15, 12))
            painter.drawLine(QPointF(8, 15), QPointF(14, 15))


class CleanComboBox(QComboBox):
    def __init__(self, icon_kind=None, parent=None):
        super().__init__(parent)
        self.icon_kind = icon_kind
        self.setMinimumHeight(28)
        self.setMaximumHeight(30)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 1.0, -0.5, -1.0)
        enabled = self.isEnabled()
        hovered = self.underMouse()
        border_color = "#a9c5ef" if enabled and hovered else "#d7e0ec"
        border = QColor(border_color if enabled else "#e1e8f3")
        text = QColor("#111827" if enabled else "#98a2b3")
        background = QColor("#fbfdff" if enabled and hovered else ("#ffffff" if enabled else "#f8fafc"))

        painter.setPen(QPen(border, 1))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 6, 6)

        text_left = 38 if self.icon_kind else 11
        if self.icon_kind == "cookie":
            painter.save()
            painter.setPen(QPen(QColor("#52627a"), 1.5))
            painter.setBrush(Qt.NoBrush)
            center = QPointF(22, self.height() / 2)
            painter.drawEllipse(center, 7, 7)
            painter.setBrush(QColor("#52627a"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(center.x() - 3, center.y() - 2), 1.1, 1.1)
            painter.drawEllipse(QPointF(center.x() + 2, center.y() + 2), 1.0, 1.0)
            painter.drawEllipse(QPointF(center.x() + 3, center.y() - 4), 0.9, 0.9)
            painter.restore()

        text_rect = self.rect().adjusted(text_left, 0, -28, 0)
        painter.setPen(text)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.currentText())

        arrow_pen = QPen(QColor("#344054" if enabled else "#aeb8c7"), 1.6)
        arrow_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(arrow_pen)
        center_x = self.width() - 17
        center_y = self.height() // 2
        painter.drawLine(QPointF(center_x - 4, center_y - 1), QPointF(center_x, center_y + 3))
        painter.drawLine(QPointF(center_x, center_y + 3), QPointF(center_x + 4, center_y - 1))

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class ActionIconButton(QToolButton):
    def __init__(self, icon_kind, parent=None):
        super().__init__(parent)
        self.icon_kind = icon_kind
        self.setObjectName("ActionButton")
        self.setFixedSize(26, 26)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        hovered = self.underMouse() and self.isEnabled()
        if hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#e6f0ff" if not self.isDown() else "#d7e7ff"))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 6, 6)

        if not self.isEnabled():
            color = QColor("#aeb8c7")
        elif self.isDown():
            color = QColor("#1e40af")
        elif hovered:
            color = QColor("#1d4ed8")
        else:
            color = QColor("#243b5a")
        pen = QPen(color, 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        if self.icon_kind == "folder":
            painter.drawLine(QPointF(7, 10), QPointF(12, 10))
            painter.drawLine(QPointF(12, 10), QPointF(14, 12))
            painter.drawLine(QPointF(14, 12), QPointF(21, 12))
            painter.drawRoundedRect(QRectF(6, 12, 16, 10), 2, 2)
        elif self.icon_kind == "remove":
            painter.drawLine(QPointF(9, 9), QPointF(19, 19))
            painter.drawLine(QPointF(19, 9), QPointF(9, 19))
        elif self.icon_kind == "trash":
            painter.drawLine(QPointF(10, 9), QPointF(18, 9))
            painter.drawLine(QPointF(12, 7), QPointF(16, 7))
            painter.drawRoundedRect(QRectF(10, 11, 8, 11), 1.5, 1.5)
            painter.drawLine(QPointF(13, 13), QPointF(13, 20))
            painter.drawLine(QPointF(15, 13), QPointF(15, 20))
        elif self.icon_kind == "more":
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            for y in (9, 14, 19):
                painter.drawEllipse(QPointF(14, y), 1.35, 1.35)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class ThumbnailBox(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ThumbBox")
        self.setFixedSize(THUMBNAIL_WIDTH, 54)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor("#eef4fb"))
        gradient.setColorAt(0.55, QColor("#e1eaf4"))
        gradient.setColorAt(1.0, QColor("#d8e2ef"))

        painter.setPen(QPen(QColor("#d6e1ef"), 1))
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, 6, 6)

        painter.setPen(QPen(QColor("#cfdae8"), 1))
        for y in (15, 31, 47):
            painter.drawLine(QPointF(8, y), QPointF(88, y - 13))

        painter.setBrush(QColor("#8fa2ba"))
        painter.setPen(Qt.NoPen)
        center = QPointF(self.width() / 2 + 2, self.height() / 2)
        triangle = QPolygonF([
            QPointF(center.x() - 6, center.y() - 8),
            QPointF(center.x() - 6, center.y() + 8),
            QPointF(center.x() + 8, center.y()),
        ])
        painter.drawPolygon(triangle)


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
        self.setMinimumHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._build()
        self.refresh()

    def _build(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 5, 12, 5)
        outer.setSpacing(ROW_COLUMN_SPACING)

        self.thumbnail = ThumbnailBox()
        outer.addWidget(self.thumbnail)

        self.item_widget = QWidget()
        self.item_widget.setMinimumWidth(MEDIA_MIN_WIDTH - THUMBNAIL_WIDTH - ROW_COLUMN_SPACING)
        self.item_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        item_area = QVBoxLayout(self.item_widget)
        item_area.setContentsMargins(0, 0, 0, 0)
        item_area.setSpacing(3)
        self.title_label = QLabel()
        self.title_label.setObjectName("RowTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setTextInteractionFlags(Qt.NoTextInteraction)
        item_area.addWidget(self.title_label)

        source_line = QHBoxLayout()
        source_line.setSpacing(6)
        self.site_button = QToolButton()
        self.site_button.setObjectName("SourceButton")
        self.site_button.setText("▶")
        self.site_button.setFixedSize(18, 18)
        self.site_button.clicked.connect(self._open_source)
        source_line.addWidget(self.site_button)

        self.domain_label = QLabel("")
        self.domain_label.setObjectName("MetaText")
        source_line.addWidget(self.domain_label)
        source_line.addStretch(1)
        item_area.addLayout(source_line)

        outer.addWidget(self.item_widget, 1)

        self.quality_combo = CleanComboBox()
        self.quality_combo.setFixedWidth(QUALITY_WIDTH)
        self.quality_combo.currentIndexChanged.connect(self._quality_changed)
        outer.addWidget(self.quality_combo)

        self.quality_value_label = QLabel()
        self.quality_value_label.setObjectName("QualityValue")
        self.quality_value_label.setFixedWidth(QUALITY_WIDTH)
        self.quality_value_label.setMaximumHeight(30)
        self.quality_value_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.quality_value_label)

        self.format_combo = CleanComboBox()
        self.format_combo.setFixedWidth(FORMAT_WIDTH)
        self.format_combo.currentIndexChanged.connect(self._format_changed)
        outer.addWidget(self.format_combo)

        self.format_label = QLabel()
        self.format_label.setObjectName("FormatValue")
        self.format_label.setFixedWidth(FORMAT_WIDTH)
        self.format_label.setMaximumHeight(30)
        self.format_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.format_label)

        self.info_widget = QWidget()
        self.info_widget.setFixedWidth(DURATION_WIDTH)
        info_layout = QHBoxLayout(self.info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)
        info_layout.setAlignment(Qt.AlignCenter)
        self.info_icon = LineIcon("clock")
        self.info_icon.setFixedSize(18, 18)
        info_layout.addWidget(self.info_icon)
        self.info_label = QLabel()
        self.info_label.setObjectName("MetaText")
        self.info_label.setAlignment(Qt.AlignCenter)
        info_layout.addWidget(self.info_label)
        outer.addWidget(self.info_widget)

        self.size_widget = QWidget()
        self.size_widget.setFixedWidth(SIZE_WIDTH)
        size_layout = QHBoxLayout(self.size_widget)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.setSpacing(4)
        size_layout.setAlignment(Qt.AlignCenter)
        self.size_icon = LineIcon("file")
        self.size_icon.setFixedSize(18, 18)
        size_layout.addWidget(self.size_icon)
        self.size_label = QLabel()
        self.size_label.setAlignment(Qt.AlignCenter)
        size_layout.addWidget(self.size_label)
        outer.addWidget(self.size_widget)

        self.status_widget = QWidget()
        self.status_widget.setFixedWidth(STATUS_WIDTH)
        status_layout = QVBoxLayout(self.status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(3)
        status_layout.setAlignment(Qt.AlignCenter)

        self.status_row = QWidget()
        status_row_layout = QHBoxLayout(self.status_row)
        status_row_layout.setContentsMargins(0, 0, 0, 0)
        status_row_layout.setSpacing(4)
        status_row_layout.setAlignment(Qt.AlignCenter)

        self.status_label = QLabel()
        self.status_label.setObjectName("StatusPill")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setMinimumWidth(72)
        self.status_label.setMaximumHeight(28)
        status_row_layout.addWidget(self.status_label)

        status_layout.addWidget(self.status_row, 0, Qt.AlignCenter)

        self.progress_text = QLabel("")
        self.progress_text.setObjectName("MetaText")
        self.progress_text.setAlignment(Qt.AlignCenter)
        status_layout.addWidget(self.progress_text, 0, Qt.AlignCenter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setFixedWidth(76)
        status_layout.addWidget(self.progress_bar, 0, Qt.AlignCenter)
        outer.addWidget(self.status_widget)

        self.actions_widget = QWidget()
        self.actions_widget.setFixedWidth(ACTIONS_WIDTH)
        actions = QHBoxLayout(self.actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(4)
        actions.setAlignment(Qt.AlignCenter)
        self.open_folder_button = ActionIconButton("folder")
        self.open_folder_button.setToolTip("폴더 열기")
        self.open_folder_button.clicked.connect(self._open_folder)
        actions.addWidget(self.open_folder_button)

        self.remove_button = ActionIconButton("remove")
        self.remove_button.setToolTip("목록에서 삭제")
        self.remove_button.clicked.connect(self._remove_row)
        actions.addWidget(self.remove_button)

        self.delete_file_button = ActionIconButton("trash")
        self.delete_file_button.setToolTip("파일 삭제")
        self.delete_file_button.clicked.connect(self._delete_file)
        actions.addWidget(self.delete_file_button)

        self.more_button = ActionIconButton("more")
        self.more_button.setToolTip("더보기")
        actions.addWidget(self.more_button)
        outer.addWidget(self.actions_widget)

    def mousePressEvent(self, event):
        self.owner.select_row_for_widget(self)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.setProperty("hovered", "true")
        self._repolish()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty("hovered", "false")
        self._repolish()
        super().leaveEvent(event)

    def refresh(self):
        candidate = self.owner.selected_candidate_for_row_ref(self.row) or self.row["candidate"]
        title = candidate.get("display_title") or candidate.get("title") or "media"
        self.title_label.setText(str(title))
        self.title_label.setToolTip(str(title))
        self.info_label.setText(row_info_text(candidate))
        self.size_label.setText(engine.display_size(candidate.get("sort_bytes")))
        self._refresh_quality_combo()
        self._refresh_format_combo()
        self._refresh_source_button()
        self.set_status(self.row.get("status") or "준비", self.row.get("status_detail") or "")
        self.set_progress(self.row.get("progress") or 0, self.row.get("progress_text") or "")
        self._refresh_actions()

    def _refresh_quality_combo(self):
        options = self.row.get("quality_options") or []
        current = max(0, min(int(self.row.get("selected_index") or 0), len(options) - 1)) if options else 0
        self.row["selected_index"] = current
        self.quality_combo.blockSignals(True)
        self.quality_combo.clear()
        for option in options:
            self.quality_combo.addItem(option["label"])
        self.quality_combo.setCurrentIndex(current)
        self.quality_combo.blockSignals(False)
        self.quality_value_label.setText(self.quality_combo.currentText())
        self._refresh_quality_mode()

    def _refresh_format_combo(self):
        option = self.owner.selected_quality_option_for_row_ref(self.row)
        formats = option.get("formats") if option else []
        current = max(0, min(int(self.row.get("selected_format_index") or 0), len(formats) - 1)) if formats else 0
        self.row["selected_format_index"] = current
        self.format_combo.blockSignals(True)
        self.format_combo.clear()
        for item in formats:
            self.format_combo.addItem(item["label"])
        self.format_combo.setCurrentIndex(current)
        self.format_combo.blockSignals(False)
        candidate = self.owner.selected_candidate_for_row_ref(self.row) or self.row["candidate"]
        label = format_display_label(candidate)
        self.format_label.setText(label)

    def _refresh_source_button(self):
        source_url = self.row.get("source_url") or ""
        domain = source_domain(source_url)
        self.domain_label.setText(domain)
        self.site_button.setToolTip(f"{domain}\n원본 링크 열기")
        self.site_button.setEnabled(bool(source_url))

    def _refresh_actions(self):
        active = self.row.get("status") in {"분석 중", "다운로드 중"}
        output_path = Path(self.row.get("output_path") or "")
        self.remove_button.setEnabled(not active)
        self.delete_file_button.setEnabled(bool(self.row.get("output_path")) and output_path.exists() and not active)

    def _refresh_quality_mode(self):
        status = self.row.get("status") or "준비"
        completed = status == "완료"
        self.quality_value_label.setText(self.quality_combo.currentText())
        self.quality_combo.setHidden(completed)
        self.quality_value_label.setHidden(not completed)
        self.format_combo.setHidden(completed)
        self.format_label.setHidden(not completed)
        locked_value = "true" if completed else "false"
        self.quality_value_label.setProperty("locked", locked_value)
        self.format_label.setProperty("locked", locked_value)
        for widget in (self.quality_value_label, self.format_label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def _quality_changed(self, index):
        self.owner.quality_changed_for_row(self.row, index)

    def _format_changed(self, index):
        self.owner.format_changed_for_row(self.row, index)

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
        self.status_label.setText(status)
        self.status_label.setToolTip(detail or status)
        self.status_label.setStyleSheet(STATUS_STYLES.get(status, STATUS_STYLES["준비"]))
        self._refresh_quality_mode()
        self._refresh_actions()

    def set_progress(self, value, text=""):
        bounded = max(0, min(100, int(float(value or 0))))
        self.row["progress"] = bounded
        active = self.row.get("status") in {"분석 중", "다운로드 중"}
        error_detail = self.row.get("status") == "오류" and self.row.get("status_detail")
        display_text = text if active else (self.row.get("status_detail") if error_detail else "")
        self.row["progress_text"] = display_text
        self.progress_bar.setValue(bounded)
        show_progress = active and (bool(display_text) or bounded > 0)
        self.progress_bar.setVisible(show_progress)
        self.progress_text.setVisible(bool(display_text))
        self.progress_text.setText(display_text)


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
        self.resize(1080, 1280)
        self.setMinimumSize(1080, 640)
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
        icon = LineIcon(icon_kind)
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

        self.folder_input = PathDisplayInput(str(Path.home() / "Videos" / APP_NAME))
        self.folder_button = ActionIconButton("folder")
        self.folder_button.setToolTip("저장 폴더 선택")
        self.folder_button.clicked.connect(self._choose_folder)
        folder_field = self._field_box("folder", self.folder_input, self.folder_button)

        self.cookie_combo = CleanComboBox("cookie")
        self.cookie_combo.addItems(COOKIE_DISPLAY_CHOICES)
        self.cookie_combo.setFixedHeight(TOP_FIELD_HEIGHT)
        self.cookie_combo.setMinimumWidth(300)
        self.cookie_combo.setMaximumWidth(360)

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
            self.folder_input.setText(folder)

    def _handle_primary_action(self):
        if not self.url_input.text().strip():
            text = QApplication.clipboard().text().strip()
            if text:
                self.url_input.setText(text)
            return
        if self.selected_row_index >= 0 and self.rows:
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
            DEFAULT_OUTPUT_EXT,
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
                widget.size_label.setText(engine.display_size(candidate.get("sort_bytes")))
                widget.info_label.setText(row_info_text(candidate))
                widget._refresh_format_combo()
                widget.quality_value_label.setText(widget.quality_combo.currentText())

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
                widget.size_label.setText(engine.display_size(candidate.get("sort_bytes")))
                widget.info_label.setText(row_info_text(candidate))
                widget.format_label.setText(format_display_label(candidate))

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
        if sys.platform.startswith("win"):
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

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
        has_selection = self.selected_row_index >= 0 and bool(self.rows)
        if not has_url:
            self.primary_button.setText("붙여넣기")
        elif has_selection:
            self.primary_button.setText("다운로드")
        else:
            self.primary_button.setText("분석")

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
