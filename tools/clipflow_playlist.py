"""Playlist streaming-event handling for ClipFlowWindow.

Provided as a mixin so the large window class stays organized. All methods
operate on ``self`` (the ClipFlowWindow instance) and only rely on the module
imports below plus methods that remain on the window class.
"""

try:
    from tools import candidate_presenter as presenter
    from tools import downloader_engine as engine
    from tools.clipflow_rows import build_quality_options
    from tools.clipflow_constants import ERROR_STATUS
except ImportError:
    import candidate_presenter as presenter
    import downloader_engine as engine
    from clipflow_rows import build_quality_options
    from clipflow_constants import ERROR_STATUS


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
