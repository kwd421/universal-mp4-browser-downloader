from pathlib import Path
from functools import lru_cache

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QToolButton, QVBoxLayout, QWidget

try:
    from tools import clipflow_theme as theme
except ImportError:
    import clipflow_theme as theme


LUCIDE_ICON_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons" / "lucide"
ICON_COLOR = theme.ICON
ICON_HOVER_COLOR = theme.ICON_HOVER
ICON_ACTIVE_COLOR = theme.ICON_ACTIVE
ICON_DISABLED_COLOR = theme.ICON_DISABLED
ICON_DANGER_COLOR = theme.DANGER
ICON_DANGER_HOVER_COLOR = theme.DANGER_HOVER
ICON_DANGER_ACTIVE_COLOR = theme.DANGER_PRESSED


def icon_path(name):
    return LUCIDE_ICON_DIR / f"{name}.svg"


def lucide_svg(name, color=ICON_COLOR):
    path = icon_path(name)
    data = path.read_text(encoding="utf-8")
    return data.replace("currentColor", color)


@lru_cache(maxsize=256)
def lucide_pixmap(name, size=20, color=ICON_COLOR, scale=2):
    renderer = QSvgRenderer(lucide_svg(name, color).encode("utf-8"))
    pixel_size = int(size * scale)
    pixmap = QPixmap(pixel_size, pixel_size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, pixel_size, pixel_size))
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap


class LucideIconWidget(QWidget):
    def __init__(self, icon_name, size=22, color=ICON_COLOR, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.icon_size = size
        self.color = color
        self.setFixedSize(size, size)

    def set_color(self, color):
        self.color = color
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(0, 0, self.icon_size, self.icon_size, lucide_pixmap(self.icon_name, self.icon_size, self.color))


class LucideIconButton(QToolButton):
    def __init__(
        self,
        icon_name,
        size=26,
        icon_size=18,
        parent=None,
        danger=False,
        icon_color=None,
        background=None,
        hover_background=None,
        bordered=False,
    ):
        super().__init__(parent)
        self.icon_name = icon_name
        self.icon_size = icon_size
        self.danger = danger
        self.icon_color = icon_color
        self.background = background
        self.hover_background = hover_background
        self.bordered = bordered
        self.setObjectName("ActionButton")
        self.setProperty("danger", "true" if danger else "false")
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)

    def tooltip_position(self):
        return self.mapToGlobal(QPoint(0, -self.sizeHint().height() - 2))

    def _icon_color(self):
        if not self.isEnabled():
            return ICON_DISABLED_COLOR
        if self.danger and self.isDown():
            return ICON_DANGER_ACTIVE_COLOR
        if self.danger and self.underMouse():
            return ICON_DANGER_HOVER_COLOR
        if self.danger:
            return ICON_DANGER_COLOR
        if self.icon_color:
            return self.icon_color
        if self.isDown():
            return ICON_ACTIVE_COLOR
        if self.underMouse():
            return ICON_HOVER_COLOR
        return ICON_COLOR

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.bordered:
            # Persistent bordered box so this reads as the same control family
            # as the adjacent combo box / secondary button.
            hovered = self.underMouse() and self.isEnabled()
            border = theme.BORDER_STRONG if hovered else theme.FIELD_BORDER
            background = theme.SURFACE_SOFT if hovered else theme.SURFACE
            painter.setPen(QPen(QColor(border), 1))
            painter.setBrush(QColor(background))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        elif self.background and self.isEnabled():
            painter.setPen(Qt.NoPen)
            background = self.hover_background if self.underMouse() and self.hover_background else self.background
            painter.setBrush(QColor(background))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 5, 5)
        elif self.underMouse() and self.isEnabled():
            painter.setPen(Qt.NoPen)
            if self.danger:
                painter.setBrush(QColor(theme.DANGER_TINT_STRONG if self.isDown() else theme.DANGER_TINT))
            else:
                painter.setBrush(QColor(theme.ACCENT_TINT_STRONG if self.isDown() else theme.ACCENT_TINT))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 6, 6)

        pixmap = lucide_pixmap(self.icon_name, self.icon_size, self._icon_color())
        x = (self.width() - self.icon_size) // 2
        y = (self.height() - self.icon_size) // 2
        painter.drawPixmap(x, y, self.icon_size, self.icon_size, pixmap)

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
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.update()


class CustomTooltip(QWidget):
    """A single, app-wide tooltip popup.

    It is transparent to mouse events and shown above the hovered widget, which
    avoids the native-tooltip flicker (the cursor never lands on the tooltip)
    and the platform dark-mode background leaking through.
    """

    _instance = None
    SHADOW_MARGIN = 12

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(
            "QLabel#CustomTooltipBubble {"
            f" background: {theme.SURFACE}; color: {theme.INK}; border: 1px solid {theme.BORDER_STRONG};"
            " border-radius: 7px; padding: 7px 10px; font-size: 12px; font-weight: 500;"
            " }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            self.SHADOW_MARGIN,
            self.SHADOW_MARGIN,
            self.SHADOW_MARGIN,
            self.SHADOW_MARGIN + 4,
        )
        layout.setSpacing(0)
        self._bubble = QLabel(self)
        self._bubble.setObjectName("CustomTooltipBubble")
        self._bubble.setWordWrap(False)
        layout.addWidget(self._bubble)
        shadow = QGraphicsDropShadowEffect(self._bubble)
        shadow.setBlurRadius(18)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(20, 22, 30, 44))
        self._bubble.setGraphicsEffect(shadow)
        self._shadow = shadow

    def setText(self, text):
        self._bubble.setText(text)

    def text(self):
        return self._bubble.text()

    def bubble_geometry(self):
        return self._bubble.geometry()

    def graphicsEffect(self):
        return self._shadow

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = CustomTooltip()
        return cls._instance


def show_tooltip_above(widget, text):
    text = str(text or "").strip()
    if not text:
        hide_tooltip()
        return
    tip = CustomTooltip.instance()
    tip.setText(text)
    tip.adjustSize()
    tip.show()
    if tip.layout() is not None:
        tip.layout().activate()
    origin = widget.mapToGlobal(QPoint(0, 0))
    bubble = tip.bubble_geometry()
    x = origin.x() + widget.width() // 2 - (bubble.x() + bubble.width() // 2)
    y = origin.y() - bubble.bottom() - 4
    screen = widget.screen()
    if screen is not None:
        available = screen.availableGeometry()
        x = max(available.left() + 4, min(x, available.right() - tip.width() - 4))
        if y < available.top() + 4:
            y = origin.y() + widget.height() - bubble.y() + 4
    tip.move(x, y)
    tip.raise_()


def hide_tooltip():
    if CustomTooltip._instance is not None:
        CustomTooltip._instance.hide()


class TooltipManager(QObject):
    """App-wide event filter that replaces native tooltips with CustomTooltip."""

    def eventFilter(self, obj, event):
        event_type = event.type()
        if event_type == QEvent.ToolTip:
            if isinstance(obj, QWidget) and obj.toolTip():
                show_tooltip_above(obj, obj.toolTip())
                return True
            hide_tooltip()
            return False
        if event_type in (QEvent.Leave, QEvent.HoverLeave, QEvent.WindowDeactivate, QEvent.MouseButtonPress):
            hide_tooltip()
        return False
