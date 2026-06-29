"""Download queue + worker coordination for ClipFlowWindow.

Provided as a mixin; all methods operate on ``self`` (the window) and rely only
on the imports below plus methods that remain on the window / other mixins.
"""

import re
import time
import unicodedata
from pathlib import Path

from PySide6.QtCore import QThread, Slot

try:
    from tools import downloader_engine as engine
    from tools.clipflow_rows import build_quality_options
    from tools.clipflow_workers import DownloadWorker
    from tools.clipflow_theme import (
        ANALYZING_STATUS, COMPLETED_STATUS, DOWNLOAD_CONCURRENCY, DOWNLOAD_STATUS, ERROR_STATUS,
        READY_STATUS, WAITING_STATUS, cookie_source_from_display,
    )
except ImportError:
    import downloader_engine as engine
    from clipflow_rows import build_quality_options
    from clipflow_workers import DownloadWorker
    from clipflow_theme import (
        ANALYZING_STATUS, COMPLETED_STATUS, DOWNLOAD_CONCURRENCY, DOWNLOAD_STATUS, ERROR_STATUS,
        READY_STATUS, WAITING_STATUS, cookie_source_from_display,
    )


class DownloadMixin:
    def _start_download(self):
        if self.selected_row_index < 0 or self.selected_row_index >= len(self.rows):
            self._set_status("다운로드할 항목을 선택하세요")
            return
        self.start_download_for_row(self.rows[self.selected_row_index])

    def start_download_for_row(self, row):
        if row not in self.rows:
            return
        if row.get("kind") == "playlist":
            self._start_playlist_children_downloads(row)
            return
        candidate = self.selected_candidate_for_row_ref(row)
        if not candidate:
            self._set_status("다운로드할 항목을 선택하세요")
            return

        if self._row_is_downloading(row):
            self._set_status("이미 다운로드 중")
            return
        if row in self.queued_download_rows:
            self._set_status("다운로드 대기 중")
            return
        existing_output = self._existing_output_path_for_row(row, candidate)
        if existing_output:
            self._mark_existing_output(row, existing_output)
            return
        if len(self.active_downloads) >= DOWNLOAD_CONCURRENCY:
            self.queued_download_rows.append(row)
            widget = row.get("widget")
            if widget:
                widget.set_status("대기")
                widget.set_progress(0, "")
            self._set_status("다운로드 대기 중")
            self._refresh_footer()
            return

        self._begin_download(row, candidate)

    def _playlist_children_for_parent(self, parent):
        parent_id = parent.get("id")
        return [row for row in self.rows if row.get("parent_playlist_id") == parent_id]

    def _start_playlist_children_downloads(self, parent):
        children = self._playlist_children_for_parent(parent)
        if not children:
            self._set_status("재생목록 하위 항목이 없습니다")
            return
        started = 0
        for child in children:
            if child.get("child_loading") or child.get("status") == ERROR_STATUS:
                continue
            before_active = len(self.active_downloads)
            before_queued = len(self.queued_download_rows)
            if child.get("status") not in {COMPLETED_STATUS, DOWNLOAD_STATUS, WAITING_STATUS}:
                child["status"] = DOWNLOAD_STATUS
                child["progress"] = 0
                child["progress_text"] = "0%"
                widget = child.get("widget")
                if widget:
                    widget.set_status(DOWNLOAD_STATUS)
                    widget.set_progress(0, "0%")
            self.start_download_for_row(child)
            if len(self.active_downloads) != before_active or len(self.queued_download_rows) != before_queued:
                started += 1
        self._refresh_playlist_parent_status(parent)
        self._set_status(DOWNLOAD_STATUS if started else "다운로드할 새 항목이 없습니다")

    def _refresh_playlist_parent_status(self, parent):
        children = [
            row
            for row in self._playlist_children_for_parent(parent)
            if not row.get("child_loading")
        ]
        candidate = parent.get("candidate") or {}
        expected = engine.safe_int(candidate.get("playlist_count") or candidate.get("item_count"))
        total = max(len(children), expected) if parent.get("analysis_loading") else len(children)
        if not children:
            self._refresh_playlist_parent_metadata(parent)
            if total:
                parent["status"] = ANALYZING_STATUS
                parent["status_detail"] = f"0/{total}"
                parent["progress"] = 0
                parent["progress_text"] = ""
            widget = parent.get("widget")
            if widget:
                widget.refresh()
            return
        self._refresh_playlist_parent_metadata(parent)
        completed = sum(1 for row in children if row.get("status") == COMPLETED_STATUS)
        active = sum(1 for row in children if row.get("status") in {DOWNLOAD_STATUS, WAITING_STATUS})
        failed = sum(1 for row in children if row.get("status") == ERROR_STATUS)
        total = max(1, total)
        progress = int(sum(engine.safe_int(row.get("progress")) for row in children) / total)
        if completed == total and len(children) >= total:
            status = COMPLETED_STATUS
            detail = ""
            progress = 100
            progress_text = ""
        elif active:
            status = DOWNLOAD_STATUS
            detail = f"{completed}/{total}"
            progress_text = f"{progress}%"
        elif failed:
            status = ERROR_STATUS
            detail = f"{completed}/{total}"
            progress_text = f"{progress}%"
        else:
            status = READY_STATUS
            detail = f"{completed}/{total}" if completed else ""
            progress_text = ""
        parent["status"] = status
        parent["status_detail"] = detail
        parent["progress"] = progress
        parent["progress_text"] = progress_text
        widget = parent.get("widget")
        if widget:
            widget.set_status(status, detail)
            widget.set_progress(progress, progress_text)

    def _begin_download(self, row, candidate=None):
        candidate = candidate or self.selected_candidate_for_row_ref(row)
        if not candidate:
            return
        self.primary_button.set_loading(False)
        self.selected_row_index = self.rows.index(row)
        self._refresh_row_selection()
        row["download_started_at"] = time.time()
        widget = row.get("widget")
        if widget:
            widget.set_status("다운로드 중")
            widget.set_progress(0, "0%")
        self._set_status("다운로드 중")

        page_url = row.get("source_url") or (self.analysis or {}).get("webpage_url") or self.url_input.text().strip()
        thread = QThread(self)
        worker = DownloadWorker(
            str(row.get("id") or ""),
            page_url,
            candidate,
            self._output_dir_for_row(row, candidate),
            cookie_source_from_display(self.cookie_combo.currentText()),
            self.download_func,
        )
        self.active_downloads.append({"thread": thread, "worker": worker, "row": row})
        self._sync_legacy_download_refs()
        self._refresh_primary_action()
        self._refresh_footer()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.event.connect(self._handle_download_worker_event)
        worker.finished.connect(self._download_worker_finished)
        worker.failed.connect(self._download_worker_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_download_thread_finished)
        thread.start()

    def _row_is_downloading(self, row):
        return any(item.get("row") is row for item in self.active_downloads)

    def _sync_legacy_download_refs(self):
        first = self.active_downloads[0] if self.active_downloads else None
        self.download_thread = first.get("thread") if first else None
        self.download_worker = first.get("worker") if first else None
        self.active_download_row = first.get("row") if first else None

    def _existing_output_path_for_row(self, row, candidate):
        saved_output = row.get("output_path") or ""
        output_path = Path(saved_output)
        if (
            saved_output
            and row.get("status") == "완료"
            and engine.completed_output_exists(output_path, candidate)
            and not engine.output_is_too_small_for_candidate(output_path, candidate)
        ):
            return output_path
        row_output_dir = self._output_dir_for_row(row, candidate)
        existing = engine.existing_output_path_for_candidate(candidate, row_output_dir)
        if existing:
            return existing
        return None

    def _output_dir_for_row(self, row, candidate):
        if row and row.get("is_playlist_child"):
            parent = self._parent_playlist_for_child(row)
            if parent:
                return engine.output_dir_for_candidate(parent.get("candidate") or {}, self.folder_input.text())
        return engine.output_dir_for_candidate(candidate, self.folder_input.text())

    def _existing_playlist_child_output(self, row, candidate, output_dir):
        output_dir = Path(output_dir).expanduser()
        if not output_dir.exists():
            return None
        keys = self._playlist_child_title_keys(candidate)
        if not keys:
            return None
        preferred_ext = str((candidate or {}).get("output_ext") or (candidate or {}).get("ext") or "").lower()
        extensions = [ext for ext in [preferred_ext, "mp4", "webm", "m4a", "mp3"] if ext]
        for ext in dict.fromkeys(extensions):
            for path in output_dir.glob(f"*.{ext}"):
                path_key = self._playlist_child_title_key(path.stem)
                if any(key and (key in path_key or path_key in key) for key in keys):
                    if engine.completed_output_exists(path, candidate):
                        return path
        return None

    def _playlist_child_title_keys(self, candidate):
        values = [
            (candidate or {}).get("display_title"),
            (candidate or {}).get("title"),
            (candidate or {}).get("alt_title"),
        ]
        keys = []
        for value in values:
            key = self._playlist_child_title_key(value)
            if key:
                keys.append(key)
            if " - " in str(value or ""):
                suffix_key = self._playlist_child_title_key(str(value).split(" - ", 1)[1])
                if suffix_key:
                    keys.append(suffix_key)
        return list(dict.fromkeys(keys))

    def _playlist_child_title_key(self, value):
        text = unicodedata.normalize("NFKC", str(value or "")).casefold()
        text = re.sub(r"^\s*\d+\s*-\s*", "", text)
        return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)

    def _mark_existing_output(self, row, output_path):
        row["output_path"] = str(output_path)
        row["progress"] = 100
        row["progress_text"] = ""
        widget = row.get("widget")
        if widget:
            widget.set_status("완료")
            widget.set_progress(100, "완료")
            widget._refresh_actions()
        self._save_completed_history()
        self._set_status(f"이미 파일 있음: {Path(output_path).name}")
        self._refresh_primary_action()
        self._refresh_footer()
        self._refresh_parent_for_child(row)

    @Slot(dict)
    def _download_finished(self, result):
        self._download_finished_for(self.active_download_row, result)

    def _download_finished_for(self, row, result):
        if row:
            selected = self.selected_candidate_for_row_ref(row)
            if selected:
                row["candidate"] = selected
                row["qualities"] = [selected]
                row["quality_options"] = build_quality_options([selected])
            self._resolve_finished_output_path(row, result)
            widget = row.get("widget")
            if widget:
                widget.set_status("완료")
                widget.set_progress(100, "완료")
                widget._refresh_actions()
            self._save_completed_history()
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
            selected = self.selected_candidate_for_row_ref(row) or {}
            if (
                engine.completed_output_exists(known_path, selected)
                and not engine.output_is_too_small_for_candidate(known_path, selected)
            ):
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
        self._download_failed_for(self.active_download_row, message)

    def _download_failed_for(self, row, message):
        message = engine.strip_ansi(message)
        if row:
            widget = row.get("widget")
            row["messages"].append(message)
            if widget:
                widget.set_status("오류", message)
                widget.set_progress(0, "")
        self._set_status(f"{engine.classify_error(message)}: {message}")

    def _handle_thread_finished(self, thread):
        row = next(
            (item.get("row") for item in self.active_downloads if item.get("thread") is thread),
            None,
        )
        self._download_thread_finished_for(row, thread)

    def _download_thread_finished_for(self, row, thread):
        self.active_downloads = [
            item for item in self.active_downloads
            if item.get("thread") is not thread and (row is None or item.get("row") is not row)
        ]
        self._sync_legacy_download_refs()
        self._refresh_primary_action()
        self._refresh_footer()
        if row:
            self._refresh_parent_for_child(row)
        self._start_queued_downloads()
        if not self.active_downloads and not self.queued_download_rows:
            self._refresh_all_playlist_parent_statuses()

    def _refresh_parent_for_child(self, row):
        if not row or not row.get("parent_playlist_id"):
            return
        parent = self._parent_playlist_for_child(row)
        if parent:
            self._refresh_playlist_parent_status(parent)

    def _refresh_all_playlist_parent_statuses(self):
        for row in self.rows:
            if row.get("kind") == "playlist":
                self._refresh_playlist_parent_status(row)

    def _start_queued_downloads(self):
        while self.queued_download_rows and len(self.active_downloads) < DOWNLOAD_CONCURRENCY:
            row = self.queued_download_rows.pop(0)
            if row not in self.rows or self._row_is_downloading(row):
                continue
            candidate = self.selected_candidate_for_row_ref(row)
            if not candidate:
                continue
            existing_output = self._existing_output_path_for_row(row, candidate)
            if existing_output:
                self._mark_existing_output(row, existing_output)
                continue
            self._begin_download(row, candidate)
