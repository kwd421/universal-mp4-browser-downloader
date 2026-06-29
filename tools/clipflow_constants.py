import os

try:
    from tools.clipflow_theme import COOKIE_CHOICES, COOKIE_DISPLAY_CHOICES
except ImportError:
    from clipflow_theme import COOKIE_CHOICES, COOKIE_DISPLAY_CHOICES


SETTINGS_ORG = os.environ.get("CLIPFLOW_SETTINGS_ORG", "ClipFlow")
SETTINGS_APP = os.environ.get("CLIPFLOW_SETTINGS_APP", "ClipFlow")
SAVE_FOLDER_SETTING = "save_folder"
COOKIE_SOURCE_SETTING = "cookie_source"
DOWNLOAD_HISTORY_SETTING = "download_history"
PREF_QUALITY_SETTING = "download_quality"
PREF_FORMAT_SETTING = "download_format"
PREF_CODEC_SETTING = "download_codec"
PREF_FRAME_SETTING = "download_frame"
SORT_KEY_SETTING = "sort_key"
SORT_DESC_SETTING = "sort_desc"

PREFERENCE_DEFAULTS = {
    "quality": "자동",
    "output_format": "자동",
    "codec": "자동",
    "frame_rate": "자동",
}
SORT_LABELS = {"latest": "최신순", "name": "이름순"}
SORT_KEYS_BY_LABEL = {label: key for key, label in SORT_LABELS.items()}
COOKIE_DISPLAY_TO_SOURCE = dict(zip(COOKIE_DISPLAY_CHOICES, COOKIE_CHOICES))
COOKIE_SOURCE_TO_DISPLAY = dict(zip(COOKIE_CHOICES, COOKIE_DISPLAY_CHOICES))
DOWNLOAD_CONCURRENCY = 3

ANALYZING_STATUS = "분석 중"
READY_STATUS = "준비"
WAITING_STATUS = "대기"
DOWNLOAD_STATUS = "다운로드 중"
COMPLETED_STATUS = "완료"
ERROR_STATUS = "오류"
AUTO_LABEL = "자동"
