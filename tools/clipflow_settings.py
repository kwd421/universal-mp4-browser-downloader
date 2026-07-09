"""Preferences, cookie source, save folder, and download-history persistence.

Provided as a mixin so the large window class stays organized. All methods
operate on ``self`` (the ClipFlowWindow instance) and rely on the module
imports below plus methods that remain on the window class or other mixins.
"""

import json
import threading
import urllib.parse
from pathlib import Path

from PySide6.QtCore import QPoint, QStandardPaths, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QGridLayout, QLabel

try:
    from tools import candidate_presenter as presenter
    from tools import downloader_engine as engine
    from tools import clipflow_theme as theme
    from tools.clipflow_updater import _dispatch_to_main_thread
    from tools.clipflow_dialogs import PreferencesDialog, _combo_text
    from tools.clipflow_widgets import CleanComboBox, CleanSwitch, ComboPopup, UpdateAvailableBanner
    from tools.clipflow_rows import build_quality_options, row_kind
    from tools.clipflow_theme import (
        APP_NAME, COMPLETED_STATUS, COOKIE_CHOICES, COOKIE_DISPLAY_CHOICES, COOKIE_SOURCE_SETTING,
        COOKIE_SOURCE_TO_DISPLAY, DOWNLOAD_CONCURRENCY, DOWNLOAD_CONCURRENCY_SETTING, DOWNLOAD_HISTORY_SETTING, PREF_CODEC_SETTING, PREF_FORMAT_SETTING,
        PREF_FRAME_SETTING, PREF_HDR_SETTING, PREF_QUALITY_SETTING, PREFERENCE_DEFAULTS, SAVE_FOLDER_SETTING,
        cookie_source_from_display,
    )
except ImportError:
    import candidate_presenter as presenter
    import downloader_engine as engine
    import clipflow_theme as theme
    from clipflow_updater import _dispatch_to_main_thread
    from clipflow_dialogs import PreferencesDialog, _combo_text
    from clipflow_widgets import CleanComboBox, CleanSwitch, ComboPopup, UpdateAvailableBanner
    from clipflow_rows import build_quality_options, row_kind
    from clipflow_theme import (
        APP_NAME, COMPLETED_STATUS, COOKIE_CHOICES, COOKIE_DISPLAY_CHOICES, COOKIE_SOURCE_SETTING,
        COOKIE_SOURCE_TO_DISPLAY, DOWNLOAD_CONCURRENCY, DOWNLOAD_CONCURRENCY_SETTING, DOWNLOAD_HISTORY_SETTING, PREF_CODEC_SETTING, PREF_FORMAT_SETTING,
        PREF_FRAME_SETTING, PREF_HDR_SETTING, PREF_QUALITY_SETTING, PREFERENCE_DEFAULTS, SAVE_FOLDER_SETTING,
        cookie_source_from_display,
    )


PREFERENCE_TOOLTIPS = {
    "화질": "자동이면 가능한 가장 높은 해상도를 고릅니다. 숫자를 고르면 그 해상도 이하에서 가장 좋은 후보를 고릅니다.",
    "포맷": "저장할 파일 형식입니다. MP3/WAV/AAC는 음원만 저장합니다.",
    "코덱": "자동이면 코덱을 제한하지 않고 best 방식으로 고릅니다. 특정 코덱을 고르면 그 코덱을 우선합니다.",
    "HDR": "끔이면 SDR 후보를 우선합니다. 켬이면 HDR 후보도 허용합니다.",
    "병렬": "동시에 받을 다운로드 개수입니다. 기본값은 3입니다.",
}


def default_save_folder():
    for location in (
        QStandardPaths.MoviesLocation,
        QStandardPaths.DownloadLocation,
        QStandardPaths.DocumentsLocation,
        QStandardPaths.HomeLocation,
    ):
        base_path = QStandardPaths.writableLocation(location)
        if base_path:
            return Path(base_path) / APP_NAME
    return Path(".").resolve() / APP_NAME


DOWNLOAD_HISTORY_MAX_ENTRIES = 100

# Query-string keys that commonly carry signed-URL / CDN tokens. Stripped from
# history entries so persisting completed downloads does not leak credentials.
_SIGNED_QUERY_KEYS = {
    "token",
    "signature",
    "sig",
    "expires",
    "expire",
    "exp",
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-date",
    "x-amz-expires",
    "x-amz-security-token",
    "x-amz-signedheaders",
}


def _strip_signed_url_tokens(value):
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlsplit(text)
    if not parsed.query:
        return text
    kept = [
        (key, val)
        for key, val in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _SIGNED_QUERY_KEYS
    ]
    query = urllib.parse.urlencode(kept, doseq=True)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


class SettingsMixin:
    def current_preferences(self):
        return presenter.DownloadPreferences(**self.preference_values)

    def _preferences_changed(self):
        for row in self.rows:
            candidate = self.selected_candidate_for_row_ref(row)
            if candidate:
                row["candidate"] = candidate
                widget = row.get("widget")
                if widget:
                    widget.refresh()

    def _initial_preferences(self):
        saved_quality = self.settings.value(PREF_QUALITY_SETTING, PREFERENCE_DEFAULTS["quality"], str)
        if str(saved_quality or "").strip() == "최고화질":
            saved_quality = "자동"
        return {
            "quality": saved_quality,
            "output_format": self.settings.value(PREF_FORMAT_SETTING, PREFERENCE_DEFAULTS["output_format"], str),
            "codec": self.settings.value(PREF_CODEC_SETTING, PREFERENCE_DEFAULTS["codec"], str),
            "frame_rate": self.settings.value(PREF_FRAME_SETTING, PREFERENCE_DEFAULTS["frame_rate"], str),
            "hdr": self.settings.value(PREF_HDR_SETTING, PREFERENCE_DEFAULTS["hdr"], str),
        }

    def _initial_download_concurrency(self):
        saved = self.settings.value(DOWNLOAD_CONCURRENCY_SETTING, DOWNLOAD_CONCURRENCY, int)
        return max(1, min(3, int(saved or DOWNLOAD_CONCURRENCY)))

    def _set_download_concurrency(self, value):
        self.download_concurrency = max(1, min(3, int(value or DOWNLOAD_CONCURRENCY)))
        self.settings.setValue(DOWNLOAD_CONCURRENCY_SETTING, self.download_concurrency)
        if hasattr(self, "_start_queued_downloads"):
            self._start_queued_downloads()
        if hasattr(self, "_refresh_footer"):
            self._refresh_footer()

    def _set_preferences(self, quality=None, output_format=None, codec=None, frame_rate=None, hdr=None):
        quality_value = quality or self.preference_values.get("quality") or PREFERENCE_DEFAULTS["quality"]
        if str(quality_value or "").strip() == "최고화질":
            quality_value = "자동"
        values = {
            "quality": quality_value,
            "output_format": output_format or self.preference_values.get("output_format") or PREFERENCE_DEFAULTS["output_format"],
            "codec": codec or self.preference_values.get("codec") or PREFERENCE_DEFAULTS["codec"],
            "frame_rate": frame_rate or self.preference_values.get("frame_rate") or PREFERENCE_DEFAULTS["frame_rate"],
            "hdr": hdr or self.preference_values.get("hdr") or PREFERENCE_DEFAULTS["hdr"],
        }
        self.preference_values = values
        self.settings.setValue(PREF_QUALITY_SETTING, values["quality"])
        self.settings.setValue(PREF_FORMAT_SETTING, values["output_format"])
        self.settings.setValue(PREF_CODEC_SETTING, values["codec"])
        self.settings.setValue(PREF_FRAME_SETTING, values["frame_rate"])
        self.settings.setValue(PREF_HDR_SETTING, values["hdr"])
        self._preferences_changed()

    def _create_preferences_dialog(self):
        return PreferencesDialog(self.current_preferences(), self)

    def _open_preferences_dialog(self):
        dialog = self._create_preferences_dialog()
        if dialog.exec() == QDialog.Accepted:
            preferences = dialog.preferences()
            self._set_preferences(
                quality=preferences.quality,
                output_format=preferences.output_format,
                codec=preferences.codec,
                frame_rate=preferences.frame_rate,
                hdr=preferences.hdr,
            )

    def _toggle_preferences_popup(self):
        if getattr(self.preference_button, "_ignore_next_popup", False):
            self.preference_button._ignore_next_popup = False
            return
        popup = getattr(self, "preferences_popup", None)
        if popup and popup.isVisible():
            popup.close()
            popup.deleteLater()
            self.preferences_popup = None
            return
        preferences = self.current_preferences()
        popup = ComboPopup(self.preference_button)
        popup.setStyleSheet(
            f"QLabel#PreferencePopupLabel {{ color: {theme.GRAPHITE}; font-size: 15px; font-weight: 700; }}"
        )
        layout = QGridLayout(popup)
        layout.setContentsMargins(10, 8, 10, 9)
        layout.setHorizontalSpacing(9)
        layout.setVerticalSpacing(5)

        quality_combo = CleanComboBox()
        quality_combo.addItems(["자동", "4320p", "2160p", "1440p", "1080p", "720p", "480p", "360p"])
        format_combo = CleanComboBox()
        format_combo.addItems(["자동", "MP4", "WEBM", "MP3", "WAV", "AAC"])
        codec_combo = CleanComboBox()
        codec_combo.addItems(["자동", "H264", "H265", "AV1", "VP9"])
        hdr_switch = CleanSwitch()
        hdr_switch.setChecked(str(preferences.hdr).strip() == "켬")
        concurrency_combo = CleanComboBox()
        concurrency_combo.addItems(["1", "2", "3"])
        concurrency_combo.setCurrentText(str(getattr(self, "download_concurrency", DOWNLOAD_CONCURRENCY)))
        for combo in (quality_combo, format_combo, codec_combo, concurrency_combo):
            combo.setObjectName("CompactComboBox")
            combo.show_arrow = False
            combo.text_alignment = Qt.AlignCenter
        quality_combo.setCurrentText(preferences.quality)
        format_combo.setCurrentText(preferences.output_format)
        codec_combo.setCurrentText(preferences.codec)

        def refresh_controls():
            audio_format = format_combo.currentText().strip().lower() in presenter.AUDIO_FORMATS
            quality_combo.setEnabled(not audio_format)
            codec_combo.setEnabled(not audio_format)
            hdr_switch.setEnabled(not audio_format)

        def apply_preferences(*_args):
            refresh_controls()
            self._set_preferences(
                quality=_combo_text(quality_combo),
                output_format=_combo_text(format_combo),
                codec=_combo_text(codec_combo),
                frame_rate=PREFERENCE_DEFAULTS["frame_rate"],
                hdr="켬" if hdr_switch.isChecked() else "끔",
            )

        for row, (label_text, combo) in enumerate(
            (
                ("화질", quality_combo),
                ("포맷", format_combo),
                ("코덱", codec_combo),
            )
        ):
            label = QLabel(label_text)
            label.setObjectName("PreferencePopupLabel")
            tooltip = PREFERENCE_TOOLTIPS.get(label_text, "")
            if tooltip:
                label.setToolTip(tooltip)
                combo.setToolTip(tooltip)
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label, row, 0)
            combo.setFixedWidth(88)
            layout.addWidget(combo, row, 1)
            combo.currentIndexChanged.connect(apply_preferences)

        hdr_row = 3
        hdr_label = QLabel("HDR")
        hdr_label.setObjectName("PreferencePopupLabel")
        hdr_label.setAlignment(Qt.AlignCenter)
        hdr_tooltip = PREFERENCE_TOOLTIPS["HDR"]
        hdr_label.setToolTip(hdr_tooltip)
        hdr_switch.setToolTip(hdr_tooltip)
        layout.addWidget(hdr_label, hdr_row, 0)
        layout.addWidget(hdr_switch, hdr_row, 1, Qt.AlignRight | Qt.AlignVCenter)
        hdr_switch.toggled.connect(apply_preferences)

        concurrency_row = 4
        concurrency_label = QLabel("병렬")
        concurrency_label.setObjectName("PreferencePopupLabel")
        concurrency_label.setAlignment(Qt.AlignCenter)
        concurrency_tooltip = PREFERENCE_TOOLTIPS["병렬"]
        concurrency_label.setToolTip(concurrency_tooltip)
        concurrency_combo.setToolTip(concurrency_tooltip)
        layout.addWidget(concurrency_label, concurrency_row, 0)
        concurrency_combo.setFixedWidth(88)
        layout.addWidget(concurrency_combo, concurrency_row, 1)
        concurrency_combo.currentIndexChanged.connect(lambda *_args, c=concurrency_combo: self._set_download_concurrency(c.currentText()))

        refresh_controls()
        popup.adjustSize()
        popup.setFixedWidth(max(172, popup.sizeHint().width()))
        popup.adjustSize()
        anchor = self.preference_button.mapToGlobal(QPoint(self.preference_button.width(), self.preference_button.height() + 6))
        x = anchor.x() - popup.width()
        y = anchor.y()
        screen = QApplication.screenAt(anchor) or self.screen()
        if screen:
            available = screen.availableGeometry()
            x = max(available.left() + 6, min(x, available.right() - popup.width() + 1))
            y = max(available.top() + 6, min(y, available.bottom() - popup.height() + 1))
        popup.move(QPoint(x, y))
        popup.destroyed.connect(lambda *_args: setattr(self, "preferences_popup", None))
        self.preferences_popup = popup
        popup.show()

    def _initial_save_folder(self):
        saved = self.settings.value(SAVE_FOLDER_SETTING, "", str)
        if saved:
            return str(Path(saved).expanduser())
        return str(default_save_folder())

    def _set_save_folder(self, folder):
        folder_text = str(Path(folder).expanduser())
        self.folder_input.setText(folder_text)
        self.settings.setValue(SAVE_FOLDER_SETTING, folder_text)

    def _restore_cookie_source(self):
        saved = self.settings.value(COOKIE_SOURCE_SETTING, COOKIE_CHOICES[0], str) or COOKIE_CHOICES[0]
        display = COOKIE_SOURCE_TO_DISPLAY.get(saved, COOKIE_DISPLAY_CHOICES[0])
        index = self.cookie_combo.findText(display)
        self.cookie_combo.setCurrentIndex(index if index >= 0 else 0)

    def _save_cookie_source(self, *_args):
        self.settings.setValue(COOKIE_SOURCE_SETTING, cookie_source_from_display(self.cookie_combo.currentText()))
        self.settings.sync()

    def _json_ready(self, value):
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    def _completed_history_payload(self):
        payload = []
        rows = self._dedupe_playlist_parent_rows(list(self.rows))
        for row in rows:
            include_playlist_parent = False
            if row.get("kind") == "playlist":
                children = [child for child in rows if child.get("parent_playlist_id") == row.get("id")]
                include_playlist_parent = any(child.get("status") == COMPLETED_STATUS for child in children)
                if include_playlist_parent:
                    self._refresh_playlist_parent_metadata(row)
            if row.get("status") != COMPLETED_STATUS and not include_playlist_parent:
                continue
            candidate = row.get("candidate") or {}
            candidate_payload = self._json_ready(candidate)
            candidate_payload.pop("url", None)
            payload.append(
                {
                    "candidate": candidate_payload,
                    "source_url": _strip_signed_url_tokens(row.get("source_url") or ""),
                    "analysis_source_url": _strip_signed_url_tokens(row.get("analysis_source_url") or ""),
                    "playlist_key": self._playlist_group_key_for_row(row) if row.get("kind") == "playlist" else row.get("playlist_key") or "",
                    "parent_playlist_id": row.get("parent_playlist_id") or "",
                    "is_playlist_child": bool(row.get("is_playlist_child")),
                    "playlist_child_index": int(row.get("playlist_child_index") or 0),
                    "expanded": bool(row.get("expanded", True)),
                    "output_path": row.get("output_path") or "",
                    "created_order": int(row.get("created_order") or 0),
                    "messages": self._json_ready(row.get("messages") or []),
                }
            )
        payload.sort(key=lambda item: int(item.get("created_order") or 0), reverse=True)
        return payload[:DOWNLOAD_HISTORY_MAX_ENTRIES]

    def _save_completed_history(self):
        self.settings.setValue(
            DOWNLOAD_HISTORY_SETTING,
            json.dumps(self._completed_history_payload(), ensure_ascii=False, default=str),
        )
        self.settings.sync()

    def _history_row_from_item(self, item):
        if not isinstance(item, dict) or not isinstance(item.get("candidate"), dict):
            return None
        candidate = item["candidate"]
        created_order = engine.safe_int(item.get("created_order")) or self._next_row_sequence()
        self._row_sequence = max(self._row_sequence, created_order)
        source_url = (
            item.get("source_url")
            or item.get("analysis_source_url")
            or candidate.get("source")
            or candidate.get("url")
            or ""
        )
        playlist_key = item.get("playlist_key") or self._playlist_key(item.get("analysis_source_url") or source_url)
        row = {
            "id": candidate.get("id") or f"history-{created_order}",
            "kind": row_kind(candidate),
            "candidate": candidate,
            "qualities": [candidate],
            "quality_options": build_quality_options([candidate]),
            "selected_index": 0,
            "selected_format_index": 0,
            "analysis_source_url": item.get("analysis_source_url") or source_url,
            "source_url": source_url,
            "playlist_key": playlist_key,
            "parent_playlist_id": item.get("parent_playlist_id") or "",
            "is_playlist_child": bool(item.get("is_playlist_child")),
            "playlist_child_index": engine.safe_int(item.get("playlist_child_index")),
            "expanded": bool(item.get("expanded", True)),
            "status": "완료",
            "status_detail": "",
            "progress": 100,
            "progress_text": "",
            "output_path": item.get("output_path") or "",
            "messages": item.get("messages") or [],
            "created_order": created_order,
        }
        if engine.clip_range_from_candidate(candidate):
            row["fixed_candidate"] = True
        if hasattr(self, "_apply_actual_output_size"):
            self._apply_actual_output_size(row)
        return row

    def _apply_restored_history(self, items):
        restored = []
        for item in items if isinstance(items, list) else []:
            row = self._history_row_from_item(item)
            if row is not None:
                restored.append(row)
        if not restored:
            return
        repaired_missing_parents = self._restore_missing_playlist_parents(restored)
        restored = self._dedupe_playlist_parent_rows(restored)
        self._attach_restored_playlist_children(restored)
        restored = self._dedupe_playlist_parent_rows(restored)
        self.rows = restored + self.rows
        self._render_rows()
        if repaired_missing_parents:
            self._save_completed_history()

    def _load_completed_history(self):
        raw = self.settings.value(DOWNLOAD_HISTORY_SETTING, "", str) or ""
        if not raw:
            return
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            return
        self._apply_restored_history(items)

    def _app_updater(self):
        app = QApplication.instance()
        if app is None:
            return None
        return getattr(app, "_clipflow_updater", None)

    def schedule_startup_update_check(self):
        updater = self._app_updater()
        if updater is None:
            QTimer.singleShot(500, self.schedule_startup_update_check)
            return
        updater.schedule_startup_check(self._show_update_available_toast)

    def _show_update_available_toast(self, info=None):
        # Session-only dismiss: once closed with ×, don't show again until next launch.
        if getattr(self, "_update_toast_dismissed_session", False):
            return
        toast = getattr(self, "update_toast", None)
        if toast is not None and toast.isVisible():
            return
        if toast is None:
            toast = UpdateAvailableBanner(self)
            toast.update_requested.connect(self._open_update_installer)
            toast.details_requested.connect(self._open_update_details)
            toast.dismissed.connect(self._hide_update_toast)
            self.update_toast = toast
        if hasattr(toast, "set_update_info"):
            toast.set_update_info(info)
        self._position_update_toast()
        toast.show()
        toast.raise_()

    def _hide_update_toast(self):
        self._update_toast_dismissed_session = True
        toast = getattr(self, "update_toast", None)
        if toast is not None:
            toast.hide()

    def _position_update_toast(self):
        toast = getattr(self, "update_toast", None)
        if toast is None:
            return
        margin = 16
        toast.adjustSize()
        x = max(margin, self.width() - toast.width() - margin)
        y = max(margin, self.height() - toast.height() - margin)
        toast.move(x, y)

    def _open_update_installer(self):
        updater = self._app_updater()
        if updater is not None:
            updater.check_for_updates()

    def _open_update_details(self):
        toast = getattr(self, "update_toast", None)
        info = toast.update_info() if toast is not None and hasattr(toast, "update_info") else {}
        version = str((info or {}).get("version") or "").strip()
        url = str((info or {}).get("release_notes_url") or "").strip()
        if not url and version:
            url = f"https://kwd421.github.io/ClipFlow/ClipFlow-{version}.md"
        if not url and not version:
            return
        try:
            from tools.clipflow_widgets import UpdateNotesDialog
        except ImportError:
            from clipflow_widgets import UpdateNotesDialog
        dialog = UpdateNotesDialog(self, version=version, notes_url=url)
        dialog.update_requested.connect(self._open_update_installer)
        dialog.exec()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_update_toast()
