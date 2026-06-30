"""Subprocess entry point for crash-isolated ClipFlow downloads."""

import json
import sys
from pathlib import Path

try:
    from tools import downloader_engine as engine
except ImportError:
    import downloader_engine as engine


def _write_payload(payload, event_path=None):
    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    if event_path:
        with Path(event_path).open("a", encoding="utf-8", errors="replace") as file:
            file.write(line)
            file.flush()
    try:
        if sys.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
    except Exception:
        pass


def run_request(request, download_func=engine.download_candidate):
    event_path = request.get("event_path")

    def emit_event(event):
        _write_payload({"type": "event", "event": event}, event_path=event_path)

    result = download_func(
        request.get("page_url") or "",
        request.get("candidate") or {},
        request.get("output_dir") or "",
        cookie_source=request.get("cookie_source") or "없음",
        proxy_url=request.get("proxy_url") or None,
        on_event=emit_event,
    )
    _write_payload({"type": "finished", "result": result}, event_path=event_path)
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--clipflow-download-worker":
        argv = argv[1:]
    if not argv:
        _write_payload({"type": "failed", "message": "Missing download request path."})
        return 2

    request_path = Path(argv[0])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _write_payload({"type": "failed", "message": f"Cannot read download request: {engine.strip_ansi(exc)}"})
        return 2

    try:
        run_request(request)
        return 0
    except Exception as exc:
        event_path = request.get("event_path") if isinstance(request, dict) else None
        _write_payload({"type": "failed", "message": engine.strip_ansi(exc)}, event_path=event_path)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
