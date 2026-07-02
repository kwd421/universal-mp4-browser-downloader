from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

try:
    from tools import candidate_presenter as presenter
    from tools.clipflow_widgets import CleanComboBox
except ImportError:
    import candidate_presenter as presenter
    from clipflow_widgets import CleanComboBox


def _combo_text(combo):
    return str(combo.currentText()).strip()


PREFERENCE_TOOLTIPS = {
    "품질": "선택한 해상도 이하에서 가장 좋은 후보를 고릅니다.",
    "포맷": "저장할 파일 형식입니다. MP3/WAV/AAC는 음원만 저장합니다.",
    "코덱": "가능하면 선택한 영상 코덱을 우선합니다. 음원 포맷에는 적용되지 않습니다.",
}


class PreferencesDialog(QDialog):
    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.setWindowTitle("품질 설정")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)

        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.quality_combo = CleanComboBox()
        self.quality_combo.addItems(["최고화질", "2160p", "1440p", "1080p", "720p", "480p", "360p"])
        self.format_combo = CleanComboBox()
        self.format_combo.addItems(["자동", "MP4", "WEBM", "MP3", "WAV", "AAC"])
        self.codec_combo = CleanComboBox()
        self.codec_combo.addItems(["자동", "H264", "H265", "AV1", "VP9"])

        self.quality_combo.setCurrentText(preferences.quality)
        self.format_combo.setCurrentText(preferences.output_format)
        self.codec_combo.setCurrentText(preferences.codec)
        self.format_combo.currentIndexChanged.connect(self.refresh_controls)

        for row, (label, combo) in enumerate(
            (
                ("품질", self.quality_combo),
                ("포맷", self.format_combo),
                ("코덱", self.codec_combo),
            )
        ):
            label_widget = QLabel(label)
            label_widget.setObjectName("MetaText")
            tooltip = PREFERENCE_TOOLTIPS.get(label, "")
            if tooltip:
                label_widget.setToolTip(tooltip)
                combo.setToolTip(tooltip)
            form.addWidget(label_widget, row, 0)
            form.addWidget(combo, row, 1)

        layout.addLayout(form)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("취소")
        self.cancel_button.setObjectName("SecondaryButton")
        self.ok_button = QPushButton("확인")
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button.clicked.connect(self.accept)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.ok_button)
        layout.addLayout(buttons)
        self.refresh_controls()

    def refresh_controls(self):
        audio_format = self.format_combo.currentText().strip().lower() in presenter.AUDIO_FORMATS
        self.codec_combo.setEnabled(not audio_format)

    def preferences(self):
        return presenter.DownloadPreferences(
            quality=_combo_text(self.quality_combo),
            output_format=_combo_text(self.format_combo),
            codec=_combo_text(self.codec_combo),
            frame_rate="자동",
        )


class DeleteConfirmDialog(QDialog):
    def __init__(self, output_path, parent=None, title_text=None, detail_text=None, window_title=None):
        super().__init__(parent)
        self.setWindowTitle(window_title or "파일 삭제")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)

        title = QLabel(title_text or "파일을 삭제하시겠습니까?")
        title.setObjectName("SectionTitle")
        detail = QLabel(detail_text if detail_text is not None else str(output_path))
        detail.setObjectName("MetaText")
        detail.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(detail)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("No")
        self.cancel_button.setObjectName("SecondaryButton")
        self.ok_button = QPushButton("Yes")
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button.clicked.connect(self.accept)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.ok_button)
        layout.addLayout(buttons)
