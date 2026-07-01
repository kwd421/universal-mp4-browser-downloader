"""Row actions for ClipFlowWindow: open/reveal, select-mode, and deletion.

Provided as a mixin so the large window class stays organized. All methods
operate on ``self`` (the ClipFlowWindow instance) and rely on the module
imports below plus methods that remain on the window class or other mixins.
"""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

try:
    from tools import downloader_engine as engine
    from tools.clipflow_dialogs import DeleteConfirmDialog
    from tools.clipflow_theme import DOWNLOAD_STATUS, PAUSED_STATUS
except ImportError:
    import downloader_engine as engine
    from clipflow_dialogs import DeleteConfirmDialog
    from clipflow_theme import DOWNLOAD_STATUS, PAUSED_STATUS


def local_file_url(path):
    return QUrl.fromLocalFile(str(Path(path).expanduser().resolve()))


class ActionMixin:
    def open_source_for_row(self, row):
        source_url = row.get("source_url") or ""
        if source_url:
            self.open_url_func(source_url)

    def open_folder_for_row(self, row):
        reveal_target = None
        open_target = None
        if row.get("kind") == "playlist":
            candidate = row.get("candidate") or {}
            playlist_folder = engine.output_dir_for_candidate(candidate, self.folder_input.text())
            if playlist_folder.exists():
                reveal_target = playlist_folder
            else:
                open_target = self._first_playlist_output_parent(row) or Path(self.folder_input.text()).expanduser()
        else:
            saved_output = row.get("output_path") or ""
            output_path = Path(saved_output)
            if saved_output and output_path.exists():
                reveal_target = output_path
            else:
                candidate = self.selected_candidate_for_row_ref(row) or row.get("candidate") or {}
                existing_output = self._existing_output_path_for_row(row, candidate)
                reveal_target = existing_output if existing_output and existing_output.exists() else None
                open_target = Path(self.folder_input.text()).expanduser()
        if reveal_target:
            self._reveal_in_file_manager(reveal_target)
            return
        open_target = open_target or Path(self.folder_input.text()).expanduser()
        open_target.mkdir(parents=True, exist_ok=True)
        self._open_path(open_target)

    def _reveal_in_file_manager(self, path):
        path = Path(path)
        if sys.platform == "darwin":
            try:
                subprocess.Popen(["open", "-R", str(path)])
                return
            except Exception:
                pass
        if sys.platform.startswith("win") and path.exists():
            try:
                subprocess.Popen(f'explorer.exe /select,"{path.resolve()}"')
                return
            except Exception:
                pass
        self._open_path(path.parent if path.is_file() else path)

    def _open_path(self, path):
        return QDesktopServices.openUrl(local_file_url(path))

    def remove_row(self, row):
        if row.get("status") in {"분석 중", DOWNLOAD_STATUS}:
            return
        if row in self.rows:
            index = self.rows.index(row)
            if row.get("kind") == "playlist":
                parent_id = row.get("id")
                self.rows = [
                    item for item in self.rows
                    if item is not row and item.get("parent_playlist_id") != parent_id
                ]
            else:
                self.rows.pop(index)
            if self.selected_row_index >= len(self.rows):
                self.selected_row_index = len(self.rows) - 1
            self._render_rows()
            self._save_completed_history()

    def _toggle_select_mode(self, *_args):
        self.select_mode = not getattr(self, "select_mode", False)
        self.select_toggle.setText("")
        self.select_toggle.setProperty("active", "true" if self.select_mode else "false")
        if hasattr(self, "_refresh_select_toggle_icon"):
            self._refresh_select_toggle_icon()
        self.select_toggle.style().unpolish(self.select_toggle)
        self.select_toggle.style().polish(self.select_toggle)
        self.select_actions.setVisible(self.select_mode)
        if not self.select_mode:
            for row in self.rows:
                row["checked"] = False
        for row in self.rows:
            widget = row.get("widget")
            if widget:
                widget.set_select_mode(self.select_mode)

    def on_row_check_changed(self):
        return

    def _select_all_rows(self):
        for row in self.rows:
            row["checked"] = bool(self._row_is_visible(row))
            widget = row.get("widget")
            if widget:
                widget.set_select_mode(True)

    def _delete_selected_from_list(self):
        self._remove_selected(delete_files=False)

    def _delete_selected_files(self):
        self._remove_selected(delete_files=True)

    def _remove_selected(self, delete_files):
        removable = [
            row
            for row in self.rows
            if row.get("checked") and row.get("status") not in {"분석 중", DOWNLOAD_STATUS}
        ]
        if not removable:
            self._set_status("선택된 항목이 없습니다")
            return
        if not self._confirm_selected(len(removable), delete_files):
            return
        if delete_files:
            for row in removable:
                self._delete_paths_for_row(row)
        keep = [row for row in self.rows if row not in removable]
        self.rows = keep
        if self.selected_row_index >= len(self.rows):
            self.selected_row_index = len(self.rows) - 1
        self._render_rows()
        self._save_completed_history()

    def _confirm_selected(self, count, delete_files):
        dialog = QDialog(self)
        dialog.setWindowTitle("파일 삭제" if delete_files else "목록에서 삭제")
        dialog.setModal(True)
        dialog.setMinimumWidth(360)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        if delete_files:
            message = f"선택한 {count}개 항목의 파일을 삭제할까요?"
            detail = "다운로드된 파일이 실제로 삭제되고 목록에서도 제거됩니다."
        else:
            message = f"선택한 {count}개 항목을 목록에서 삭제할까요?"
            detail = "파일은 삭제되지 않고 목록에서만 제거됩니다."
        title = QLabel(message)
        title.setObjectName("SectionTitle")
        title.setWordWrap(True)
        detail_label = QLabel(detail)
        detail_label.setObjectName("MetaText")
        detail_label.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(detail_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("취소")
        cancel.setObjectName("SecondaryButton")
        confirm = QPushButton("삭제")
        confirm.setObjectName("DangerButton" if delete_files else "")
        cancel.clicked.connect(dialog.reject)
        confirm.clicked.connect(dialog.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)
        return dialog.exec() == QDialog.Accepted

    def delete_file_for_row(self, row):
        if row.get("status") == DOWNLOAD_STATUS:
            return
        output_path = self._delete_target_for_row(row)
        delete_paths = self._delete_paths_for_row(row, dry_run=True)
        if output_path is None and not delete_paths:
            return
        confirm_target = output_path or (delete_paths[0] if delete_paths else None)
        confirmed = (
            self.confirm_delete_func(confirm_target)
            if self.confirm_delete_func
            else self._confirm_file_delete(confirm_target, row)
        )
        if not confirmed:
            return
        try:
            if row.get("kind") == "playlist":
                output_path = output_path or engine.output_dir_for_candidate(row.get("candidate") or {}, self.folder_input.text())
                self._delete_playlist_output_files(row, output_path)
            else:
                self._delete_paths_for_row(row)
        except OSError as exc:
            QMessageBox.warning(self, "파일 삭제 실패", str(exc))
            return
        self._remove_rows_after_file_delete(row)
        self._save_completed_history()

    def _delete_target_for_row(self, row):
        if row.get("kind") == "playlist":
            return engine.output_dir_for_candidate(row.get("candidate") or {}, self.folder_input.text())
        saved_output = row.get("output_path") or ""
        if saved_output:
            return Path(saved_output)
        candidate = self.selected_candidate_for_row_ref(row) or row.get("candidate") or {}
        return self._existing_output_path_for_row(row, candidate)

    def _delete_paths_for_row(self, row, dry_run=False):
        paths = self._download_output_paths_for_row(row)
        if dry_run:
            return [path for path in paths if path.exists()]
        deleted = []
        for path in paths:
            if not path.exists():
                continue
            if path.is_dir():
                try:
                    path.rmdir()
                    deleted.append(path)
                except OSError:
                    pass
                continue
            try:
                path.unlink()
                deleted.append(path)
            except OSError:
                pass
        return deleted

    def _download_output_paths_for_row(self, row):
        if row.get("kind") == "playlist":
            playlist_dir = engine.output_dir_for_candidate(row.get("candidate") or {}, self.folder_input.text())
            paths = []
            for child in self._playlist_children_for_parent(row):
                paths.extend(self._download_output_paths_for_row(child))
            paths.append(playlist_dir)
            return list(dict.fromkeys(paths))

        candidate = self.selected_candidate_for_row_ref(row) or row.get("candidate") or {}
        output_dir = self._output_dir_for_row(row, candidate) if hasattr(self, "_output_dir_for_row") else engine.output_dir_for_candidate(candidate, self.folder_input.text())
        output_dir = Path(output_dir).expanduser()
        paths = []
        saved_output = row.get("output_path") or ""
        if saved_output:
            paths.append(Path(saved_output).expanduser())
        final_path = engine.final_output_path_for_candidate(candidate, output_dir)
        if final_path:
            paths.append(Path(final_path).expanduser())
            if output_dir.exists():
                final_name = final_path.name
                try:
                    paths.extend(path for path in output_dir.iterdir() if path.name.startswith(final_name))
                except OSError:
                    pass
        return list(dict.fromkeys(paths))

    def _remove_rows_after_file_delete(self, row):
        if row.get("kind") == "playlist":
            parent_id = row.get("id")
            self.rows = [
                item for item in self.rows
                if item is not row and item.get("parent_playlist_id") != parent_id
            ]
        else:
            parent = self._parent_playlist_for_child(row)
            if row in self.rows:
                self.rows.remove(row)
            if parent:
                parent["playlist_entries"] = [
                    {"candidate": child.get("candidate") or {}, "qualities": child.get("qualities") or []}
                    for child in self._playlist_children_for_parent(parent)
                    if child is not row and not child.get("child_loading")
                ]
                self._refresh_playlist_parent_status(parent)
        if self.selected_row_index >= len(self.rows):
            self.selected_row_index = len(self.rows) - 1
        self._render_rows()

    def _create_delete_confirm_dialog(self, output_path, row=None):
        if row and row.get("kind") == "playlist":
            child_count = len([
                child
                for child in self._playlist_children_for_parent(row)
                if not child.get("child_loading")
            ])
            return DeleteConfirmDialog(
                output_path,
                self,
                title_text="재생목록을 삭제하시겠습니까?",
                detail_text=f"{output_path}\n하위 파일 {child_count}개도 함께 삭제됩니다.",
                window_title="재생목록 삭제",
            )
        return DeleteConfirmDialog(output_path, self)

    def _confirm_file_delete(self, output_path, row=None):
        dialog = self._create_delete_confirm_dialog(output_path, row)
        return dialog.exec() == QDialog.Accepted
