import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidgetItem,
    QTableWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    from tools import candidate_presenter as presenter
    from tools import downloader_engine as engine
except ImportError:
    import candidate_presenter as presenter
    import downloader_engine as engine


COOKIE_CHOICES = ["없음", "Chrome", "Edge", "Firefox"]
EXTENSION_CHOICES = ["MP4", "WEBM", "WAV"]

APP_STYLE = """
QMainWindow {
    background: #f4f8ff;
}
QFrame#Card {
    background: #ffffff;
    border: 1px solid #dce6f4;
    border-radius: 12px;
}
QLabel {
    color: #1f2937;
    font-size: 13px;
}
QLineEdit, QComboBox {
    background: #ffffff;
    border: 1px solid #cad7e8;
    border-radius: 8px;
    padding: 8px 10px;
    min-height: 22px;
}
QPushButton {
    background: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 9px 16px;
    font-weight: 600;
}
QPushButton:disabled {
    background: #9db7e8;
}
QPushButton#SecondaryButton {
    background: #eef4ff;
    color: #1f3b70;
    border: 1px solid #cbdaf1;
}
QTableWidget {
    background: #ffffff;
    border: 1px solid #d6e1ef;
    border-radius: 8px;
    gridline-color: #edf2f8;
    selection-background-color: #e6f0ff;
    selection-color: #102033;
}
QHeaderView::section {
    background: #f7fbff;
    color: #344054;
    border: none;
    border-bottom: 1px solid #d6e1ef;
    padding: 8px;
    font-weight: 600;
}
QTextEdit {
    background: #0f172a;
    color: #dbeafe;
    border: none;
    border-radius: 8px;
    padding: 8px;
    font-family: Consolas, monospace;
}
QProgressBar {
    border: 1px solid #cbdaf1;
    border-radius: 7px;
    background: #eef4ff;
    text-align: center;
}
QProgressBar::chunk {
    background: #22c55e;
    border-radius: 6px;
}
"""


class AnalyzeWorker(QObject):
    event = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, url, cookie_source, output_ext, analyze_func):
        super().__init__()
        self.url = url
        self.cookie_source = cookie_source
        self.output_ext = output_ext
        self.analyze_func = analyze_func

    @Slot()
    def run(self):
        try:
            analysis = self.analyze_func(
                self.url,
                cookie_source=self.cookie_source,
                output_ext=self.output_ext,
                on_event=self.event.emit,
            )
            self.finished.emit(analysis)
        except Exception as exc:
            self.failed.emit(str(exc))


class ClipFlowWindow(QMainWindow):
    def __init__(self, analyze_func=engine.analyze_url):
        super().__init__()
        self.analyze_func = analyze_func
        self.analysis = None
        self.rows = []
        self.analysis_thread = None
        self.analysis_worker = None
        self.setWindowTitle("ClipFlow")
        self.resize(1120, 720)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        self._refresh_primary_action()

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(14)

        title = QLabel("ClipFlow")
        title.setStyleSheet("font-size: 24px; font-weight: 700; color: #111827;")
        layout.addWidget(title)
        layout.addWidget(self._build_input_card())
        layout.addWidget(self._build_list_card(), 1)
        layout.addWidget(self._build_log_card())
        layout.addWidget(self._build_status_bar())

        self.setCentralWidget(root)

    def _card(self):
        frame = QFrame()
        frame.setObjectName("Card")
        frame.setFrameShape(QFrame.StyledPanel)
        return frame

    def _build_input_card(self):
        card = self._card()
        grid = QGridLayout(card)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("동영상 페이지 URL")
        self.url_input.textChanged.connect(self._refresh_primary_action)

        self.format_combo = QComboBox()
        self.format_combo.addItems(EXTENSION_CHOICES)

        self.primary_button = QPushButton()
        self.primary_button.clicked.connect(self._handle_primary_action)

        self.folder_input = QLineEdit(str(Path.home() / "Downloads"))
        self.folder_button = QPushButton("폴더")
        self.folder_button.setObjectName("SecondaryButton")
        self.folder_button.clicked.connect(self._choose_folder)

        self.cookie_combo = QComboBox()
        self.cookie_combo.addItems(COOKIE_CHOICES)

        grid.addWidget(QLabel("URL"), 0, 0)
        grid.addWidget(self.url_input, 0, 1)
        grid.addWidget(self.format_combo, 0, 2)
        grid.addWidget(self.primary_button, 0, 3)
        grid.addWidget(QLabel("저장 폴더"), 1, 0)
        grid.addWidget(self.folder_input, 1, 1)
        grid.addWidget(self.folder_button, 1, 2)
        grid.addWidget(QLabel("쿠키"), 1, 3)
        grid.addWidget(self.cookie_combo, 1, 4)
        grid.setColumnStretch(1, 1)
        return card

    def _build_list_card(self):
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)

        header = QHBoxLayout()
        label = QLabel("다운로드 목록")
        label.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.count_label = QLabel("0개")
        self.count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(label)
        header.addStretch(1)
        header.addWidget(self.count_label)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["제목", "길이", "확장자", "품질", "예상 크기", "상태"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 6):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._refresh_primary_action)

        layout.addLayout(header)
        layout.addWidget(self.table)
        return card

    def _build_log_card(self):
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 12, 18, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        label = QLabel("로그")
        label.setStyleSheet("font-weight: 700;")
        self.log_toggle = QToolButton()
        self.log_toggle.setText("접기")
        self.log_toggle.setCheckable(True)
        self.log_toggle.clicked.connect(self._toggle_log)
        header.addWidget(label)
        header.addStretch(1)
        header.addWidget(self.log_toggle)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(140)
        self.log_output.append("ClipFlow 준비 완료")

        layout.addLayout(header)
        layout.addWidget(self.log_output)
        return card

    def _build_status_bar(self):
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.status_label = QLabel("준비 완료")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout.addWidget(self.status_label)
        layout.addWidget(self.progress, 1)
        return footer

    def _toggle_log(self):
        collapsed = self.log_toggle.isChecked()
        self.log_output.setVisible(not collapsed)
        self.log_toggle.setText("펼치기" if collapsed else "접기")

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.folder_input.text())
        if folder:
            self.folder_input.setText(folder)

    def _handle_primary_action(self):
        if not self.url_input.text().strip():
            text = QApplication.clipboard().text().strip()
            if text:
                self.url_input.setText(text)
            return
        if self.table.currentRow() >= 0 and self.rows:
            self._set_status("다운로드 연결은 다음 checkpoint에서 활성화됩니다.")
            return
        self._start_analysis()

    def _start_analysis(self):
        if self.analysis_thread and self.analysis_thread.isRunning():
            return

        url = self.url_input.text().strip()
        if not url:
            return

        self.analysis = None
        self.rows = []
        self.table.setRowCount(0)
        self.count_label.setText("0개")
        self.progress.setRange(0, 0)
        self.primary_button.setEnabled(False)
        self._set_status("분석 중")

        self.analysis_thread = QThread(self)
        self.analysis_worker = AnalyzeWorker(
            url,
            self.cookie_combo.currentText(),
            self.format_combo.currentText(),
            self.analyze_func,
        )
        self.analysis_worker.moveToThread(self.analysis_thread)
        self.analysis_thread.started.connect(self.analysis_worker.run)
        self.analysis_worker.event.connect(self._handle_engine_event)
        self.analysis_worker.finished.connect(self._analysis_finished)
        self.analysis_worker.failed.connect(self._analysis_failed)
        self.analysis_worker.finished.connect(self.analysis_thread.quit)
        self.analysis_worker.failed.connect(self.analysis_thread.quit)
        self.analysis_thread.finished.connect(self.analysis_worker.deleteLater)
        self.analysis_thread.finished.connect(self._analysis_thread_finished)
        self.analysis_thread.start()

    @Slot(dict)
    def _analysis_finished(self, analysis):
        self.analysis = analysis
        self._populate_rows(presenter.group_candidates(analysis.get("candidates") or []))
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self._set_status(f"영상 {len(self.rows)}개")
        for warning in analysis.get("warnings") or []:
            self.log_output.append(str(warning))

    @Slot(str)
    def _analysis_failed(self, message):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._set_status(f"{engine.classify_error(message)}: {message}")

    @Slot()
    def _analysis_thread_finished(self):
        self.primary_button.setEnabled(True)
        self.analysis_thread = None
        self.analysis_worker = None
        self._refresh_primary_action()

    @Slot(dict)
    def _handle_engine_event(self, event):
        event_type = event.get("type")
        message = event.get("message") or event.get("path") or ""
        if event_type == "progress":
            self.progress.setRange(0, 100)
            self.progress.setValue(max(0, min(100, int(float(event.get("percent") or 0)))))
            if message:
                self.status_label.setText(message)
        elif event_type == "status":
            if message:
                self.status_label.setText(message)
                self.log_output.append(message)
        elif event_type in {"log", "file", "done"}:
            if message:
                self.log_output.append(message)

    def _populate_rows(self, rows):
        self.rows = rows
        self.table.setRowCount(len(rows))
        self.count_label.setText(f"{len(rows)}개")
        for row_index, row in enumerate(rows):
            candidate = row["candidate"]
            self.table.setItem(row_index, 0, QTableWidgetItem(candidate.get("display_title") or candidate.get("title") or "video"))
            self.table.setItem(row_index, 1, QTableWidgetItem(engine.display_duration(candidate.get("duration"))))
            self.table.setItem(row_index, 2, QTableWidgetItem(str(candidate.get("output_ext") or candidate.get("ext") or "").upper()))
            combo = QComboBox()
            for quality in row["qualities"]:
                combo.addItem(presenter.quality_label(quality))
            combo.currentIndexChanged.connect(lambda index, row_index=row_index: self._quality_changed(row_index, index))
            self.table.setCellWidget(row_index, 3, combo)
            self.table.setItem(row_index, 4, QTableWidgetItem(engine.display_size(candidate.get("sort_bytes"))))
            self.table.setItem(row_index, 5, QTableWidgetItem("대기"))
            row["selected_index"] = 0
        if rows:
            self.table.selectRow(0)
        self._refresh_primary_action()

    def _quality_changed(self, row_index, quality_index):
        if row_index < 0 or row_index >= len(self.rows):
            return
        row = self.rows[row_index]
        row["selected_index"] = max(0, min(quality_index, len(row["qualities"]) - 1))
        candidate = self.selected_candidate_for_row(row_index)
        if candidate:
            self.table.setItem(row_index, 4, QTableWidgetItem(engine.display_size(candidate.get("sort_bytes"))))

    def selected_candidate_for_row(self, row_index):
        if row_index < 0 or row_index >= len(self.rows):
            return None
        row = self.rows[row_index]
        selected_index = max(0, min(int(row.get("selected_index") or 0), len(row["qualities"]) - 1))
        return row["qualities"][selected_index]

    def _refresh_primary_action(self):
        has_url = bool(self.url_input.text().strip())
        has_selection = self.table.currentRow() >= 0 and bool(self.rows)
        if not has_url:
            self.primary_button.setText("붙여넣기")
        elif has_selection:
            self.primary_button.setText("다운로드")
        else:
            self.primary_button.setText("분석")

    def _set_status(self, message):
        self.status_label.setText(message)
        self.log_output.append(message)


def main():
    app = QApplication(sys.argv)
    window = ClipFlowWindow()
    window.show()

    if os.environ.get("CLIPFLOW_QT_SMOKE") == "1":
        QTimer.singleShot(0, lambda: (print("ClipFlow smoke launch OK"), app.quit()))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
