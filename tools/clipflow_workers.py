from PySide6.QtCore import QObject, Signal, Slot


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


class DownloadWorker(QObject):
    event = Signal(str, dict)
    finished = Signal(str, dict)
    failed = Signal(str, str)

    def __init__(self, row_id, page_url, candidate, output_dir, cookie_source, download_func):
        super().__init__()
        self.row_id = row_id
        self.page_url = page_url
        self.candidate = candidate
        self.output_dir = output_dir
        self.cookie_source = cookie_source
        self.download_func = download_func

    @Slot()
    def run(self):
        try:
            def emit_event(event):
                self.event.emit(self.row_id, event)

            result = self.download_func(
                self.page_url,
                self.candidate,
                self.output_dir,
                cookie_source=self.cookie_source,
                on_event=emit_event,
            )
            self.finished.emit(self.row_id, result)
        except Exception as exc:
            self.failed.emit(self.row_id, str(exc))
