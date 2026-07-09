import os
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QToolTip

APP_NAME = "ClipFlow"
DEFAULT_OUTPUT_EXT = "MP4"
COOKIE_CHOICES = ["없음", "Chrome", "Edge", "Firefox", "Safari", "Brave", "Opera", "Vivaldi", "Whale", "Chromium"]
COOKIE_DISPLAY_CHOICES = ["쿠키 미사용", "Chrome", "Edge", "Firefox", "Safari", "Brave", "Opera", "Vivaldi", "Whale", "Chromium"]
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
# Palette — light by default; dark is a softer low-glare variant.
# apply_theme_mode("light"|"dark") swaps tokens and rebuilds APP_STYLE.
# ---------------------------------------------------------------------------
THEME_MODE = "light"

# Named swatches — hex only lives here (and palette dicts below).
# Neutral steps follow a soft AAA-friendly scale (no pure black/white body chrome):
#   light: FAFAFA…171717 · dark: 171717…F5F5F5  (see webs.tistory.com/182)
#
# Surface hierarchy (same roles in light + dark — never melt controls into page):
#   CANVAS       — window page background
#   SURFACE      — cards / panels / rows (one step above canvas)
#   FIELD_FILL   — inputs, secondary buttons, combos (control chrome wells)
#   FIELD_BORDER — outlines for that control chrome
#   BORDER       — soft list/card hairlines only
#   GRAPHITE     — solid fills / icon ink (not control outlines)
# Soft white scale (AAA-friendly neutrals) — no pure-#FFF page, no beige.
# Steps: canvas 100 → surface 50 → raised base; ink 800 not pure black.
SOFT_WHITE_50 = "#FAFAFA"
SOFT_WHITE_100 = "#F5F5F5"
SOFT_WHITE_200 = "#E5E5E5"
SOFT_WHITE_300 = "#D4D4D4"
SOFT_WHITE_BASE = "#FFFFFF"
PURE_WHITE = "#FFFFFF"
PURE_BLACK = "#000000"
# Site favicon chrome is theme-independent (never flips black↔white with mode).
FAVICON_GLOBE = "#737373"
YOUTUBE_PLAY = PURE_WHITE

LIGHT_PALETTE = {
    # Soft gray-white page; cards/controls one step lighter (less glare than chalk UI).
    "CANVAS": SOFT_WHITE_100,
    "SURFACE": SOFT_WHITE_50,
    "SURFACE_SOFT": SOFT_WHITE_200,
    "SURFACE_RAISED": SOFT_WHITE_BASE,
    "SURFACE_SUNKEN": SOFT_WHITE_200,
    "BORDER": SOFT_WHITE_200,
    "BORDER_STRONG": SOFT_WHITE_300,
    "INK": "#262626",
    "INK_SOFT": "#404040",
    "MUTED": "#737373",
    "MUTED_SOFT": "#A3A3A3",
    "GRAPHITE": "#404040",
    "GRAPHITE_HOVER": "#262626",
    "GRAPHITE_PRESSED": "#171717",
    "GRAPHITE_DISABLED": SOFT_WHITE_200,
    "ON_ACCENT": PURE_WHITE,
    # Control wells: clean base white on soft canvas; outline near-black.
    "FIELD_FILL": SOFT_WHITE_BASE,
    "FIELD_FILL_HOVER": SOFT_WHITE_50,
    "FIELD_BORDER": "#171717",
    "FIELD_BORDER_HOVER": "#262626",
    "ACCENT": "#0070F3",
    "ACCENT_HOVER": "#0761D1",
    "ACCENT_PRESSED": "#0655BB",
    "ACCENT_TINT": "#E8F1FE",
    "ACCENT_TINT_STRONG": "#D3E4FD",
    "ACCENT_SOFT": "#3B9EFF",
    "SUCCESS": "#0F7B3F",
    "SUCCESS_TINT": "#E6F4EA",
    "SUCCESS_BORDER": "#9CD3B0",
    "SUCCESS_BORDER_STRONG": "#6FBF8E",
    "DANGER": "#E5484D",
    "DANGER_HOVER": "#CF3035",
    "DANGER_PRESSED": "#B91C1C",
    "DANGER_TINT": "#FDECED",
    "DANGER_TINT_STRONG": "#FBD5D7",
    "YOUTUBE_RED": "#FF0000",
    "SHADOW": "#14161E",
    "ICON_DISABLED": "#C4C4CC",
}

# Dark: same hierarchy as light — page / card / control well clearly stepped.
# Hover steps are intentionally large so focus/hover reads at a glance.
DARK_PALETTE = {
    "CANVAS": "#121212",
    "SURFACE": "#1C1C1C",
    "SURFACE_SOFT": "#3A3A3A",
    "SURFACE_RAISED": "#222222",
    "SURFACE_SUNKEN": "#0E0E0E",
    "BORDER": "#333333",
    "BORDER_STRONG": "#5A5A5A",
    "INK": "#E8E8E8",
    "INK_SOFT": "#D4D4D4",
    "MUTED": "#A3A3A3",
    "MUTED_SOFT": "#8A8A8A",
    "GRAPHITE": "#D4D4D4",
    "GRAPHITE_HOVER": "#FFFFFF",
    "GRAPHITE_PRESSED": "#F5F5F5",
    "GRAPHITE_DISABLED": "#333333",
    "ON_ACCENT": "#121212",
    # Control wells sit above canvas + cards; hover jumps a clear step brighter.
    "FIELD_FILL": "#2C2C2C",
    "FIELD_FILL_HOVER": "#484848",
    "FIELD_BORDER": "#C4C4C4",
    "FIELD_BORDER_HOVER": "#FFFFFF",
    "ACCENT": "#4B9BFF",
    "ACCENT_HOVER": "#7ABCFF",
    "ACCENT_PRESSED": "#3A8AEB",
    "ACCENT_TINT": "#1A2C44",
    "ACCENT_TINT_STRONG": "#2A4570",
    "ACCENT_SOFT": "#7ABCFF",
    "SUCCESS": "#4ADE80",
    "SUCCESS_TINT": "#14261A",
    "SUCCESS_BORDER": "#2A5A3C",
    "SUCCESS_BORDER_STRONG": "#357A4E",
    "DANGER": "#F07178",
    "DANGER_HOVER": "#F28B90",
    "DANGER_PRESSED": "#E0555C",
    "DANGER_TINT": "#2A1618",
    "DANGER_TINT_STRONG": "#3A1C20",
    "YOUTUBE_RED": "#FF0000",
    "SHADOW": PURE_BLACK,
    "ICON_DISABLED": "#525252",
}

PROGRESS_RAINBOW = (
    "#2F80ED",
    "#9B51E0",
    "#EB5757",
    "#F2C94C",
    "#27AE60",
)

CANVAS = LIGHT_PALETTE["CANVAS"]
SURFACE = LIGHT_PALETTE["SURFACE"]
SURFACE_SOFT = LIGHT_PALETTE["SURFACE_SOFT"]
SURFACE_RAISED = LIGHT_PALETTE["SURFACE_RAISED"]
SURFACE_SUNKEN = LIGHT_PALETTE["SURFACE_SUNKEN"]
BORDER = LIGHT_PALETTE["BORDER"]
BORDER_STRONG = LIGHT_PALETTE["BORDER_STRONG"]
INK = LIGHT_PALETTE["INK"]
INK_SOFT = LIGHT_PALETTE["INK_SOFT"]
MUTED = LIGHT_PALETTE["MUTED"]
MUTED_SOFT = LIGHT_PALETTE["MUTED_SOFT"]
GRAPHITE = LIGHT_PALETTE["GRAPHITE"]
GRAPHITE_HOVER = LIGHT_PALETTE["GRAPHITE_HOVER"]
GRAPHITE_PRESSED = LIGHT_PALETTE["GRAPHITE_PRESSED"]
GRAPHITE_DISABLED = LIGHT_PALETTE["GRAPHITE_DISABLED"]
ON_ACCENT = LIGHT_PALETTE["ON_ACCENT"]
FIELD_FILL = LIGHT_PALETTE["FIELD_FILL"]
FIELD_FILL_HOVER = LIGHT_PALETTE["FIELD_FILL_HOVER"]
FIELD_BORDER = LIGHT_PALETTE["FIELD_BORDER"]
FIELD_BORDER_HOVER = LIGHT_PALETTE["FIELD_BORDER_HOVER"]
ACCENT = LIGHT_PALETTE["ACCENT"]
ACCENT_HOVER = LIGHT_PALETTE["ACCENT_HOVER"]
ACCENT_PRESSED = LIGHT_PALETTE["ACCENT_PRESSED"]
ACCENT_TINT = LIGHT_PALETTE["ACCENT_TINT"]
ACCENT_TINT_STRONG = LIGHT_PALETTE["ACCENT_TINT_STRONG"]
ACCENT_SOFT = LIGHT_PALETTE["ACCENT_SOFT"]
SUCCESS = LIGHT_PALETTE["SUCCESS"]
SUCCESS_TINT = LIGHT_PALETTE["SUCCESS_TINT"]
SUCCESS_BORDER = LIGHT_PALETTE["SUCCESS_BORDER"]
SUCCESS_BORDER_STRONG = LIGHT_PALETTE["SUCCESS_BORDER_STRONG"]
DANGER = LIGHT_PALETTE["DANGER"]
DANGER_HOVER = LIGHT_PALETTE["DANGER_HOVER"]
DANGER_PRESSED = LIGHT_PALETTE["DANGER_PRESSED"]
DANGER_TINT = LIGHT_PALETTE["DANGER_TINT"]
DANGER_TINT_STRONG = LIGHT_PALETTE["DANGER_TINT_STRONG"]
YOUTUBE_RED = LIGHT_PALETTE["YOUTUBE_RED"]
SHADOW = LIGHT_PALETTE["SHADOW"]
ICON = GRAPHITE
ICON_HOVER = GRAPHITE
ICON_ACTIVE = ACCENT
ICON_DISABLED = LIGHT_PALETTE["ICON_DISABLED"]


def _compose_app_style():
    return f"""
QMainWindow {{
    background: {CANVAS};
    font-family: "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", "Helvetica Neue", "Segoe UI";
}}
QDialog {{
    background: {SURFACE};
}}
QFrame#Panel {{
    background: {SURFACE};
    border: 1px solid {FIELD_BORDER};
    border-radius: 12px;
}}
QFrame#ListPanel {{
    background: transparent;
    border: none;
}}
QFrame#FieldBox {{
    background: {FIELD_FILL};
    border: 1px solid {FIELD_BORDER};
    border-radius: 8px;
}}
QFrame#FieldBox:hover {{
    background: {FIELD_FILL_HOVER};
    border-color: {FIELD_BORDER_HOVER};
}}
QFrame#FieldBox[focused="true"] {{
    background: {FIELD_FILL};
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
    background: transparent;
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
QFrame#InputDivider {{
    background: {FIELD_BORDER};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
QToolButton#SourceLinkButton {{
    background: transparent;
    border: none;
    color: {MUTED};
    font-size: 12px;
    padding: 0px;
    border-radius: 6px;
}}
QToolButton#SourceLinkButton:hover {{
    color: {INK};
    background: {SURFACE_SOFT};
}}
QToolButton#HelpButton {{
    background: {SURFACE};
    border: 1px solid {FIELD_BORDER};
    border-radius: 21px;
    color: {INK};
    font-weight: 700;
}}
QToolButton#HelpButton:hover {{
    background: {SURFACE_SOFT};
    border-color: {FIELD_BORDER_HOVER};
}}
QToolButton#ActionButton {{
    color: {INK_SOFT};
    font-size: 15px;
}}
QPushButton#FloatingButton {{
    background: {SURFACE};
    color: {INK};
    border: 1px solid {FIELD_BORDER};
    border-radius: 14px;
    padding: 5px 12px;
    font-weight: 600;
}}
QPushButton#FloatingButton:hover {{
    background: {SURFACE_SOFT};
    border-color: {FIELD_BORDER_HOVER};
}}
QFrame#UpdateToast {{
    background: {SURFACE};
    color: {INK};
    border: 1px solid {FIELD_BORDER};
    border-radius: 12px;
}}
QLabel#UpdateToastMessage {{
    color: {INK};
    font-size: 14px;
    font-weight: 650;
    margin: 0px;
    padding: 0px;
}}
QToolButton#UpdateToastDismiss {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 0px;
    margin: 0px;
}}
QToolButton#UpdateToastDismiss:hover {{
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
QLabel#UpdateNotesTitle {{
    font-size: 22px;
    font-weight: 700;
    color: {INK};
}}
QTextBrowser#UpdateNotesBody {{
    background: {SURFACE};
    color: {INK};
    border: 1px solid {FIELD_BORDER};
    border-radius: 10px;
    padding: 12px 14px;
    font-size: 14px;
    selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
}}
QLabel#SectionTitle {{
    font-size: 15px;
    font-weight: 700;
    color: {INK};
}}
QLabel#RowTitle {{
    font-size: 12px;
    font-weight: 600;
    color: {INK};
}}
QLabel#MetaText {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel#SortLabel {{
    color: {MUTED};
    font-size: 13px;
    font-weight: 600;
}}
QLabel#PlaylistPill {{
    background: {ACCENT_TINT};
    color: {ACCENT};
    border-radius: 9px;
    padding: 1px 8px 0px 8px;
    font-size: 11px;
    font-weight: 700;
    min-height: 18px;
    max-height: 18px;
    margin-top: 2px;
}}
QLabel#FieldIcon {{
    color: {GRAPHITE};
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
QComboBox#CompactComboBox {{
    padding: 0px;
    min-height: 30px;
    border: none;
}}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    color: {INK};
    border: 1px solid {FIELD_BORDER};
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: {SURFACE_SOFT};
    selection-color: {INK};
}}
QMenu {{
    background: {SURFACE};
    border: 1px solid {FIELD_BORDER};
    border-radius: 10px;
    padding: 4px;
}}
QMenu::item {{
    background: transparent;
    color: {INK};
    padding: 6px 12px;
    margin: 1px 2px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 500;
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
    border: 1px solid {FIELD_BORDER};
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
QLineEdit#BareInput:focus {{
    border: none;
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
    border: 1px solid {FIELD_BORDER};
}}
QPushButton#SecondaryButton {{
    background: {FIELD_FILL};
    color: {INK};
    border: 1px solid {FIELD_BORDER};
    font-size: 13px;
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
    background: {FIELD_FILL_HOVER};
    border-color: {FIELD_BORDER_HOVER};
}}
QPushButton#IconButton {{
    background: transparent;
    color: {GRAPHITE};
    border: none;
    border-radius: 7px;
    padding: 0px;
}}
QPushButton#IconButton:hover {{
    background: {SURFACE_SOFT};
    color: {INK};
}}
QPushButton#IconButton:pressed {{
    background: {SURFACE_SOFT};
    color: {INK};
}}
QPushButton#IconButton[active="true"] {{
    background: {ACCENT_TINT};
    color: {ACCENT};
}}
QPushButton#SecondaryButton:pressed {{
    background: {SURFACE_SOFT};
}}
QPushButton#GhostButton {{
    background: transparent;
    color: {GRAPHITE};
    border: none;
    border-radius: 7px;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#GhostButton:hover {{
    background: {SURFACE_SOFT};
    color: {INK};
}}
QPushButton#GhostButton:pressed {{
    background: {SURFACE_SOFT};
    color: {INK};
}}
QPushButton#GhostButton[active="true"] {{
    background: {ACCENT_TINT};
    color: {ACCENT};
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
    background: {SURFACE};
    color: {INK};
    border: 1px solid {FIELD_BORDER};
    border-radius: 7px;
    padding: 7px 10px;
    font-size: 12px;
    font-weight: 500;
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
QScrollBar[scrollable="false"]:vertical {{
    background: transparent;
}}
QScrollBar[scrollable="false"]::handle:vertical {{
    background: transparent;
}}
QScrollBar[scrollable="false"]::handle:vertical:hover {{
    background: transparent;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""


def _compose_status_styles():
    return {
        "준비": f"background: {SURFACE_SOFT}; color: {MUTED};",
        "대기": f"background: {SURFACE_SOFT}; color: {MUTED};",
        "분석 중": f"background: {ACCENT_TINT}; color: {ACCENT_PRESSED};",
        "다운로드 중": f"background: {ACCENT_TINT}; color: {ACCENT_PRESSED};",
        "완료": f"background: {SUCCESS_TINT}; color: {SUCCESS};",
        "오류": f"background: {DANGER_TINT}; color: {DANGER};",
    }


def _sync_icon_module_colors():
    # Avoid circular import during module init; safe once icons is loaded.
    icons = sys.modules.get("tools.clipflow_icons") or sys.modules.get("clipflow_icons")
    if icons is None:
        return
    if not hasattr(icons, "lucide_pixmap"):
        return
    icons.ICON_COLOR = ICON
    icons.ICON_HOVER_COLOR = ICON_HOVER
    icons.ICON_ACTIVE_COLOR = ICON_ACTIVE
    icons.ICON_DISABLED_COLOR = ICON_DISABLED
    icons.ICON_DANGER_COLOR = DANGER
    icons.ICON_DANGER_HOVER_COLOR = DANGER_HOVER
    icons.ICON_DANGER_ACTIVE_COLOR = DANGER_PRESSED
    cache_clear = getattr(icons.lucide_pixmap, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()


def apply_theme_mode(mode="light"):
    """Apply light/dark palette tokens and rebuild stylesheets."""
    global THEME_MODE, APP_STYLE, STATUS_STYLES
    global ICON, ICON_HOVER, ICON_ACTIVE, ICON_DISABLED
    mode = "dark" if str(mode or "").strip().lower() == "dark" else "light"
    THEME_MODE = mode
    palette = DARK_PALETTE if mode == "dark" else LIGHT_PALETTE
    g = globals()
    for key, value in palette.items():
        g[key] = value
    # Icons track graphite (soft off-black / off-white) — never pure #000/#FFF body chrome.
    ICON = GRAPHITE
    ICON_HOVER = GRAPHITE_HOVER
    ICON_ACTIVE = ACCENT
    ICON_DISABLED = palette["ICON_DISABLED"]
    APP_STYLE = _compose_app_style()
    STATUS_STYLES = _compose_status_styles()
    _sync_icon_module_colors()
    return THEME_MODE


APP_STYLE = ""
STATUS_STYLES = {}
apply_theme_mode("light")


def preferred_font_family(default_family=""):
    available = set(QFontDatabase.families())
    for family in FONT_FALLBACKS:
        if family in available:
            return family
    return default_family


def apply_tracking(widget, spacing, weight=None):
    """Apply absolute letter-spacing (and optional weight) to a widget's font."""
    font = widget.font()
    if font.pointSize() <= 0 and font.pixelSize() <= 0:
        font.setPointSize(10)
    font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    if weight is not None:
        font.setWeight(weight)
    widget.setFont(font)


def configure_app_font(app):
    global _FONT_CONFIGURED
    if _FONT_CONFIGURED:
        return
    selected_family = preferred_font_family(app.font().family())
    font = QFont(selected_family, 10)
    app.setFont(font)
    QToolTip.setFont(font)
    _FONT_CONFIGURED = True


def _app_icon_asset_path():
    return Path(__file__).resolve().parents[1] / "assets" / "icons" / "app_icon.png"


def create_app_icon(size=64):
    asset = _app_icon_asset_path()
    if asset.exists():
        pixmap = QPixmap(str(asset))
        if not pixmap.isNull():
            return QIcon(pixmap)

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


# ---------------------------------------------------------------------------
# Application constants (shared by the window and its mixins). Kept here in the
# neutral base module so mixin modules can import them without creating a
# circular dependency on clipflow_qt.
# ---------------------------------------------------------------------------
SETTINGS_ORG = os.environ.get("CLIPFLOW_SETTINGS_ORG", "ClipFlow")
SETTINGS_APP = os.environ.get("CLIPFLOW_SETTINGS_APP", "ClipFlow")
SAVE_FOLDER_SETTING = "save_folder"
COOKIE_SOURCE_SETTING = "cookie_source"
DOWNLOAD_HISTORY_SETTING = "download_history"
PREF_QUALITY_SETTING = "download_quality"
PREF_FORMAT_SETTING = "download_format"
PREF_CODEC_SETTING = "download_codec"
PREF_FRAME_SETTING = "download_frame"
PREF_HDR_SETTING = "download_hdr"
SORT_KEY_SETTING = "sort_key"
SORT_DESC_SETTING = "sort_desc"
WINDOW_SIZE_SETTING = "window_size"
DOWNLOAD_CONCURRENCY_SETTING = "download_concurrency"
PERMANENT_DELETE_SETTING = "permanent_delete"
THEME_MODE_SETTING = "theme_mode"

PREFERENCE_DEFAULTS = {
    "quality": "자동",
    "output_format": "자동",
    "codec": "자동",
    "frame_rate": "자동",
    "hdr": "끔",
}
SORT_LABELS = {"latest": "다운로드순", "name": "이름순"}
SORT_KEYS_BY_LABEL = {label: key for key, label in SORT_LABELS.items()}
COOKIE_DISPLAY_TO_SOURCE = dict(zip(COOKIE_DISPLAY_CHOICES, COOKIE_CHOICES))
COOKIE_SOURCE_TO_DISPLAY = dict(zip(COOKIE_CHOICES, COOKIE_DISPLAY_CHOICES))
DOWNLOAD_CONCURRENCY = 3

ANALYZING_STATUS = "분석 중"
READY_STATUS = "준비"
WAITING_STATUS = "대기"
DOWNLOAD_STATUS = "다운로드 중"
PAUSED_STATUS = "일시정지"
COMPLETED_STATUS = "완료"
ERROR_STATUS = "오류"
AUTO_LABEL = "자동"


def cookie_source_from_display(display_text):
    text = str(display_text or "").strip()
    if text in COOKIE_DISPLAY_TO_SOURCE:
        return COOKIE_DISPLAY_TO_SOURCE[text]
    if text.startswith("쿠키:"):
        text = text.split(":", 1)[1].strip()
    return text or "없음"
