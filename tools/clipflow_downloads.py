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
        if prepared_candidate.get("clip_range") and hasattr(self, "_apply_download_candidate_to_row"):
            self._apply_download_candidate_to_row(row, prepared_candidate)
        candidate = prepared_candidate

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
        if len(self.active_downloads) >= self._download_concurrency_limit():
            self.queued_download_rows.append(row)
            widget = row.get("widget")
            if widget:
                widget.set_status("대기")
                widget.set_progress(0, "")
            self._set_status("다운로드 대기 중")
            self._refresh_footer()
            return

        download_func = self._local_segment_download_func_for_row(row, candidate) or self._local_audio_download_func_for_row(row, candidate)
        if download_func:
            self._begin_download(row, candidate, download_func=download_func)
        else:
            self._begin_download(row, candidate)

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
        parent["status"] = status
        parent["status_detail"] = detail
        parent["progress"] = progress
        parent["progress_text"] = progress_text
        widget = parent.get("widget")
        if widget:
            widget.set_status(status, detail)
            widget.set_progress(progress, progress_text)

    def _begin_download(self, row, candidate=None, download_func=None):
        candidate = candidate or self.selected_candidate_for_row_ref(row)
        if not candidate:
            return
        resume_progress = 0
        resume_progress_text = ""
        if row.get("status") == PAUSED_STATUS:
            resume_progress = max(0, min(99, engine.safe_int(row.get("progress"))))
            resume_progress_text = row.get("progress_text") or (f"{resume_progress}%" if resume_progress else "")
        try:
            download_candidate = self._candidate_for_download(row, candidate) if hasattr(self, "_candidate_for_download") else candidate
        except ValueError as exc:
            self._set_row_download_error(row, str(exc))
            return
        if download_candidate.get("clip_range") and hasattr(self, "_apply_download_candidate_to_row"):
            self._apply_download_candidate_to_row(row, download_candidate)
        download_candidate["_clipflow_row_id"] = str(row.get("id") or "")
        self.primary_button.set_loading(False)
        self.selected_row_index = self.rows.index(row)
        self._refresh_row_selection()
        row["download_started_at"] = time.time()
        row["download_starting"] = True
        widget = row.get("widget")
        if widget:
            widget.set_status("다운로드 중")
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
            self._output_dir_for_row(row, candidate),
            cookie_source_from_display(self.cookie_combo.currentText()),
            download_func or self.download_func,
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

    def pause_download_for_row(self, row):
        if not row or row not in self.rows:
            return
        if row.get("kind") == "playlist":
            row["_playlist_auto_download_paused"] = True
            self._analysis_auto_download = False
            for child in self._playlist_children_for_parent(row):
                if child.get("status") in {DOWNLOAD_STATUS, WAITING_STATUS} or child in self.queued_download_rows:
                    self.pause_download_for_row(child)
            self._set_row_paused(row)
            self._refresh_playlist_parent_status(row)
            self._refresh_parent_for_child(row)
            self._refresh_footer()
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
        for item in items:
            self._cancel_active_download_item(item)
        self.active_downloads = [item for item in self.active_downloads if item.get("row") is not row]
        self._set_row_paused(row)
        self._sync_legacy_download_refs()
        self._refresh_primary_action()
        self._refresh_footer()
        self._refresh_parent_for_child(row)
        self._start_queued_downloads()

    def _cancel_active_download_item(self, item):
        row = item.get("row")
        row_id = str((row or {}).get("id") or "")
        if row_id:
            try:
                engine.cancel_download_request(row_id)
            except Exception:
                pass
        thread = item.get("thread")
        if thread:
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
                        wait(1000)
                    except TypeError:
                        wait()

    def _set_row_paused(self, row):
        row["download_starting"] = False
        row["status"] = PAUSED_STATUS
        row["status_detail"] = ""
        row["progress_text"] = row.get("progress_text") or ""
        widget = row.get("widget")
        if widget:
            widget.set_status(PAUSED_STATUS)
            widget.set_progress(row.get("progress") or 0, row.get("progress_text") or "")
            widget._refresh_actions()
        self._set_status(PAUSED_STATUS)

    def _set_row_download_error(self, row, message):
        message = str(message or "")
        if row:
            row["download_starting"] = False
            row["status"] = ERROR_STATUS
            row["status_detail"] = message
            row["progress"] = 0
            row["progress_text"] = ""
            row.setdefault("messages", []).append(message)
            widget = row.get("widget")
            if widget:
                widget.set_status(ERROR_STATUS, message)
                widget.set_progress(0, "")
                widget._refresh_actions()
        self._set_status(message)

    def resume_download_for_row(self, row):
        if not row or row not in self.rows:
            return
        if row.get("kind") == "playlist":
            row.pop("_playlist_auto_download_paused", None)
            if row.get("analysis_loading"):
                self._analysis_auto_download = True
            for child in self._playlist_children_for_parent(row):
                if child.get("status") == PAUSED_STATUS:
                    self.resume_download_for_row(child)
            self._start_playlist_children_downloads(row)
            self._refresh_playlist_parent_status(row)
            return
        if row.get("status") == PAUSED_STATUS:
            row.pop("download_cancel_requested", None)
            self.start_download_for_row(row)

    def _sync_legacy_download_refs(self):
        first = self.active_downloads[0] if self.active_downloads else None
        self.download_thread = first.get("thread") if first else None
        self.download_worker = first.get("worker") if first else None
        self.active_download_row = first.get("row") if first else None

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
        row["status"] = "완료"
        row["status_detail"] = "이미 있는 파일"
        row["progress"] = 100
        row["progress_text"] = "이미 있는 파일"
        widget = row.get("widget")
        if widget:
            widget.refresh()
            widget.set_status("완료", "이미 있는 파일")
            widget.set_progress(100, "이미 있는 파일")
            widget._refresh_actions()
        if hasattr(self, "_next_row_sequence"):
            row["created_order"] = self._next_row_sequence()
        if hasattr(self, "_render_rows"):
            self._render_rows()
        if hasattr(self, "_scroll_row_to_top"):
            self._scroll_row_to_top(row)
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
        row["status_detail"] = ""
        row["progress_text"] = ""
        widget = row.get("widget")
        if widget:
            widget.set_status("완료", "")
            widget.set_progress(100, "")
            widget._refresh_actions()

    @Slot(dict)
    def _download_finished(self, result):
        self._download_finished_for(self.active_download_row, result)

    def _download_finished_for(self, row, result):
        if row:
            if row.pop("download_cancel_requested", False):
                self._set_row_paused(row)
                return
            row["download_starting"] = False
            selected = self.selected_candidate_for_row_ref(row)
            if selected:
                row["candidate"] = selected
                row["qualities"] = [selected]
                row["quality_options"] = build_quality_options([selected])
            self._resolve_finished_output_path(row, result)
            self._apply_actual_output_size(row)
            widget = row.get("widget")
            if widget:
                widget.refresh()
                widget.set_status("완료")
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
            if row.pop("download_cancel_requested", False):
                self._set_row_paused(row)
                return
            row["download_starting"] = False
            widget = row.get("widget")
            row["messages"].append(message)
            if widget:
                widget.set_status("오류", message)
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
                continue
            candidate = self.selected_candidate_for_row_ref(row)
            if not candidate:
                continue
            existing_output = self._existing_output_path_for_row(row, candidate)
            if existing_output:
                self._mark_existing_output(row, existing_output)
                continue
            download_func = self._local_segment_download_func_for_row(row, candidate) or self._local_audio_download_func_for_row(row, candidate)
            if download_func:
                self._begin_download(row, candidate, download_func=download_func)
            else:
                self._begin_download(row, candidate)
