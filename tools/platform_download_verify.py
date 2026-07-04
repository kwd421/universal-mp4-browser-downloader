#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

from tools import candidate_presenter as presenter
from tools import downloader_engine as engine


def verify_cookie_source():
    return os.environ.get("CLIPFLOW_VERIFY_COOKIE_SOURCE") or os.environ.get("UMP4_VERIFY_COOKIE_SOURCE") or "없음"

VERIFY_PREFERENCES = presenter.DownloadPreferences(
    quality="자동",
    output_format="자동",
    codec="자동",
    frame_rate="자동",
    hdr="끔",
)

PLATFORMS = [
    ("youtube", "https://www.youtube.com/watch?v=jNQXAC9IVRw", "yt-dlp", 360),
    ("chzzk", "https://chzzk.naver.com/clips/z0DUTFaKDZ", "yt-dlp", 720),
    ("instagram", "https://www.instagram.com/reel/DUl354timp1/", "yt-dlp", 720),
    ("vimeo", "https://vimeo.com/76979871", "yt-dlp", 720),
    (
        "tiktok",
        "https://www.tiktok.com/@anchaeheeee/video/7651974997644168468?is_from_webapp=1&sender_device=pc",
        "yt-dlp",
        720,
    ),
    ("pornhub", "https://www.pornhub.com/view_video.php?viewkey=6861453eadd37", "dom", 480),
    ("xvideos", "https://www.xvideos.com/video.klvdubb4d47/49079845/0/full_version_https_bit.ly_36cjbb4", "dom", 480),
    ("redtube", "https://www.redtube.com/198689351", "dom", 720),
    ("xhamster", "https://xhamster.desi/videos/femaleagent-shy-beauty-takes-the-bait-1509445", "dom", 240),
]


def safe_int(value):
    return engine.safe_int(value)


def pick_verify_candidate(candidates):
    return presenter.select_candidate_for_preferences(list(candidates or []), VERIFY_PREFERENCES)


def best_available_height(candidates):
    heights = [
        presenter._effective_height_for_auto(candidate)
        for candidate in (candidates or [])
    ]
    return max(heights) if heights else 0


def verify_assets(url, candidate, mp4_path, favicon_urls=None):
    stem = mp4_path.stem
    out_dir = mp4_path.parent
    referer = url or candidate.get("referer") or candidate.get("source")
    thumbnail_url = str(candidate.get("thumbnail") or "").strip()
    row = {
        "thumbnail_ok": False,
        "thumbnail_url": thumbnail_url,
        "thumbnail_path": "",
        "thumbnail_bytes": 0,
        "favicon_ok": False,
        "favicon_url": "",
        "favicon_path": "",
        "favicon_bytes": 0,
        "asset_error": "",
    }
    errors = []
    if not thumbnail_url.lower().startswith(("http://", "https://")):
        errors.append("Candidate thumbnail URL is missing.")
    else:
        try:
            saved = engine.save_thumbnail_asset(thumbnail_url, out_dir, stem, referer=referer)
            row["thumbnail_ok"] = True
            row["thumbnail_path"] = saved.get("path") or ""
            row["thumbnail_bytes"] = safe_int(saved.get("bytes"))
            row["thumbnail_url"] = saved.get("url") or thumbnail_url
        except Exception as exc:
            errors.append(f"thumbnail: {exc}")

    try:
        saved = engine.save_favicon_asset(url, out_dir, stem, candidate_urls=favicon_urls)
        row["favicon_ok"] = True
        row["favicon_path"] = saved.get("path") or ""
        row["favicon_bytes"] = safe_int(saved.get("bytes"))
        row["favicon_url"] = saved.get("url") or ""
    except Exception as exc:
        errors.append(f"favicon: {exc}")

    if errors:
        row["asset_error"] = "; ".join(errors)
    return row


def verify_resolution(candidate, candidates, mp4_path, min_height):
    selected_height = presenter._effective_height_for_auto(candidate)
    actual_width, actual_height = engine.probe_video_resolution(mp4_path)
    actual_max = max(actual_width, actual_height)
    best_height = best_available_height(candidates)
    effective_min = min_height
    if best_height and best_height < min_height:
        effective_min = best_height
    expected_floor = effective_min
    if best_height:
        expected_floor = max(expected_floor, int(best_height * 0.85))
    if selected_height:
        expected_floor = max(expected_floor, int(selected_height * 0.85))
    quality_ok = actual_max >= expected_floor if expected_floor else actual_max > 0
    return {
        "selected_format_id": candidate.get("format_id"),
        "selected_height": selected_height,
        "selected_resolution": candidate.get("resolution"),
        "best_available_height": best_height,
        "actual_width": actual_width,
        "actual_height": actual_height,
        "actual_resolution": f"{actual_width}x{actual_height}" if actual_width and actual_height else "",
        "expected_min_height": expected_floor,
        "quality_ok": quality_ok,
    }


def verify_platform(name, url, expected_path, min_height, out_root):
    started = time.time()
    row = {
        "platform": name,
        "mode": "live",
        "url": url,
        "expected_path": expected_path,
        "preferences": VERIFY_PREFERENCES.__dict__,
        "ok": False,
        "analyze_ok": False,
        "download_ok": False,
        "thumbnail_ok": False,
        "favicon_ok": False,
        "quality_ok": False,
        "source": None,
        "title": None,
        "candidate_count": 0,
        "selected_format_id": None,
        "selected_height": 0,
        "selected_resolution": "",
        "best_available_height": 0,
        "actual_width": 0,
        "actual_height": 0,
        "actual_resolution": "",
        "expected_min_height": min_height,
        "thumbnail_url": "",
        "thumbnail_path": "",
        "thumbnail_bytes": 0,
        "favicon_url": "",
        "favicon_path": "",
        "favicon_bytes": 0,
        "file_path": "",
        "file_bytes": 0,
        "error": "",
        "elapsed_seconds": 0,
    }
    candidates = []
    try:
        analysis = engine.analyze_url(url, cookie_source=verify_cookie_source())
        row["analyze_ok"] = True
        row["source"] = analysis.get("source")
        row["title"] = analysis.get("title")
        candidates = analysis.get("candidates") or []
        row["candidate_count"] = len(candidates)
        if not candidates:
            raise RuntimeError("No candidates returned from analysis.")
        candidate = pick_verify_candidate(candidates)
        if not candidate:
            raise RuntimeError("No downloadable candidate could be selected.")
        out_dir = out_root / name / str(int(time.time() * 1000))
        out_dir.mkdir(parents=True, exist_ok=True)
        before = time.time()
        engine.download_candidate(url, candidate, out_dir, cookie_source=verify_cookie_source())
        newest = engine.newest_file(out_dir, candidate.get("output_ext") or "mp4", since=before - 2)
        if not newest or not newest.exists():
            raise RuntimeError("Download finished but no output file was found.")
        row["download_ok"] = True
        row["file_path"] = str(newest)
        row["file_bytes"] = newest.stat().st_size
        assets = verify_assets(url, candidate, newest, analysis.get("favicon_urls"))
        row.update(assets)
        quality = verify_resolution(candidate, candidates, newest, min_height)
        row.update(quality)
        row["ok"] = (
            row["file_bytes"] > 50_000
            and row["thumbnail_ok"]
            and row["favicon_ok"]
            and row["quality_ok"]
        )
        if not row["ok"] and not row["error"]:
            problems = []
            if row["file_bytes"] <= 50_000:
                problems.append(f"Output file too small: {row['file_bytes']} bytes")
            if not row["thumbnail_ok"]:
                problems.append("Thumbnail was not saved.")
            if not row["favicon_ok"]:
                problems.append("Favicon was not saved.")
            if not row["quality_ok"]:
                problems.append(
                    "Resolution check failed: "
                    f"actual={row.get('actual_resolution') or 'unknown'} "
                    f"selected={row.get('selected_height')}p "
                    f"expected_min={row.get('expected_min_height')}p"
                )
            if assets.get("asset_error"):
                problems.append(assets["asset_error"])
            row["error"] = "; ".join(problems)
    except Exception as exc:
        row["error"] = str(exc)
    row["elapsed_seconds"] = round(time.time() - started, 2)
    return row


def main():
    out_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("downloads-verify")
    out_root.mkdir(parents=True, exist_ok=True)
    results = [verify_platform(name, url, path, min_height, out_root) for name, url, path, min_height in PLATFORMS]
    summary_path = out_root / "platform-download-verify.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = sum(1 for row in results if row["ok"])
    print(json.dumps({"passed": passed, "total": len(results), "summary": str(summary_path)}, ensure_ascii=False))
    for row in results:
        status = "OK" if row["ok"] else "FAIL"
        print(
            f"{status} {row['platform']}: mp4={row.get('file_bytes', 0)} "
            f"sel={row.get('selected_height', 0)}p actual={row.get('actual_resolution','')} "
            f"thumb={row.get('thumbnail_bytes', 0)} favicon={row.get('favicon_bytes', 0)} "
            f"err={row.get('error','')[:120]}"
        )


if __name__ == "__main__":
    main()