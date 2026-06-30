"""Subprocess entry point for crash-isolated ClipFlow URL analysis."""

import json
import sys
from pathlib import Path

try:
    from tools import downloader_engine as engine
except ImportError:
    import downloader_engine as engine


def _write_payload(payload):
    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    stdout_buffer = getattr(sys.stdout, "buffer", None)
    if stdout_buffer is not None:
        stdout_buffer.write(line.encode("utf-8"))
        stdout_buffer.flush()
        return
    sys.stdout.write(line)
    sys.stdout.flush()


def run_request(request, analyze_func=engine.analyze_url):
    def emit_event(event):
        _write_payload({"type": "event", "event": event})

    result = analyze_func(
        request.get("url") or "",
        cookie_source=request.get("cookie_source") or "없음",
        output_ext=request.get("output_ext") or None,
        proxy_url=request.get("proxy_url") or None,
        on_event=emit_event,
    )
    _write_payload({"type": "finished", "result": result})
    return result


def run_persistent(input_stream=None):
    input_stream = input_stream or sys.stdin
    for line in input_stream:
        text = str(line or "").strip()
        if not text:
            continue
        try:
            request = json.loads(text)
        except Exception as exc:
            _write_payload({"type": "failed", "message": f"Cannot read analysis request: {engine.strip_ansi(exc)}"})
            continue
        try:
            run_request(request)
        except Exception as exc:
            _write_payload({"type": "failed", "message": engine.strip_ansi(exc)})
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--clipflow-analysis-worker":
        argv = argv[1:]
    if argv and argv[0] == "--persistent":
        return run_persistent()
    if not argv:
        _write_payload({"type": "failed", "message": "Missing analysis request path."})
        return 2

    request_path = Path(argv[0])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _write_payload({"type": "failed", "message": f"Cannot read analysis request: {engine.strip_ansi(exc)}"})
        return 2

    try:
        run_request(request)
        return 0
    except Exception as exc:
        _write_payload({"type": "failed", "message": engine.strip_ansi(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
