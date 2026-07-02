import html as html_lib
import re
from urllib.parse import urljoin, urlparse

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QCheckBox, QComboBox, QFrame, QLabel, QLineEdit, QPushButton, QToolButton, QVBoxLayout, QWidget
from shiboken6 import isValid

try:
    from tools.clipflow_icons import ICON_COLOR, ICON_DISABLED_COLOR, ICON_HOVER_COLOR, LucideIconWidget, lucide_pixmap
    from tools.clipflow_theme import THUMBNAIL_WIDTH
    from tools import clipflow_theme as theme
except ImportError:
    from clipflow_icons import ICON_COLOR, ICON_DISABLED_COLOR, ICON_HOVER_COLOR, LucideIconWidget, lucide_pixmap
    from clipflow_theme import THUMBNAIL_WIDTH
    import clipflow_theme as theme


THUMBNAIL_PREVIEW_SCALE = 4
THUMBNAIL_PREVIEW_CURSOR_GAP = 10


class Spinner(QWidget):
    """A small indeterminate loading spinner (rotating accent arc)."""

    def __init__(self, size=20, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._advance)

    def start(self):
        if not self._timer.isActive():
            self._timer.start()
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _advance(self):
        self._angle = (self._angle - 30) % 360
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(theme.ACCENT), 2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        margin = 2
        rect = QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)
        painter.drawArc(rect, int(self._angle * 16), int(270 * 16))


class CleanCheckBox(QCheckBox):
    """A self-painted checkbox: rounded square, accent fill with a white check
    when checked. Replaces the platform indicator for a clean, consistent look."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(20, 20)

    def sizeHint(self):
        return QSize(20, 20)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        size = 18
        x = (self.width() - size) // 2
        y = (self.height() - size) // 2
        rect = QRectF(x, y, size, size)
        if self.isChecked():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawRoundedRect(rect, 5, 5)
            painter.drawPixmap(x + 2, y + 2, 14, 14, lucide_pixmap("check", 14, "#FFFFFF"))
        else:
            border = theme.ACCENT if self.underMouse() else theme.FIELD_BORDER_HOVER
            painter.setPen(QPen(QColor(border), 1.4))
            painter.setBrush(QColor(theme.SURFACE))
            painter.drawRoundedRect(rect, 5, 5)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class ClearingUrlInput(QLineEdit):
    clicked_for_edit = Signal()
    pasted = Signal()

    def mousePressEvent(self, event):
        self.clicked_for_edit.emit()
        super().mousePressEvent(event)

    def insertFromMimeData(self, source):
        super().insertFromMimeData(source)
        self.pasted.emit()

    def _set_field_focus(self, focused):
        box = self.parent()
        if box is not None and box.objectName() == "FieldBox":
            box.setProperty("focused", "true" if focused else "false")
            box.style().unpolish(box)
            box.style().polish(box)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._set_field_focus(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._set_field_focus(False)


class PathDisplayInput(QLineEdit):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setReadOnly(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.IBeamCursor)

    def _set_field_focus(self, focused):
        box = self.parent()
        if box is not None and box.objectName() == "FieldBox":
            box.setProperty("focused", "true" if focused else "false")
            box.style().unpolish(box)
            box.style().polish(box)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._set_field_focus(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._set_field_focus(False)


class TimecodeInput(QWidget):
    textChanged = Signal(str)
    editingComplete = Signal()

    def __init__(self, placeholder=None, parent=None):
        del placeholder
        super().__init__(parent)
        self.setObjectName("BareInput")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.IBeamCursor)
        self._parts = [None, None, None]
        self._selected_segment = None
        self._entry_buffer = ""
        self._segment_rects = []
        self.setMinimumSize(164, 28)

    def placeholderText(self):
        return "HH:MM:SS"

    def sizeHint(self):
        return QSize(164, 28)

    def selected_segment(self):
        return -1 if self._selected_segment is None else self._selected_segment

    def has_selected_segment(self):
        return self._selected_segment is not None

    def set_selected_segment(self, segment):
        self._selected_segment = max(0, min(2, int(segment)))
        self._entry_buffer = ""
        self.setFocus(Qt.MouseFocusReason)
        self.update()

    def display_text(self):
        labels = ("HH", "MM", "SS")
        return ":".join(labels[index] if value is None else f"{value:02d}" for index, value in enumerate(self._parts))

    def text(self):
        if all(value is None for value in self._parts):
            return ""
        return ":".join(f"{(value if value is not None else 0):02d}" for value in self._parts)

    def setText(self, text):
        old = self.text()
        text = str(text or "").strip()
        if not text:
            self._parts = [None, None, None]
        else:
            if text.isdigit():
                padded = text[:6].ljust(6, "0")
                raw_parts = [padded[0:2], padded[2:4], padded[4:6]]
            else:
                raw_parts = text.split(":")
                if len(raw_parts) > 3:
                    raw_parts = raw_parts[:3]
                while len(raw_parts) < 3:
                    raw_parts.append("0")
            values = []
            for raw in raw_parts:
                try:
                    value = int(raw or 0)
                except ValueError:
                    value = 0
                values.append(max(0, min(99, value)))
            self._parts = values
        self._entry_buffer = ""
        self.update()
        if self.text() != old:
            self.textChanged.emit(self.text())

    def clear(self):
        self.setText("")

    def set_time_parts(self, hours, minutes, seconds):
        self.setText(f"{int(hours or 0):02d}:{int(minutes or 0):02d}:{int(seconds or 0):02d}")

    def normalize_text(self):
        return self.text()

    def time_seconds(self):
        text = self.text()
        if not text:
            return None
        hours, minutes, seconds = (int(part or 0) for part in text.split(":"))
        return float(hours * 3600 + minutes * 60 + seconds)

    def mousePressEvent(self, event):
        for index, rect in enumerate(self._segment_rects):
            if rect.contains(event.position().toPoint()):
                self.set_selected_segment(index)
                event.accept()
                return
        self.set_selected_segment(0)
        event.accept()

    def keyPressEvent(self, event):
        key = event.key()
        text = event.text()
        if text.isdigit():
            self._type_digit(text)
            event.accept()
            return
        if key in (Qt.Key_Left, Qt.Key_Backtab):
            self.set_selected_segment(max(0, self.selected_segment() - 1))
            event.accept()
            return
        if key in (Qt.Key_Right, Qt.Key_Tab):
            self.set_selected_segment(min(2, self.selected_segment() + 1))
            event.accept()
            return
        if key in (Qt.Key_Backspace, Qt.Key_Delete):
            if self._selected_segment is None:
                self.set_selected_segment(0)
            self._parts[self._selected_segment] = None
            self._entry_buffer = ""
            self.update()
            self.textChanged.emit(self.text())
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        self._entry_buffer = ""
        super().focusOutEvent(event)

    def _type_digit(self, digit):
        if self._selected_segment is None:
            self.set_selected_segment(0)
        segment = self._selected_segment
        self._entry_buffer = (self._entry_buffer + digit)[-2:]
        value = int(self._entry_buffer)
        limit = 99 if segment == 0 else 59
        if value > limit:
            self._parts[segment] = None
            self._entry_buffer = ""
            self.update()
            self.textChanged.emit(self.text())
            return
        for index in range(segment):
            if self._parts[index] is None:
                self._parts[index] = 0
        self._parts[segment] = value
        if len(self._entry_buffer) >= 2:
            if segment < 2:
                self._selected_segment = segment + 1
            else:
                self.editingComplete.emit()
            self._entry_buffer = ""
        self.update()
        self.textChanged.emit(self.text())

    def _part_rects(self, painter):
        metrics = painter.fontMetrics()
        box_width = 34
        box_height = min(28, max(24, self.height() - 4))
        unit_gap = 4
        group_gap = 8
        unit_widths = [metrics.horizontalAdvance(unit) for unit in ("h", "m", "s")]
        total = box_width * 3 + unit_gap * 3 + sum(unit_widths) + group_gap * 2
        x = (self.width() - total) / 2
        y = (self.height() - box_height) // 2
        rects = []
        for index, unit_width in enumerate(unit_widths):
            rects.append(QRect(int(x), y, box_width, box_height))
            x += box_width + unit_gap + unit_width
            if index < 2:
                x += group_gap
        return rects

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = painter.font()
        font.setPixelSize(13)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        self._segment_rects = self._part_rects(painter)
        labels = self.display_text().split(":")
        metrics = painter.fontMetrics()
        units = ("h", "m", "s")
        for index, label in enumerate(labels):
            selected = index == self._selected_segment and self.hasFocus()
            rect = self._segment_rects[index]
            painter.setPen(QPen(QColor(theme.ACCENT if selected else theme.FIELD_BORDER), 1))
            painter.setBrush(QColor(theme.ACCENT_TINT if selected else theme.SURFACE))
            painter.drawRoundedRect(rect, 7, 7)
            color = theme.MUTED if self._parts[index] is None else theme.INK
            painter.setPen(QColor(color))
            painter.drawText(rect, Qt.AlignCenter, "--" if self._parts[index] is None else label)
            unit_x = rect.right() + 5
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(QRect(unit_x, 0, metrics.horizontalAdvance(units[index]) + 1, self.height()), Qt.AlignVCenter | Qt.AlignLeft, units[index])


def _rounded_pixmap(pixmap, width, height, radius):
    scaled = pixmap.scaled(width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    result = QPixmap(width, height)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, width, height), radius, radius)
    painter.setClipPath(path)
    x = (width - scaled.width()) // 2
    y = (height - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    return result


def source_domain(url):
    parsed = urlparse(str(url or ""))
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
ATTR_RE = re.compile(r"""([:\w-]+)\s*=\s*("[^"]*"|'[^']*'|[^\s"'=<>`]+)""", re.IGNORECASE)


def _tag_attributes(tag):
    attributes = {}
    for key, raw_value in ATTR_RE.findall(str(tag or "")):
        value = raw_value.strip()
        if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
            value = value[1:-1]
        attributes[key.lower()] = html_lib.unescape(value)
    return attributes


def favicon_urls_from_html(html_text, page_url):
    urls = []
    seen = set()
    for tag in LINK_TAG_RE.findall(str(html_text or "")):
        attrs = _tag_attributes(tag)
        rel = attrs.get("rel", "").lower()
        href = attrs.get("href", "").strip()
        if "icon" not in rel or not href:
            continue
        icon_url = urljoin(page_url, href)
        if icon_url and icon_url not in seen:
            seen.add(icon_url)
            urls.append(icon_url)
    return urls


def default_favicon_urls(url):
    parsed = urlparse(str(url or ""))
    scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
    if not parsed.netloc:
        return []
    origin = f"{scheme}://{parsed.netloc}"
    return [
        f"{origin}/favicon.ico",
        f"{origin}/favicon.png",
        f"{origin}/apple-touch-icon.png",
    ]


class AboveTooltipMixin:
    def tooltip_position(self):
        return self.mapToGlobal(QPoint(0, -self.sizeHint().height() - 10))


class MarqueeLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._marquee_offset = 0
        self._marquee_timer = QTimer(self)
        self._marquee_timer.setInterval(80)
        self._marquee_timer.timeout.connect(self._advance_marquee)

    def start_marquee_if_needed(self):
        overflow = self.fontMetrics().horizontalAdvance(self.text()) > max(1, self.width() - 4)
        if overflow and not self._marquee_timer.isActive():
            self._marquee_timer.start()
        elif not overflow:
            self.stop_marquee()

    def stop_marquee(self):
        self._marquee_timer.stop()
        self._marquee_offset = 0
        self.update()

    def _advance_marquee(self):
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        if text_width <= self.width():
            self.stop_marquee()
            return
        self._marquee_offset = (self._marquee_offset + 2) % (text_width + 36)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.start_marquee_if_needed()

    def paintEvent(self, event):
        if not self._marquee_timer.isActive() or not self.text():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setPen(QColor(theme.INK))
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        y = (self.height() + self.fontMetrics().ascent() - self.fontMetrics().descent()) // 2
        x = -self._marquee_offset
        painter.drawText(x, y, self.text())
        painter.drawText(x + text_width + 36, y, self.text())


class SourceLinkButton(AboveTooltipMixin, QToolButton):
    _network_manager = None
    _icon_cache = {}
    _youtube_icon_cache = {}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source_url = ""
        self.favicon_url = ""
        self._reply = None
        self._icon_candidates = []
        self._seen_icon_candidates = set()
        self._page_checked = False
        self.setObjectName("SourceLinkButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.setIconSize(QSize(20, 20))
        self.setFixedSize(20, 20)
        self.setAutoRaise(True)
        self._set_fallback_icon()

    @classmethod
    def network_manager(cls):
        if cls._network_manager is None:
            cls._network_manager = QNetworkAccessManager()
        return cls._network_manager

    def set_source_url(self, url):
        url = str(url or "").strip()
        if url == self.source_url:
            return
        self.source_url = url
        domain = source_domain(url)
        self.setText("")
        self.setToolTip(f"{domain}\n원본 링크 열기" if domain else "")
        self.setEnabled(bool(url))
        self._set_fallback_icon()
        if self._reply:
            self._reply.abort()
            self._reply = None
        if not domain:
            self.favicon_url = ""
            return
        if domain in {"youtube.com", "youtu.be"} or domain.endswith(".youtube.com"):
            self.setIcon(QIcon(self._youtube_icon(20)))
            self.favicon_url = ""
            return
        cached = self._icon_cache.get(domain)
        if cached:
            self.setIcon(cached)
            return
        self._icon_candidates = []
        self._seen_icon_candidates = set()
        self._page_checked = False
        self._queue_icon_candidates(default_favicon_urls(url))
        self._fetch_next_icon_candidate()

    def _set_fallback_icon(self):
        self.setIcon(QIcon(lucide_pixmap("globe-2", 20, ICON_COLOR)))

    def _icon_target_rect(self):
        icon_size = self.iconSize()
        draw_size = min(icon_size.width(), icon_size.height(), max(1, self.width()), max(1, self.height()))
        return QRect((self.width() - draw_size) // 2, (self.height() - draw_size) // 2, draw_size, draw_size)

    @classmethod
    def _youtube_icon(cls, size):
        cached = cls._youtube_icon_cache.get(size)
        if cached:
            return cached
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#FF0000"))
        painter.drawRoundedRect(QRectF(0.5, 2, size - 1, size - 4), 4, 4)
        play = QPainterPath()
        play.moveTo(size * 0.40, size * 0.31)
        play.lineTo(size * 0.40, size * 0.69)
        play.lineTo(size * 0.72, size * 0.50)
        play.closeSubpath()
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawPath(play)
        painter.end()
        cls._youtube_icon_cache[size] = pixmap
        return pixmap

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.underMouse() and self.isEnabled():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.SURFACE_SOFT))
            painter.drawRoundedRect(QRectF(self.rect()), 5, 5)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = self._icon_target_rect()
        pixmap = self.icon().pixmap(rect.size())
        if not pixmap.isNull():
            painter.drawPixmap(rect, pixmap)

    def _queue_icon_candidates(self, urls):
        for icon_url in urls:
            if not icon_url or icon_url in self._seen_icon_candidates:
                continue
            self._seen_icon_candidates.add(icon_url)
            self._icon_candidates.append(icon_url)

    def _make_request(self, url):
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", b"Mozilla/5.0")
        request.setRawHeader(b"Accept", b"text/html,image/avif,image/webp,image/png,image/svg+xml,image/*,*/*;q=0.8")
        return request

    def _fetch_next_icon_candidate(self):
        domain = source_domain(self.source_url)
        while self._icon_candidates:
            self.favicon_url = self._icon_candidates.pop(0)
            reply = self.network_manager().get(self._make_request(self.favicon_url))
            self._reply = reply
            reply.finished.connect(
                lambda reply=reply, domain=domain, favicon_url=self.favicon_url: self._favicon_finished(
                    reply, domain, favicon_url
                )
            )
            return
        if self.source_url and not self._page_checked:
            self._page_checked = True
            page_url = self.source_url
            reply = self.network_manager().get(self._make_request(page_url))
            self._reply = reply
            reply.finished.connect(lambda reply=reply, page_url=page_url: self._icon_page_finished(reply, page_url))
            return
        self.favicon_url = ""

    def _favicon_finished(self, reply, domain, favicon_url):
        if not isValid(self):
            reply.deleteLater()
            return
        if reply is not self._reply:
            reply.deleteLater()
            return
        self._reply = None
        try:
            if favicon_url != self.favicon_url:
                return
            if reply.error() != QNetworkReply.NoError:
                self._fetch_next_icon_candidate()
                return
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()) and not pixmap.isNull():
                icon = QIcon(pixmap)
                self._icon_cache[domain] = icon
                if domain == source_domain(self.source_url):
                    self.setIcon(icon)
            else:
                self._fetch_next_icon_candidate()
        finally:
            reply.deleteLater()

    def _icon_page_finished(self, reply, page_url):
        if not isValid(self):
            reply.deleteLater()
            return
        if reply is not self._reply:
            reply.deleteLater()
            return
        self._reply = None
        try:
            if reply.error() == QNetworkReply.NoError:
                html_bytes = bytes(reply.readAll())
                html_text = html_bytes[:524288].decode("utf-8", "ignore")
                self._queue_icon_candidates(favicon_urls_from_html(html_text, page_url))
            self._fetch_next_icon_candidate()
        finally:
            reply.deleteLater()


class ComboPopup(QFrame):
    """Self-painted dropdown surface.

    macOS dark-mode does not propagate the app stylesheet to Qt.Popup
    top-level windows, so the background is painted directly here to guarantee
    a light surface regardless of OS appearance or stylesheet cascade.
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.setBrush(QColor(theme.SURFACE))
        painter.drawRoundedRect(rect, 10, 10)

    def closeEvent(self, event):
        parent = self.parent()
        if parent is not None:
            setattr(parent, "_ignore_next_popup", True)
            QTimer.singleShot(200, lambda owner=parent: setattr(owner, "_ignore_next_popup", False))
        super().closeEvent(event)


class CleanComboBox(QComboBox):
    def __init__(self, icon_kind=None, parent=None):
        super().__init__(parent)
        self.icon_kind = icon_kind
        self.show_arrow = True
        self.text_alignment = Qt.AlignLeft
        self.setMinimumHeight(28)
        self.setMaximumHeight(42)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 1.0, -0.5, -1.0)
        enabled = self.isEnabled()
        hovered = self.underMouse()
        border_color = theme.FIELD_BORDER_HOVER if enabled and hovered else theme.FIELD_BORDER
        text_color = theme.INK if enabled else theme.MUTED_SOFT
        background = theme.SURFACE_SOFT if enabled and hovered else (theme.SURFACE if enabled else theme.SURFACE_SUNKEN)

        painter.setPen(QPen(QColor(border_color if enabled else theme.BORDER), 1))
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, 8, 8)

        enabled_icon_color = ICON_HOVER_COLOR if enabled and hovered else (ICON_COLOR if enabled else ICON_DISABLED_COLOR)
        text = self.currentText()
        text_font = painter.font()
        text_font.setPixelSize(13)
        text_font.setWeight(QFont.DemiBold)
        painter.setFont(text_font)
        center = bool(self.text_alignment & Qt.AlignHCenter)

        if center:
            # Centre the icon + text together so the pair sits truly centred.
            metrics = painter.fontMetrics()
            icon_width = 16 if self.icon_kind else 0
            icon_gap = 6 if self.icon_kind else 0
            group_width = icon_width + icon_gap + metrics.horizontalAdvance(text)
            start_x = max(10.0, (self.width() - group_width) / 2)
            if self.icon_kind:
                painter.drawPixmap(int(start_x), (self.height() - 16) // 2, 16, 16, lucide_pixmap(self.icon_kind, 16, enabled_icon_color))
            text_x = start_x + icon_width + icon_gap
            painter.setPen(QColor(text_color))
            painter.drawText(QRectF(text_x, 0, self.width() - text_x, self.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        else:
            if self.icon_kind:
                painter.drawPixmap(14, (self.height() - 16) // 2, 16, 16, lucide_pixmap(self.icon_kind, 16, enabled_icon_color))
            text_left = 38 if self.icon_kind else 11
            text_rect = self.rect().adjusted(text_left, 0, -28 if self.show_arrow else -11, 0)
            painter.setPen(QColor(text_color))
            painter.drawText(text_rect, Qt.AlignVCenter | self.text_alignment, text)

        if self.show_arrow:
            arrow_color = ICON_HOVER_COLOR if enabled and hovered else (ICON_COLOR if enabled else ICON_DISABLED_COLOR)
            painter.drawPixmap(self.width() - 22, (self.height() - 14) // 2, 14, 14, lucide_pixmap("chevron-down", 14, arrow_color))

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def changeEvent(self, event):
        self.update()
        super().changeEvent(event)

    def mousePressEvent(self, event):
        active_popup = getattr(self, "_active_popup", None)
        if active_popup and active_popup.isVisible():
            active_popup.close()
            active_popup.deleteLater()
            self._active_popup = None
            self._suppress_next_release_popup = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self, "_suppress_next_release_popup", False):
            self._suppress_next_release_popup = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def showPopup(self):
        if getattr(self, "_ignore_next_popup", False):
            self._ignore_next_popup = False
            return
        active_popup = getattr(self, "_active_popup", None)
        if active_popup and active_popup.isVisible():
            active_popup.close()
            active_popup.deleteLater()
            self._active_popup = None
            return
        # Self-painted popup (see ComboPopup) + explicit per-popup stylesheet,
        # because Qt.Popup windows do not inherit the app stylesheet on macOS.
        popup = ComboPopup(self)
        popup.setStyleSheet(
            f"QPushButton#ComboOption {{"
            f" background: transparent; border: none; border-radius: 7px;"
            f" padding: 6px 10px 6px 10px; color: {theme.INK};"
            f" font-size: 13px; font-weight: 500; text-align: left; }}"
            f"QPushButton#ComboOption:hover {{ background: {theme.SURFACE_SOFT}; }}"
            f"QPushButton#ComboOption[selected=\"true\"] {{ color: {theme.ACCENT}; font-weight: 700; }}"
        )
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(1)
        current = self.currentIndex()
        for index in range(self.count()):
            option = QPushButton(self.itemText(index), popup)
            option.setObjectName("ComboOption")
            option.setProperty("selected", "true" if index == current else "false")
            option.setCursor(Qt.PointingHandCursor)
            option.setFlat(True)
            option.clicked.connect(lambda _checked=False, idx=index, pop=popup: self._choose_option(idx, pop))
            layout.addWidget(option)
        popup.adjustSize()
        popup.setFixedWidth(max(self.width(), popup.sizeHint().width()))
        popup.move(self.mapToGlobal(QPoint(0, self.height() + 6)))
        self._active_popup = popup
        popup.show()

    def _choose_option(self, index, popup):
        popup.close()
        popup.deleteLater()
        self._active_popup = None
        self.setCurrentIndex(index)

    def hidePopup(self):
        super().hidePopup()


class ThumbnailPlaceholder(QFrame):
    _network_manager = None
    _active_preview_owner = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ThumbBox")
        self.setFixedSize(THUMBNAIL_WIDTH, 54)
        self.setMouseTracking(True)
        self.icon = LucideIconWidget("play", size=22, color=theme.MUTED, parent=self)
        self.thumbnail_url = ""
        self._pixmap = QPixmap()
        self._scaled_pixmap = QPixmap()
        self._scaled_target_size = QSize()
        self._reply = None
        self._preview = None
        self._preview_label = None
        self._preview_pixmap = QPixmap()
        self._preview_pixmap_key = None
        self._preview_hide_timer = QTimer(self)
        self._preview_hide_timer.setSingleShot(True)
        self._preview_hide_timer.setInterval(90)
        self._preview_hide_timer.timeout.connect(self._hide_preview_if_cursor_left)

    @classmethod
    def network_manager(cls):
        if cls._network_manager is None:
            cls._network_manager = QNetworkAccessManager()
        return cls._network_manager

    def set_thumbnail_url(self, url, referer=""):
        url = str(url or "").strip()
        if url == self.thumbnail_url:
            return
        self.thumbnail_url = url
        self._pixmap = QPixmap()
        self._scaled_pixmap = QPixmap()
        self._scaled_target_size = QSize()
        self._preview_pixmap = QPixmap()
        self._preview_pixmap_key = None
        self.icon.show()
        if self._reply:
            self._reply.abort()
            self._reply = None
        if not url:
            self.update()
            return
        parsed = QUrl.fromUserInput(url)
        if parsed.isLocalFile():
            self._set_pixmap(QPixmap(parsed.toLocalFile()))
            return
        if parsed.scheme() not in {"http", "https"}:
            self.update()
            return
        request = QNetworkRequest(parsed)
        if referer:
            request.setRawHeader(b"Referer", str(referer).encode("utf-8"))
        self._reply = self.network_manager().get(request)
        self._reply.finished.connect(self._thumbnail_finished)

    def _thumbnail_finished(self):
        reply = self._reply
        self._reply = None
        if not reply:
            return
        try:
            if reply.error() == QNetworkReply.NoError:
                pixmap = QPixmap()
                if pixmap.loadFromData(reply.readAll()):
                    self._set_pixmap(pixmap)
        finally:
            reply.deleteLater()

    def _set_pixmap(self, pixmap):
        self._scaled_pixmap = QPixmap()
        self._scaled_target_size = QSize()
        self._preview_pixmap = QPixmap()
        self._preview_pixmap_key = None
        if pixmap.isNull():
            self.icon.show()
            self.update()
            return
        self._pixmap = pixmap
        self.icon.hide()
        self.update()

    def resizeEvent(self, event):
        self.icon.move((self.width() - self.icon.width()) // 2, (self.height() - self.icon.height()) // 2)
        super().resizeEvent(event)

    def _scaled_thumbnail_pixmap(self):
        target_size = self.size()
        if self._scaled_pixmap.isNull() or self._scaled_target_size != target_size:
            self._scaled_pixmap = self._pixmap.scaled(target_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            self._scaled_target_size = QSize(target_size.width(), target_size.height())
        return self._scaled_pixmap

    @staticmethod
    def preview_geometry(cursor_pos, preview_size, screen_rect):
        width = preview_size.width()
        height = preview_size.height()
        gap = THUMBNAIL_PREVIEW_CURSOR_GAP
        x = cursor_pos.x() + gap
        y = cursor_pos.y() - height - gap + 1
        if x + width - 1 > screen_rect.right():
            x = cursor_pos.x() - width - gap + 1
        if y < screen_rect.top():
            y = cursor_pos.y() + gap
        x = max(screen_rect.left(), min(x, screen_rect.right() - width + 1))
        y = max(screen_rect.top(), min(y, screen_rect.bottom() - height + 1))
        return QRect(x, y, width, height)

    @staticmethod
    def event_global_pos(event):
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        if hasattr(event, "globalPos"):
            return event.globalPos()
        return QCursor.pos()

    def _preview_size(self):
        return QSize(self.width() * THUMBNAIL_PREVIEW_SCALE, self.height() * THUMBNAIL_PREVIEW_SCALE)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)
        painter.setClipPath(path)
        scaled = self._scaled_thumbnail_pixmap()
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)

    def enterEvent(self, event):
        self._preview_hide_timer.stop()
        self._show_preview(self.event_global_pos(event))
        super().enterEvent(event)

    def mouseMoveEvent(self, event):
        self._preview_hide_timer.stop()
        self._move_preview(self.event_global_pos(event))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._schedule_preview_hide()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._hide_preview()
        super().hideEvent(event)

    def _show_preview(self, cursor_pos=None):
        if self._pixmap.isNull():
            return
        active_owner = ThumbnailPlaceholder._active_preview_owner
        if active_owner is not None and active_owner is not self:
            if isValid(active_owner):
                active_owner._hide_preview()
            else:
                ThumbnailPlaceholder._active_preview_owner = None
        ThumbnailPlaceholder._active_preview_owner = self
        self._preview_hide_timer.stop()
        preview_size = self._preview_size()
        width, height = preview_size.width(), preview_size.height()
        if self._preview is None:
            preview_flags = Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
            if hasattr(Qt, "WindowTransparentForInput"):
                preview_flags |= Qt.WindowTransparentForInput
            self._preview = QFrame(None, preview_flags)
            self._preview.setAttribute(Qt.WA_TranslucentBackground, True)
            self._preview.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._preview.setAttribute(Qt.WA_ShowWithoutActivating, True)
            preview_layout = QVBoxLayout(self._preview)
            preview_layout.setContentsMargins(0, 0, 0, 0)
            self._preview_label = QLabel(self._preview)
            self._preview_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            preview_layout.addWidget(self._preview_label)
        self._preview_label.setFixedSize(width, height)
        key = (self._pixmap.cacheKey(), width, height, 12)
        if self._preview_pixmap.isNull() or self._preview_pixmap_key != key:
            self._preview_pixmap = _rounded_pixmap(self._pixmap, width, height, 12)
            self._preview_pixmap_key = key
        self._preview_label.setPixmap(self._preview_pixmap)
        self._preview.adjustSize()
        self._move_preview(cursor_pos)
        self._preview.show()
        self._preview.raise_()

    def _move_preview(self, cursor_pos=None):
        if self._preview is None:
            return
        cursor_pos = cursor_pos or QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos) or QGuiApplication.primaryScreen()
        if not screen:
            return
        geometry = self.preview_geometry(cursor_pos, self._preview_size(), screen.availableGeometry())
        self._preview.setGeometry(geometry)

    def _hide_preview(self):
        self._preview_hide_timer.stop()
        if self._preview is not None:
            self._preview.hide()
        if ThumbnailPlaceholder._active_preview_owner is self:
            ThumbnailPlaceholder._active_preview_owner = None

    def _schedule_preview_hide(self):
        if self._preview is not None and self._preview.isVisible():
            self._preview_hide_timer.start()

    def _hide_preview_if_cursor_left(self, cursor_pos=None):
        if self._preview is None:
            return
        cursor_pos = cursor_pos or QCursor.pos()
        if self.rect().contains(self.mapFromGlobal(cursor_pos)):
            return
        self._hide_preview()


class PrimaryActionButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._advance)

    def set_loading(self, loading):
        loading = bool(loading)
        if self._loading == loading:
            return
        self._loading = loading
        if loading:
            self._timer.start()
        else:
            self._timer.stop()
            self._angle = 0
        self.update()

    def is_loading(self):
        return self._loading

    def _advance(self):
        self._angle = (self._angle - 28) % 360
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._loading:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(theme.ON_ACCENT), 2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        size = 14
        rect = QRectF(20, (self.height() - size) / 2, size, size)
        painter.drawArc(rect, int(self._angle * 16), int(270 * 16))
