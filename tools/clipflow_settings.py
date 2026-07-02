"""Preferences, cookie source, save folder, and download-history persistence.

Provided as a mixin so the large window class stays organized. All methods
operate on ``self`` (the ClipFlowWindow instance) and rely on the module
imports below plus methods that remain on the window class or other mixins.
"""

import json
from pathlib import Path

from PySide6.QtCore import QPoint, QStandardPaths
from PySide6.QtWidgets import QApplication, QDialog, QGridLayout, QLabel

try:
    from tools import candidate_presenter as presenter
    from tools import downloader_engine as engine
    from tools import clipflow_theme as theme
    from tools.clipflow_dialogs import PreferencesDialog, _combo_text
    from tools.clipflow_widgets import CleanComboBox, ComboPopup
    from tools.clipflow_rows import build_quality_options, row_kind
    from tools.clipflow_theme import (
        APP_NAME, COMPLETED_STATUS, COOKIE_CHOICES, COOKIE_DISPLAY_CHOICES, COOKIE_SOURCE_SETTING,
        COOKIE_SOURCE_TO_DISPLAY, DOWNLOAD_CONCURRENCY, DOWNLOAD_CONCURRENCY_SETTING, DOWNLOAD_HISTORY_SETTING, PREF_CODEC_SETTING, PREF_FORMAT_SETTING,
        PREF_FRAME_SETTING, PREF_QUALITY_SETTING, PREFERENCE_DEFAULTS, SAVE_FOLDER_SETTING,
        cookie_source_from_display,
    )
except ImportError:
    import candidate_presenter as presenter
    import downloader_engine as engine
    import clipflow_theme as theme
    from clipflow_dialogs import PreferencesDialog, _combo_text
    from clipflow_widgets import CleanComboBox, ComboPopup
    from clipflow_rows import build_quality_options, row_kind
    from clipflow_theme import (
        APP_NAME, COMPLETED_STATUS, COOKIE_CHOICES, COOKIE_DISPLAY_CHOICES, COOKIE_SOURCE_SETTING,
        COOKIE_SOURCE_TO_DISPLAY, DOWNLOAD_CONCURRENCY, DOWNLOAD_CONCURRENCY_SETTING, DOWNLOAD_HISTORY_SETTING, PREF_CODEC_SETTING, PREF_FORMAT_SETTING,
        PREF_FRAME_SETTING, PREF_QUALITY_SETTING, PREFERENCE_DEFAULTS, SAVE_FOLDER_SETTING,
        cookie_source_from_display,
    )


PREFERENCE_TOOLTIPS = {
    "품질": "선택한 해상도 이하에서 가장 좋은 후보를 고릅니다.",
    "포맷": "저장할 파일 형식입니다. MP3/WAV/AAC는 음원만 저장합니다.",
    "코덱": "가능하면 선택한 영상 코덱을 우선합니다. 음원 포맷에는 적용되지 않습니다.",
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
        return {
            "quality": self.settings.value(PREF_QUALITY_SETTING, PREFERENCE_DEFAULTS["quality"], str),
            "output_format": self.settings.value(PREF_FORMAT_SETTING, PREFERENCE_DEFAULTS["output_format"], str),
            "codec": self.settings.value(PREF_CODEC_SETTING, PREFERENCE_DEFAULTS["codec"], str),
            "frame_rate": self.settings.value(PREF_FRAME_SETTING, PREFERENCE_DEFAULTS["frame_rate"], str),
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

    def _set_preferences(self, quality=None, output_format=None, codec=None, frame_rate=None):
        values = {
            "quality": quality or self.preference_values.get("quality") or PREFERENCE_DEFAULTS["quality"],
            "output_format": output_format or self.preference_values.get("output_format") or PREFERENCE_DEFAULTS["output_format"],
            "codec": codec or self.preference_values.get("codec") or PREFERENCE_DEFAULTS["codec"],
            "frame_rate": frame_rate or self.preference_values.get("frame_rate") or PREFERENCE_DEFAULTS["frame_rate"],
        }
        self.preference_values = values
        self.settings.setValue(PREF_QUALITY_SETTING, values["quality"])
        self.settings.setValue(PREF_FORMAT_SETTING, values["output_format"])
        self.settings.setValue(PREF_CODEC_SETTING, values["codec"])
        self.settings.setValue(PREF_FRAME_SETTING, values["frame_rate"])
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
            f"QLabel#PreferencePopupLabel {{ color: {theme.MUTED}; font-size: 12px; font-weight: 600; }}"
        )
        layout = QGridLayout(popup)
        layout.setContentsMargins(8, 7, 8, 8)
        layout.setHorizontalSpacing(7)
        layout.setVerticalSpacing(5)

        quality_combo = CleanComboBox()
        quality_combo.addItems(["최고화질", "2160p", "1440p", "1080p", "720p", "480p", "360p"])
        format_combo = CleanComboBox()
        format_combo.addItems(["자동", "MP4", "WEBM", "MP3", "WAV", "AAC"])
        codec_combo = CleanComboBox()
        codec_combo.addItems(["자동", "H264", "H265", "AV1", "VP9"])
        concurrency_combo = CleanComboBox()
        concurrency_combo.addItems(["1", "2", "3"])
        concurrency_combo.setCurrentText(str(getattr(self, "download_concurrency", DOWNLOAD_CONCURRENCY)))
        for combo in (quality_combo, format_combo, codec_combo, concurrency_combo):
            combo.setObjectName("CompactComboBox")
        quality_combo.setCurrentText(preferences.quality)
        format_combo.setCurrentText(preferences.output_format)
        codec_combo.setCurrentText(preferences.codec)

        def refresh_controls():
            audio_format = format_combo.currentText().strip().lower() in presenter.AUDIO_FORMATS
            codec_combo.setEnabled(not audio_format)

        def apply_preferences(*_args):
            refresh_controls()
            self._set_preferences(
                quality=_combo_text(quality_combo),
                output_format=_combo_text(format_combo),
                codec=_combo_text(codec_combo),
                frame_rate=PREFERENCE_DEFAULTS["frame_rate"],
            )

        for row, (label_text, combo) in enumerate(
            (
                ("품질", quality_combo),
                ("포맷", format_combo),
                ("코덱", codec_combo),
                ("병렬", concurrency_combo),
            )
        ):
            label = QLabel(label_text)
            label.setObjectName("PreferencePopupLabel")
            tooltip = PREFERENCE_TOOLTIPS.get(label_text, "")
            if tooltip:
                label.setToolTip(tooltip)
                combo.setToolTip(tooltip)
            layout.addWidget(label, row, 0)
            combo.setFixedWidth(140)
            layout.addWidget(combo, row, 1)
            if combo is concurrency_combo:
                combo.currentIndexChanged.connect(lambda *_args, c=concurrency_combo: self._set_download_concurrency(c.currentText()))
            else:
                combo.currentIndexChanged.connect(apply_preferences)

        refresh_controls()
        popup.adjustSize()
        popup.setFixedWidth(max(214, popup.sizeHint().width()))
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
            payload.append(
                {
                    "candidate": self._json_ready(candidate),
                    "source_url": row.get("source_url") or "",
                    "analysis_source_url": row.get("analysis_source_url") or "",
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
        return payload

    def _save_completed_history(self):
        self.settings.setValue(
            DOWNLOAD_HISTORY_SETTING,
            json.dumps(self._completed_history_payload(), ensure_ascii=False, default=str),
        )
        self.settings.sync()

    def _load_completed_history(self):
        raw = self.settings.value(DOWNLOAD_HISTORY_SETTING, "", str) or ""
        if not raw:
            return
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            return
        restored = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("candidate"), dict):
                continue
            candidate = item["candidate"]
            created_order = engine.safe_int(item.get("created_order")) or self._next_row_sequence()
            self._row_sequence = max(self._row_sequence, created_order)
            source_url = item.get("source_url") or item.get("analysis_source_url") or candidate.get("source") or candidate.get("url") or ""
            playlist_key = item.get("playlist_key") or self._playlist_key(
                item.get("analysis_source_url") or source_url
            )
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
            if hasattr(self, "_apply_actual_output_size"):
                self._apply_actual_output_size(row)
            restored.append(row)
        if restored:
            repaired_missing_parents = self._restore_missing_playlist_parents(restored)
            restored = self._dedupe_playlist_parent_rows(restored)
            self._attach_restored_playlist_children(restored)
            restored = self._dedupe_playlist_parent_rows(restored)
            self.rows = restored + self.rows
            self._render_rows()
            if repaired_missing_parents:
                self._save_completed_history()
