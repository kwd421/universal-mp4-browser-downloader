"""Row rendering, sorting, selection, and playlist-layout for ClipFlowWindow.

Provided as a mixin so the large window class stays organized. All methods
operate on ``self`` (the ClipFlowWindow instance) and rely on the module
imports below plus methods that remain on the window class or other mixins.
"""

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

try:
    from tools import candidate_presenter as presenter
    from tools.clipflow_rows import DownloadRowWidget, build_quality_options
    from tools.clipflow_theme import (
        AUTO_LABEL,
        DEFAULT_OUTPUT_EXT,
        SORT_DESC_SETTING,
        SORT_KEY_SETTING,
        SORT_KEYS_BY_LABEL,
    )
except ImportError:
    import candidate_presenter as presenter
    from clipflow_rows import DownloadRowWidget, build_quality_options
    from clipflow_theme import (
        AUTO_LABEL,
        DEFAULT_OUTPUT_EXT,
        SORT_DESC_SETTING,
        SORT_KEY_SETTING,
        SORT_KEYS_BY_LABEL,
    )


class RenderMixin:
    def _visible_rows(self):
        return [row for row in self.rows if self._row_is_visible(row)]

    def _render_rows(self):
        app = QApplication.instance()
        self._sort_rows()
        row_widgets = []
        for row_index, row in enumerate(self.rows):
            if app is not None and row_index and row_index % 4 == 0:
                app.processEvents()
            widget = row.get("widget")
            if widget is None:
                widget = DownloadRowWidget(self, row)
                row["widget"] = widget
            else:
                widget.refresh()
            widget.set_select_mode(self.select_mode)
            render_widget = self._row_render_widget(row, widget)
            row_widgets.append((row, widget, render_widget))

        expected_widgets = {render_widget for _row, _widget, render_widget in row_widgets}
        existing_widgets = []
        for index in range(self.row_layout.count() - 1):
            item = self.row_layout.itemAt(index)
            widget = item.widget() if item else None
            if widget:
                existing_widgets.append(widget)
        for widget in existing_widgets:
            if widget in expected_widgets:
                continue
            self.row_layout.removeWidget(widget)
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()

        for index, (row, widget, render_widget) in enumerate(row_widgets):
            current_index = self.row_layout.indexOf(render_widget)
            if current_index != index:
                if current_index >= 0:
                    self.row_layout.removeWidget(render_widget)
                self.row_layout.insertWidget(index, render_widget)
            visible = self._row_is_visible(row)
            render_widget.setVisible(visible)
            widget.setVisible(visible)
        visible_rows = self._visible_rows()
        self.count_label.setText(f"{len(self.rows)}개")
        if hasattr(self, "empty_state"):
            self.empty_state.setGeometry(self.scroll_area.viewport().rect())
            self.empty_state.setVisible(not visible_rows)
            if not visible_rows:
                self.empty_state.raise_()
        self._refresh_footer()
        self._refresh_row_selection()
        self._refresh_primary_action()
        self._refresh_playlist_float_button()
        self._refresh_scrollbar_activity()
        QTimer.singleShot(0, self._refresh_hovered_row_under_cursor)

    def _refresh_hovered_row_under_cursor(self):
        cursor_pos = QCursor.pos()
        for row in self.rows:
            widget = row.get("widget")
            if not widget:
                continue
            hovered = widget.isVisible() and widget.rect().contains(widget.mapFromGlobal(cursor_pos))
            widget._set_hovered(hovered)

    def _refresh_scrollbar_activity(self, *_args):
        if not hasattr(self, "scroll_area"):
            return
        bar = self.scroll_area.verticalScrollBar()
        scrollable = "true" if bar.maximum() > bar.minimum() else "false"
        if bar.property("scrollable") == scrollable:
            return
        bar.setProperty("scrollable", scrollable)
        bar.style().unpolish(bar)
        bar.style().polish(bar)
        bar.update()

    def _row_render_widget(self, row, widget):
        if not row.get("is_playlist_child"):
            row["render_widget"] = widget
            return widget
        container = row.get("render_widget")
        if container is None or container is widget:
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(28, 0, 0, 0)
            layout.setSpacing(0)
            layout.addWidget(widget)
            row["render_widget"] = container
        return container

    def playlist_expansion_changed(self, row):
        self._sync_row_layout_geometry()
        before_top = self._row_viewport_top(row)
        if isinstance(row, dict) and not row.get("expanded"):
            selected = self.rows[self.selected_row_index] if 0 <= self.selected_row_index < len(self.rows) else None
            if selected and selected.get("parent_playlist_id") == row.get("id"):
                self.selected_row_index = self.rows.index(row)
        if self._playlist_parent_needs_child_analysis(row):
            source_url = self._playlist_source_url(row)
            row["expanded"] = True
            self.url_input.setText(source_url)
            self._start_analysis(auto_download=False)
            return
        if self._set_playlist_child_visibility(row):
            self._sync_row_layout_geometry()
            self._refresh_footer()
            self._refresh_row_selection()
            self._refresh_primary_action()
            self._refresh_playlist_float_button()
        else:
            self._render_rows()
        self._restore_row_viewport_top(row, before_top)
        QTimer.singleShot(0, self._refresh_playlist_float_button)

    def _set_playlist_child_visibility(self, row):
        if not isinstance(row, dict) or row.get("kind") != "playlist":
            return False
        children = self._playlist_children_for_parent(row)
        if not children:
            return True
        render_widgets = []
        for child in children:
            render_widget = child.get("render_widget") or child.get("widget")
            if render_widget is None or self.row_layout.indexOf(render_widget) < 0:
                return False
            render_widgets.append(render_widget)
        visible = bool(row.get("expanded"))
        for child, render_widget in zip(children, render_widgets):
            render_widget.setVisible(visible)
            widget = child.get("widget")
            if widget and widget is not render_widget:
                widget.setVisible(visible)
        return True

    def _sync_row_layout_geometry(self):
        if not hasattr(self, "row_layout") or not hasattr(self, "row_container"):
            return
        self.row_layout.activate()
        self.row_container.adjustSize()
        self.row_container.updateGeometry()

    def _row_viewport_top(self, row):
        widget = (row.get("render_widget") or row.get("widget")) if isinstance(row, dict) else None
        if not widget:
            return None
        return widget.mapTo(self.scroll_area.viewport(), QPoint(0, 0)).y()

    def _restore_row_viewport_top(self, row, before_top):
        if before_top is None:
            return
        after_top = self._row_viewport_top(row)
        if after_top is None:
            return
        delta = after_top - before_top
        if not delta:
            return
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(max(bar.minimum(), min(bar.maximum(), bar.value() + delta)))

    def _expanded_playlist_row(self):
        for row in self.rows:
            if row.get("kind") == "playlist" and row.get("expanded") and row.get("widget"):
                return row
        return None

    def _position_playlist_float_button(self):
        if not hasattr(self, "playlist_float_button"):
            return
        viewport = self.scroll_area.viewport()
        x = max(8, viewport.width() - self.playlist_float_button.width() - 12)
        self.playlist_float_button.move(x, 10)
        self.playlist_float_button.raise_()

    def _refresh_playlist_float_button(self):
        if not hasattr(self, "playlist_float_button"):
            return
        row = self._expanded_playlist_row()
        widget = row.get("widget") if row else None
        visible = False
        if widget:
            top = widget.mapTo(self.scroll_area.viewport(), QPoint(0, 0)).y()
            parent_bottom = top + widget.height()
            bottom = parent_bottom
            child_widgets = [
                child.get("widget")
                for child in self.rows
                if child.get("parent_playlist_id") == row.get("id") and child.get("widget")
            ]
            for child_widget in child_widgets:
                child_top = child_widget.mapTo(self.scroll_area.viewport(), QPoint(0, 0)).y()
                bottom = max(bottom, child_top + child_widget.height())
            visible = parent_bottom <= 0 and bottom > 0
        self.playlist_float_button.setVisible(visible)
        if visible:
            self._position_playlist_float_button()

    def _scroll_row_to_top(self, row):
        widget = row.get("widget") if isinstance(row, dict) else None
        if not widget:
            return
        top = widget.mapTo(self.row_container, QPoint(0, 0)).y()
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(max(bar.minimum(), min(bar.maximum(), top)))

    def _collapse_floating_playlist(self):
        row = self._expanded_playlist_row()
        if not row:
            return
        row["expanded"] = False
        self._render_rows()
        self._scroll_row_to_top(row)
        self._refresh_playlist_float_button()

    def _next_row_sequence(self):
        self._row_sequence += 1
        return self._row_sequence

    def _sort_rows(self):
        reverse = bool(self.sort_desc)
        top_rows = []
        child_rows = []
        parent_ids = set()
        for row in self.rows:
            if row.get("is_playlist_child"):
                child_rows.append(row)
            else:
                top_rows.append(row)
                parent_ids.add(row.get("id"))
        attached_children = {parent_id: [] for parent_id in parent_ids}
        orphan_children = []
        for row in child_rows:
            parent_id = row.get("parent_playlist_id")
            if parent_id in attached_children:
                attached_children[parent_id].append(row)
            else:
                orphan_children.append(row)
        top_rows.extend(orphan_children)
        if self.sort_key == "name":
            top_rows.sort(key=lambda row: self._row_sort_name(row), reverse=reverse)
        else:
            top_rows.sort(key=lambda row: int(row.get("created_order") or 0), reverse=reverse)
        sorted_rows = []
        for row in top_rows:
            sorted_rows.append(row)
            children = attached_children.get(row.get("id")) or []
            children.sort(key=lambda child: (int(child.get("playlist_child_index") or 0), int(child.get("created_order") or 0)))
            sorted_rows.extend(children)
        self.rows = sorted_rows

    def _row_sort_name(self, row):
        candidate = self.selected_candidate_for_row_ref(row) or row.get("candidate") or {}
        return str(candidate.get("display_title") or candidate.get("title") or "").casefold()

    def _sort_changed(self):
        self.sort_key = SORT_KEYS_BY_LABEL.get(self.sort_order_combo.currentText(), "latest")
        self.settings.setValue(SORT_KEY_SETTING, self.sort_key)
        self._render_rows()

    def _sort_direction_icon(self):
        return "arrow-down-wide-narrow" if self.sort_desc else "arrow-up-narrow-wide"

    def _refresh_sort_direction_button(self):
        if not hasattr(self, "sort_direction_button"):
            return
        self.sort_direction_button.icon_name = self._sort_direction_icon()
        self.sort_direction_button.setToolTip("내림차순" if self.sort_desc else "오름차순")
        self.sort_direction_button.update()

    def _toggle_sort_direction(self):
        self.sort_desc = not self.sort_desc
        self.settings.setValue(SORT_DESC_SETTING, "true" if self.sort_desc else "false")
        self._refresh_sort_direction_button()
        self._render_rows()

    def select_row(self, index):
        if index < 0 or index >= len(self.rows):
            self.selected_row_index = -1
        else:
            self.selected_row_index = index
        self._refresh_row_selection()
        self._refresh_primary_action()

    def select_row_for_widget(self, widget):
        for index, row in enumerate(self.rows):
            if row.get("widget") is widget:
                self.select_row(index)
                return

    def _refresh_row_selection(self):
        for index, row in enumerate(self.rows):
            widget = row.get("widget")
            if widget:
                widget.set_selected(index == self.selected_row_index)

    def quality_changed_for_row(self, row, quality_index):
        if row not in self.rows:
            return
        options = row.get("quality_options") or []
        row["selected_index"] = max(0, min(int(quality_index), len(options) - 1)) if options else 0
        row["selected_format_index"] = 0
        candidate = self.selected_candidate_for_row_ref(row)
        if candidate:
            row["candidate"] = candidate
            widget = row.get("widget")
            if widget:
                widget.refresh()

    def format_changed_for_row(self, row, format_index):
        if row not in self.rows:
            return
        option = self.selected_quality_option_for_row_ref(row)
        formats = option.get("formats") if option else []
        row["selected_format_index"] = max(0, min(int(format_index), len(formats) - 1)) if formats else 0
        candidate = self.selected_candidate_for_row_ref(row)
        if candidate:
            row["candidate"] = candidate
            widget = row.get("widget")
            if widget:
                widget.refresh()

    def selected_quality_option_for_row_ref(self, row):
        if not row:
            return None
        options = row.get("quality_options")
        if options is None:
            options = build_quality_options(row.get("qualities") or [])
            row["quality_options"] = options
        if not options:
            return None
        selected_index = max(0, min(int(row.get("selected_index") or 0), len(options) - 1))
        row["selected_index"] = selected_index
        return options[selected_index]

    def selected_candidate_for_row_ref(self, row):
        if row and row.get("fixed_candidate"):
            return row.get("candidate")
        if row and row.get("kind") == "playlist":
            candidate = dict(row.get("candidate") or {})
            preferences = self.current_preferences()
            output_format = preferences.output_format
            if str(output_format).casefold() == AUTO_LABEL.casefold():
                output_format = DEFAULT_OUTPUT_EXT
            candidate["output_ext"] = str(output_format).lower()
            candidate["ext"] = str(output_format).lower()
            return candidate
        if row and row.get("status") == "완료":
            return row.get("candidate")
        selected = presenter.select_candidate_for_preferences(row.get("qualities") or [], self.current_preferences())
        if selected:
            return selected
        option = self.selected_quality_option_for_row_ref(row)
        if not option:
            return None
        formats = option.get("formats") or []
        if not formats:
            return None
        selected_format_index = max(0, min(int(row.get("selected_format_index") or 0), len(formats) - 1))
        row["selected_format_index"] = selected_format_index
        return formats[selected_format_index]["candidate"]

    def selected_candidate_for_row(self, row_index):
        if row_index < 0 or row_index >= len(self.rows):
            return None
        return self.selected_candidate_for_row_ref(self.rows[row_index])
