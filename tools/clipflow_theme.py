from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap

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

# ---------------------------------------------------------------------------
# Palette — clean light "product" surface (Vercel lineage): a near-white canvas,
# crisp white cards, hairline gray borders, near-black ink, a BLACK primary
# action, and a single blue used only for focus / progress / links. Flat, no
# gradients, minimal shadow. Single source of truth for every module.
# ---------------------------------------------------------------------------
CANVAS = "#FAFAFA"
SURFACE = "#FFFFFF"
SURFACE_SOFT = "#F4F4F5"
SURFACE_RAISED = "#FFFFFF"
SURFACE_SUNKEN = "#FFFFFF"
BORDER = "#EAEAEA"
BORDER_STRONG = "#D4D4D8"
FIELD_BORDER = "#E4E4E7"
FIELD_BORDER_HOVER = "#C4C4CC"

INK = "#171717"
INK_SOFT = "#3F3F46"
MUTED = "#71717A"
MUTED_SOFT = "#A1A1AA"

# Primary action = solid black (Vercel signature). Names kept for low churn.
GRAPHITE = "#171717"
GRAPHITE_HOVER = "#000000"
GRAPHITE_PRESSED = "#2A2A2A"
GRAPHITE_DISABLED = "#F4F4F5"
ON_ACCENT = "#FFFFFF"

# Blue is an information accent only (focus ring, progress, links, selection).
ACCENT = "#0070F3"
ACCENT_HOVER = "#0761D1"
ACCENT_PRESSED = "#0655BB"
ACCENT_TINT = "#E8F1FE"
ACCENT_TINT_STRONG = "#D3E4FD"
ACCENT_SOFT = "#3B9EFF"

SUCCESS = "#0F7B3F"
SUCCESS_TINT = "#E6F4EA"
DANGER = "#E5484D"
DANGER_HOVER = "#CF3035"
DANGER_PRESSED = "#B91C1C"
DANGER_TINT = "#FDECED"
DANGER_TINT_STRONG = "#FBD5D7"

ICON = "#71717A"
ICON_HOVER = "#171717"
ICON_ACTIVE = ACCENT
ICON_DISABLED = "#C4C4CC"

APP_STYLE = f"""
QMainWindow {{
    background: {CANVAS};
    font-family: "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", "Helvetica Neue", "Segoe UI";
}}
QDialog {{
    background: {SURFACE};
}}
QFrame#Panel {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#ListPanel {{
    background: transparent;
    border: none;
}}
QFrame#FieldBox {{
    background: {SURFACE};
    border: 1px solid {FIELD_BORDER};
    border-radius: 8px;
}}
QFrame#FieldBox:hover {{
    border-color: {FIELD_BORDER_HOVER};
}}
QFrame#FieldBox[focused="true"] {{
    background: {SURFACE};
    border-color: {ACCENT};
}}
QFrame#DownloadRow {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#DownloadRow[selected="true"] {{
    background: {SURFACE};
    border-color: {BORDER};
}}
QFrame#DownloadRow[hovered="true"] {{
    background: {SURFACE_SOFT};
    border-color: {BORDER_STRONG};
}}
QFrame#DownloadRow[selected="true"][hovered="true"] {{
    background: {SURFACE_SOFT};
    border-color: {BORDER_STRONG};
}}
QWidget#RowContainer {{
    background: transparent;
}}
QFrame#ActionOverlay {{
    background: {SURFACE};
    border: none;
}}
QFrame#ThumbBox {{
    background: {SURFACE_SOFT};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QLabel#CountChip {{
    background: {SURFACE_SOFT};
    color: {MUTED};
    border-radius: 8px;
    padding: 1px 8px;
    font-size: 12px;
    font-weight: 600;
}}
QLabel#Eyebrow {{
    color: {MUTED_SOFT};
    font-size: 11px;
    font-weight: 700;
}}
QFrame#FooterDivider {{
    background: {BORDER};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
QToolButton#SourceLinkButton {{
    background: transparent;
    border: none;
    color: {MUTED};
    font-size: 12px;
    padding: 2px 7px;
    border-radius: 6px;
}}
QToolButton#SourceLinkButton:hover {{
    color: {INK};
    background: {SURFACE_SOFT};
}}
QToolButton#HelpButton {{
    background: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 21px;
    color: {INK};
    font-weight: 700;
}}
QToolButton#HelpButton:hover {{
    background: {SURFACE_SOFT};
}}
QToolButton#ActionButton {{
    color: {INK_SOFT};
    font-size: 15px;
}}
QPushButton#FloatingButton {{
    background: {SURFACE};
    color: {INK};
    border: 1px solid {BORDER_STRONG};
    border-radius: 14px;
    padding: 5px 12px;
    font-weight: 600;
}}
QPushButton#FloatingButton:hover {{
    background: {SURFACE_SOFT};
}}
QLabel {{
    color: {INK};
    font-size: 13px;
}}
QLabel#WindowTitle {{
    font-size: 18px;
    font-weight: 700;
    color: {INK};
}}
QLabel#SectionTitle {{
    font-size: 15px;
    font-weight: 700;
    color: {INK};
}}
QLabel#RowTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {INK};
}}
QLabel#MetaText {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel#PlaylistPill {{
    background: {ACCENT_TINT};
    color: {ACCENT};
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel#FieldIcon {{
    color: {MUTED};
    font-size: 16px;
}}
QLabel#FormatValue, QLabel#QualityValue {{
    background: {SURFACE};
    border: 1px solid {FIELD_BORDER};
    border-radius: 7px;
    padding: 7px 10px;
    color: {INK};
}}
QLabel#QualityValue[locked="true"], QLabel#FormatValue[locked="true"] {{
    background: transparent;
    border: none;
    padding: 0px;
    color: {INK_SOFT};
}}
QLabel#StatusPill {{
    border-radius: 11px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 600;
}}
QLineEdit, QComboBox {{
    background: {SURFACE};
    border: 1px solid {FIELD_BORDER};
    border-radius: 8px;
    padding: 8px 10px;
    min-height: 22px;
    color: {INK};
    selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    color: {INK};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: {SURFACE_SOFT};
    selection-color: {INK};
}}
QMenu {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 5px;
}}
QMenu::item {{
    background: transparent;
    color: {INK};
    padding: 8px 16px;
    border-radius: 7px;
    font-size: 13px;
}}
QMenu::item:selected {{
    background: {SURFACE_SOFT};
    color: {INK};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 5px 8px;
}}
QFrame#ComboPopup {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QPushButton#ComboOption {{
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 9px 14px;
    color: {INK};
    font-size: 13px;
    font-weight: 500;
    text-align: left;
}}
QPushButton#ComboOption:hover {{
    background: {SURFACE_SOFT};
}}
QPushButton#ComboOption[selected="true"] {{
    color: {ACCENT};
    font-weight: 700;
}}
QLineEdit#BareInput {{
    background: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px;
}}
QPushButton#InlinePaste {{
    background: transparent;
    border: none;
    color: {ACCENT};
    font-weight: 600;
    font-size: 13px;
    padding: 0px 6px;
}}
QPushButton#InlinePaste:hover {{
    color: {ACCENT_HOVER};
}}
QPushButton {{
    background: {GRAPHITE};
    color: {ON_ACCENT};
    border: none;
    border-radius: 8px;
    padding: 9px 18px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: {GRAPHITE_HOVER};
}}
QPushButton:pressed {{
    background: {GRAPHITE_PRESSED};
}}
QPushButton:disabled {{
    background: {GRAPHITE_DISABLED};
    color: {MUTED_SOFT};
}}
QPushButton#SecondaryButton {{
    background: {SURFACE};
    color: {INK};
    border: 1px solid {FIELD_BORDER};
    font-weight: 600;
}}
QPushButton#DangerButton {{
    background: {DANGER};
    color: {ON_ACCENT};
    border: none;
    font-weight: 600;
}}
QPushButton#DangerButton:hover {{
    background: {DANGER_HOVER};
}}
QPushButton#DangerButton:pressed {{
    background: {DANGER_PRESSED};
}}
QPushButton#SecondaryButton:hover {{
    background: {SURFACE_SOFT};
    border-color: {BORDER_STRONG};
}}
QPushButton#SecondaryButton:pressed {{
    background: {SURFACE_SOFT};
}}
QToolButton {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px;
}}
QToolButton:hover {{
    background: {SURFACE_SOFT};
}}
QToolButton:disabled {{
    color: {ICON_DISABLED};
}}
QToolTip {{
    background: {INK};
    color: {SURFACE};
    border: none;
    border-radius: 7px;
    padding: 6px 9px;
    font-size: 12px;
}}
QProgressBar {{
    border: none;
    border-radius: 3px;
    background: {SURFACE_SOFT};
    height: 6px;
    max-height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 3px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QCheckBox {{
    spacing: 6px;
    color: {MUTED};
    font-size: 13px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {FIELD_BORDER};
    border-radius: 5px;
    background: {SURFACE};
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px 2px 2px 0px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: {MUTED_SOFT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""

STATUS_STYLES = {
    "준비": f"background: {SURFACE_SOFT}; color: {MUTED};",
    "대기": f"background: {SURFACE_SOFT}; color: {MUTED};",
    "분석 중": f"background: {ACCENT_TINT}; color: {ACCENT_PRESSED};",
    "다운로드 중": f"background: {ACCENT_TINT}; color: {ACCENT_PRESSED};",
    "완료": f"background: {SUCCESS_TINT}; color: {SUCCESS};",
    "오류": f"background: {DANGER_TINT}; color: {DANGER};",
}


def preferred_font_family(default_family=""):
    available = set(QFontDatabase.families())
    for family in FONT_FALLBACKS:
        if family in available:
            return family
    return default_family


def apply_tracking(widget, spacing, weight=None):
    """Apply absolute letter-spacing (and optional weight) to a widget's font."""
    font = widget.font()
    font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    if weight is not None:
        font.setWeight(weight)
    widget.setFont(font)


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
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(GRAPHITE))
    painter.drawRoundedRect(rect, size * 0.28, size * 0.28)

    painter.setPen(QColor(ON_ACCENT))
    painter.setFont(QFont(preferred_font_family(), max(12, int(size * 0.34)), QFont.Bold))
    painter.drawText(rect, Qt.AlignCenter, "Cf")
    painter.end()
    return QIcon(pixmap)
