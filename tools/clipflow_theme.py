from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter, QPixmap

APP_NAME = "ClipFlow"
DEFAULT_OUTPUT_EXT = "MP4"
COOKIE_CHOICES = ["없음", "Chrome", "Firefox", "Edge"]
COOKIE_DISPLAY_CHOICES = ["쿠키 미사용", "Chrome", "Firefox", "Edge"]
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
FONT_FALLBACKS = ["Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", "Helvetica Neue", "Segoe UI"]
_FONT_CONFIGURED = False

APP_STYLE = """
QMainWindow {
    background: #f5f9ff;
    font-family: "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", "Helvetica Neue", "Segoe UI";
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
    border-radius: 8px;
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
QFrame#ActionOverlay {
    background: #ffffff;
    border-left: 1px solid #edf2f8;
}
QFrame#ThumbBox {
    background: #e9eff7;
    border: 1px solid #d8e2ef;
    border-radius: 6px;
}
QToolButton#SourceLinkButton {
    background: transparent;
    border: none;
    color: #52627a;
    font-size: 12px;
    padding: 0px 2px;
}
QToolButton#SourceLinkButton:hover {
    color: #2563eb;
    background: transparent;
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
QPushButton#FloatingButton {
    background: #ffffff;
    color: #1d4ed8;
    border: 1px solid #bfd0e6;
    border-radius: 15px;
    padding: 5px 12px;
    font-weight: 700;
}
QPushButton#FloatingButton:hover {
    background: #edf4ff;
    border-color: #93b4e8;
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
QToolTip {
    background: #ffffff;
    color: #1f2937;
    border: 1px solid #cbdaf1;
    border-radius: 6px;
    padding: 6px 8px;
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


def preferred_font_family(default_family=""):
    available = set(QFontDatabase.families())
    for family in FONT_FALLBACKS:
        if family in available:
            return family
    return default_family


def configure_app_font(app):
    global _FONT_CONFIGURED
    if _FONT_CONFIGURED:
        return
    selected_family = preferred_font_family(app.font().family())
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
    painter.setFont(QFont(preferred_font_family(), max(12, int(size * 0.34)), QFont.Bold))
    painter.drawText(rect, Qt.AlignCenter, "Cf")
    painter.end()
    return QIcon(pixmap)

