"""Playlist streaming-event handling for ClipFlowWindow.

Provided as a mixin so the large window class stays organized. All methods
operate on ``self`` (the ClipFlowWindow instance) and only rely on the module
imports below plus methods that remain on the window class.
"""

from pathlib import Path

try:
    from tools import candidate_presenter as presenter
    from tools import downloader_engine as engine
    from tools.clipflow_rows import build_quality_options, row_kind, row_source_url
    from tools.clipflow_theme import (
        ANALYZING_STATUS,
        COMPLETED_STATUS,
        DOWNLOAD_STATUS,
        ERROR_STATUS,
        READY_STATUS,
        WAITING_STATUS,
    )
except ImportError:
    import candidate_presenter as presenter
    import downloader_engine as engine
    from clipflow_rows import build_quality_options, row_kind, row_source_url
    from clipflow_theme import (
        ANALYZING_STATUS,
        COMPLETED_STATUS,
        DOWNLOAD_STATUS,
        ERROR_STATUS,
        READY_STATUS,
        WAITING_STATUS,
    )


class PlaylistMixin:
    def _handle_playlist_analysis_event(self, event):
        event_type = event.get("type")
        parent = self._ensure_playlist_event_parent(event)
        if not parent:
            return
        if event_type == "playlist_entry_loading":
            self._ensure_playlist_loading_child(parent, event.get("index"), event.get("title"), event.get("source_url") or event.get("url"))
            self._render_rows()
            return
        if event_type == "playlist_entry":
            entry_rows = self._replace_playlist_loading_with_entry(parent, event)
            self._render_rows()
            if self._analysis_auto_download:
                for entry_row in entry_rows or []:
                    self.start_download_for_row(entry_row)
            return
        if event_type == "playlist_failed_entry":
            self._replace_playlist_loading_with_failed_entry(parent, event)
            self._render_rows()
            return
        if event_type == "playlist_complete":
            self.rows = [
                row
                for row in self.rows
                if not (row.get("parent_playlist_id") == parent.get("id") and row.get("child_loading"))
            ]
            parent["analysis_loading"] = False
            self._analysis_auto_download = False
            self._refresh_playlist_parent_metadata(parent)
            self._refresh_playlist_parent_status(parent)
            self._render_rows()
            return
        self._ensure_playlist_loading_child(parent, event.get("index"), event.get("title"), event.get("source_url") or event.get("url"))
        self._render_rows()

    def _ensure_playlist_event_parent(self, event):
        source_url = event.get("source_url") or event.get("url") or self.url_input.text().strip()
        parent = self._find_row_by_id(self._playlist_event_parent_id)
        if not parent:
            parent = next((row for row in self.rows if row.get("kind") == "playlist" and row.get("analysis_loading")), None)
        if not parent:
            parent = self._playlist_parent_loading_row(source_url)
            self.rows = [parent] + [row for row in self.rows if not self._is_analysis_loading_row(row)]
        self._playlist_event_parent_id = parent.get("id") or ""
        if event.get("type") == "playlist_parent":
            title = event.get("title") or source_url
            count = engine.safe_int(event.get("count"))
            parent["candidate"].update(
                {
                    "title": title,
                    "display_title": title,
                    "item_count": count,
                    "playlist_count": count,
                    "source": source_url,
                    "url": source_url,
                    "webpage_url": source_url,
                }
            )
            parent["analysis_source_url"] = source_url
            parent["source_url"] = source_url
            parent["input_url"] = event.get("input_url") or source_url
        parent.setdefault("expanded", True)
        return parent

    def _ensure_playlist_loading_child(self, parent, index=None, title=None, source_url=None):
        parent_id = parent.get("id")
        if not parent_id:
            return
        child_index = engine.safe_int(index) or 0
        existing = next((row for row in self.rows if row.get("parent_playlist_id") == parent_id and row.get("child_loading")), None)
        if existing:
            if child_index:
                existing["playlist_child_index"] = child_index
            if title:
                existing["candidate"]["title"] = title
                existing["candidate"]["display_title"] = title
            if source_url:
                existing["source_url"] = source_url
                existing["analysis_source_url"] = source_url
                existing["input_url"] = source_url
            return
        source_url = source_url or parent.get("analysis_source_url") or parent.get("source_url") or self.url_input.text().strip()
        loading = self._playlist_child_loading_row(parent_id, source_url)
        if child_index:
            loading["playlist_child_index"] = child_index
        if title:
            loading["candidate"]["title"] = title
            loading["candidate"]["display_title"] = title
        children = self._playlist_children_for_parent(parent)
        insert_index = (self.rows.index(children[-1]) + 1) if children else (self.rows.index(parent) + 1 if parent in self.rows else len(self.rows))
        self.rows.insert(insert_index, loading)

    def _replace_playlist_loading_with_entry(self, parent, event):
        candidates = event.get("candidates") if isinstance(event.get("candidates"), list) else None
        if candidates is None:
            candidate = event.get("candidate") if isinstance(event.get("candidate"), dict) else None
            candidates = [candidate] if candidate else []
        candidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
        if not candidates:
            return []
        self._playlist_event_candidates.extend(candidates)
        analysis = event.get("analysis") if isinstance(event.get("analysis"), dict) else {}
        source_url = event.get("source_url") or event.get("url") or analysis.get("webpage_url") or parent.get("analysis_source_url") or parent.get("source_url") or self.url_input.text().strip()
        grouped = presenter.group_candidates(candidates)
        children = self._playlist_child_rows_from_grouped(parent, grouped, analysis or {"url": source_url, "webpage_url": source_url}, source_url)
        child_index = engine.safe_int(event.get("index")) or self._next_playlist_child_index(parent)
        for offset, child in enumerate(children):
            index = child_index + offset
            child["id"] = f"{parent['id']}-child-{index}"
            child["playlist_child_index"] = index
        self._replace_playlist_loading_rows(parent, child_index, children)
        self._refresh_playlist_parent_metadata(parent)
        self._ensure_next_playlist_loading(parent, child_index)
        return children

    def _replace_playlist_loading_with_failed_entry(self, parent, event):
        child_index = engine.safe_int(event.get("index")) or self._next_playlist_child_index(parent)
        source_url = event.get("source_url") or event.get("url") or parent.get("analysis_source_url") or parent.get("source_url") or self.url_input.text().strip()
        title = event.get("title") or source_url or f"Video {child_index}"
        candidate = self._placeholder_candidate(source_url)
        candidate.update({"id": f"{parent['id']}-failed-{child_index}", "title": title, "display_title": title, "source": source_url, "url": source_url, "webpage_url": source_url})
        failed = {
            "id": f"{parent['id']}-failed-{child_index}",
            "kind": "video",
            "candidate": candidate,
            "qualities": [candidate],
            "quality_options": build_quality_options([candidate]),
            "selected_index": 0,
            "selected_format_index": 0,
            "analysis_source_url": source_url,
            "source_url": source_url,
            "input_url": source_url,
            "status": ERROR_STATUS,
            "status_detail": str(event.get("message") or event.get("error") or ""),
            "progress": 0,
            "progress_text": "",
            "output_path": "",
            "messages": [str(event.get("message") or event.get("error") or "")],
            "created_order": self._next_row_sequence(),
            "parent_playlist_id": parent["id"],
            "is_playlist_child": True,
            "playlist_child_index": child_index,
            "playlist_key": parent.get("playlist_key"),
        }
        self._replace_playlist_loading_rows(parent, child_index, [failed])
        self._refresh_playlist_parent_metadata(parent)
        self._ensure_next_playlist_loading(parent, child_index)

    def _next_playlist_child_index(self, parent):
        indices = [engine.safe_int(row.get("playlist_child_index")) for row in self._playlist_children_for_parent(parent)]
        return (max(indices) if indices else 0) + 1

    def _replace_playlist_loading_rows(self, parent, child_index, replacement_rows):
        parent_id = parent.get("id")
        loading_rows = [
            row for row in self.rows
            if row.get("parent_playlist_id") == parent_id and row.get("child_loading")
        ]
        target = next((row for row in loading_rows if engine.safe_int(row.get("playlist_child_index")) == child_index), None) or (loading_rows[0] if loading_rows else None)
        insert_index = self.rows.index(target) if target in self.rows else self._playlist_child_insert_index(parent, child_index)
        if target in self.rows:
            self.rows.remove(target)
        existing_ids = {row.get("id") for row in replacement_rows}
        self.rows = [
            row for row in self.rows
            if not (row.get("parent_playlist_id") == parent_id and engine.safe_int(row.get("playlist_child_index")) == child_index and not row.get("child_loading") and row.get("id") not in existing_ids)
        ]
        insert_index = min(insert_index, len(self.rows))
        for row in reversed(replacement_rows):
            self.rows.insert(insert_index, row)

    def _playlist_child_insert_index(self, parent, child_index):
        insert_index = self.rows.index(parent) + 1 if parent in self.rows else len(self.rows)
        for index, row in enumerate(self.rows):
            if row.get("parent_playlist_id") != parent.get("id"):
                continue
            if engine.safe_int(row.get("playlist_child_index")) < child_index:
                insert_index = index + 1
        return insert_index

    def _ensure_next_playlist_loading(self, parent, child_index):
        count = engine.safe_int((parent.get("candidate") or {}).get("playlist_count") or (parent.get("candidate") or {}).get("item_count"))
        next_index = child_index + 1
        if count and next_index > count:
            return
        self._ensure_playlist_loading_child(parent, next_index)

    def _replace_playlist_children(self, parent, grouped_rows, source_url, keep_loading=False):
        parent_id = parent.get("id")
        if not parent_id:
            return
        loading_rows = [
            row
            for row in self.rows
            if keep_loading and row.get("parent_playlist_id") == parent_id and row.get("child_loading")
        ]
        self.rows = [
            row
            for row in self.rows
            if not (row.get("parent_playlist_id") == parent_id and not row.get("child_loading"))
            and not (row.get("parent_playlist_id") == parent_id and row.get("child_loading"))
        ]
        children = self._playlist_child_rows_from_grouped(parent, grouped_rows, {"url": source_url, "webpage_url": source_url}, source_url)
        insert_index = self.rows.index(parent) + 1 if parent in self.rows else len(self.rows)
        for row in reversed(children + loading_rows):
            self.rows.insert(insert_index, row)

    def _playlist_key(self, url):
        return engine.playlist_identity_key(url)

    def _playlist_key_for_row(self, row):
        if not row:
            return ""
        candidate = row.get("candidate") or {}
        return (
            row.get("playlist_key")
            or self._playlist_key(row.get("input_url") or "")
            or self._playlist_key(row.get("analysis_source_url") or "")
            or self._playlist_key(row.get("source_url") or "")
            or self._playlist_key(candidate.get("webpage_url") or "")
            or self._playlist_key(candidate.get("url") or "")
            or self._playlist_key(candidate.get("source") or "")
        )

    def _playlist_group_key_for_row(self, row):
        if not isinstance(row, dict):
            return ""
        key = self._playlist_key_for_row(row)
        if key:
            return key
        candidate = row.get("candidate") or {}
        return str(
            row.get("analysis_source_url")
            or row.get("source_url")
            or row.get("input_url")
            or candidate.get("webpage_url")
            or candidate.get("url")
            or candidate.get("source")
            or ""
        ).strip()

    def _dedupe_playlist_parent_rows(self, rows):
        keep_by_key = {}
        key_by_parent_id = {}
        replace_parent_ids = {}
        duplicate_parent_ids = set()
        for row in rows:
            if row.get("kind") != "playlist":
                continue
            key = self._playlist_group_key_for_row(row)
            if not key:
                continue
            row["playlist_key"] = key
            row_id = row.get("id")
            if row_id:
                key_by_parent_id[row_id] = key
            current = keep_by_key.get(key)
            if current is None or int(row.get("created_order") or 0) >= int(current.get("created_order") or 0):
                if current and current.get("id"):
                    duplicate_parent_ids.add(current.get("id"))
                    replace_parent_ids[current.get("id")] = row_id
                keep_by_key[key] = row
            else:
                if row_id:
                    duplicate_parent_ids.add(row_id)
                    replace_parent_ids[row_id] = current.get("id")
        if not duplicate_parent_ids:
            return rows
        deduped = []
        for row in rows:
            if row.get("kind") == "playlist" and row.get("id") in duplicate_parent_ids:
                continue
            parent_id = row.get("parent_playlist_id")
            replacement_id = replace_parent_ids.get(parent_id)
            if replacement_id:
                row["parent_playlist_id"] = replacement_id
                row["playlist_key"] = key_by_parent_id.get(replacement_id) or row.get("playlist_key") or ""
            deduped.append(row)
        return deduped

    def _playlist_parent_row_from_analysis(self, analysis, grouped_rows, source_url, parent_id=None):
        created_order = self._next_row_sequence()
        parent_id = parent_id or f"playlist-{created_order}"
        playlist_candidate = self._playlist_candidate_from_analysis(analysis, grouped_rows, source_url)
        playlist_candidate["id"] = parent_id
        return {
            "id": parent_id,
            "kind": "playlist",
            "candidate": playlist_candidate,
            "qualities": [playlist_candidate],
            "quality_options": build_quality_options([playlist_candidate]),
            "selected_index": 0,
            "selected_format_index": 0,
            "analysis_source_url": source_url,
            "source_url": source_url,
            "input_url": analysis.get("url") or source_url,
            "status": READY_STATUS,
            "status_detail": "",
            "progress": 0,
            "progress_text": "",
            "output_path": "",
            "messages": [],
            "created_order": created_order,
            "playlist_entries": grouped_rows,
            "expanded": True,
            "playlist_key": self._playlist_key(analysis.get("url") or source_url),
        }

    def _playlist_child_rows_from_grouped(self, parent, grouped_rows, analysis, source_url):
        children = []
        for index, grouped_row in enumerate(grouped_rows, start=1):
            child = self._video_row_from_grouped(grouped_row, analysis, source_url)
            child["id"] = f"{parent['id']}-child-{index}"
            child["parent_playlist_id"] = parent["id"]
            child["is_playlist_child"] = True
            child["playlist_child_index"] = index
            child["playlist_key"] = parent.get("playlist_key")
            child["source_url"] = row_source_url(analysis, child.get("candidate") or {}) or child.get("source_url") or source_url
            children.append(child)
        return children

    def _find_playlist_parent_for_analysis(self, analysis, source_url):
        return self._find_playlist_parent_for_url(analysis.get("url") or source_url)

    def _find_playlist_parent_for_url(self, url):
        key = self._playlist_key(url)
        if not key:
            return None
        for row in self.rows:
            if row.get("kind") == "playlist" and self._playlist_key_for_row(row) == key:
                return row
        return None

    def _update_playlist_rows(self, parent, analysis, grouped_rows, source_url):
        parent_id = parent.get("id")
        if not parent_id:
            return
        replacement = self._playlist_parent_row_from_analysis(analysis, grouped_rows, source_url, parent_id=parent_id)
        replacement["created_order"] = parent.get("created_order") or replacement.get("created_order")
        replacement["expanded"] = parent.get("expanded", True)
        parent.clear()
        parent.update(replacement)
        existing_children = {
            self._row_media_identity(row): row
            for row in self.rows
            if row.get("parent_playlist_id") == parent_id
        }
        children = []
        for child in self._playlist_child_rows_from_grouped(parent, grouped_rows, analysis, source_url):
            existing = existing_children.get(self._row_media_identity(child))
            if existing:
                child["id"] = existing.get("id") or child.get("id")
                child["created_order"] = existing.get("created_order") or child.get("created_order")
                if existing.get("status") in {COMPLETED_STATUS, DOWNLOAD_STATUS, WAITING_STATUS}:
                    for key in ("status", "status_detail", "progress", "progress_text", "output_path", "messages", "download_started_at"):
                        child[key] = existing.get(key, child.get(key))
                child["widget"] = existing.get("widget")
            children.append(child)
        self.rows = [row for row in self.rows if row.get("parent_playlist_id") != parent_id]
        insert_index = self.rows.index(parent) + 1 if parent in self.rows else 0
        for child in reversed(children):
            self.rows.insert(insert_index, child)

    def _finalize_progressive_playlist_rows(self, parent, analysis, grouped_rows, source_url):
        parent_id = parent.get("id")
        if not parent_id:
            return
        replacement = self._playlist_parent_row_from_analysis(analysis, grouped_rows, source_url, parent_id=parent_id)
        replacement["created_order"] = parent.get("created_order") or replacement.get("created_order")
        replacement["expanded"] = parent.get("expanded", True)
        replacement["widget"] = parent.get("widget")
        replacement["render_widget"] = parent.get("render_widget")
        parent.clear()
        parent.update(replacement)
        parent["analysis_loading"] = False
        self.rows = [
            row
            for row in self.rows
            if not (row.get("parent_playlist_id") == parent_id and row.get("child_loading"))
        ]
        self._refresh_playlist_parent_status(parent)

    def _row_media_identity(self, row):
        candidate = row.get("candidate") or {}
        return (
            candidate.get("source")
            or candidate.get("webpage_url")
            or candidate.get("url")
            or row.get("source_url")
            or row.get("id")
            or ""
        )

    def _video_row_from_grouped(self, grouped_row, analysis, source_url):
        candidate = grouped_row["candidate"]
        created_order = self._next_row_sequence()
        return {
            "id": f"video-{created_order}",
            "kind": row_kind(candidate),
            "candidate": candidate,
            "qualities": grouped_row["qualities"],
            "quality_options": build_quality_options(grouped_row["qualities"]),
            "selected_index": 0,
            "selected_format_index": 0,
            "analysis_source_url": source_url,
            "source_url": source_url or row_source_url(analysis, candidate),
            "input_url": analysis.get("url") or source_url,
            "status": READY_STATUS,
            "status_detail": "",
            "progress": 0,
            "progress_text": "",
            "output_path": "",
            "messages": [],
            "created_order": created_order,
        }

    def _playlist_candidate_from_analysis(self, analysis, grouped_rows, source_url):
        first_candidate = (grouped_rows[0].get("candidate") if grouped_rows else {}) or {}
        candidates = [row.get("candidate") or {} for row in grouped_rows]
        title = (
            analysis.get("playlist_title")
            or analysis.get("title")
            or first_candidate.get("display_title")
            or first_candidate.get("title")
            or "Playlist"
        )
        return {
            "id": "playlist",
            "media_type": "playlist",
            "format_selector": "bestvideo*+bestaudio/best",
            "title": title,
            "display_title": title,
            "thumbnail": first_candidate.get("thumbnail") or "",
            "duration": sum(engine.safe_int(candidate.get("duration")) for candidate in candidates),
            "sort_bytes": sum(engine.safe_int(candidate.get("sort_bytes")) for candidate in candidates),
            "item_count": engine.safe_int(analysis.get("playlist_count")) or len(grouped_rows),
            "playlist_count": engine.safe_int(analysis.get("playlist_count")) or len(grouped_rows),
            "source": source_url,
            "url": source_url,
            "webpage_url": source_url,
            "output_ext": self._preferred_output_ext(),
            "ext": self._preferred_output_ext(),
        }

    def _refresh_playlist_parent_metadata(self, parent):
        if not parent or parent.get("kind") != "playlist":
            return
        candidate = parent.get("candidate") or {}
        children = [
            row
            for row in self._playlist_children_for_parent(parent)
            if not row.get("child_loading")
        ]
        count = len(children)
        if parent.get("analysis_loading"):
            expected = engine.safe_int(candidate.get("playlist_count") or candidate.get("item_count"))
            count = max(count, expected)
        candidate["duration"] = sum(engine.safe_int((child.get("candidate") or {}).get("duration")) for child in children)
        candidate["sort_bytes"] = sum(engine.safe_int((child.get("candidate") or {}).get("sort_bytes")) for child in children)
        candidate["item_count"] = count
        candidate["playlist_count"] = count
        parent["playlist_entries"] = [
            {"candidate": child.get("candidate") or {}, "qualities": child.get("qualities") or []}
            for child in children
        ]

    def _parent_playlist_for_child(self, child_row):
        parent_id = child_row.get("parent_playlist_id")
        if not parent_id:
            return None
        for row in self.rows:
            if row.get("id") == parent_id:
                return row
        return None

    def _restore_missing_playlist_parents(self, rows):
        existing_ids = {row.get("id") for row in rows if row.get("kind") == "playlist"}
        missing_groups = {}
        for row in rows:
            parent_id = row.get("parent_playlist_id")
            if not row.get("is_playlist_child") or not parent_id or parent_id in existing_ids:
                continue
            missing_groups.setdefault(parent_id, []).append(row)
        repaired = False
        for parent_id, children in missing_groups.items():
            key = next((child.get("playlist_key") for child in children if child.get("playlist_key")), "")
            output_dirs = []
            for child in children:
                output_path = child.get("output_path") or ""
                if output_path:
                    output_dirs.append(Path(output_path).expanduser().parent)
            common_dir = output_dirs[0] if output_dirs and all(path == output_dirs[0] for path in output_dirs) else None
            title = common_dir.name if common_dir else "재생목록"
            source_url = key if str(key).startswith(("http://", "https://")) else ""
            preferred_ext = self._preferred_output_ext()
            candidate = {
                "id": parent_id,
                "media_type": "playlist",
                "format_selector": "bestvideo*+bestaudio/best",
                "title": title,
                "display_title": title,
                "thumbnail": (children[0].get("candidate") or {}).get("thumbnail") or "",
                "duration": sum(engine.safe_int((child.get("candidate") or {}).get("duration")) for child in children),
                "sort_bytes": sum(engine.safe_int((child.get("candidate") or {}).get("sort_bytes")) for child in children),
                "item_count": len(children),
                "playlist_count": len(children),
                "source": source_url,
                "url": source_url,
                "webpage_url": source_url,
                "output_ext": preferred_ext,
                "ext": preferred_ext,
            }
            created_orders = [engine.safe_int(child.get("created_order")) for child in children]
            created_order = max(0, min(order for order in created_orders if order) - 1) if any(created_orders) else self._next_row_sequence()
            rows.append(
                {
                    "id": parent_id,
                    "kind": "playlist",
                    "candidate": candidate,
                    "qualities": [candidate],
                    "quality_options": build_quality_options([candidate]),
                    "selected_index": 0,
                    "selected_format_index": 0,
                    "analysis_source_url": source_url,
                    "source_url": source_url,
                    "playlist_key": key,
                    "parent_playlist_id": "",
                    "is_playlist_child": False,
                    "playlist_child_index": 0,
                    "expanded": True,
                    "status": COMPLETED_STATUS,
                    "status_detail": "",
                    "progress": 100,
                    "progress_text": "",
                    "output_path": "",
                    "messages": [],
                    "created_order": created_order,
                    "playlist_entries": [
                        {"candidate": child.get("candidate") or {}, "qualities": child.get("qualities") or []}
                        for child in children
                    ],
                }
            )
            repaired = True
        return repaired

    def _attach_restored_playlist_children(self, rows):
        parents_by_key = {}
        for row in rows:
            if row.get("kind") != "playlist":
                continue
            key = self._playlist_key_for_row(row)
            if key and key not in parents_by_key:
                parents_by_key[key] = row
        child_counts = {}
        for row in rows:
            if row.get("kind") == "playlist" or row.get("is_playlist_child"):
                continue
            key = self._playlist_key_for_row(row)
            parent = parents_by_key.get(key)
            if not parent:
                continue
            parent_id = parent.get("id")
            child_counts[parent_id] = child_counts.get(parent_id, 0) + 1
            row["parent_playlist_id"] = parent_id
            row["is_playlist_child"] = True
            row["playlist_child_index"] = child_counts[parent_id]
            row["playlist_key"] = key

    def _playlist_parent_loading_row(self, url):
        created_order = self._next_row_sequence()
        parent_id = f"playlist-loading-{created_order}"
        candidate = self._placeholder_candidate(url)
        candidate.update(
            {
                "id": parent_id,
                "media_type": "playlist",
                "format_selector": "bestvideo*+bestaudio/best",
                "item_count": 0,
                "playlist_count": 0,
                "source": url,
                "webpage_url": url,
            }
        )
        return {
            "id": parent_id,
            "kind": "playlist",
            "candidate": candidate,
            "qualities": [candidate],
            "quality_options": build_quality_options([candidate]),
            "selected_index": 0,
            "selected_format_index": 0,
            "analysis_source_url": url,
            "source_url": url,
            "input_url": url,
            "status": READY_STATUS,
            "status_detail": "",
            "progress": 0,
            "progress_text": "",
            "output_path": "",
            "messages": [],
            "created_order": created_order,
            "playlist_entries": [],
            "expanded": True,
            "analysis_loading": True,
        }

    def _playlist_child_loading_row(self, parent_id, url):
        return {
            "id": f"{parent_id}-loading",
            "kind": "video",
            "candidate": self._placeholder_candidate(url),
            "qualities": [],
            "quality_options": [],
            "selected_index": 0,
            "selected_format_index": 0,
            "analysis_source_url": url,
            "source_url": url,
            "input_url": url,
            "status": ANALYZING_STATUS,
            "status_detail": "",
            "progress": 0,
            "progress_text": ANALYZING_STATUS,
            "output_path": "",
            "messages": [],
            "created_order": self._next_row_sequence(),
            "parent_playlist_id": parent_id,
            "is_playlist_child": True,
            "child_loading": True,
            "analysis_loading": True,
            "playlist_child_index": 0,
        }

    def _playlist_parent_needs_child_analysis(self, row):
        if not isinstance(row, dict) or row.get("kind") != "playlist":
            return False
        if row.get("analysis_loading") or self.analysis_thread:
            return False
        if self._playlist_children_for_parent(row):
            return False
        return bool(self._playlist_source_url(row))

    def _playlist_source_url(self, row):
        if not isinstance(row, dict):
            return ""
        candidate = row.get("candidate") or {}
        return str(
            row.get("analysis_source_url")
            or row.get("source_url")
            or row.get("input_url")
            or candidate.get("webpage_url")
            or candidate.get("url")
            or candidate.get("source")
            or ""
        ).strip()

    def _first_playlist_output_parent(self, row):
        for entry in row.get("playlist_entries") or []:
            child = entry if isinstance(entry, dict) else {}
            saved_output = child.get("output_path") or ""
            output_path = Path(saved_output)
            if saved_output and output_path.exists():
                return output_path.parent
            candidate = child.get("candidate") if isinstance(child.get("candidate"), dict) else None
            expected = engine.existing_output_path_for_candidate(candidate or {}, self.folder_input.text())
            if expected:
                return expected.parent
        return None

    def _delete_playlist_output_files(self, row, playlist_dir):
        playlist_dir = Path(playlist_dir).expanduser()
        paths = []
        for child in self._playlist_children_for_parent(row):
            saved_output = child.get("output_path") or ""
            if saved_output:
                path = Path(saved_output).expanduser()
            else:
                path = engine.existing_output_path_for_candidate(child.get("candidate") or {}, playlist_dir)
            if path and path.exists() and path.is_file():
                try:
                    path.relative_to(playlist_dir)
                except ValueError:
                    continue
                paths.append(path)
        for path in dict.fromkeys(paths):
            path.unlink()
        save_folder = Path(self.folder_input.text()).expanduser().resolve()
        if playlist_dir.exists() and playlist_dir.resolve() != save_folder:
            try:
                playlist_dir.rmdir()
            except OSError:
                pass
