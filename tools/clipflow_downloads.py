"""Download queue + worker coordination for ClipFlowWindow.

Provided as a mixin; all methods operate on ``self`` (the window) and rely only
on the imports below plus methods that remain on the window / other mixins.
"""

import re
import time
import unicodedata
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Slot

try:
    from tools import downloader_engine as engine
    from tools.clipflow_rows import build_quality_options
    from tools.clipflow_workers import DownloadWorker
    from tools.clipflow_theme import (
        ANALYZING_STATUS, COMPLETED_STATUS, DOWNLOAD_CONCURRENCY, DOWNLOAD_STATUS, ERROR_STATUS,
        PAUSED_STATUS, READY_STATUS, WAITING_STATUS, cookie_source_from_display,
    )
except ImportError:
    import downloader_engine as engine
    from clipflow_rows import build_quality_options
    from clipflow_workers import DownloadWorker
    from clipflow_theme import (
        ANALYZING_STATUS, COMPLETED_STATUS, DOWNLOAD_CONCURRENCY, DOWNLOAD_STATUS, ERROR_STATUS,
        PAUSED_STATUS, READY_STATUS, WAITING_STATUS, cookie_source_from_display,
    )


class DownloadMixin:
    def _set_row_status(self, row, status, detail=""):
        """Update row model first; widget only paints (does not own status)."""
        if not isinstance(row, dict):
            return
        row["status"] = status
        row["status_detail"] = detail if detail is not None else ""
        widget = row.get("widget")
        if widget is not None:
            widget.set_status(status, row["status_detail"])

    def _download_concurrency_limit(self):
        try:
            return max(1, min(3, int(getattr(self, "download_concurrency", DOWNLOAD_CONCURRENCY) or DOWNLOAD_CONCURRENCY)))
        except (TypeError, ValueError):
            return DOWNLOAD_CONCURRENCY

    def _start_download(self):
        if self.selected_row_index < 0 or self.selected_row_index >= len(self.rows):
            self._set_status("다운로드할 항목을 선택하세요")
            return
        self.start_download_for_row(self.rows[self.selected_row_index])

    def extract_audio_for_row(self, row, audio_ext):
        if row not in self.rows:
            return
        base = row.get("candidate") or {}
        ext_lower = str(audio_ext).lower()
        candidate = dict(base)
        candidate["output_ext"] = audio_ext
        candidate["ext"] = ext_lower
        candidate["format_selector"] = "bestaudio/best"
        candidate.pop("media_type", None)
        order = self._next_row_sequence()
        audio_row = {
            "id": f"audio-{order}",
            "kind": "video",
            "candidate": candidate,
            "qualities": [candidate],
            "quality_options": build_quality_options([candidate]),
            "selected_index": 0,
            "selected_format_index": 0,
            "fixed_candidate": True,
            "analysis_source_url": row.get("analysis_source_url") or row.get("source_url") or "",
            "source_url": row.get("source_url") or "",
            "input_url": row.get("input_url") or row.get("source_url") or "",
            "status": READY_STATUS,
            "status_detail": "",
            "progress": 0,
            "progress_text": "",
            "output_path": "",
            "messages": [],
            "created_order": order,
        }
        source_path = self._audio_extract_source_path(row)
        if source_path:
            audio_row["local_audio_source_path"] = str(source_path)
        self.rows.insert(self.rows.index(row) + 1, audio_row)
        self._render_rows()
        self.start_download_for_row(audio_row)

    def _audio_extract_source_path(self, row):
        base = row.get("candidate") or {}
        saved_output = row.get("output_path") or ""
        if saved_output:
            saved_path = Path(saved_output).expanduser()
            if engine.completed_output_exists(saved_path, base):
                return saved_path
        existing = self._existing_output_path_for_row(row, base) if base else None
        if existing and engine.completed_output_exists(existing, base):
            return existing
        return None

    def _segment_extract_source_path(self, row):
        base = row.get("candidate") or {}
        saved_output = row.get("output_path") or ""
        if saved_output:
            saved_path = Path(saved_output).expanduser()
            if engine.completed_output_exists(saved_path, base):
                return saved_path
        existing = self._existing_output_path_for_row(row, base) if base else None
        if existing and engine.completed_output_exists(existing, base):
            return existing
        return None

    def _local_audio_download_func_for_row(self, row, candidate):
        source_value = row.get("local_audio_source_path") or ""
        if not source_value:
            return None
        ext = engine.normalized_output_ext((candidate or {}).get("output_ext") or (candidate or {}).get("ext"))
        if ext not in engine.AUDIO_OUTPUT_EXTENSIONS:
            return None
        source_path = Path(source_value).expanduser()
        if not source_path.is_file():
            return None

        def convert_local_audio(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
            del page_url, candidate, output_dir, cookie_source, proxy_url
            return engine.convert_existing_media_to_audio(
                source_path,
                ext,
                output_dir=source_path.parent,
                on_event=on_event,
            )

        return convert_local_audio

    def _local_segment_download_func_for_row(self, row, candidate):
        source_value = row.get("local_segment_source_path") or ""
        if not source_value:
            return None
        source_path = Path(source_value).expanduser()
        if not source_path.is_file():
            return None

        def extract_local_segment(page_url, candidate, output_dir, cookie_source=None, proxy_url=None, on_event=None):
            del page_url, cookie_source, proxy_url
            return engine.extract_existing_media_segment(
                source_path,
                candidate,
                output_dir=output_dir,
                on_event=on_event,
            )

        return extract_local_segment

    def _clip_range_tuple(self, candidate):
        clip_range = engine.clip_range_from_candidate(candidate or {})
        if not clip_range:
            return None
        return (clip_range.get("start"), clip_range.get("end"))

    def _row_owns_clip_range(self, row, clip_tuple):
        if not clip_tuple:
            return True
        if not row or not row.get("fixed_candidate"):
            return False
        return self._clip_range_tuple(row.get("candidate") or {}) == clip_tuple

    def _row_clip_download_base_candidate(self, row):
        base = row.get("download_base_candidate") if row else None
        if isinstance(base, dict) and base:
            return dict(base)
        candidate = dict((row or {}).get("candidate") or {})
        clip_range = candidate.get("clip_range")
        if not clip_range:
            return candidate
        cleaned = dict(candidate)
        suffix = engine.clip_range_suffix(clip_range)
        for key in ("title", "display_title"):
            text = str(cleaned.get(key) or "")
            if suffix and text.endswith(suffix):
                cleaned[key] = text[: -len(suffix)].rstrip()
        cleaned.pop("clip_range", None)
        cleaned.pop("clip_cut_mode", None)
        source_duration = engine.safe_int(cleaned.get("source_duration"))
        if source_duration:
            cleaned["duration"] = source_duration
        source_size = engine.safe_int(cleaned.get("source_filesize"))
        if source_size:
            cleaned["sort_bytes"] = source_size
            if engine.safe_int(cleaned.get("filesize")):
                cleaned["filesize"] = source_size
                cleaned["filesize_approx"] = 0
            else:
                cleaned["filesize"] = 0
                cleaned["filesize_approx"] = source_size
        return cleaned

    def _restore_row_base_display_if_needed(self, row):
        if not row or row.get("fixed_candidate"):
            return
        base = self._row_clip_download_base_candidate(row)
        if not base:
            return
        current = dict(row.get("candidate") or {})
        if current == base:
            return
        row["candidate"] = base
        saved_qualities = row.get("download_base_qualities")
        if isinstance(saved_qualities, list) and saved_qualities:
            row["qualities"] = list(saved_qualities)
            saved_options = row.get("download_base_quality_options")
            row["quality_options"] = list(saved_options) if isinstance(saved_options, list) and saved_options else build_quality_options(row["qualities"])
        widget = row.get("widget")
        if widget:
            widget.refresh()

    def _clip_spawn_candidate_from_row(self, row, prepared_candidate):
        return self._spawn_download_candidate_from_row(row, prepared_candidate)

    def _download_target_signature(self, candidate, row=None):
        candidate = candidate or {}
        clip = self._clip_range_tuple(candidate)
        media_id = str(
            candidate.get("id")
            or candidate.get("format_id")
            or candidate.get("format_selector")
            or ""
        ).strip()
        ext = str(candidate.get("output_ext") or candidate.get("ext") or "").strip().lower()
        source = str(
            candidate.get("source")
            or candidate.get("webpage_url")
            or candidate.get("url")
            or (row or {}).get("source_url")
            or (row or {}).get("input_url")
            or ""
        ).strip()
        return (source, clip, media_id, ext)

    def _active_download_candidate_for_row(self, row):
        if not row:
            return None
        for item in getattr(self, "active_downloads", []) or []:
            if item.get("row") is row and isinstance(item.get("candidate"), dict):
                return item.get("candidate")
        queued = (row or {}).get("_queued_download_candidate")
        if isinstance(queued, dict):
            return queued
        active = (row or {}).get("active_download_candidate")
        if isinstance(active, dict):
            return active
        return None

    def _row_target_candidate(self, row):
        active = self._active_download_candidate_for_row(row)
        if active:
            return active
        return (row or {}).get("candidate") or {}

    def _download_targets_match(self, row, prepared_candidate):
        if not row or not prepared_candidate:
            return False
        return self._download_target_signature(self._row_target_candidate(row), row) == self._download_target_signature(
            prepared_candidate, row
        )

    def _row_is_queued(self, row):
        return bool(row) and row in getattr(self, "queued_download_rows", [])

    def _row_is_unclaimed_analysis_row(self, row):
        if not row:
            return False
        if row.get("fixed_candidate"):
            return False
        if row.get("output_path"):
            return False
        if row.get("download_started_at"):
            return False
        if row.get("download_starting"):
            return False
        if row.get("active_download_candidate") or row.get("_queued_download_candidate"):
            return False
        if hasattr(self, "_row_is_downloading") and self._row_is_downloading(row):
            return False
        if self._row_is_queued(row):
            return False
        status = row.get("status")
        if status in {DOWNLOAD_STATUS, WAITING_STATUS, COMPLETED_STATUS, PAUSED_STATUS, ANALYZING_STATUS}:
            return False
        # READY (or empty) analysis cards can be claimed by the first download.
        return status in {None, "", READY_STATUS, ERROR_STATUS}

    def _should_spawn_download_sibling_row(self, row, prepared_candidate):
        """Spawn a new card unless this is an exact duplicate or an unclaimed analysis row."""
        if not row or not prepared_candidate:
            return False
        if self._download_targets_match(row, prepared_candidate):
            return False
        if self._row_is_unclaimed_analysis_row(row):
            return False
        return True

    def _should_spawn_clip_sibling_row(self, row):
        # Backward-compatible name: busy/completed rows used to always spawn for a new clip.
        if not row:
            return False
        if row.get("status") == COMPLETED_STATUS:
            return True
        if hasattr(self, "_row_is_downloading") and self._row_is_downloading(row):
            return True
        if row in getattr(self, "queued_download_rows", []):
            return True
        return False

    def _spawn_download_candidate_from_row(self, row, prepared_candidate):
        prepared = dict(prepared_candidate or {})
        base = self._row_clip_download_base_candidate(row)
        if not base:
            return prepared
        rebuilt = dict(base)
        clip_range = engine.clip_range_from_candidate(prepared)
        if clip_range:
            rebuilt["clip_range"] = clip_range
            cut_mode = prepared.get("clip_cut_mode")
            if cut_mode:
                rebuilt["clip_cut_mode"] = cut_mode
            return engine.candidate_with_clip_range_metadata(rebuilt)
        rebuilt.pop("clip_range", None)
        rebuilt.pop("clip_cut_mode", None)
        # Prefer request metadata (title/ext/etc.) when spawning a full sibling from a clip card.
        for key in ("title", "display_title", "output_ext", "ext", "format_selector", "id", "format_id"):
            if prepared.get(key) not in (None, ""):
                rebuilt[key] = prepared.get(key)
        return rebuilt

    def _spawn_clip_range_download_row(self, source_row, prepared_candidate):
        return self._spawn_download_row(source_row, prepared_candidate)

    def _spawn_download_row(self, source_row, prepared_candidate):
        if not source_row or not prepared_candidate:
            return None
        prepared = dict(prepared_candidate)
        if prepared.get("clip_range"):
            prepared = engine.candidate_with_clip_range_metadata(prepared)
        created_order = self._next_row_sequence()
        clip_locked = bool(engine.clip_range_from_candidate(prepared))
        new_row = {
            "id": f"{source_row.get('id') or 'row'}-dl-{created_order}",
            "kind": source_row.get("kind") or "video",
            "candidate": prepared,
            "qualities": [prepared],
            "quality_options": build_quality_options([prepared]),
            "selected_index": 0,
            "selected_format_index": 0,
            "fixed_candidate": clip_locked,
            "analysis_source_url": source_row.get("analysis_source_url") or source_row.get("source_url") or "",
            "source_url": source_row.get("source_url") or prepared.get("source") or prepared.get("url") or "",
            "input_url": source_row.get("input_url") or source_row.get("source_url") or "",
            "status": READY_STATUS,
            "status_detail": "",
            "progress": 0,
            "progress_text": "",
            "output_path": "",
            "messages": [],
            "created_order": created_order,
            "parent_playlist_id": source_row.get("parent_playlist_id") or "",
            "is_playlist_child": bool(source_row.get("is_playlist_child")),
            "playlist_child_index": source_row.get("playlist_child_index") or 0,
            "playlist_key": source_row.get("playlist_key") or "",
        }
        if not clip_locked:
            new_row["download_base_candidate"] = dict(prepared)
        insert_at = self.rows.index(source_row) + 1
        self.rows.insert(insert_at, new_row)
        if hasattr(self, "_render_rows"):
            self._render_rows()
        return new_row

    def start_download_for_row(self, row):
        if row not in self.rows:
            return
        row_has_own_clip_range = bool(row.get("fixed_candidate") and (row.get("candidate") or {}).get("clip_range"))
        if hasattr(self, "current_clip_range") and not row_has_own_clip_range:
            try:
                self.current_clip_range()
            except ValueError as exc:
                self._set_status(str(exc))
                return
        if row.get("kind") == "playlist":
            self._start_playlist_children_downloads(row)
            return
        candidate = self.selected_candidate_for_row_ref(row)
        if not candidate:
            self._set_status("다운로드할 항목을 선택하세요")
            return
        try:
            prepared_candidate = self._candidate_for_download(row, candidate) if hasattr(self, "_candidate_for_download") else dict(candidate)
        except ValueError as exc:
            self._set_row_download_error(row, str(exc))
            return
        requested_clip = self._clip_range_tuple(prepared_candidate)
        if self._should_spawn_download_sibling_row(row, prepared_candidate):
            self._restore_row_base_display_if_needed(row)
            spawn_candidate = self._spawn_download_candidate_from_row(row, prepared_candidate)
            sibling = self._spawn_download_row(row, spawn_candidate)
            if sibling:
                self.start_download_for_row(sibling)
                return
        if requested_clip and self._row_owns_clip_range(row, requested_clip) and hasattr(self, "_apply_download_candidate_to_row"):
            self._apply_download_candidate_to_row(row, prepared_candidate)
        candidate = prepared_candidate

        if self._row_is_downloading(row) or self._row_is_queued(row):
            if self._row_is_downloading(row):
                self._set_status("이미 다운로드 중")
            else:
                self._set_status("다운로드 대기 중")
            return
        existing_output = self._existing_output_path_for_row(row, candidate)
        if existing_output:
            self._notify_existing_output(row, existing_output, candidate)
            return
        if len(self.active_downloads) >= self._download_concurrency_limit():
            row["_queued_download_candidate"] = dict(candidate)
            self.queued_download_rows.append(row)
            self._set_row_status(row, WAITING_STATUS, "")
            widget = row.get("widget")
            if widget:
                widget.set_progress(0, "")
            self._set_status("다운로드 대기 중")
            self._refresh_footer()
            return

        download_func = self._local_segment_download_func_for_row(row, candidate) or self._local_audio_download_func_for_row(row, candidate)
        if download_func:
            self._begin_download(row, candidate, download_func=download_func, prepared=True)
        else:
            self._begin_download(row, candidate, prepared=True)

    def _playlist_children_for_parent(self, parent):
        parent_id = parent.get("id")
        return [row for row in self.rows if row.get("parent_playlist_id") == parent_id]

    def _start_playlist_children_downloads(self, parent):
        parent.pop("_playlist_auto_download_paused", None)
        if parent.get("analysis_loading"):
            self._analysis_auto_download = True
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
                child["progress"] = 0
                child["progress_text"] = "0%"
                self._set_row_status(child, DOWNLOAD_STATUS, "")
                widget = child.get("widget")
                if widget:
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
                parent["status"] = PAUSED_STATUS if parent.get("_playlist_auto_download_paused") else ANALYZING_STATUS
                parent["status_detail"] = f"0/{total}"
                parent["progress"] = 0
                parent["progress_text"] = "0%" if parent.get("_playlist_auto_download_paused") else ""
            widget = parent.get("widget")
            if widget:
                widget.refresh()
            return
        self._refresh_playlist_parent_metadata(parent)
        completed = sum(1 for row in children if row.get("status") == COMPLETED_STATUS)
        active = sum(1 for row in children if row.get("status") in {DOWNLOAD_STATUS, WAITING_STATUS})
        paused = sum(1 for row in children if row.get("status") == PAUSED_STATUS)
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
        elif parent.get("_playlist_auto_download_paused"):
            status = PAUSED_STATUS
            detail = f"{completed}/{total}" if total else ""
            progress_text = f"{progress}%"
        elif paused:
            status = PAUSED_STATUS
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
        parent["progress"] = progress
        parent["progress_text"] = progress_text
        self._set_row_status(parent, status, detail)
        widget = parent.get("widget")
        if widget:
            widget.set_progress(progress, progress_text)

    def _begin_download(self, row, candidate=None, download_func=None, *, prepared=False):
        # When caller already prepared a target (start_download_for_row / queue), keep it.
        # Re-reading live UI clip here was overwriting an in-flight full download with a later clip.
        if candidate is None:
            candidate = self.selected_candidate_for_row_ref(row)
            prepared = False
        if not candidate:
            return
        resume_progress = 0
        resume_progress_text = ""
        if row.get("status") == PAUSED_STATUS:
            resume_progress = max(0, min(99, engine.safe_int(row.get("progress"))))
            resume_progress_text = row.get("progress_text") or (f"{resume_progress}%" if resume_progress else "")
        download_candidate = dict(candidate)
        if not prepared and hasattr(self, "_candidate_for_download"):
            try:
                download_candidate = self._candidate_for_download(row, candidate)
            except ValueError as exc:
                self._set_row_download_error(row, str(exc))
                return
        if download_candidate.get("clip_range") and hasattr(self, "_apply_download_candidate_to_row"):
            self._apply_download_candidate_to_row(row, download_candidate)
        download_candidate["_clipflow_row_id"] = str(row.get("id") or "")
        self.primary_button.set_loading(False)
        self.selected_row_index = self.rows.index(row)
        self._refresh_row_selection()
        if row.get("status") != PAUSED_STATUS:
            row["output_path"] = ""
            row["status_detail"] = ""
        row["download_started_at"] = time.time()
        row.pop("analysis_loading", None)
        row.pop("child_loading", None)
        row["download_starting"] = True
        row.pop("download_finishing", None)
        row.pop("_queued_download_candidate", None)
        row["active_download_candidate"] = dict(download_candidate)
        self._set_row_status(row, DOWNLOAD_STATUS, "")
        widget = row.get("widget")
        if widget:
            if resume_progress:
                widget.set_progress(resume_progress, resume_progress_text or "이어받기 준비 중")
            else:
                widget.set_progress(0, "다운로드 준비 중")
        self._set_status("이어받기 준비 중" if resume_progress else "다운로드 준비 중")

        page_url = row.get("source_url") or (self.analysis or {}).get("webpage_url") or self.url_input.text().strip()
        thread = QThread(self)
        worker = DownloadWorker(
            str(row.get("id") or ""),
            page_url,
            download_candidate,
            self._output_dir_for_row(row, download_candidate),
            cookie_source_from_display(self.cookie_combo.currentText()),
            download_func or self.download_func,
        )
        self.active_downloads.append(
            {"thread": thread, "worker": worker, "row": row, "candidate": dict(download_candidate)}
        )
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

    def pause_download_for_row(self, row):
        if not row or row not in self.rows:
            return
        if row.get("kind") == "playlist":
            was_analyzing = bool(
                row.get("analysis_loading")
                or (self.analysis_thread and self.analysis_thread.isRunning() and self._playlist_event_parent_id == row.get("id"))
            )
            auto_download = bool(self._analysis_auto_download)
            for child in self._playlist_children_for_parent(row):
                if child.get("status") in {DOWNLOAD_STATUS, WAITING_STATUS} or child in self.queued_download_rows:
                    self.pause_download_for_row(child)
            if was_analyzing and hasattr(self, "_pause_playlist_analysis"):
                self._pause_playlist_analysis(row, auto_download=auto_download)
            else:
                row["_playlist_auto_download_paused"] = True
                self._analysis_auto_download = False
            self._set_row_paused(row)
            if row.get("analysis_loading") or row.get("_playlist_analysis_resume"):
                row["progress_text"] = "분석 일시정지"
                self._set_row_status(row, PAUSED_STATUS, "분석 일시정지")
                widget = row.get("widget")
                if widget:
                    widget._refresh_actions()
            self._refresh_playlist_parent_status(row)
            self._refresh_parent_for_child(row)
            self._refresh_footer()
            self._render_rows()
            return
        if row in self.queued_download_rows:
            self.queued_download_rows = [queued for queued in self.queued_download_rows if queued is not row]
            self._set_row_paused(row)
            self._sync_legacy_download_refs()
            self._refresh_primary_action()
            self._refresh_footer()
            self._refresh_parent_for_child(row)
            return
        items = [item for item in self.active_downloads if item.get("row") is row]
        if not items:
            return
        row["download_cancel_requested"] = True
        pending_items = []
        for item in items:
            if not self._cancel_active_download_item(item):
                pending_items.append(item)
        if pending_items:
            # Keep live threads in active_downloads so _row_is_downloading / finished
            # handlers still find this row until the worker actually exits.
            self.active_downloads = [
                item
                for item in self.active_downloads
                if item.get("row") is not row or item in pending_items
            ]
            row["_pause_cleanup_pending"] = True
            row["progress_text"] = row.get("progress_text") or ""
            self._set_row_status(row, PAUSED_STATUS, "일시정지 정리 중")
            widget = row.get("widget")
            if widget:
                widget.set_progress(row.get("progress") or 0, row.get("progress_text") or "")
                widget._refresh_actions()
            QTimer.singleShot(600, lambda r=row: self._finish_delayed_pause_cleanup(r))
        else:
            self.active_downloads = [item for item in self.active_downloads if item.get("row") is not row]
            self._set_row_paused(row)
        self._sync_legacy_download_refs()
        self._refresh_primary_action()
        self._refresh_footer()
        self._refresh_parent_for_child(row)
        self._start_queued_downloads()

    def _finish_delayed_pause_cleanup(self, row):
        if not row or row not in self.rows:
            return
        if self._row_is_downloading(row):
            QTimer.singleShot(600, lambda r=row: self._finish_delayed_pause_cleanup(r))
            return
        # Thread gone: now safe to wipe partials. finished-handler may already have cleaned.
        if row.get("_pause_cleanup_pending") or row.get("download_cancel_requested"):
            self._complete_pause_cleanup(row)

    def _complete_pause_cleanup(self, row):
        """Finish pause after workers exit; optionally resume if user clicked during cleanup."""
        if not row:
            return
        should_resume = bool(row.pop("_resume_after_pause_cleanup", False))
        row.pop("_pause_cleanup_pending", None)
        self._set_row_paused(row)
        if should_resume and row in self.rows:
            # finished() may run before thread-finished removes the active item;
            # wait until the row is fully idle before starting a new download.
            row["_resume_after_pause_cleanup"] = True
            QTimer.singleShot(0, lambda r=row: self._resume_after_pause_cleanup_when_idle(r))

    def _resume_after_pause_cleanup_when_idle(self, row):
        if not row or row not in self.rows:
            return
        if self._row_is_downloading(row):
            QTimer.singleShot(100, lambda r=row: self._resume_after_pause_cleanup_when_idle(r))
            return
        row.pop("_resume_after_pause_cleanup", None)
        self.resume_download_for_row(row)

    def _cancel_active_download_item(self, item):
        """Request cancel and wait briefly. Returns True if the worker thread has stopped."""
        row = item.get("row")
        row_id = str((row or {}).get("id") or "")
        if row_id:
            try:
                engine.cancel_download_request(row_id)
            except Exception:
                pass
        thread = item.get("thread")
        if not thread:
            return True
        for method_name in ("requestInterruption", "quit"):
            method = getattr(thread, method_name, None)
            if callable(method):
                method()
        wait = getattr(thread, "wait", None)
        stopped = True
        if callable(wait):
            try:
                stopped = bool(wait(800))
            except TypeError:
                stopped = bool(wait())
        if not stopped:
            terminate = getattr(thread, "terminate", None)
            if callable(terminate):
                terminate()
            if callable(wait):
                try:
                    stopped = bool(wait(1000))
                except TypeError:
                    wait()
                    stopped = not thread.isRunning()
        if not stopped:
            try:
                stopped = not thread.isRunning()
            except Exception:
                stopped = False
        return bool(stopped)

    def _set_row_paused(self, row):
        self._cleanup_row_partial_files(row)
        row["download_starting"] = False
        row.pop("download_finishing", None)
        row.pop("active_download_candidate", None)
        row.pop("_queued_download_candidate", None)
        row.pop("_pause_cleanup_pending", None)
        row.pop("download_cancel_requested", None)
        row["progress_text"] = row.get("progress_text") or ""
        self._set_row_status(row, PAUSED_STATUS, "")
        widget = row.get("widget")
        if widget:
            widget.set_progress(row.get("progress") or 0, row.get("progress_text") or "")
            widget._refresh_actions()
        self._set_status(PAUSED_STATUS)

    def _set_row_download_error(self, row, message):
        message = str(message or "")
        if row:
            self._cleanup_row_partial_files(row)
            row["download_starting"] = False
            row.pop("download_finishing", None)
            row.pop("active_download_candidate", None)
            row.pop("_queued_download_candidate", None)
            row["progress"] = 0
            row["progress_text"] = ""
            row.setdefault("messages", []).append(message)
            self._set_row_status(row, ERROR_STATUS, message)
            widget = row.get("widget")
            if widget:
                widget.set_progress(0, "")
                widget._refresh_actions()
        self._set_status(message)

    def resume_download_for_row(self, row):
        if not row or row not in self.rows:
            return
        # Do not clear cancel flags or start a second worker while the old one is exiting.
        if row.get("_pause_cleanup_pending") or (
            row.get("status") == PAUSED_STATUS and self._row_is_downloading(row)
        ):
            row["_resume_after_pause_cleanup"] = True
            self._set_status("일시정지 정리 후 다시 시작합니다")
            return
        if row.get("kind") == "playlist":
            needs_analysis_resume = bool(row.get("_playlist_analysis_resume") or row.get("analysis_loading"))
            for child in self._playlist_children_for_parent(row):
                if child.get("status") == PAUSED_STATUS:
                    self.resume_download_for_row(child)
            if needs_analysis_resume and hasattr(self, "_resume_playlist_analysis"):
                if self._resume_playlist_analysis(row):
                    # Also download any already-ready children if auto-download was on.
                    resume = row.get("_playlist_analysis_resume") or {}
                    if resume.get("auto_download") or self._analysis_auto_download:
                        for child in self._playlist_children_for_parent(row):
                            if child.get("child_loading") or child.get("status") in {
                                COMPLETED_STATUS,
                                DOWNLOAD_STATUS,
                                WAITING_STATUS,
                                ERROR_STATUS,
                                PAUSED_STATUS,
                            }:
                                continue
                            self.start_download_for_row(child)
                    self._refresh_playlist_parent_status(row)
                    self._render_rows()
                    return
            row.pop("_playlist_auto_download_paused", None)
            row.pop("_playlist_analysis_resume", None)
            self._start_playlist_children_downloads(row)
            self._refresh_playlist_parent_status(row)
            return
        if row.get("status") == PAUSED_STATUS:
            row.pop("download_cancel_requested", None)
            row.pop("_resume_after_pause_cleanup", None)
            self.start_download_for_row(row)

    def _sync_legacy_download_refs(self):
        first = self.active_downloads[0] if self.active_downloads else None
        self.download_thread = first.get("thread") if first else None
        self.download_worker = first.get("worker") if first else None
        self.active_download_row = first.get("row") if first else None

    def _cleanup_row_partial_files(self, row, candidate=None):
        if not row:
            return
        try:
            selected = candidate or self.selected_candidate_for_row_ref(row) or row.get("candidate") or {}
            output_dir = self._output_dir_for_row(row, selected)
            output_path = engine.final_output_path_for_candidate(selected, output_dir)
            if output_path:
                engine.cleanup_partial_output_files(output_path)
        except Exception:
            pass

    def _existing_output_path_for_row(self, row, candidate):
        saved_output = row.get("output_path") or ""
        output_path = Path(saved_output)
        row_output_dir = self._output_dir_for_row(row, candidate)
        expected_output = engine.final_output_path_for_candidate(candidate, row_output_dir)
        saved_matches_candidate = False
        if saved_output and expected_output is not None:
            try:
                saved_matches_candidate = output_path.expanduser().resolve() == Path(expected_output).expanduser().resolve()
            except OSError:
                saved_matches_candidate = output_path.expanduser() == Path(expected_output).expanduser()
        if (
            saved_output
            and row.get("status") == "완료"
            and saved_matches_candidate
            and engine.completed_output_exists(output_path, candidate)
            and not engine.output_is_too_small_for_candidate(output_path, candidate)
        ):
            return output_path
        existing = engine.existing_output_path_for_candidate(candidate, row_output_dir)
        if existing:
            return existing
        return None

    def _normalize_output_path(self, path):
        if not path:
            return None
        try:
            return Path(path).expanduser().resolve()
        except OSError:
            return Path(path).expanduser()

    def _find_row_for_existing_output(self, output_path, candidate, exclude_row=None):
        """Prefer an existing completed/busy card for this file/target over a fresh analysis card."""
        target_path = self._normalize_output_path(output_path)
        target_sig = self._download_target_signature(candidate)
        path_match = None
        target_match = None
        for row in self.rows:
            if row is exclude_row:
                continue
            if hasattr(self, "_is_analysis_loading_row") and self._is_analysis_loading_row(row):
                continue
            if row.get("kind") == "playlist" and not row.get("is_playlist_child"):
                continue
            row_path = self._normalize_output_path(row.get("output_path") or "")
            if target_path and row_path and row_path == target_path:
                path_match = path_match or row
                if row.get("status") == COMPLETED_STATUS:
                    return row
            row_sig = self._download_target_signature(self._row_target_candidate(row), row)
            if row_sig == target_sig:
                if self._row_is_downloading(row) or self._row_is_queued(row):
                    return row
                if row.get("status") == COMPLETED_STATUS:
                    target_match = target_match or row
        return path_match or target_match

    def _row_is_ephemeral_duplicate_notice_row(self, row):
        """Fresh analysis/ready card that should not stay after redirecting an existing-file notice."""
        if not row:
            return False
        if self._row_is_downloading(row) or self._row_is_queued(row):
            return False
        if row.get("download_starting") or row.get("active_download_candidate"):
            return False
        if row.get("status") in {DOWNLOAD_STATUS, WAITING_STATUS, PAUSED_STATUS, ANALYZING_STATUS}:
            return False
        if row.get("status") == COMPLETED_STATUS and row.get("output_path") and row.get("status_detail") != "이미 있는 파일":
            return False
        if row.get("fixed_candidate") and row.get("status") == COMPLETED_STATUS and row.get("output_path"):
            return False
        return True

    def _discard_ephemeral_row(self, row):
        if not row or row not in self.rows:
            return
        if row in getattr(self, "queued_download_rows", []):
            self.queued_download_rows = [item for item in self.queued_download_rows if item is not row]
        try:
            index = self.rows.index(row)
        except ValueError:
            return
        self.rows.pop(index)
        if getattr(self, "selected_row_index", -1) == index:
            self.selected_row_index = -1
        elif getattr(self, "selected_row_index", -1) > index:
            self.selected_row_index -= 1
        if hasattr(self, "_render_rows"):
            self._render_rows()
        if hasattr(self, "_refresh_row_selection"):
            self._refresh_row_selection()
        if hasattr(self, "_refresh_primary_action"):
            self._refresh_primary_action()

    def _notify_existing_output(self, row, output_path, candidate=None):
        """Show existing-file notice on the best matching card; drop a fresh duplicate card if needed."""
        prepared = candidate or (row or {}).get("candidate") or {}
        owner = self._find_row_for_existing_output(output_path, prepared, exclude_row=row)
        if owner is None:
            owner = row
        if owner is not None and owner is not row and row is not None and self._row_is_ephemeral_duplicate_notice_row(row):
            self._discard_ephemeral_row(row)
        if owner is None:
            return None
        self._mark_existing_output(owner, output_path)
        return owner

    def _output_dir_for_row(self, row, candidate):
        base = self.folder_input.text()
        try:
            base = str(engine.windows_long_path(base))
        except Exception:
            base = str(base or "")
        if row and row.get("is_playlist_child"):
            parent = self._parent_playlist_for_child(row)
            if parent:
                return engine.output_dir_for_candidate(parent.get("candidate") or {}, base)
        return engine.output_dir_for_candidate(candidate, base)

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

    def _apply_actual_output_size(self, row, output_path=None):
        if not row:
            return
        path = Path(output_path or row.get("output_path") or "")
        if not path.is_file():
            return
        try:
            actual_size = path.stat().st_size
        except OSError:
            return
        if actual_size <= 0:
            return
        selected = self.selected_candidate_for_row_ref(row) or row.get("candidate") or {}
        candidate = dict(selected)
        candidate["filesize"] = actual_size
        candidate["filesize_approx"] = 0
        candidate["sort_bytes"] = actual_size
        candidate["size_source"] = "actual"
        row["candidate"] = candidate
        row["qualities"] = [candidate]
        row["quality_options"] = build_quality_options([candidate])
        row["selected_index"] = 0
        row["selected_format_index"] = 0

    def _mark_existing_output(self, row, output_path):
        row["output_path"] = str(output_path)
        self._apply_actual_output_size(row, output_path)
        row["progress"] = 100
        row["progress_text"] = "이미 있는 파일"
        self._set_row_status(row, COMPLETED_STATUS, "이미 있는 파일")
        widget = row.get("widget")
        if widget:
            widget.refresh()
            widget.set_progress(100, "이미 있는 파일")
            widget._refresh_actions()
        if hasattr(self, "_render_rows"):
            self._render_rows()
        if hasattr(self, "_scroll_row_to_top"):
            self._scroll_row_to_top(row)
        widget = row.get("widget")
        if widget and hasattr(widget, "flash_existing_output_notice"):
            widget.flash_existing_output_notice()
        token = time.monotonic()
        row["_existing_notice_token"] = token
        QTimer.singleShot(3000, lambda: self._clear_existing_output_notice(row, token))
        self._save_completed_history()
        self._set_status(f"이미 파일 있음: {Path(output_path).name}")
        self._refresh_primary_action()
        self._refresh_footer()
        self._refresh_parent_for_child(row)

    def _clear_existing_output_notice(self, row, token):
        if not isinstance(row, dict) or row.get("_existing_notice_token") != token:
            return
        row.pop("_existing_notice_token", None)
        if row.get("status") != "완료" or row.get("status_detail") != "이미 있는 파일":
            return
        row["progress_text"] = ""
        self._set_row_status(row, COMPLETED_STATUS, "")
        widget = row.get("widget")
        if widget:
            widget.set_progress(100, "")
            widget._refresh_actions()

    @Slot(dict)
    def _download_finished(self, result):
        self._download_finished_for(self.active_download_row, result)

    def _download_finished_for(self, row, result):
        if row:
            if row.pop("download_cancel_requested", False) or row.get("_pause_cleanup_pending"):
                self._complete_pause_cleanup(row)
                return
            row["download_starting"] = False
            row.pop("download_finishing", None)
            row.pop("active_download_candidate", None)
            row.pop("_queued_download_candidate", None)
            clip_locked = bool(engine.clip_range_from_candidate(row.get("candidate") or {}))
            if clip_locked:
                row["fixed_candidate"] = True
            elif not row.get("local_segment_source_path"):
                row.pop("fixed_candidate", None)
            if not row.get("fixed_candidate"):
                selected = self.selected_candidate_for_row_ref(row)
                if selected:
                    row["candidate"] = selected
                    row["qualities"] = [selected]
                    row["quality_options"] = build_quality_options([selected])
            self._resolve_finished_output_path(row, result)
            self._apply_actual_output_size(row)
            row["progress"] = 100
            row["progress_text"] = "완료"
            self._set_row_status(row, COMPLETED_STATUS, "")
            widget = row.get("widget")
            if widget:
                widget.refresh()
                widget.set_progress(100, "완료")
                widget._refresh_actions()
            self._save_completed_history()
        self._set_status("완료")
        output_dir = result.get("output_dir") if isinstance(result, dict) else None
        if output_dir:
            self._append_event_message(str(output_dir))

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
            if row.pop("download_cancel_requested", False) or row.get("_pause_cleanup_pending"):
                self._complete_pause_cleanup(row)
                return
            self._cleanup_row_partial_files(row)
            row["download_starting"] = False
            row.pop("download_finishing", None)
            row.setdefault("messages", []).append(message)
            self._set_row_status(row, ERROR_STATUS, message)
            widget = row.get("widget")
            if widget:
                widget.set_progress(0, "")
        self._set_status(f"{engine.classify_error(message)}: {message}")
        self._maybe_prompt_macos_cookie_permission(message)

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
        while self.queued_download_rows and len(self.active_downloads) < self._download_concurrency_limit():
            row = self.queued_download_rows.pop(0)
            if row not in self.rows or self._row_is_downloading(row):
                row.pop("_queued_download_candidate", None)
                continue
            queued_candidate = row.pop("_queued_download_candidate", None)
            if isinstance(queued_candidate, dict) and queued_candidate:
                candidate = dict(queued_candidate)
                prepared = True
            else:
                candidate = self.selected_candidate_for_row_ref(row)
                prepared = False
                if candidate and hasattr(self, "_candidate_for_download"):
                    try:
                        candidate = self._candidate_for_download(row, candidate)
                        prepared = True
                    except ValueError as exc:
                        self._set_row_download_error(row, str(exc))
                        continue
            if not candidate:
                continue
            existing_output = self._existing_output_path_for_row(row, candidate)
            if existing_output:
                self._notify_existing_output(row, existing_output, candidate)
                continue
            download_func = self._local_segment_download_func_for_row(row, candidate) or self._local_audio_download_func_for_row(row, candidate)
            if download_func:
                self._begin_download(row, candidate, download_func=download_func, prepared=prepared)
            else:
                self._begin_download(row, candidate, prepared=prepared)
