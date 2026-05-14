import os
import io
import queue
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from tkinter import Tk, StringVar, Text, filedialog
from tkinter import ttk

try:
    from tools import downloader_engine as engine
    from tools import candidate_presenter as presenter
except ImportError:
    import downloader_engine as engine
    import candidate_presenter as presenter

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None


COOKIE_CHOICES = ["없음", "Chrome", "Edge", "Firefox"]
EXTENSION_CHOICES = ["MP4", "WEBM", "WAV"]
VERIFY_TIMEOUT_SECONDS = 180
THUMBNAIL_SIZE = (96, 54)
TREE_ROW_HEIGHT = 68
THUMBNAIL_LOAD_LIMIT = 30
CANDIDATE_COLUMNS = [
    ("resolution", "해상도", 95),
    ("duration", "길이", 70),
    ("ext", "확장자", 70),
    ("quality", "품질", 150),
    ("size", "예상 크기", 105),
    ("note", "설명", 260),
]


def run_headless_verification(
    url,
    output_json,
    output_dir,
    cookie_source="없음",
    proxy_url=None,
    output_ext=None,
    should_download=False,
    download_candidate_index=0,
    analyze_func=engine.analyze_url,
    download_func=engine.download_candidate,
):
    started_at = time.time()
    events = []

    def on_event(event):
        events.append(event)

    try:
        analysis = analyze_func(url, cookie_source=cookie_source, proxy_url=proxy_url, output_ext=output_ext, on_event=on_event)
        candidates = analysis.get("candidates") or []
        result = {
            "ok": True,
            "url": url,
            "title": analysis.get("title"),
            "candidate_count": len(candidates),
            "candidates": candidates,
            "warnings": analysis.get("warnings") or [],
            "events": events,
            "download": None,
        }
        if should_download:
            if not candidates:
                raise RuntimeError("No downloadable candidate was found.")
            selected_index = max(0, min(int(download_candidate_index or 0), len(candidates) - 1))
            candidate = candidates[selected_index]
            before_download = time.time()
            download = download_func(
                analysis.get("webpage_url") or url,
                candidate,
                output_dir,
                cookie_source,
                proxy_url=proxy_url,
                on_event=on_event,
            )
            output_extension = (candidate.get("output_ext") or candidate.get("ext") or "mp4").lower()
            newest = engine.newest_file(output_dir, output_extension, since=before_download - 2)
            result["download"] = {
                **download,
                "selected_candidate": candidate,
                "mp4_path": str(newest) if newest else "",
                "mp4_exists": bool(newest and newest.exists()),
            }
            result["ok"] = bool(result["download"]["mp4_exists"])
        result["elapsed_seconds"] = round(time.time() - started_at, 2)
    except Exception as exc:
        result = {
            "ok": False,
            "url": url,
            "error_class": engine.classify_error(str(exc)),
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "events": events,
            "elapsed_seconds": round(time.time() - started_at, 2),
        }

    if output_json:
        engine.write_json(output_json, result)
    return result


def quality_label(candidate):
    return presenter.quality_label(candidate)
    ext = str(candidate.get("output_ext") or candidate.get("ext") or "").upper()
    size = engine.display_size(candidate.get("sort_bytes"))
    if candidate.get("media_type") == "audio" or ext == "WAV":
        note = candidate.get("note") or "audio"
        return f"{ext} · {size} · {note}"
    resolution = candidate.get("resolution") or "unknown"
    return f"{resolution} · {ext} · {size}"


def filter_manifest_duplicates(candidates):
    return presenter.filter_manifest_duplicates(candidates)


def filter_visible_quality_duplicates(candidates):
    return presenter.filter_visible_quality_duplicates(candidates)


def group_candidates(candidates):
    return presenter.group_candidates(candidates)


class UrlDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Universal MP4 Downloader")
        self.root.minsize(860, 560)
        self.events = queue.Queue()
        self.analysis = None
        self.candidates = {}
        self.candidate_groups = {}
        self.quality_candidates = {}
        self.thumbnail_images = {}
        self.output_dir = StringVar(value=str(Path.home() / "Downloads"))
        self.cookie_source = StringVar(value=COOKIE_CHOICES[0])
        self.output_extension = StringVar(value=EXTENSION_CHOICES[0])
        self.quality_choice = StringVar()
        self.url = StringVar()
        self.status = StringVar(value="URL을 붙여넣고 분석을 누르세요")
        self.progress_value = StringVar(value="0")
        self._build_ui()
        self.url.trace_add("write", lambda *_args: self._refresh_analyze_button())
        self.output_extension.trace_add("write", lambda *_args: self._refresh_download_button())
        self.root.after(100, self._poll_events)

    def _build_ui(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        top = ttk.Frame(root, padding=10)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="URL").grid(row=0, column=0, padx=(0, 6), sticky="w")
        url_entry = ttk.Entry(top, textvariable=self.url)
        url_entry.grid(row=0, column=1, sticky="ew")
        url_entry.bind("<FocusIn>", lambda event: event.widget.select_range(0, "end"))
        url_entry.bind("<Return>", lambda event: self.analyze_or_paste())
        ttk.Combobox(top, textvariable=self.output_extension, values=EXTENSION_CHOICES, width=8, state="readonly").grid(row=0, column=2, padx=(6, 0))
        self.analyze_button = ttk.Button(top, text="붙여넣기", command=self.analyze_or_paste)
        self.analyze_button.grid(row=0, column=3, padx=(6, 0))

        controls = ttk.Frame(root, padding=(10, 0, 10, 8))
        controls.grid(row=1, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="저장 폴더").grid(row=0, column=0, padx=(0, 6), sticky="w")
        ttk.Entry(controls, textvariable=self.output_dir).grid(row=0, column=1, sticky="ew")
        ttk.Button(controls, text="폴더", command=self.choose_folder).grid(row=0, column=2, padx=(6, 12))
        ttk.Label(controls, text="쿠키").grid(row=0, column=3, padx=(0, 6))
        ttk.Combobox(controls, textvariable=self.cookie_source, values=COOKIE_CHOICES, width=10, state="readonly").grid(row=0, column=4)

        table_frame = ttk.Frame(root, padding=(10, 0, 10, 8))
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        style = ttk.Style(root)
        style.configure("Candidate.Treeview", rowheight=TREE_ROW_HEIGHT)
        columns = tuple(column[0] for column in CANDIDATE_COLUMNS)
        self.tree = ttk.Treeview(table_frame, columns=columns, show="tree headings", selectmode="browse", style="Candidate.Treeview")
        self.tree.heading("#0", text="영상")
        self.tree.column("#0", width=420, minwidth=320, anchor="w")
        for key, heading, width in CANDIDATE_COLUMNS:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        bottom = ttk.Frame(root, padding=(10, 0, 10, 10))
        bottom.grid(row=3, column=0, sticky="ew")
        bottom.columnconfigure(3, weight=1)
        ttk.Label(bottom, text="품질").grid(row=0, column=0, sticky="w")
        self.quality_combo = ttk.Combobox(bottom, textvariable=self.quality_choice, values=[], width=34, state="readonly")
        self.quality_combo.grid(row=0, column=1, padx=(6, 10), sticky="w")
        self.quality_combo.bind("<<ComboboxSelected>>", self._on_quality_select)
        self.download_button = ttk.Button(bottom, text="선택 항목 MP4 다운로드", command=self.start_download)
        self.download_button.grid(row=0, column=2, sticky="w")
        ttk.Label(bottom, textvariable=self.status).grid(row=0, column=3, padx=(12, 0), sticky="ew")
        self.progress = ttk.Progressbar(bottom, maximum=100)
        self.progress.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 6))
        self.log = Text(bottom, height=7, wrap="word")
        self.log.grid(row=2, column=0, columnspan=4, sticky="ew")
        self._refresh_analyze_button()
        self._refresh_download_button()

    def _refresh_analyze_button(self):
        if hasattr(self, "analyze_button"):
            self.analyze_button.configure(text="분석" if self.url.get().strip() else "붙여넣기")

    def _refresh_download_button(self):
        if hasattr(self, "download_button"):
            self.download_button.configure(text=f"선택 항목 {self.output_extension.get()} 다운로드")

    def analyze_or_paste(self):
        if self.url.get().strip():
            self.start_analysis()
            return
        try:
            pasted = self.root.clipboard_get().strip()
        except Exception:
            pasted = ""
        if pasted:
            self.url.set(pasted)
            self.status.set("URL 붙여넣음")
        else:
            self.status.set("클립보드에 URL이 없습니다")

    def choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.output_dir.get(), title="저장 폴더 선택")
        if folder:
            self.output_dir.set(folder)
            self.add_log(f"저장 폴더: {folder}")

    def add_log(self, message):
        if not message:
            return
        stamp = time.strftime("%H:%M:%S")
        self.log.insert("end", f"[{stamp}] {message}\n")
        self.log.see("end")

    def start_analysis(self):
        url = self.url.get().strip()
        if not url:
            self.analyze_or_paste()
            return
        self.analysis = None
        self.candidates.clear()
        self.candidate_groups.clear()
        self.quality_candidates.clear()
        self.thumbnail_images.clear()
        self.quality_choice.set("")
        self.quality_combo.configure(values=[])
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.progress.configure(value=0)
        self.status.set("분석 중")
        self.add_log(f"분석 시작: {url}")
        threading.Thread(target=self._analyze_worker, args=(url, self.cookie_source.get(), self.output_extension.get()), daemon=True).start()

    def _analyze_worker(self, url, cookie_source, output_ext):
        try:
            result = engine.analyze_url(
                url,
                cookie_source=cookie_source,
                output_ext=output_ext,
                on_event=lambda event: self.events.put(("event", event)),
            )
            self.events.put(("analysis", result))
        except Exception as exc:
            self.events.put(("error", {"message": str(exc), "class": engine.classify_error(str(exc))}))

    def _candidate_values(self, candidate):
        values = []
        for key, _heading, _width in CANDIDATE_COLUMNS:
            if key == "size":
                values.append(engine.display_size(candidate.get("sort_bytes")))
            elif key == "quality":
                values.append(quality_label(candidate))
            elif key == "duration":
                values.append(engine.display_duration(candidate.get("duration")))
            elif key == "resolution" and str(candidate.get("output_ext") or "").lower() == "wav":
                values.append("")
            else:
                values.append(candidate.get(key) or "")
        return tuple(values)

    def _thumbnail_bytes_for(self, candidate):
        thumbnail_url = str(candidate.get("thumbnail") or "").strip()
        if not thumbnail_url.lower().startswith(("http://", "https://")):
            return None
        try:
            request = urllib.request.Request(
                thumbnail_url,
                headers={
                    "User-Agent": engine.USER_AGENT,
                    "Accept-Language": engine.ACCEPT_LANGUAGE,
                },
            )
            with urllib.request.urlopen(request, timeout=4) as response:
                return response.read(2_500_000)
        except (OSError, urllib.error.URLError, ValueError):
            return None

    def _photo_from_thumbnail_bytes(self, data):
        if Image is None or ImageTk is None or not data:
            return None
        try:
            image = Image.open(io.BytesIO(data))
            image.thumbnail(THUMBNAIL_SIZE)
            return ImageTk.PhotoImage(image)
        except (OSError, ValueError):
            return None

    def _start_thumbnail_worker(self, iid, candidate):
        def worker():
            data = self._thumbnail_bytes_for(candidate)
            if data:
                self.events.put(("thumbnail", {"iid": iid, "data": data}))

        threading.Thread(target=worker, daemon=True).start()

    def _show_analysis(self, analysis):
        self.analysis = analysis
        self.thumbnail_images.clear()
        self.candidate_groups.clear()
        self.quality_candidates.clear()
        rows = group_candidates(analysis.get("candidates", []))
        for index, group in enumerate(rows, start=1):
            iid = group["id"]
            candidate = group["candidate"]
            self.candidates[iid] = candidate
            self.candidate_groups[iid] = group["qualities"]
            self.tree.insert(
                "",
                "end",
                iid=iid,
                text=candidate.get("display_title") or candidate.get("title") or "video",
                values=self._candidate_values(candidate),
            )
            if index <= THUMBNAIL_LOAD_LIMIT:
                self._start_thumbnail_worker(iid, candidate)
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self._on_tree_select()
        self.status.set(f"영상 {len(children)}개")
        self.add_log(f"분석 완료: 영상 {len(children)}개")
        for warning in analysis.get("warnings") or []:
            self.add_log(warning)

    def start_download(self):
        if not self.analysis:
            self.status.set("먼저 분석하세요")
            return
        selected = self.tree.selection()
        if not selected:
            self.status.set("다운로드할 항목을 선택하세요")
            return
        candidate = self._selected_quality_candidate(selected[0])
        if not candidate:
            self.status.set("다운로드할 품질을 선택하세요")
            return
        self.progress.configure(value=0)
        self.status.set("다운로드 준비 중")
        self.add_log(f"다운로드 시작: {candidate.get('format_id')} {candidate.get('resolution')}")
        threading.Thread(target=self._download_worker, args=(candidate,), daemon=True).start()

    def _selected_quality_candidate(self, iid):
        label = self.quality_choice.get()
        if label and label in self.quality_candidates:
            return self.quality_candidates[label]
        return self.candidates.get(iid)

    def _on_tree_select(self, event=None):
        selected = self.tree.selection()
        if not selected:
            self.quality_choice.set("")
            self.quality_combo.configure(values=[])
            return
        iid = selected[0]
        qualities = self.candidate_groups.get(iid) or [self.candidates.get(iid)]
        qualities = [candidate for candidate in qualities if candidate]
        self.quality_candidates.clear()
        labels = []
        for index, candidate in enumerate(qualities, start=1):
            label = f"{index}. {quality_label(candidate)}"
            self.quality_candidates[label] = candidate
            labels.append(label)
        self.quality_combo.configure(values=labels)
        if labels:
            self.quality_choice.set(labels[0])
            self.candidates[iid] = self.quality_candidates[labels[0]]

    def _on_quality_select(self, event=None):
        selected = self.tree.selection()
        if not selected:
            return
        iid = selected[0]
        candidate = self.quality_candidates.get(self.quality_choice.get())
        if not candidate:
            return
        self.candidates[iid] = candidate
        self.tree.item(iid, values=self._candidate_values(candidate))

    def _download_worker(self, candidate):
        try:
            result = engine.download_candidate(
                self.analysis.get("webpage_url") or self.url.get().strip(),
                candidate,
                self.output_dir.get(),
                cookie_source=self.cookie_source.get(),
                on_event=lambda event: self.events.put(("event", event)),
            )
            self.events.put(("download", result))
        except Exception as exc:
            self.events.put(("error", {"message": str(exc), "class": engine.classify_error(str(exc))}))

    def _handle_event(self, event):
        event_type = event.get("type")
        if event_type == "progress":
            self.progress.configure(value=max(0, min(100, float(event.get("percent") or 0))))
            self.status.set(event.get("message") or "다운로드 중")
        elif event_type == "status":
            self.status.set(event.get("message") or "")
            self.add_log(event.get("message"))
        elif event_type == "log":
            self.add_log(event.get("message"))
        elif event_type == "done":
            self.progress.configure(value=100)
            self.status.set("완료")
            self.add_log(event.get("path") or "완료")
        elif event_type == "file":
            self.add_log(event.get("path"))

    def _poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "event":
                    self._handle_event(payload)
                elif kind == "analysis":
                    self._show_analysis(payload)
                elif kind == "download":
                    self.progress.configure(value=100)
                    self.status.set("완료")
                    self.add_log(payload.get("output_dir"))
                elif kind == "thumbnail":
                    photo = self._photo_from_thumbnail_bytes(payload.get("data"))
                    iid = payload.get("iid")
                    if photo and iid and self.tree.exists(iid):
                        self.thumbnail_images[iid] = photo
                        self.tree.item(iid, image=photo)
                elif kind == "error":
                    self.status.set(payload.get("class") or "오류")
                    self.add_log(f"{payload.get('class')}: {payload.get('message')}")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)


def main():
    verify_url = os.environ.get("UMP4_VERIFY_URL", "").strip()
    verify_out = os.environ.get("UMP4_VERIFY_OUT", "").strip()
    if verify_url:
        output_dir = os.environ.get("UMP4_VERIFY_DOWNLOAD_DIR") or str(Path.home() / "Downloads")
        cookie_source = os.environ.get("UMP4_VERIFY_COOKIE_SOURCE") or "없음"
        proxy_url = os.environ.get("UMP4_VERIFY_PROXY") or None
        output_ext = os.environ.get("UMP4_VERIFY_EXTENSION") or None
        should_download = os.environ.get("UMP4_VERIFY_DOWNLOAD", "") == "1"
        candidate_index = engine.safe_int(os.environ.get("UMP4_VERIFY_CANDIDATE_INDEX"))
        run_headless_verification(verify_url, verify_out, output_dir, cookie_source, proxy_url, output_ext, should_download, candidate_index)
        return

    root = Tk()
    UrlDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
