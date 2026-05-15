import json
import os
import re
import html as html_lib
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7778.167 Safari/537.36"
)
ACCEPT_LANGUAGE = "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
CHZZK_CLIP_RE = re.compile(r"https?://chzzk\.naver\.com/clips/([A-Za-z0-9_-]+)")
GENERIC_TITLE_RE = re.compile(r"^(?:video(?:\s+\d+)?|post by .+)$", re.IGNORECASE)
TRAILING_DOMAIN_TITLE_RE = re.compile(
    r"\s+(?:-|–|—|\|)\s+(?:www\.)?[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+\s*$",
    re.IGNORECASE,
)
VIDEO_EXTENSIONS = {"mp4", "m4v", "mov", "webm", "mkv", "flv", "ts"}
AUDIO_OUTPUT_EXTENSIONS = {"mp3", "wav", "aac"}
OUTPUT_EXTENSIONS = {"mp4", "webm"} | AUDIO_OUTPUT_EXTENSIONS
ALL_OUTPUT_EXT = "all"
SIZE_PROBE_LIMIT = 12
COOKIE_SOURCES = {
    "chrome": ("chrome",),
    "google chrome": ("chrome",),
    "edge": ("edge",),
    "microsoft edge": ("edge",),
    "firefox": ("firefox",),
}


def emit_event(callback, event_type, **payload):
    event = {"type": event_type, **payload}
    if callback:
        callback(event)
    return event


class EventLogger:
    def __init__(self, callback=None):
        self.callback = callback

    def debug(self, msg):
        if not str(msg).startswith("[debug]"):
            emit_event(self.callback, "log", message=str(msg))

    def warning(self, msg):
        lower = str(msg).lower()
        if "ffprobe not found" in lower and "unable to extract metadata" in lower:
            return
        emit_event(self.callback, "log", message=f"Warning: {msg}")

    def error(self, msg):
        emit_event(self.callback, "log", message=f"Error: {msg}")


def ffmpeg_path():
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def safe_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def cookie_spec(cookie_source):
    source = str(cookie_source or "").strip().lower()
    if not source or source in {"none", "no", "없음"}:
        return None
    return COOKIE_SOURCES.get(source)


def normalize_proxy_url(proxy_url):
    proxy = str(proxy_url or "").strip()
    if not proxy or proxy.lower() in {"none", "no", "direct", "없음"}:
        return None
    return proxy


def proxy_url_from_windows_server(proxy_server):
    server = str(proxy_server or "").strip()
    if not server:
        return None
    if ";" in server:
        parts = {}
        for item in server.split(";"):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            parts[key.strip().lower()] = value.strip()
        server = parts.get("https") or parts.get("http") or next((value for value in parts.values() if value), "")
    if not server:
        return None
    if not re.match(r"^[a-z][a-z0-9+.-]*://", server, re.IGNORECASE):
        server = f"http://{server}"
    return normalize_proxy_url(server)


def windows_user_proxy_url():
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not safe_int(proxy_enable):
                return None
            proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
            return proxy_url_from_windows_server(proxy_server)
    except (OSError, ImportError, FileNotFoundError):
        return None


def environment_proxy_url(environ=None):
    env = environ if environ is not None else os.environ
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        proxy = normalize_proxy_url(env.get(key))
        if proxy:
            return proxy
    return None


def effective_proxy_url(explicit_proxy=None, environ=None, windows_proxy_fetcher=windows_user_proxy_url):
    if explicit_proxy is not None:
        raw = str(explicit_proxy or "").strip()
        if raw.lower() in {"none", "no", "direct", "없음"}:
            return None
        if raw:
            return normalize_proxy_url(raw)
    proxy = environment_proxy_url(environ)
    if proxy:
        return proxy
    try:
        return normalize_proxy_url(windows_proxy_fetcher())
    except Exception:
        return None


def classify_error(message):
    lower = str(message or "").lower()
    if "drm" in lower or "encrypted" in lower:
        return "DRM 가능성"
    if any(token in lower for token in ["connectionreseterror", "connection was reset", "curl: (35)", "forcibly closed"]):
        return "브라우저 지문/TLS 차단 가능성"
    if any(token in lower for token in ["login", "private", "forbidden", "unauthorized", "401", "403"]):
        return "로그인/권한 필요"
    if "unsupported" in lower or "no video" in lower or "no suitable" in lower:
        return "지원되지 않는 스트림"
    return "네트워크/추출 오류"


def resolution_for(fmt):
    width = safe_int(fmt.get("width"))
    height = safe_int(fmt.get("height"))
    if width and height:
        return f"{width}x{height}"
    if height:
        return f"{height}p"
    return str(fmt.get("resolution") or "unknown")


def display_size(num_bytes):
    size = safe_int(num_bytes)
    if not size:
        return "unknown"
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def display_duration(seconds):
    total = safe_int(seconds)
    if not total:
        return ""
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def compact_text(value, limit=90):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def clean_video_title(value):
    title = html_lib.unescape(compact_text(value, limit=180))
    while title:
        cleaned = TRAILING_DOMAIN_TITLE_RE.sub("", title).strip()
        if cleaned == title:
            break
        title = cleaned
    return title


def filename_stem_for_candidate(candidate):
    title = clean_video_title(candidate.get("display_title") or candidate.get("title") or "video")
    try:
        from yt_dlp.utils import sanitize_filename

        title = sanitize_filename(title, restricted=False, is_id=False)
    except Exception:
        title = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", title).strip()
    title = compact_text(title.strip(" ."), limit=160)
    return title or "video"


def output_dir_for_candidate(candidate, output_dir):
    output_path = Path(output_dir).expanduser()
    if str((candidate or {}).get("media_type") or "").lower() != "playlist":
        return output_path
    folder_name = filename_stem_for_candidate(candidate)
    if output_path.name == folder_name:
        return output_path
    return output_path / folder_name


def escape_yt_dlp_template_literal(value):
    return str(value).replace("%", "%%")


def looks_like_playlist_url(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    path = parsed.path.lower()
    query = urllib.parse.parse_qs(parsed.query)
    if any(str(value or "").strip() for value in query.get("list", [])):
        return True
    return "playlist" in path


def caption_title_from_info(*infos):
    for info in infos:
        if not isinstance(info, dict):
            continue
        for key in ("description", "caption", "alt_title"):
            title = clean_video_title(info.get(key))
            if title:
                return title
    return ""


def uploader_name_from_info(*infos):
    for info in infos:
        if not isinstance(info, dict):
            continue
        for key in ("uploader", "channel", "creator", "artist", "author"):
            name = clean_video_title(info.get(key))
            if name:
                return name
    return ""


def prefix_title_with_uploader(title, uploader):
    title = str(title or "").strip()
    uploader = str(uploader or "").strip()
    if not title or not uploader:
        return title or uploader
    title_folded = title.casefold()
    uploader_folded = uploader.casefold()
    if title_folded.startswith(uploader_folded):
        return title
    return f"{uploader} - {title}"


def display_title_for(video_info, root_info):
    raw_title = clean_video_title(video_info.get("title") or root_info.get("title")) or "video"
    if GENERIC_TITLE_RE.match(raw_title or ""):
        raw_title = caption_title_from_info(video_info, root_info) or raw_title
    return prefix_title_with_uploader(raw_title, uploader_name_from_info(video_info, root_info))


def thumbnail_from_info(info):
    if not isinstance(info, dict):
        return ""
    if info.get("thumbnail"):
        return str(info["thumbnail"])
    thumbnails = info.get("thumbnails") or []
    if not thumbnails:
        return ""
    usable = [item for item in thumbnails if isinstance(item, dict) and item.get("url")]
    if not usable:
        return ""
    best = sorted(usable, key=lambda item: safe_int(item.get("width")) * safe_int(item.get("height")), reverse=True)[0]
    return str(best.get("url") or "")


def parse_content_range(value):
    match = re.search(r"/(\d+)\s*$", str(value or ""))
    return safe_int(match.group(1)) if match else 0


def http_content_length(url, timeout=3):
    if not str(url or "").lower().startswith(("http://", "https://")):
        return 0
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": ACCEPT_LANGUAGE,
    }
    try:
        request = urllib.request.Request(url, headers=headers, method="HEAD")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            length = safe_int(response.headers.get("Content-Length"))
            if length:
                return length
            ranged = parse_content_range(response.headers.get("Content-Range"))
            if ranged:
                return ranged
    except (OSError, urllib.error.URLError, ValueError):
        pass

    try:
        request = urllib.request.Request(url, headers={**headers, "Range": "bytes=0-0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            ranged = parse_content_range(response.headers.get("Content-Range"))
            if ranged:
                return ranged
            return safe_int(response.headers.get("Content-Length"))
    except (OSError, urllib.error.URLError, ValueError):
        return 0


def enrich_missing_sizes(candidates, size_probe=http_content_length, limit=SIZE_PROBE_LIMIT):
    checked = 0
    for candidate in candidates:
        if safe_int(candidate.get("sort_bytes")):
            continue
        if candidate.get("is_manifest") or is_manifest_format(candidate):
            continue
        if checked >= limit:
            break
        checked += 1
        size = safe_int(size_probe(candidate.get("url") or ""))
        if not size:
            continue
        candidate["filesize_approx"] = size
        candidate["sort_bytes"] = size
        candidate["size_source"] = "http"
    return candidates


def find_chzzk_clip_uid(*urls):
    for url in urls:
        if not url:
            continue
        match = CHZZK_CLIP_RE.search(str(url))
        if match:
            return match.group(1)
    return None


def http_json(url, params=None, headers=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": ACCEPT_LANGUAGE,
            "Accept": "application/json,text/plain,*/*",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def chzzk_clip_detail(clip_uid):
    return http_json(
        f"https://api.chzzk.naver.com/service/v1/clips/{clip_uid}/detail",
        params=[
            ("optionalProperties", "COMMENT"),
            ("optionalProperties", "PRIVATE_USER_BLOCK"),
            ("optionalProperties", "PENALTY"),
            ("optionalProperties", "MAKER_CHANNEL"),
            ("optionalProperties", "OWNER_CHANNEL"),
        ],
        headers={
            "Referer": f"https://chzzk.naver.com/clips/{clip_uid}",
            "Origin": "https://chzzk.naver.com",
            "Front-Client-Product-Type": "web",
            "Front-Client-Platform-Type": "PC",
        },
    )


def chzzk_shortform_card(clip_uid, video_id, rec_id):
    return http_json(
        "https://api-videohub.naver.com/shortformhub/feeds/v9/card",
        params={
            "seedType": "SPECIFIC",
            "serviceType": "CHZZK",
            "seedMediaId": video_id,
            "mediaType": "VOD",
            "panelType": "sdk_chzzk",
            "referer": f"https://chzzk.naver.com/clips/{clip_uid}",
            "recType": "CHZZK",
            "recId": rec_id or json.dumps({"seedClipUID": clip_uid, "fromType": "GLOBAL", "listType": "RECOMMEND"}),
            "enableReverse": "false",
            "adAllowed": "Y",
            "clickNsc": "chzzk_url_clip",
            "clickArea": "clip_item",
            "deviceType": "html5_mo",
        },
        headers={
            "Referer": "https://m.naver.com/shorts/",
            "Origin": "https://m.naver.com",
        },
    )


def extract_chzzk_media_urls(card_payload):
    mp4_candidates = []
    hls_candidates = []

    def add_url(url, width=0, height=0, bandwidth=0):
        if not isinstance(url, str) or not url.startswith("http"):
            return
        item = {
            "url": url,
            "width": safe_int(width),
            "height": safe_int(height),
            "bandwidth": safe_int(bandwidth),
        }
        lower = url.lower()
        if ".mp4" in lower:
            mp4_candidates.append(item)
        elif ".m3u8" in lower:
            hls_candidates.append(item)

    def walk(value):
        if isinstance(value, dict):
            base_urls = value.get("BaseURL")
            if isinstance(base_urls, list):
                for base_url in base_urls:
                    add_url(base_url, value.get("@width"), value.get("@height"), value.get("@bandwidth"))
            bitrate = value.get("bitrate") if isinstance(value.get("bitrate"), dict) else {}
            add_url(value.get("@nvod:m3u"), value.get("@width"), value.get("@height"), value.get("@bandwidth"))
            add_url(value.get("source"), value.get("width"), value.get("height"), bitrate.get("video"))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(card_payload)

    def best(candidates):
        deduped = {item["url"]: item for item in candidates}
        return sorted(deduped.values(), key=lambda item: (item["height"], item["width"], item["bandwidth"]), reverse=True)

    return best(mp4_candidates), best(hls_candidates)


def analyze_chzzk_clip(url, on_event=None):
    clip_uid = find_chzzk_clip_uid(url)
    if not clip_uid:
        return None

    emit_event(on_event, "status", message=f"CHZZK 클립 분석 중: {clip_uid}")
    detail = chzzk_clip_detail(clip_uid)
    content = detail.get("content") or {}
    if content.get("adult") or (content.get("optionalProperty") or {}).get("privateUserBlock") or (content.get("optionalProperty") or {}).get("penalty"):
        raise RuntimeError("CHZZK clip is not publicly playable in this session.")

    video_id = content.get("videoId")
    if not video_id:
        raise RuntimeError("CHZZK clip detail did not include a videoId.")

    card = chzzk_shortform_card(clip_uid, video_id, content.get("recId"))
    mp4_candidates, hls_candidates = extract_chzzk_media_urls(card)
    candidates = []
    title = content.get("clipTitle") or content.get("title") or f"CHZZK clip {clip_uid}"
    thumbnail = (
        content.get("thumbnailImageUrl")
        or content.get("clipImageUrl")
        or content.get("imageUrl")
        or content.get("previewImageUrl")
        or ""
    )
    for index, item in enumerate(mp4_candidates + hls_candidates, start=1):
        ext = "mp4" if ".mp4" in item["url"].lower() else "m3u8"
        candidates.append(
            {
                "id": f"chzzk-{index}",
                "format_id": f"chzzk-{item['height'] or index}",
                "format_selector": "best",
                "url": item["url"],
                "title": title,
                "display_title": title,
                "thumbnail": thumbnail,
                "duration": 0,
                "ext": ext,
                "resolution": f"{item['width']}x{item['height']}" if item["width"] and item["height"] else (f"{item['height']}p" if item["height"] else "unknown"),
                "height": item["height"],
                "fps": 0,
                "vcodec": "unknown",
                "acodec": "unknown",
                "filesize": 0,
                "filesize_approx": 0,
                "sort_bytes": 0,
                "size_source": "unknown",
                "source": f"https://chzzk.naver.com/clips/{clip_uid}",
                "note": "CHZZK direct MP4" if ext == "mp4" else "CHZZK HLS",
            }
        )
    candidates = sort_candidates(enrich_missing_sizes(candidates))
    return {
        "url": url,
        "webpage_url": f"https://chzzk.naver.com/clips/{clip_uid}",
        "title": candidates[0]["title"] if candidates else f"CHZZK clip {clip_uid}",
        "candidates": candidates,
        "warnings": [],
    }


def iter_video_infos(info):
    if not isinstance(info, dict):
        return
    entries = info.get("entries")
    if entries:
        for entry in entries:
            if isinstance(entry, dict):
                yield from iter_video_infos(entry)
        return
    yield info


def best_audio_format(formats):
    audio = [
        fmt
        for fmt in formats
        if str(fmt.get("vcodec") or "none").lower() == "none"
        and str(fmt.get("acodec") or "none").lower() != "none"
    ]
    return sorted(
        audio,
        key=lambda fmt: (
            1 if str(fmt.get("ext") or "").lower() == "m4a" else 0,
            safe_int(fmt.get("filesize") or fmt.get("filesize_approx")),
            safe_int(fmt.get("abr")),
        ),
        reverse=True,
    )[0] if audio else None


def sort_candidates(candidates):
    return sorted(
        candidates,
        key=lambda candidate: (
            1 if safe_int(candidate.get("sort_bytes")) > 0 else 0,
            safe_int(candidate.get("sort_bytes")),
            safe_int(candidate.get("height")),
            safe_int(candidate.get("fps")),
        ),
        reverse=True,
    )


def normalized_output_ext(output_ext):
    ext = str(output_ext or "").strip().lower()
    if ext == ALL_OUTPUT_EXT:
        return ALL_OUTPUT_EXT
    return ext if ext in OUTPUT_EXTENSIONS else None


def chrome_impersonation_target():
    try:
        import curl_cffi  # noqa: F401
        from yt_dlp.networking.impersonate import ImpersonateTarget

        return ImpersonateTarget.from_str("chrome-110:windows-10")
    except Exception:
        return None


def should_retry_with_impersonation(message):
    return classify_error(message) == "브라우저 지문/TLS 차단 가능성"


def is_audio_format(fmt):
    return (
        str(fmt.get("vcodec") or "none").lower() == "none"
        and str(fmt.get("acodec") or "none").lower() != "none"
    )


def format_protocol(fmt):
    return str(fmt.get("protocol") or "")


def is_manifest_format(fmt):
    protocol = format_protocol(fmt).lower()
    url = str(fmt.get("url") or "").lower()
    return "m3u8" in protocol or "dash" in protocol or ".m3u8" in url or ".mpd" in url


def bitrate_duration_size(fmt, duration=0):
    bitrate_kbps = safe_int(fmt.get("tbr") or fmt.get("vbr") or fmt.get("abr"))
    seconds = safe_int(fmt.get("duration") or duration)
    if not bitrate_kbps or not seconds:
        return 0
    return int(bitrate_kbps * 1000 * seconds / 8)


def media_size_for_format(fmt, duration=0, extra_size=0):
    if is_manifest_format(fmt):
        estimated = bitrate_duration_size(fmt, duration)
        if estimated:
            return estimated + safe_int(extra_size), "bitrate"
        return 0, "unknown"

    declared = safe_int(fmt.get("filesize") or fmt.get("filesize_approx"))
    if declared:
        return declared + safe_int(extra_size), "metadata"
    return 0, "unknown"


def candidate_filesize_fields(fmt, sort_bytes=0, size_source="unknown"):
    if is_manifest_format(fmt):
        if size_source == "bitrate":
            return 0, safe_int(sort_bytes)
        return 0, 0
    return safe_int(fmt.get("filesize")), safe_int(fmt.get("filesize_approx"))


def candidates_from_info(info, output_ext=None):
    requested_ext = normalized_output_ext(output_ext)
    include_all = requested_ext == ALL_OUTPUT_EXT
    requested_filter = None if include_all else requested_ext
    audio_output_exts = (
        [requested_filter]
        if requested_filter in AUDIO_OUTPUT_EXTENSIONS
        else sorted(AUDIO_OUTPUT_EXTENSIONS)
        if include_all
        else []
    )
    candidates = []
    seen = set()
    for video_info in iter_video_infos(info):
        title = clean_video_title(video_info.get("title") or info.get("title")) or "video"
        display_title = display_title_for(video_info, info)
        thumbnail = thumbnail_from_info(video_info) or thumbnail_from_info(info)
        duration = safe_int(video_info.get("duration") or info.get("duration"))
        formats = video_info.get("formats") or []
        audio = best_audio_format(formats)
        for fmt in formats:
            format_id = str(fmt.get("format_id") or "")
            ext = str(fmt.get("ext") or "").lower()
            vcodec = str(fmt.get("vcodec") or "unknown")
            acodec = str(fmt.get("acodec") or "unknown")
            if audio_output_exts and is_audio_format(fmt):
                if not is_audio_format(fmt):
                    continue
                size, size_source = media_size_for_format(fmt, duration)
                filesize, filesize_approx = candidate_filesize_fields(fmt, size, size_source)
                source = video_info.get("webpage_url") or video_info.get("original_url") or info.get("webpage_url") or ""
                for audio_output_ext in audio_output_exts:
                    key = (source, audio_output_ext, format_id, fmt.get("url"))
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(
                        {
                            "id": f"{len(candidates) + 1}",
                            "format_id": format_id or "bestaudio",
                            "format_selector": format_id or "bestaudio",
                            "url": fmt.get("url") or source,
                            "title": title,
                            "display_title": display_title,
                            "thumbnail": thumbnail,
                            "duration": duration,
                            "ext": audio_output_ext,
                            "source_ext": ext or "unknown",
                            "output_ext": audio_output_ext,
                            "resolution": "",
                            "height": 0,
                            "fps": 0,
                            "vcodec": "none",
                            "acodec": acodec,
                            "filesize": filesize,
                            "filesize_approx": filesize_approx,
                            "sort_bytes": size,
                            "size_source": size_source,
                            "source": source,
                            "protocol": format_protocol(fmt),
                            "is_manifest": is_manifest_format(fmt),
                            "media_type": "audio",
                            "note": str(fmt.get("format_note") or fmt.get("format") or "audio"),
                        }
                    )
                if requested_filter in AUDIO_OUTPUT_EXTENSIONS:
                    continue

            if requested_filter in AUDIO_OUTPUT_EXTENSIONS:
                continue

            if requested_filter and ext != requested_filter:
                continue
            has_video = vcodec.lower() != "none" or ext in VIDEO_EXTENSIONS or safe_int(fmt.get("height")) > 0
            if not has_video or vcodec.lower() == "none":
                continue

            audio_size = 0
            if acodec.lower() == "none" and audio:
                audio_size, _audio_size_source = media_size_for_format(audio, duration)
            sort_bytes, size_source = media_size_for_format(fmt, duration, audio_size)
            filesize, filesize_approx = candidate_filesize_fields(fmt, sort_bytes, size_source)
            selector = format_id or "best"
            if acodec.lower() == "none":
                selector = f"{selector}+bestaudio[ext=m4a]/bestaudio/best"
                acodec = "bestaudio"

            source = video_info.get("webpage_url") or video_info.get("original_url") or info.get("webpage_url") or ""
            key = (source, format_id, fmt.get("url"))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "id": f"{len(candidates) + 1}",
                    "format_id": format_id or "best",
                    "format_selector": selector,
                    "url": fmt.get("url") or source,
                    "title": title,
                    "display_title": display_title,
                    "thumbnail": thumbnail,
                    "duration": duration,
                    "ext": ext or "unknown",
                    "source_ext": ext or "unknown",
                    "output_ext": requested_filter or ext or "mp4",
                    "resolution": resolution_for(fmt),
                    "height": safe_int(fmt.get("height")),
                    "fps": safe_int(fmt.get("fps")),
                    "vcodec": vcodec,
                    "acodec": acodec,
                    "filesize": filesize,
                    "filesize_approx": filesize_approx,
                    "sort_bytes": sort_bytes,
                    "size_source": size_source,
                    "source": source,
                    "protocol": format_protocol(fmt),
                    "is_manifest": is_manifest_format(fmt),
                    "media_type": "video",
                    "note": str(fmt.get("format_note") or fmt.get("format") or ""),
                }
            )

        if not formats and video_info.get("url"):
            if requested_filter in AUDIO_OUTPUT_EXTENSIONS:
                continue
            direct_ext = str(video_info.get("ext") or "unknown").lower()
            if requested_filter and direct_ext != requested_filter:
                continue
            size, size_source = media_size_for_format(video_info, duration)
            filesize, filesize_approx = candidate_filesize_fields(video_info, size, size_source)
            candidates.append(
                {
                    "id": f"{len(candidates) + 1}",
                    "format_id": "best",
                    "format_selector": "best",
                    "url": video_info["url"],
                    "title": title,
                    "display_title": display_title,
                    "thumbnail": thumbnail,
                    "duration": duration,
                    "ext": direct_ext,
                    "source_ext": direct_ext,
                    "output_ext": requested_filter or direct_ext,
                    "resolution": resolution_for(video_info),
                    "height": safe_int(video_info.get("height")),
                    "fps": safe_int(video_info.get("fps")),
                    "vcodec": str(video_info.get("vcodec") or "unknown"),
                    "acodec": str(video_info.get("acodec") or "unknown"),
                    "filesize": filesize,
                    "filesize_approx": filesize_approx,
                    "sort_bytes": size,
                    "size_source": size_source,
                    "source": video_info.get("webpage_url") or video_info["url"],
                    "protocol": format_protocol(video_info),
                    "is_manifest": is_manifest_format(video_info),
                    "media_type": "video",
                    "note": "direct",
                }
            )
    return sort_candidates(candidates)


def build_ydl_options(cookie_source="없음", on_event=None, quiet=True, proxy_url=None, impersonate=False, allow_playlist=False):
    options = {
        "quiet": quiet,
        "no_warnings": quiet,
        "noplaylist": not allow_playlist,
        "http_headers": {
            "User-Agent": USER_AGENT,
            "Accept-Language": ACCEPT_LANGUAGE,
        },
        "logger": EventLogger(on_event),
    }
    spec = cookie_spec(cookie_source)
    if spec:
        options["cookiesfrombrowser"] = spec
    proxy = effective_proxy_url(proxy_url)
    if proxy:
        options["proxy"] = proxy
    bundled_ffmpeg = ffmpeg_path()
    if bundled_ffmpeg:
        options["ffmpeg_location"] = bundled_ffmpeg
    if impersonate:
        target = chrome_impersonation_target()
        if target:
            options["impersonate"] = target
    return options


def build_download_options(candidate, output_dir, cookie_source="없음", on_event=None, proxy_url=None):
    output_dir = output_dir_for_candidate(candidate, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    is_playlist = str((candidate or {}).get("media_type") or "").lower() == "playlist"
    options = build_ydl_options(cookie_source=cookie_source, on_event=on_event, quiet=True, proxy_url=proxy_url, allow_playlist=is_playlist)
    output_ext = normalized_output_ext(candidate.get("output_ext")) or "mp4"
    output_name = "%(playlist_index)s - %(title).200B.%(ext)s" if is_playlist else f"{escape_yt_dlp_template_literal(filename_stem_for_candidate(candidate))}.%(ext)s"
    headers = options.setdefault("http_headers", {})
    if candidate.get("referer"):
        headers["Referer"] = candidate["referer"]
    if candidate.get("origin"):
        headers["Origin"] = candidate["origin"]
    options.update(
        {
            "format": candidate.get("format_selector") or "bestvideo*+bestaudio/best",
            "outtmpl": str(output_dir / output_name),
            "windowsfilenames": True,
            "continuedl": True,
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": 4,
            "progress_hooks": [progress_hook(on_event)],
            "postprocessor_hooks": [postprocessor_hook(on_event)],
        }
    )
    if output_ext in AUDIO_OUTPUT_EXTENSIONS:
        options.update(
            {
                "final_ext": output_ext,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": output_ext}],
            }
        )
    else:
        options.update(
            {
                "format_sort": ["vcodec:h264", "quality", "res", "fps", "hdr:12", "acodec:aac"],
                "merge_output_format": output_ext,
                "final_ext": output_ext,
                "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": output_ext}],
            }
        )
    return options


def progress_hook(on_event=None):
    def hook(data):
        status = data.get("status")
        if status == "downloading":
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            if total:
                percent = max(0, min(100, downloaded * 100 / total))
                speed = (data.get("_speed_str") or "").strip()
                eta = (data.get("_eta_str") or "").strip()
                emit_event(on_event, "progress", percent=percent, message=f"{percent:.1f}% {speed} ETA {eta}".strip())
            else:
                emit_event(on_event, "status", message="Downloading")
        elif status == "finished":
            emit_event(on_event, "status", message="Merging or converting MP4")
            if data.get("filename"):
                emit_event(on_event, "file", path=data["filename"])

    return hook


def postprocessor_hook(on_event=None):
    def hook(data):
        name = data.get("postprocessor") or ""
        if data.get("status") == "started" and name:
            emit_event(on_event, "status", message=f"Running {name}")

    return hook


def find_browser_executable(environ=None, which_func=shutil.which, path_exists=None):
    env = os.environ if environ is None else environ
    if path_exists is None:
        path_exists = lambda path: Path(path).exists()
    home = env.get("HOME") or env.get("USERPROFILE") or str(Path.home())
    path_names = [
        "chrome.exe",
        "msedge.exe",
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "microsoft-edge-stable",
    ]
    candidates = [
        env.get("UMP4_BROWSER_PATH"),
        *[which_func(name) for name in path_names],
        str(Path(env.get("ProgramFiles", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(env.get("ProgramFiles(x86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(env.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(env.get("ProgramFiles", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
        str(Path(env.get("ProgramFiles(x86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        str(Path(home) / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"),
        str(Path(home) / "Applications" / "Microsoft Edge.app" / "Contents" / "MacOS" / "Microsoft Edge"),
        str(Path(home) / "Applications" / "Chromium.app" / "Contents" / "MacOS" / "Chromium"),
    ]
    for candidate in candidates:
        candidate = str(candidate or "")
        if candidate and path_exists(candidate):
            return candidate
    return ""


def clean_browser_dom(dom):
    text = str(dom or "")
    starts = [idx for idx in (text.lower().find("<!doctype"), text.lower().find("<html")) if idx >= 0]
    if starts:
        text = text[min(starts) :]
    return text


def dump_dom_with_browser(url, on_event=None, timeout=90):
    browser = find_browser_executable()
    if not browser:
        raise RuntimeError("Chrome/Edge browser was not found for browser DOM fallback.")
    emit_event(on_event, "status", message="브라우저 DOM 분석 중")
    with tempfile.TemporaryDirectory(prefix="ump4-browser-") as profile_dir:
        command = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-extensions",
            f"--user-data-dir={profile_dir}",
            "--dump-dom",
            url,
        ]
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    dom = clean_browser_dom(completed.stdout)
    if completed.returncode != 0 and not dom:
        raise RuntimeError((completed.stderr or "Browser DOM fallback failed.").strip())
    if not dom:
        raise RuntimeError("Browser DOM fallback returned an empty page.")
    return dom


def extract_json_array_after(text, marker):
    idx = text.find(marker)
    if idx < 0:
        return None
    start = text.find("[", idx)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def media_definitions_from_html(dom):
    text = html_lib.unescape(str(dom or ""))
    raw = extract_json_array_after(text, '"mediaDefinitions"')
    if not raw:
        raw = extract_json_array_after(text, "mediaDefinitions")
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [item for item in data if isinstance(item, dict)]


def player_script_media_from_html(dom):
    text = html_lib.unescape(str(dom or "")).replace("\\/", "/")
    items = []
    for match in re.finditer(
        r"(?:html5player\.)?setVideo(?P<kind>HLS|UrlLow|UrlHigh|URL)\s*\(\s*(?P<quote>['\"])(?P<url>https?://.*?)(?P=quote)\s*\)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        media_url = urllib.parse.unquote(match.group("url")).strip()
        if not media_url:
            continue
        kind = match.group("kind").lower()
        height_match = re.search(r"[_/-](?P<height>\d{3,4})p(?:[_.?/-]|$)", media_url, flags=re.IGNORECASE)
        height = safe_int(height_match.group("height")) if height_match else 0
        if not height and kind == "urllow":
            height = 240
        elif not height and kind == "urlhigh":
            height = 360
        items.append(
            {
                "videoUrl": media_url,
                "format": "hls" if kind == "hls" else "mp4",
                "quality": height or ("hls" if kind == "hls" else kind),
                "height": height,
                "source": "player-script",
            }
        )
    return items


def first_html_match(dom, patterns):
    text = str(dom or "")
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return compact_text(html_lib.unescape(match.group(1)))
    return ""


def title_from_browser_dom(dom):
    return clean_video_title(first_html_match(dom, [r"<title[^>]*>(.*?)</title>"])) or "Browser video"


def thumbnail_from_browser_dom(dom):
    return first_html_match(
        dom,
        [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'setThumbUrl(?:169)?\(\s*["\']([^"\']+)["\']\s*\)',
        ],
    )


def duration_from_browser_dom(dom):
    text = compact_text(html_lib.unescape(str(dom or "")), limit=20000)
    patterns = [
        r"(?:video\s*)?duration\s*[:：]\s*(\d{1,2}:\d{2}(?::\d{2})?)",
        r'<meta[^>]+property=["\']og:video:duration["\'][^>]+content=["\'](\d+)["\']',
        r'<meta[^>]+content=["\'](\d+)["\'][^>]+property=["\']og:video:duration["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1)
        if ":" not in value:
            return safe_int(value)
        parts = [safe_int(part) for part in value.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0


def size_from_browser_dom(dom):
    text = compact_text(html_lib.unescape(str(dom or "")), limit=20000)
    match = re.search(
        r"(?:file\s*)?size\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)\s*(KB|MB|GB|B)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).upper()
    multiplier = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}.get(unit, 1)
    return int(value * multiplier)


def html_attrs(tag):
    attrs = {}
    for match in re.finditer(r"([:\w-]+)\s*=\s*(['\"])(.*?)\2", str(tag or ""), flags=re.DOTALL):
        attrs[match.group(1).lower()] = html_lib.unescape(match.group(3)).strip()
    return attrs


def height_from_media_url(media_url):
    match = re.search(r"(?<!\d)(\d{3,4})p(?!\d)", str(media_url or ""), flags=re.IGNORECASE)
    return safe_int(match.group(1)) if match else 0


def generic_video_media_from_html(dom, base_url):
    text = html_lib.unescape(str(dom or "")).replace("\\/", "/")
    items = []
    duration = duration_from_browser_dom(text)
    page_size = size_from_browser_dom(text)
    for match in re.finditer(r"<video\b(?P<attrs>[^>]*)>(?P<body>.*?)</video>", text, flags=re.IGNORECASE | re.DOTALL):
        video_attrs = html_attrs(match.group("attrs"))
        poster = video_attrs.get("poster") or ""
        sources = []
        if video_attrs.get("src"):
            sources.append((video_attrs.get("src"), video_attrs))
        for source_match in re.finditer(r"<source\b(?P<attrs>[^>]*)>", match.group("body"), flags=re.IGNORECASE | re.DOTALL):
            source_attrs = html_attrs(source_match.group("attrs"))
            if source_attrs.get("src"):
                sources.append((source_attrs.get("src"), source_attrs))
        for media_url, attrs in sources:
            absolute_url = urllib.parse.urljoin(base_url, media_url)
            items.append(
                {
                    "videoUrl": absolute_url,
                    "format": attrs.get("type") or "html-video",
                    "quality": height_from_media_url(absolute_url),
                    "height": height_from_media_url(absolute_url),
                    "width": safe_int(attrs.get("width") or video_attrs.get("width")),
                    "duration": duration,
                    "filesize": page_size,
                    "poster": urllib.parse.urljoin(base_url, poster) if poster else "",
                    "source": "html-video",
                }
            )
    return items


def analyze_browser_dom_media(url, dom, output_ext=None, on_event=None):
    requested_ext = normalized_output_ext(output_ext)
    if requested_ext in AUDIO_OUTPUT_EXTENSIONS:
        raise RuntimeError("Browser DOM fallback does not expose audio-only candidates.")
    if requested_ext == ALL_OUTPUT_EXT:
        requested_ext = None
    title = title_from_browser_dom(dom)
    thumbnail = thumbnail_from_browser_dom(dom)
    fallback_duration = duration_from_browser_dom(dom)
    parsed = urllib.parse.urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    candidates = []
    seen = set()
    for item in [*media_definitions_from_html(dom), *player_script_media_from_html(dom), *generic_video_media_from_html(dom, url)]:
        media_url = item.get("videoUrl") or item.get("url")
        if not media_url:
            continue
        media_url = html_lib.unescape(str(media_url)).replace("\\/", "/")
        lower_url = media_url.lower()
        is_hls = ".m3u8" in lower_url or str(item.get("format") or "").lower() == "hls"
        is_dash = ".mpd" in lower_url
        is_mp4 = ".mp4" in lower_url or is_hls
        if requested_ext and requested_ext not in {"mp4", "webm"}:
            continue
        if requested_ext == "webm" and "webm" not in lower_url:
            continue
        if not (is_hls or is_dash or is_mp4):
            continue
        if media_url in seen:
            continue
        seen.add(media_url)
        height = safe_int(item.get("height") or item.get("quality")) or height_from_media_url(media_url)
        width = safe_int(item.get("width"))
        ext = "webm" if "webm" in lower_url else "mp4"
        source = str(item.get("source") or "media")
        format_label = item.get("format") or source
        quality = item.get("quality") or ""
        duration = safe_int(item.get("duration") or fallback_duration)
        size = safe_int(item.get("filesize") or item.get("filesize_approx"))
        size_source = "metadata" if size else "unknown"
        filesize, filesize_approx = candidate_filesize_fields({"filesize": size, "url": media_url}, size, size_source)
        format_id_label = f"browser-{height}" if height else f"browser-{format_label}"
        candidates.append(
            {
                "id": f"browser-{len(candidates) + 1}",
                "format_id": format_id_label,
                "format_selector": "best",
                "url": media_url,
                "title": title,
                "display_title": title,
                "thumbnail": item.get("poster") or thumbnail,
                "duration": duration,
                "ext": requested_ext or ext,
                "source_ext": ext,
                "output_ext": requested_ext or ext,
                "resolution": f"{width}x{height}" if width and height else (f"{height}p" if height else "unknown"),
                "height": height,
                "fps": 0,
                "vcodec": "unknown",
                "acodec": "unknown",
                "filesize": filesize,
                "filesize_approx": filesize_approx,
                "sort_bytes": size,
                "size_source": size_source,
                "source": url,
                "protocol": "m3u8" if is_hls else ("dash" if is_dash else "https"),
                "is_manifest": is_hls or is_dash,
                "media_type": "video",
                "referer": url,
                "origin": origin,
                "note": f"browser {format_label} {quality}".strip(),
            }
        )
    candidates = sort_candidates(enrich_missing_sizes(candidates))
    if not candidates:
        raise RuntimeError("Browser DOM fallback found no downloadable media entries.")
    return {
        "url": url,
        "webpage_url": url,
        "title": title,
        "source": "browser-dom",
        "candidates": candidates,
        "warnings": [],
    }


def analyze_url(
    url,
    cookie_source="없음",
    ydl_factory=None,
    on_event=None,
    proxy_url=None,
    output_ext=None,
    browser_dom_fetcher=None,
):
    if not str(url or "").strip():
        raise ValueError("URL is required.")
    url = str(url).strip()
    warnings = []

    chzzk = analyze_chzzk_clip(url, on_event=on_event)
    if chzzk:
        return chzzk

    if ydl_factory is None:
        from yt_dlp import YoutubeDL

        ydl_factory = YoutubeDL

    allow_playlist = looks_like_playlist_url(url)

    def extract_with(source, impersonate=False):
        options = build_ydl_options(
            cookie_source=source,
            on_event=on_event,
            quiet=True,
            proxy_url=proxy_url,
            impersonate=impersonate,
            allow_playlist=allow_playlist,
        )
        options.update({"simulate": True, "skip_download": True, "check_formats": False})
        emit_event(on_event, "status", message="URL 분석 중")
        with ydl_factory(options) as ydl:
            return ydl.extract_info(url, download=False)

    info = None
    pending_error = None
    try:
        info = extract_with(cookie_source)
    except Exception as exc:
        pending_error = exc
        if should_retry_with_impersonation(str(exc)) and chrome_impersonation_target():
            warning = "브라우저 지문/TLS 차단 가능성, Chrome 방식으로 재시도: " + str(exc)
            warnings.append(warning)
            emit_event(on_event, "log", message=warning)
            try:
                info = extract_with(cookie_source, impersonate=True)
            except Exception as retry_exc:
                pending_error = retry_exc
        elif cookie_spec(cookie_source):
            warning = "쿠키 읽기 실패, 쿠키 없이 재시도 가능: " + str(exc)
            warnings.append(warning)
            emit_event(on_event, "log", message=warning)
            try:
                info = extract_with("없음")
            except Exception as retry_exc:
                pending_error = retry_exc
                if should_retry_with_impersonation(str(retry_exc)) and chrome_impersonation_target():
                    warning = "브라우저 지문/TLS 차단 가능성, Chrome 방식으로 재시도: " + str(retry_exc)
                    warnings.append(warning)
                    emit_event(on_event, "log", message=warning)
                    try:
                        info = extract_with("없음", impersonate=True)
                    except Exception as impersonate_exc:
                        pending_error = impersonate_exc

    if info is None:
        if pending_error and should_retry_with_impersonation(str(pending_error)):
            try:
                fetcher = browser_dom_fetcher or dump_dom_with_browser
                dom = fetcher(url, on_event=on_event)
                result = analyze_browser_dom_media(url, dom, output_ext=output_ext, on_event=on_event)
                warning = "브라우저 DOM fallback 사용: " + str(pending_error)
                result["warnings"] = [*warnings, warning, *(result.get("warnings") or [])]
                emit_event(on_event, "log", message=warning)
                return result
            except Exception as browser_exc:
                warning = "브라우저 DOM fallback 실패: " + str(browser_exc)
                warnings.append(warning)
                emit_event(on_event, "log", message=warning)
        if pending_error:
            raise pending_error
        raise RuntimeError("URL analysis failed.")

    candidates = sort_candidates(enrich_missing_sizes(candidates_from_info(info, output_ext=output_ext)))
    if not candidates:
        raise RuntimeError("No downloadable non-audio video formats were found.")
    entries = info.get("entries") if isinstance(info, dict) else None
    is_playlist = bool(allow_playlist and entries)
    playlist_title = clean_video_title(info.get("title") or info.get("playlist_title") or "") if isinstance(info, dict) else ""
    return {
        "url": url,
        "webpage_url": info.get("webpage_url") or url,
        "title": clean_video_title(info.get("title") or candidates[0].get("title")) or "video",
        "is_playlist": is_playlist,
        "playlist_title": playlist_title,
        "playlist_count": safe_int(info.get("playlist_count") or info.get("n_entries") or (len(entries) if entries else 0)),
        "candidates": candidates,
        "warnings": warnings,
    }


def download_candidate(page_url, candidate, output_dir, cookie_source="없음", ydl_factory=None, on_event=None, proxy_url=None):
    if ydl_factory is None:
        from yt_dlp import YoutubeDL

        ydl_factory = YoutubeDL

    target_url = candidate.get("source") or page_url or candidate.get("url")
    if candidate.get("format_selector") == "best" and candidate.get("url"):
        target_url = candidate["url"]
    options = build_download_options(candidate, output_dir, cookie_source=cookie_source, on_event=on_event, proxy_url=proxy_url)
    emit_event(on_event, "status", message="Starting download")
    with ydl_factory(options) as ydl:
        ydl.download([target_url])
    emit_event(on_event, "done", path=str(output_dir))
    return {"ok": True, "output_dir": str(output_dir), "target_url": target_url}


def legacy_job_to_candidate(job):
    media_url = job.get("mediaUrl") or job.get("pageUrl")
    return {
        "id": "legacy",
        "format_id": job.get("candidateKind") or "best",
        "format_selector": "best",
        "url": media_url,
        "title": "video",
        "ext": "unknown",
        "resolution": "unknown",
        "height": 0,
        "fps": 0,
        "vcodec": "unknown",
        "acodec": "unknown",
        "filesize": 0,
        "filesize_approx": 0,
        "sort_bytes": 0,
        "duration": 0,
        "output_ext": "mp4",
        "source": job.get("pageUrl") or media_url,
        "note": "legacy",
    }


def download_legacy_job(job, on_event=None):
    candidate = legacy_job_to_candidate(job)
    return download_candidate(
        job.get("pageUrl") or job.get("mediaUrl"),
        candidate,
        job["outputDir"],
        cookie_source=job.get("cookieSource") or "없음",
        proxy_url=job.get("proxyUrl"),
        on_event=on_event,
    )


def write_json(path, payload):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def newest_mp4(output_dir, since=0):
    return newest_file(output_dir, "mp4", since=since)


def newest_file(output_dir, extension, since=0):
    files = []
    ext = str(extension or "mp4").lstrip(".")
    for path in Path(output_dir).glob(f"*.{ext}"):
        if path.stat().st_mtime >= since:
            files.append(path)
    return max(files, key=lambda path: path.stat().st_mtime, default=None)
