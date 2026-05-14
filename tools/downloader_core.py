import json
import sys

try:
    from tools import downloader_engine as engine
except ImportError:
    import downloader_engine as engine


def emit(event):
    print(json.dumps(event, ensure_ascii=True), flush=True)


def main():
    if len(sys.argv) != 2:
        emit({"type": "error", "message": "job.json path is required"})
        return 2

    try:
        with open(sys.argv[1], "r", encoding="utf-8-sig") as handle:
            job = json.load(handle)
        engine.download_legacy_job(job, on_event=emit)
        return 0
    except Exception as exc:
        emit({"type": "error", "message": f"{engine.classify_error(str(exc))}: {exc}"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
