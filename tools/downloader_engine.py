import http.client
import json
import os
import re
import html as html_lib
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import queue
import contextlib
import http.server
import urllib.parse
import urllib.error
import urllib.request
import atexit
import concurrent.futures
from pathlib import Path


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7778.167 Safari/537.36"
)
ACCEPT_LANGUAGE = "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
CHZZK_CLIP_RE = re.compile(r"https?://chzzk\.naver\.com/clips/([A-Za-z0-9_-]+)")
CHZZK_VIDEO_RE = re.compile(r"https?://chzzk\.naver\.com/video/(\d+)")
GENERIC_TITLE_RE = re.compile(r"^(?:video(?:\s+\d+)?|post by .+)$", re.IGNORECASE)
TRAILING_DOMAIN_TITLE_RE = re.compile(
    r"\s+(?:-|–|—|\|)\s+(?:www\.)?[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+\s*$",
    re.IGNORECASE,
)
ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+(?:\.\d+)?)D)?(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?(?:(?P<minutes>\d+(?:\.\d+)?)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$",
    re.IGNORECASE,
)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_APPCAST_BYTES = 1 * 1024 * 1024

VIDEO_EXTENSIONS = {"mp4", "m4v", "mov", "webm", "mkv", "flv", "ts"}
AUDIO_OUTPUT_EXTENSIONS = {"mp3", "wav", "aac"}
OUTPUT_EXTENSIONS = {"mp4", "webm"} | AUDIO_OUTPUT_EXTENSIONS
ALL_OUTPUT_EXT = "all"
SIZE_PROBE_LIMIT = 12
DIRECT_MEDIA_PARALLEL_THRESHOLD = 64 * 1024 * 1024
DIRECT_MEDIA_PARALLEL_MIN_SIZE = 2 * 1024 * 1024
DIRECT_MEDIA_PARALLEL_PART_SIZE = 16 * 1024 * 1024
DIRECT_MEDIA_PARALLEL_WORKERS = 4
DIRECT_MEDIA_PROXY_PART_SIZE = 4 * 1024 * 1024
DIRECT_MEDIA_SEGMENT_NO_PROGRESS_TIMEOUT = 30.0
PAGE_THUMBNAIL_TIMEOUT = 8
BROWSER_DOM_MANIFEST_NO_PROGRESS_TIMEOUT = 120.0
BROWSER_DOM_HTML_CACHE_MAX_AGE = 90.0
BROWSER_DOM_HTML_CACHE_DOWNLOAD_MAX_AGE = 300.0
BROWSER_DOM_HLS_PARALLEL_MAX_BYTES = 64 * 1024 * 1024
BROWSER_DOM_HLS_PARALLEL_MAX_SEGMENTS = 240
def _env_int(name, default, minimum=1, maximum=64):
    try:
        return max(minimum, min(maximum, int(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


# HLS parallel: workers = live TCP connections (keep low to avoid CDN throttle).
# max_in_flight = queued futures; can exceed workers to keep the pipeline full.
HLS_PARALLEL_WORKERS = _env_int("CLIPFLOW_HLS_WORKERS", 4, 1, 16)
HLS_PARALLEL_MAX_IN_FLIGHT = _env_int(
    "CLIPFLOW_HLS_MAX_IN_FLIGHT",
    HLS_PARALLEL_WORKERS * 4,
    HLS_PARALLEL_WORKERS,
    128,
)
CHZZK_DIRECT_MEDIA_WORKERS = _env_int("CLIPFLOW_CHZZK_DIRECT_WORKERS", 8, 1, 16)
CHZZK_DIRECT_MEDIA_PART_SIZE = _env_int("CLIPFLOW_CHZZK_DIRECT_PART_MB", 128, 1, 1024) * 1024 * 1024
CHZZK_AUTO_ROUTE_MIN_BYTES = 64 * 1024 * 1024
CHZZK_ROUTE_PROBE_BYTES = _env_int("CLIPFLOW_CHZZK_PROBE_MB", 4, 1, 32) * 1024 * 1024
CHZZK_ROUTE_PROBE_HLS_SEGMENTS = _env_int("CLIPFLOW_CHZZK_PROBE_HLS_SEGMENTS", 3, 1, 8)
CHZZK_ROUTE_PROBE_TIMEOUT = _env_int("CLIPFLOW_CHZZK_PROBE_TIMEOUT_SEC", 12, 3, 30)
CHZZK_ROUTE_LARGE_VOD_BYTES = 10 * 1024 * 1024 * 1024
CHZZK_ROUTE_LONG_VOD_SECONDS = 3600
CHZZK_DIRECT_RANGE_THROTTLE_RATIO = 0.65
HLS_SEGMENT_READ_CHUNK = 1024 * 1024
HLS_PARALLEL_PROGRESS_INTERVAL = 0.25
HLS_SEGMENT_RETRIES = 3
# CHZZK/DASH declared BANDWIDTH is a peak variant rate; measured VOD size is usually lower.
CHZZK_PEAK_BANDWIDTH_SIZE_FACTOR = 0.72
YTDLP_CONCURRENT_FRAGMENT_DOWNLOADS = 16
YTDLP_HTTP_CHUNK_SIZE = 10 * 1024 * 1024
_PARALLEL_HTTP_STATE = threading.local()
_HLS_PARALLEL_PIPELINE_OBSERVER = None
_HLS_PARALLEL_PIPELINE_OBSERVER_LOCK = threading.Lock()
_BROWSER_DOM_HTML_CACHE = {}
COOKIE_SOURCES = {
    "chrome": ("chrome",),
    "google chrome": ("chrome",),
    "chromium": ("chromium",),
    "edge": ("edge",),
    "microsoft edge": ("edge",),
    "firefox": ("firefox",),
    "safari": ("safari",),
    "brave": ("brave",),
    "opera": ("opera",),
    "vivaldi": ("vivaldi",),
    "whale": ("whale",),
}


class DirectMediaRangeUnsupported(RuntimeError):
    pass


class ChzzkDirectSlowFallback(RuntimeError):
    pass
_YOUTUBE_DL_FACTORY = None
_FFMPEG_PATH_UNSET = object()
_FFMPEG_PATH = _FFMPEG_PATH_UNSET


def curl_resolve_entries_for_hostname(hostname, port):
    import socket

    host = str(hostname or "").strip()
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        return []
    port = safe_int(port)
    if not (1 <= port <= 65535):
        return []
    entries = []
    seen = set()
    try:
        for _, _, _, _, sockaddr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
            ip = str(sockaddr[0] or "")
            if not ip or "%" in ip:
                continue
            entry = f"{host}:{port}:{ip}"
            if entry in seen:
                continue
            seen.add(entry)
            entries.append(entry)
    except OSError:
        return []
    return entries


def curl_resolve_entries_for_url(url):
    from urllib.parse import urlparse

    parsed = urlparse(str(url or ""))
    host = parsed.hostname
    if not host:
        return []
    if parsed.port:
        port = parsed.port
    elif parsed.scheme == "http":
        port = 80
    else:
        port = 443
    return curl_resolve_entries_for_hostname(host, port)


def apply_curl_cffi_system_dns_patch():
    try:
        from curl_cffi.const import CurlOpt
        from yt_dlp.networking import _curlcffi as curlcffi_mod
    except ImportError:
        return False

    original_send = curlcffi_mod.CurlCFFIRH._send
    if getattr(original_send, "_ump4_system_dns_patched", False):
        return True

    def _send_with_system_dns(self, request):
        entries = curl_resolve_entries_for_url(request.url)
        if not entries:
            return original_send(self, request)
        original_get_instance = self._get_instance

        def get_instance_with_system_dns(*args, **kwargs):
            session = original_get_instance(*args, **kwargs)
            session.curl.setopt(CurlOpt.RESOLVE, entries)
            return session

        self._get_instance = get_instance_with_system_dns
        try:
            return original_send(self, request)
        finally:
            self._get_instance = original_get_instance

    _send_with_system_dns._ump4_system_dns_patched = True
    curlcffi_mod.CurlCFFIRH._send = _send_with_system_dns
    return True


def youtube_dl_factory():
    global _YOUTUBE_DL_FACTORY
    if _YOUTUBE_DL_FACTORY is None:
        from yt_dlp import YoutubeDL

        apply_curl_cffi_system_dns_patch()
        _YOUTUBE_DL_FACTORY = YoutubeDL
    return _YOUTUBE_DL_FACTORY


def yt_dlp_windows_version():
    try:
        from yt_dlp.utils import _utils

        return _utils.get_windows_version()
    except Exception:
        return ()


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text):
    return ANSI_ESCAPE_RE.sub("", str(text or ""))


def emit_event(callback, event_type, **payload):
    if "message" in payload:
        payload["message"] = strip_ansi(payload["message"])
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
    global _FFMPEG_PATH
    if _FFMPEG_PATH is not _FFMPEG_PATH_UNSET:
        return _FFMPEG_PATH
    try:
        import imageio_ffmpeg

        _FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        _FFMPEG_PATH = None
    return _FFMPEG_PATH


def ffprobe_path():
    ffmpeg = ffmpeg_path()
    if ffmpeg:
        probe = Path(ffmpeg).with_name("ffprobe" + (".exe" if os.name == "nt" else ""))
        if probe.exists():
            return str(probe)
    return shutil.which("ffprobe")


def _browser_dom_cache_key(url):
    return str(url or "").strip().rstrip("/")


def remember_browser_dom_html(url, html):
    key = _browser_dom_cache_key(url)
    text = clean_browser_dom(html)
    if not key or not dom_html_looks_usable(text):
        return
    _BROWSER_DOM_HTML_CACHE[key] = (time.monotonic(), text)


def browser_dom_html_cached(url, max_age=None):
    key = _browser_dom_cache_key(url)
    entry = _BROWSER_DOM_HTML_CACHE.get(key)
    if not entry:
        return None
    fetched_at, html = entry
    age_limit = BROWSER_DOM_HTML_CACHE_MAX_AGE if max_age is None else float(max_age)
    if time.monotonic() - fetched_at > age_limit:
        _BROWSER_DOM_HTML_CACHE.pop(key, None)
        return None
    return html


def probe_stream_duration(url, candidate=None):
    probe = ffprobe_path()
    if not probe:
        return 0
    headers = direct_media_request_headers(candidate or {})
    header_arg = "".join(f"{key}: {value}\r\n" for key, value in headers.items())
    command = [
        probe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
    ]
    if header_arg:
        command.extend(["-headers", header_arg])
    command.append(str(url or ""))
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=30,
        )
        return safe_int(float(str(completed.stdout or "").strip()))
    except (OSError, subprocess.CalledProcessError, ValueError, subprocess.TimeoutExpired):
        return 0


def probe_video_resolution(path):
    probe = ffprobe_path()
    if not probe:
        return 0, 0
    command = [
        probe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0",
        str(path),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return 0, 0
    parts = [part.strip() for part in str(completed.stdout or "").split(",") if part.strip()]
    if len(parts) < 2:
        return 0, 0
    return safe_int(parts[0]), safe_int(parts[1])


def ffmpeg_path_for_yt_dlp(ffmpeg_exe=None, cache_dir=None):
    value = ffmpeg_exe or ffmpeg_path()
    if not value:
        return None
    source = Path(value)
    standard_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if source.name.lower() == standard_name:
        return str(source)
    if cache_dir is None:
        root = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "ClipFlow" / "bin"
    else:
        root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / standard_name
    try:
        if target.exists() and source.exists() and target.stat().st_size == source.stat().st_size:
            return str(target)
    except OSError:
        pass
    try:
        if target.exists():
            target.unlink()
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)
    try:
        target.chmod(target.stat().st_mode | 0o111)
    except OSError:
        pass
    return str(target)


@contextlib.contextmanager
def yt_dlp_ffmpeg_path_context(options):
    ffmpeg_exe = (options or {}).get("external_downloader") or (options or {}).get("ffmpeg_location")
    if not ffmpeg_exe:
        yield
        return
    ffmpeg_dir = str(Path(ffmpeg_exe).parent)
    original = os.environ.get("PATH", "")
    parts = [part for part in original.split(os.pathsep) if part]
    if any(os.path.normcase(part) == os.path.normcase(ffmpeg_dir) for part in parts):
        yield
        return
    os.environ["PATH"] = ffmpeg_dir + (os.pathsep + original if original else "")
    try:
        yield
    finally:
        os.environ["PATH"] = original


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


def cookiesfrombrowser_spec(cookie_source):
    spec = cookie_spec(cookie_source)
    if not spec:
        return None
    browser_key = spec[0]
    profiles = browser_cookie_profile_dirs(browser_key)
    if len(profiles) == 1:
        return (browser_key, str(profiles[0]))
    return spec


def cookiesfile_from_env():
    cookie_file = str(os.environ.get("CLIPFLOW_COOKIES_FILE") or os.environ.get("UMP4_COOKIES_FILE") or "").strip()
    if not cookie_file:
        return None
    path = Path(cookie_file).expanduser()
    return str(path) if path.is_file() else None


CHZZK_COOKIE_DOMAIN_KEYWORDS = ("naver", "chzzk")


def cookie_header_from_jar(cookie_jar, domain_keywords=CHZZK_COOKIE_DOMAIN_KEYWORDS):
    if not cookie_jar:
        return ""
    pairs = {}
    keywords = tuple(str(keyword or "").lower() for keyword in (domain_keywords or ()) if str(keyword or "").strip())
    for cookie in cookie_jar:
        domain = str(getattr(cookie, "domain", "") or "").lower()
        if keywords and not any(keyword in domain for keyword in keywords):
            continue
        name = getattr(cookie, "name", None)
        value = getattr(cookie, "value", None)
        if name and value is not None:
            pairs[str(name)] = str(value)
    return "; ".join(f"{name}={value}" for name, value in pairs.items())


def load_cookie_jar(cookie_source):
    cookie_file = cookiesfile_from_env()
    if cookie_file:
        from http.cookiejar import MozillaCookieJar

        jar = MozillaCookieJar(cookie_file)
        jar.load(ignore_discard=True, ignore_expires=True)
        return jar
    spec = cookiesfrombrowser_spec(cookie_source)
    if not spec:
        return None
    from yt_dlp.cookies import extract_cookies_from_browser

    browser = spec[0]
    profile = spec[2] if len(spec) > 2 else None
    return extract_cookies_from_browser(browser, profile)


def cookie_header_for_source(cookie_source):
    try:
        jar = load_cookie_jar(cookie_source)
    except Exception:
        return ""
    return cookie_header_from_jar(jar)


def candidate_with_request_cookies(candidate, cookie_source):
    cookie_header = cookie_header_for_source(cookie_source)
    if not cookie_header:
        return candidate
    prepared = dict(candidate or {})
    prepared["_cookie_header"] = cookie_header
    return prepared


def browser_cookie_error(exc):
    text = str(exc or "").lower()
    return (
        "failed to decrypt with dpapi" in text
        or "could not decrypt" in text and "cookie" in text
        or "could not copy chrome cookie database" in text
        or "could not find" in text and "cookies database" in text
        or "browser cookies" in text and "decrypt" in text
    )


def should_retry_with_browser_cookies(message):
    lower = str(message or "").lower()
    return any(
        token in lower
        for token in (
            "empty media response",
            "instagram api is not granting access",
            "use --cookies-from-browser",
            "login required",
        )
    ) or ("cookies" in lower and "authentication" in lower)


def browser_cookie_profile_dirs(browser_key):
    home = Path.home()
    mapping = {
        "chrome": home / "Library/Application Support/Google/Chrome",
        "chromium": home / "Library/Application Support/Chromium",
        "edge": home / "Library/Application Support/Microsoft Edge",
        "brave": home / "Library/Application Support/BraveSoftware/Brave-Browser",
        "opera": home / "Library/Application Support/com.operasoftware.Opera",
        "vivaldi": home / "Library/Application Support/Vivaldi",
        "firefox": home / "Library/Application Support/Firefox/Profiles",
        "safari": home / "Library/Cookies",
    }
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA") or "")
        mapping = {
            "chrome": local / "Google/Chrome/User Data",
            "chromium": local / "Chromium/User Data",
            "edge": local / "Microsoft/Edge/User Data",
            "brave": local / "BraveSoftware/Brave-Browser/User Data",
            "opera": local / "Opera Software/Opera Stable",
            "vivaldi": local / "Vivaldi/User Data",
            "firefox": Path(os.environ.get("APPDATA") or "") / "Mozilla/Firefox/Profiles",
            "safari": None,
        }
    base = mapping.get(str(browser_key or "").strip().lower())
    if not base:
        return []
    if browser_key == "firefox":
        if not base.exists():
            return []
        return [path for path in base.glob("*") if path.is_dir()]
    if browser_key == "safari":
        cookie_file = base / "Cookies.binarycookies"
        return [base] if cookie_file.exists() else []
    if not base.exists():
        return []
    profiles = [path for path in base.glob("Profile *") if (path / "Cookies").exists()]
    default = base / "Default"
    if (default / "Cookies").exists():
        profiles.insert(0, default)
    return profiles


def browser_cookie_db_available(browser_key):
    return bool(browser_cookie_profile_dirs(browser_key))


def macos_full_disk_access_hint(app_name="ClipFlow"):
    name = str(app_name or "ClipFlow")
    return (
        f"‘전체 디스크 접근 열기’를 누르면 시스템 설정이 열리고 목록에 {name}이(가) 추가돼요. "
        "스위치만 켜고 다시 시도하세요."
    )


def full_disk_access_provoke_paths(cookie_source=None):
    if sys.platform != "darwin":
        return []
    home = Path.home()
    paths = []
    source_key = str(cookie_source or "chrome").strip().lower()
    for profile_dir in browser_cookie_profile_dirs(source_key):
        cookie_path = profile_dir / "Cookies"
        if cookie_path.exists():
            paths.append(str(cookie_path))
    if source_key == "firefox":
        for profile_dir in browser_cookie_profile_dirs("firefox"):
            for name in ("cookies.sqlite", "cookies.sqlite-wal"):
                cookie_path = profile_dir / name
                if cookie_path.exists():
                    paths.append(str(cookie_path))
    if source_key == "safari":
        cookie_path = home / "Library/Cookies/Cookies.binarycookies"
        if cookie_path.exists():
            paths.append(str(cookie_path))
    for fallback in (
        home / "Library/Application Support/Google/Chrome/Default/Cookies",
        home / "Library/Cookies/Cookies.binarycookies",
        home / "Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies",
        home / "Library/Safari/Bookmarks.plist",
    ):
        text = str(fallback)
        if fallback.exists() and text not in paths:
            paths.append(text)
    return paths


def provoke_macos_full_disk_access_registration(cookie_source=None):
    for path in full_disk_access_provoke_paths(cookie_source):
        try:
            with open(path, "rb") as handle:
                handle.read(1)
        except Exception:
            continue


def browser_cookie_sources_for_retry(preferred=None):
    order = []
    preferred_key = str(preferred or "").strip().lower()
    if preferred_key and preferred_key not in {"none", "no", "없음"} and preferred_key in COOKIE_SOURCES:
        order.append(preferred_key)
    for key in ("chrome", "chromium", "edge", "brave", "firefox", "safari", "opera", "vivaldi"):
        if key not in order:
            order.append(key)
    return [key for key in order if browser_cookie_db_available(key)]


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
    if any(
        token in lower
        for token in [
            "connectionreseterror",
            "connection was reset",
            "curl: (35)",
            "forcibly closed",
            "ssl: unexpected_eof",
            "unexpected_eof_while_reading",
            "ssl_connect",
            "ssl error",
            "tls connect error",
        ]
    ):
        return "브라우저 지문/TLS 차단 가능성"
    if "451" in lower or "unavailable for legal reasons" in lower:
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


# File browsers disagree on the size base: Windows Explorer uses binary units
# (1024) but labels them "KB/MB/GB", while macOS Finder (since 10.6) uses
# decimal (1000). Match whichever host we run on so the app's number lines up
# with what the user sees in their own file browser.
SIZE_UNIT_BASE = 1024 if sys.platform.startswith("win") else 1000


def display_size(num_bytes):
    size = safe_int(num_bytes)
    if not size:
        return "unknown"
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < SIZE_UNIT_BASE or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= SIZE_UNIT_BASE
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


def parse_timecode(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("-"):
        raise ValueError("구간 시간은 0 이상이어야 합니다.")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError("시간 형식은 HH:MM:SS 또는 MM:SS로 입력하세요.")
    try:
        values = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError("시간은 숫자로 입력하세요.") from exc
    if any(part < 0 for part in values):
        raise ValueError("구간 시간은 0 이상이어야 합니다.")
    if len(values) == 1:
        return values[0]
    if any(part >= 60 for part in values[1:]):
        raise ValueError("분과 초는 59 이하로 입력하세요.")
    total = 0.0
    for part in values:
        total = total * 60 + part
    return total


def normalize_clip_range(start_text, end_text, duration=0):
    start = parse_timecode(start_text)
    end = parse_timecode(end_text)
    if start is None and end is None:
        return None
    start = float(start or 0)
    if end is not None:
        end = float(end)
        duration = safe_int(duration)
        if duration and end > duration:
            end = float(duration)
        if end <= start:
            raise ValueError("종료구간은 시작구간보다 뒤여야 합니다.")
    return {"start": float(start), "end": end}


def clip_range_from_candidate(candidate):
    clip_range = (candidate or {}).get("clip_range")
    if not isinstance(clip_range, dict):
        return None
    start = clip_range.get("start")
    end = clip_range.get("end")
    try:
        source_duration = (candidate or {}).get("source_duration") or (candidate or {}).get("duration") or 0
        normalized = normalize_clip_range(start, end, duration=source_duration)
    except ValueError:
        return None
    return normalized


def format_timecode_for_filename(seconds):
    seconds = max(0, int(float(seconds or 0)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}h{minutes:02d}m{secs:02d}s"
    return f"{minutes:02d}m{secs:02d}s"


def clip_range_suffix(clip_range):
    if not isinstance(clip_range, dict):
        return ""
    try:
        normalized = normalize_clip_range(clip_range.get("start"), clip_range.get("end"))
    except ValueError:
        return ""
    if not normalized:
        return ""
    start = format_timecode_for_filename(normalized["start"])
    end = normalized.get("end")
    end_text = format_timecode_for_filename(end) if end is not None else "end"
    return f"[{start}-{end_text}]"


def title_with_clip_range_suffix(title, clip_range):
    text = str(title or "").strip()
    suffix = clip_range_suffix(clip_range)
    if not suffix:
        return text
    if text.endswith(suffix):
        return text
    return f"{text} {suffix}".strip()


def clip_cut_mode(candidate):
    return "accurate" if str((candidate or {}).get("clip_cut_mode") or "").lower() == "accurate" else "fast"


def ffmpeg_progress_speed_label(speed_text, cut_mode="fast"):
    text = str(speed_text or "").strip()
    if not text:
        return ""
    if text.endswith("x"):
        return f"{'정확 컷 처리' if cut_mode == 'accurate' else '처리'} {text}"
    return text


def candidate_with_clip_range_metadata(candidate):
    prepared = dict(candidate or {})
    clip_range = clip_range_from_candidate(prepared)
    if not clip_range:
        return prepared
    prepared["clip_range"] = clip_range
    for key in ("title", "display_title"):
        value = prepared.get(key)
        if value:
            prepared[key] = title_with_clip_range_suffix(value, clip_range)
    if not prepared.get("display_title") and prepared.get("title"):
        prepared["display_title"] = prepared["title"]
    if not prepared.get("title") and prepared.get("display_title"):
        prepared["title"] = prepared["display_title"]

    original_duration = safe_int((candidate or {}).get("duration"))
    if original_duration and not prepared.get("source_duration"):
        prepared["source_duration"] = original_duration
    start = float(clip_range.get("start") or 0)
    end = clip_range.get("end")
    clip_duration = 0
    if end is not None:
        clip_duration = max(0, int(round(float(end) - start)))
    elif original_duration and start < original_duration:
        clip_duration = max(0, int(round(original_duration - start)))
    if clip_duration:
        prepared["duration"] = clip_duration

    original_size = candidate_expected_size(candidate)
    if original_size and not prepared.get("source_filesize"):
        prepared["source_filesize"] = original_size
    if original_size and original_duration and clip_duration:
        estimated = max(1, int(round(original_size * min(clip_duration, original_duration) / original_duration)))
        prepared["sort_bytes"] = estimated
        if safe_int((candidate or {}).get("filesize")):
            prepared["filesize"] = estimated
            prepared["filesize_approx"] = 0
        else:
            prepared["filesize"] = 0
            prepared["filesize_approx"] = estimated
        prepared["size_source"] = "clip_estimate"
    return prepared


def filename_stem_for_candidate(candidate):
    title = clean_video_title(candidate.get("display_title") or candidate.get("title") or "video")
    title = title_with_clip_range_suffix(title, (candidate or {}).get("clip_range"))
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


def final_output_path_for_candidate(candidate, output_dir):
    if str((candidate or {}).get("media_type") or "").lower() == "playlist":
        return None
    output_ext = normalized_output_ext((candidate or {}).get("output_ext")) or "mp4"
    return output_dir_for_candidate(candidate, output_dir) / f"{filename_stem_for_candidate(candidate)}.{output_ext}"


def candidate_expected_size(candidate):
    return safe_int(
        (candidate or {}).get("sort_bytes")
        or (candidate or {}).get("filesize")
        or (candidate or {}).get("filesize_approx")
    )


def completed_output_exists(path, candidate):
    if not path or not path.exists():
        return False
    try:
        return path.stat().st_size > 0
    except OSError:
        return False


def output_is_too_small_for_candidate(path, candidate, min_ratio=0.2):
    expected_size = candidate_expected_size(candidate)
    if not expected_size or expected_size < 1024 * 1024:
        return False
    try:
        actual_size = path.stat().st_size
    except OSError:
        return True
    return actual_size < expected_size * min_ratio


def existing_output_path_for_candidate(candidate, output_dir):
    output_path = final_output_path_for_candidate(candidate, output_dir)
    if completed_output_exists(output_path, candidate) and not output_is_too_small_for_candidate(output_path, candidate):
        return output_path
    return None


def remove_too_small_existing_output(candidate, output_dir, on_event=None):
    output_path = final_output_path_for_candidate(candidate, output_dir)
    if not completed_output_exists(output_path, candidate) or not output_is_too_small_for_candidate(output_path, candidate):
        return False
    try:
        output_path.unlink()
    except OSError as exc:
        emit_event(on_event, "status", message=f"Could not replace partial file: {exc}")
        return False
    emit_event(on_event, "status", message=f"Replacing partial file: {output_path.name}")
    return True


def partial_output_paths_for_target(output_path):
    output_path = Path(output_path).expanduser()
    part_path = output_path.with_name(output_path.name + ".part")
    paths = [
        part_path,
        part_path.with_suffix(part_path.suffix + ".media"),
        output_path.with_name(output_path.stem + ".trim.part" + output_path.suffix),
    ]
    if part_path.name:
        prefix = part_path.name + "."
        for sibling in part_path.parent.iterdir():
            if sibling.is_file() and sibling.name.startswith(prefix):
                paths.append(sibling)
    unique = []
    seen = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def cleanup_partial_output_files(output_path, on_event=None):
    removed = []
    errors = []
    for path in partial_output_paths_for_target(output_path):
        try:
            if path.is_file():
                path.unlink()
                removed.append(path.name)
        except OSError as exc:
            errors.append(f"{path.name}: {exc}")
    if removed:
        emit_event(on_event, "log", message=f"Removed stale partial files: {', '.join(removed)}")
    if errors:
        emit_event(on_event, "status", message=f"Could not remove partial files: {'; '.join(errors)}")
    return bool(removed) and not errors


def terminate_process_tree(process, timeout=2.0):
    if process is None:
        return
    poll = getattr(process, "poll", None)
    if callable(poll) and poll() is not None:
        return
    pid = safe_int(getattr(process, "pid", 0))
    if os.name == "nt" and pid > 0:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=_download_worker_creationflags(),
        )
        wait = getattr(process, "wait", None)
        if callable(wait):
            try:
                wait(timeout=timeout)
            except (subprocess.TimeoutExpired, TypeError):
                try:
                    wait()
                except Exception:
                    pass
        return
    terminate = getattr(process, "terminate", None)
    if callable(terminate):
        try:
            terminate()
        except Exception:
            pass
    wait = getattr(process, "wait", None)
    if callable(wait):
        try:
            wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill = getattr(process, "kill", None)
            if callable(kill):
                try:
                    kill()
                except Exception:
                    pass
            try:
                wait(timeout=timeout)
            except Exception:
                pass
        except TypeError:
            try:
                wait()
            except Exception:
                pass


def run_ffmpeg_command(command, timeout=900, error_label="ffmpeg failed"):
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **_hidden_subprocess_kwargs(),
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        terminate_process_tree(process)
        raise RuntimeError(f"{error_label}: timed out after {int(timeout)}s") from exc
    if process.returncode != 0:
        message = (stderr or stdout or error_label).strip()
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="replace")
        raise RuntimeError(str(message))
    return stdout, stderr


def convert_existing_media_to_audio(input_path, output_ext, output_dir=None, on_event=None, ffmpeg_exe=None, runner=None):
    input_path = Path(input_path).expanduser()
    if not input_path.is_file():
        raise FileNotFoundError(f"Source file not found: {input_path}")

    ext = normalized_output_ext(output_ext)
    if ext not in AUDIO_OUTPUT_EXTENSIONS:
        raise ValueError(f"Unsupported audio output extension: {output_ext}")

    output_dir = Path(output_dir).expanduser() if output_dir else input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{input_path.stem}.{ext}"
    result = {"ok": True, "output_dir": str(output_dir), "output_path": str(output_path)}

    if output_path == input_path or completed_output_exists(output_path, {"output_ext": ext}):
        emit_event(on_event, "status", message=f"File already exists: {output_path.name}")
        emit_event(on_event, "file", path=str(output_path))
        emit_event(on_event, "done", path=str(output_path))
        return result

    ffmpeg_exe = ffmpeg_exe or ffmpeg_path() or shutil.which("ffmpeg")
    if not ffmpeg_exe:
        raise RuntimeError("ffmpeg is required for audio extraction")

    command = [str(ffmpeg_exe), "-y", "-i", str(input_path), "-vn", str(output_path)]
    emit_event(on_event, "status", message="Extracting audio")
    completed = (runner or subprocess.run)(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_hidden_subprocess_kwargs(),
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "ffmpeg audio extraction failed").strip()
        raise RuntimeError(message)

    emit_event(on_event, "file", path=str(output_path))
    emit_event(on_event, "done", path=str(output_path))
    return result


def extract_existing_media_segment(input_path, candidate, output_dir=None, on_event=None, ffmpeg_exe=None, runner=None):
    input_path = Path(input_path).expanduser()
    if not input_path.is_file():
        raise FileNotFoundError(f"Source file not found: {input_path}")
    clip_range = clip_range_from_candidate(candidate)
    if not clip_range:
        raise RuntimeError("Clip range is required for segment extraction")
    output_dir = Path(output_dir).expanduser() if output_dir else input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = final_output_path_for_candidate(candidate, output_dir)
    if output_path is None:
        raise RuntimeError("Segment output path could not be determined.")
    result = {"ok": True, "output_dir": str(output_dir), "output_path": str(output_path)}
    if completed_output_exists(output_path, candidate):
        emit_event(on_event, "status", message=f"File already exists: {output_path.name}")
        emit_event(on_event, "file", path=str(output_path))
        emit_event(on_event, "done", path=str(output_path))
        return result

    ffmpeg_exe = ffmpeg_exe or ffmpeg_path() or shutil.which("ffmpeg")
    if not ffmpeg_exe:
        raise RuntimeError("ffmpeg is required for segment extraction")

    part_path = output_path.with_name(output_path.name + ".part")
    start = float(clip_range["start"])
    end = clip_range.get("end")
    duration = float(end - start) if end is not None else 0
    output_format = normalized_output_ext((candidate or {}).get("output_ext")) or input_path.suffix.lstrip(".") or "mp4"
    command = [str(ffmpeg_exe), "-y", "-hide_banner"]
    if clip_cut_mode(candidate) == "accurate":
        command += ["-i", str(input_path), "-ss", str(start)]
    else:
        command += ["-ss", str(start), "-i", str(input_path)]
    if duration:
        command += ["-t", str(duration)]
    command += ["-map", "0"]
    if clip_cut_mode(candidate) == "accurate":
        command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k"]
    else:
        command += ["-c", "copy"]
    command += ["-movflags", "+faststart", "-f", output_format, str(part_path)]
    emit_event(on_event, "status", message="Extracting selected segment")
    completed = (runner or subprocess.run)(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_hidden_subprocess_kwargs(),
    )
    if completed.returncode != 0:
        try:
            part_path.unlink()
        except OSError:
            pass
        message = (completed.stderr or completed.stdout or "ffmpeg segment extraction failed").strip()
        raise RuntimeError(message)
    if not completed_output_exists(part_path, candidate):
        raise RuntimeError("ffmpeg segment extraction produced no output")
    part_path.replace(output_path)
    emit_event(on_event, "progress", percent=100, message="100.0%")
    emit_event(on_event, "file", path=str(output_path))
    emit_event(on_event, "done", path=str(output_path))
    return result


def escape_yt_dlp_template_literal(value):
    return str(value).replace("%", "%%")


def looks_like_playlist_url(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    path = parsed.path.lower()
    query = urllib.parse.parse_qs(parsed.query)
    if is_youtube_radio_watch_url(parsed, query):
        return False
    if is_youtube_short_video_url(parsed) and youtube_playlist_id(parsed, query).upper().startswith("RD"):
        return False
    if any(str(value or "").strip() for value in query.get("list", [])):
        return True
    return "playlist" in path


def is_youtube_short_video_url(url_or_parsed):
    parsed = url_or_parsed if isinstance(url_or_parsed, urllib.parse.ParseResult) else urllib.parse.urlparse(str(url_or_parsed or ""))
    host = parsed.netloc.lower().removeprefix("www.")
    return host == "youtu.be" and bool(parsed.path.strip("/"))


def youtube_video_id(url_or_parsed, query=None):
    parsed = url_or_parsed if isinstance(url_or_parsed, urllib.parse.ParseResult) else urllib.parse.urlparse(str(url_or_parsed or ""))
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.strip("/")
    query = query if query is not None else urllib.parse.parse_qs(parsed.query)
    if host == "youtu.be" and path:
        return path.split("/", 1)[0]
    if host in {"youtube.com", "m.youtube.com"} and parsed.path.lower() == "/watch":
        return next((str(value or "").strip() for value in query.get("v", []) if str(value or "").strip()), "")
    return ""


def youtube_playlist_id(url_or_parsed, query=None):
    parsed = url_or_parsed if isinstance(url_or_parsed, urllib.parse.ParseResult) else urllib.parse.urlparse(str(url_or_parsed or ""))
    query = query if query is not None else urllib.parse.parse_qs(parsed.query)
    return next((str(value or "").strip() for value in query.get("list", []) if str(value or "").strip()), "")


def needs_youtube_playlist_choice(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    query = urllib.parse.parse_qs(parsed.query)
    return bool(youtube_video_id(parsed, query) and youtube_playlist_id(parsed, query))


def youtube_single_video_url(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    query = urllib.parse.parse_qs(parsed.query)
    video_id = youtube_video_id(parsed, query)
    if not video_id:
        return str(url or "")
    host = parsed.netloc.lower().removeprefix("www.")
    if host == "youtu.be":
        return urllib.parse.urlunparse((parsed.scheme or "https", "youtu.be", f"/{video_id}", "", "", ""))
    return strip_playlist_query(url)


def youtube_playlist_url(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    query = urllib.parse.parse_qs(parsed.query)
    playlist_id = youtube_playlist_id(parsed, query)
    if not playlist_id:
        return str(url or "")
    return urllib.parse.urlunparse(("https", "www.youtube.com", "/playlist", "", urllib.parse.urlencode({"list": playlist_id}), ""))


def is_youtube_radio_watch_url(url_or_parsed, query=None):
    parsed = url_or_parsed if isinstance(url_or_parsed, urllib.parse.ParseResult) else urllib.parse.urlparse(str(url_or_parsed or ""))
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in {"youtube.com", "m.youtube.com"}:
        return False
    if parsed.path.lower() != "/watch":
        return False
    query = query if query is not None else urllib.parse.parse_qs(parsed.query)
    if not any(str(value or "").strip() for value in query.get("v", [])):
        return False
    list_id = next((str(value or "").strip() for value in query.get("list", []) if str(value or "").strip()), "")
    return bool(query.get("start_radio")) or list_id.upper().startswith("RD")


def playlist_identity_key(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    query = urllib.parse.parse_qs(parsed.query)
    list_values = [str(value or "").strip() for value in query.get("list", [])]
    playlist_id = next((value for value in list_values if value), "")
    if playlist_id:
        host = parsed.netloc.lower().removeprefix("www.")
        return f"{host}:list:{playlist_id}"
    normalized = urllib.parse.urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower().removeprefix("www."),
            parsed.path.rstrip("/").lower(),
            "",
            "",
            "",
        )
    )
    return normalized


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


YOUTUBE_THUMBNAIL_AREAS = {
    "maxresdefault": 1280 * 720,
    "sddefault": 640 * 480,
    "hqdefault": 480 * 360,
    "mqdefault": 320 * 180,
    "default": 120 * 90,
}
YOUTUBE_THUMBNAIL_NAME_SCORES = (
    ("maxresdefault", 5),
    ("sddefault", 4),
    ("hqdefault", 3),
    ("mqdefault", 2),
    ("default", 1),
)
THUMBNAIL_URL_FORMAT_SCORES = (
    (".avif", 0),
    (".jpg", 3),
    (".jpeg", 3),
    (".png", 3),
    (".webp", 2),
)


def thumbnail_url_format_score(url):
    path = urllib.parse.urlsplit(str(url or "")).path.lower()
    for ext, score in THUMBNAIL_URL_FORMAT_SCORES:
        if path.endswith(ext):
            return score
    return 1


def youtube_thumbnail_name_score(url):
    text = str(url or "")
    if "i.ytimg.com/" not in text:
        return 0
    path = urllib.parse.urlsplit(text).path.lower()
    if "/vi_lc/" in path:
        return -1
    best = 0
    for name, score in YOUTUBE_THUMBNAIL_NAME_SCORES:
        if f"/{name}." in path:
            best = max(best, score)
    if "/vi/" in path and best == 0:
        best = 3
    elif "/vi_webp/" in path:
        best = max(best, 2)
    return best


def thumbnail_item_area(item):
    width = safe_int((item or {}).get("width"))
    height = safe_int((item or {}).get("height"))
    url = str((item or {}).get("url") or "")
    if width > 0 and height > 0:
        if width >= 1280 and height >= 720 and width * height >= 1920 * 1080:
            return 0
        return width * height
    path = urllib.parse.urlsplit(url).path.lower()
    for name, area in YOUTUBE_THUMBNAIL_AREAS.items():
        if f"/{name}." in path:
            return area
    return 0


def thumbnail_variant_tier_score(url):
    match = re.search(r"(\d+)_([tp])\.(jpg|jpeg|png|webp|avif)\b", str(url or ""), re.IGNORECASE)
    if not match:
        return 0, 0
    tier = safe_int(match.group(1))
    if match.group(2).lower() == "p":
        return tier, -2
    return tier, 2


def _upgrade_thumbnail_tier_url(url):
    text = str(url or "").strip()
    if not text:
        return text
    tier_match = re.search(r"(\d+)_t\.(jpg|jpeg)\b", text, re.IGNORECASE)
    if tier_match and safe_int(tier_match.group(1)) < 30:
        return re.sub(r"(\d+)_t\.(jpg|jpeg)\b", r"30_t.\2", text, count=1, flags=re.IGNORECASE)
    if re.search(r"\d+_p\.avif\b", text, re.IGNORECASE):
        return re.sub(r"\d+_p\.avif\b", "30_t.jpg", text, flags=re.IGNORECASE)
    return text


def thumbnail_from_info(info):
    if not isinstance(info, dict):
        return ""
    thumbnails = info.get("thumbnails") or []
    usable = [item for item in thumbnails if isinstance(item, dict) and item.get("url")]
    if info.get("thumbnail"):
        usable.append({"url": info["thumbnail"], "id": "primary"})
    if not usable:
        return ""

    def score(item):
        url = str(item.get("url") or "")
        role_score, tier_score = thumbnail_variant_tier_score(url)
        return (
            thumbnail_url_format_score(url),
            youtube_thumbnail_name_score(url),
            role_score,
            tier_score,
            thumbnail_item_area(item),
        )

    best = sorted(usable, key=score, reverse=True)[0]
    return _upgrade_thumbnail_tier_url(str(best.get("url") or ""))


LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
HTML_ATTR_RE = re.compile(r"""([:\w-]+)\s*=\s*("[^"]*"|'[^']*'|[^\s"'=<>`]+)""", re.IGNORECASE)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".ico", ".gif", ".svg"}


def _html_tag_attributes(tag):
    attributes = {}
    for key, raw_value in HTML_ATTR_RE.findall(str(tag or "")):
        value = raw_value.strip()
        if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
            value = value[1:-1]
        attributes[key.lower()] = html_lib.unescape(value)
    return attributes


def favicon_urls_from_html(html_text, page_url):
    urls = []
    seen = set()
    for tag in LINK_TAG_RE.findall(str(html_text or "")):
        attrs = _html_tag_attributes(tag)
        rel = attrs.get("rel", "").lower()
        href = attrs.get("href", "").strip()
        if "icon" not in rel or not href:
            continue
        icon_url = urllib.parse.urljoin(page_url, href)
        if icon_url and icon_url not in seen:
            seen.add(icon_url)
            urls.append(icon_url)
    return urls


def default_favicon_urls(url):
    parsed = urllib.parse.urlsplit(str(url or ""))
    scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
    if not parsed.netloc:
        return []
    origin = f"{scheme}://{parsed.netloc}"
    return [
        f"{origin}/favicon.ico",
        f"{origin}/favicon.png",
        f"{origin}/apple-touch-icon.png",
    ]


def external_favicon_lookup_url(page_url):
    parsed = urllib.parse.urlsplit(str(page_url or ""))
    if not parsed.netloc:
        return ""
    scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
    origin = f"{scheme}://{parsed.netloc}"
    query = urllib.parse.urlencode(
        {
            "client": "SOCIAL",
            "type": "FAVICON",
            "fallback_opts": "TYPE,SIZE,URL",
            "url": origin,
            "size": "128",
        }
    )
    return f"https://t0.gstatic.com/faviconV2?{query}"


def favicon_candidate_urls(page_url, dom_html=None):
    urls = []
    seen = set()
    lookup = external_favicon_lookup_url(page_url)
    for candidate in [
        *favicon_urls_from_html(dom_html or "", page_url),
        *default_favicon_urls(page_url),
        *([lookup] if lookup else []),
    ]:
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    return urls


def image_extension_from_response(content_type, url):
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/x-icon": ".ico",
        "image/vnd.microsoft.icon": ".ico",
        "image/svg+xml": ".svg",
    }
    if mime in mapping:
        return mapping[mime]
    path = urllib.parse.urlsplit(str(url or "")).path.lower()
    for ext in IMAGE_EXTENSIONS:
        if path.endswith(ext):
            return ext
    return ".img"


def read_limited(response, max_bytes, chunk=64 * 1024):
    # Bound memory when the user pastes an external page/media URL that a
    # server answers with an oversized body.
    chunks = []
    total = 0
    while True:
        block = response.read(chunk)
        if not block:
            break
        total += len(block)
        if total > max_bytes:
            raise RuntimeError(f"Response too large: > {max_bytes} bytes")
        chunks.append(block)
    return b"".join(chunks)


def fetch_binary_url(url, referer=None, timeout=20, headers=None, max_bytes=MAX_IMAGE_BYTES):
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": ACCEPT_LANGUAGE,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        **(headers or {}),
    }
    if referer:
        request_headers["Referer"] = referer
    request = urllib.request.Request(str(url or ""), headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type") or ""
            return read_limited(response, max_bytes), content_type
    except Exception as urllib_exc:
        try:
            apply_curl_cffi_system_dns_patch()
            from curl_cffi import requests as curl_requests

            response = curl_requests.get(
                str(url or ""),
                headers=request_headers,
                impersonate="chrome",
                timeout=timeout,
                stream=True,
            )
            response.raise_for_status()
            chunks = []
            total = 0
            for block in response.iter_content(chunk_size=64 * 1024):
                if not block:
                    continue
                total += len(block)
                if total > max_bytes:
                    raise RuntimeError(f"Response too large: > {max_bytes} bytes")
                chunks.append(block)
            return b"".join(chunks), response.headers.get("Content-Type") or ""
        except Exception:
            raise urllib_exc


def download_image_asset(url, output_path, referer=None, min_bytes=500, timeout=20):
    data, content_type = fetch_binary_url(url, referer=referer, timeout=timeout)
    if len(data) < min_bytes:
        raise RuntimeError(f"Image too small: {len(data)} bytes")
    output_path = Path(output_path).expanduser()
    ext = image_extension_from_response(content_type, url)
    if output_path.suffix.lower() not in IMAGE_EXTENSIONS:
        output_path = Path(f"{output_path}{ext}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return {
        "ok": True,
        "path": str(output_path),
        "bytes": len(data),
        "url": str(url),
        "content_type": content_type,
    }


def save_thumbnail_asset(thumbnail_url, output_dir, stem, referer=None, min_bytes=1000):
    thumbnail_url = str(thumbnail_url or "").strip()
    if not thumbnail_url.lower().startswith(("http://", "https://")):
        raise RuntimeError("Thumbnail URL is missing or invalid.")
    output_dir = Path(output_dir).expanduser()
    return download_image_asset(
        thumbnail_url,
        output_dir / f"{stem}.thumb",
        referer=referer,
        min_bytes=min_bytes,
    )


def save_favicon_asset(page_url, output_dir, stem, dom_html=None, candidate_urls=None, min_bytes=100, timeout=20):
    page_url = str(page_url or "").strip()
    if not page_url.lower().startswith(("http://", "https://")):
        raise RuntimeError("Page URL is missing or invalid.")
    output_dir = Path(output_dir).expanduser()
    if candidate_urls:
        urls = []
        seen = set()
        for candidate_url in candidate_urls:
            if candidate_url and candidate_url not in seen:
                seen.add(candidate_url)
                urls.append(candidate_url)
    else:
        html = dom_html
        if html is None:
            try:
                html = fetch_dom_html_with_urllib(page_url, timeout=min(20, timeout))
            except (OSError, urllib.error.URLError, ValueError, TimeoutError):
                html = ""
        urls = favicon_candidate_urls(page_url, html)
    errors = []
    for candidate_url in urls:
        try:
            return download_image_asset(
                candidate_url,
                output_dir / f"{stem}.favicon",
                referer=page_url,
                min_bytes=min_bytes,
                timeout=timeout,
            )
        except Exception as exc:
            errors.append(f"{candidate_url}: {exc}")
    raise RuntimeError(errors[-1] if errors else "No favicon candidate could be downloaded.")


def parse_content_range(value):
    match = re.search(r"/(\d+)\s*$", str(value or ""))
    return safe_int(match.group(1)) if match else 0


def http_content_length(url, timeout=3, headers=None):
    if not str(url or "").lower().startswith(("http://", "https://")):
        return 0
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": ACCEPT_LANGUAGE,
        **dict(headers or {}),
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
            status = safe_int(getattr(response, "status", 0))
            ranged = parse_content_range(response.headers.get("Content-Range"))
            if ranged:
                return ranged
            length = safe_int(response.headers.get("Content-Length"))
            if status == 200 and length:
                return length
            return 0
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


DURATION_PROBE_LIMIT = 3


def duration_from_hls_playlist_text(playlist_text):
    total = 0.0
    for line in str(playlist_text or "").splitlines():
        line = line.strip()
        if not line.startswith("#EXTINF:"):
            continue
        value = line.split(":", 1)[1].split(",", 1)[0].strip()
        try:
            total += float(value)
        except ValueError:
            continue
    return safe_int(total)


def probe_manifest_duration(url, candidate=None):
    media_url = str(url or "").strip()
    if ".m3u8" not in media_url.lower():
        return 0
    headers = direct_media_request_headers(candidate or {})
    try:
        resolved_url, playlist_text = resolve_hls_media_playlist(media_url, headers)
        duration = duration_from_hls_playlist_text(playlist_text)
        if duration:
            return duration
    except Exception:
        pass
    return probe_stream_duration(media_url, candidate)


def enrich_missing_durations(candidates, duration_probe=None, limit=DURATION_PROBE_LIMIT):
    probe = duration_probe or probe_manifest_duration
    checked = 0
    for candidate in candidates:
        if safe_int(candidate.get("duration")):
            continue
        media_url = str(candidate.get("url") or "")
        if not media_url:
            continue
        if not (candidate.get("is_manifest") or ".m3u8" in media_url.lower()):
            continue
        if checked >= limit:
            break
        checked += 1
        duration = safe_int(probe(media_url, candidate))
        if duration:
            candidate["duration"] = duration
    return candidates


def find_chzzk_clip_uid(*urls):
    for url in urls:
        if not url:
            continue
        match = CHZZK_CLIP_RE.search(str(url))
        if match:
            return match.group(1)
    return None


def find_chzzk_video_no(*urls):
    for url in urls:
        if not url:
            continue
        match = CHZZK_VIDEO_RE.search(str(url))
        if match:
            return match.group(1)
    return None


def nested_value(value, *keys):
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def chzzk_channel_name(*payloads):
    paths = [
        ("channel", "channelName"),
        ("ownerChannel", "channelName"),
        ("makerChannel", "channelName"),
        ("interaction", "subscription", "name"),
        ("card", "interaction", "subscription", "name"),
        ("subscription", "name"),
    ]
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for path in paths:
            name = clean_video_title(nested_value(payload, *path))
            if name:
                return name
    return ""


def chzzk_display_title(title, channel):
    title = clean_video_title(title)
    channel = clean_video_title(channel)
    if not title or not channel:
        return title or channel
    title_folded = title.casefold()
    channel_folded = channel.casefold()
    if title_folded == channel_folded:
        return channel
    if title_folded.startswith(channel_folded):
        remainder = title[len(channel):].lstrip(" \t-–—_:|")
        if remainder:
            return f"{channel} - {remainder}"
    return f"{channel} - {title}"


def seconds_from_duration_value(value):
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value or "").strip()
    if not text:
        return 0
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return max(0, int(float(text)))
    match = ISO_DURATION_RE.match(text)
    if not match:
        return 0
    days = float(match.group("days") or 0)
    hours = float(match.group("hours") or 0)
    minutes = float(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    return max(0, int(days * 86400 + hours * 3600 + minutes * 60 + seconds))


def chzzk_duration(*values):
    for value in values:
        seconds = seconds_from_duration_value(value)
        if seconds:
            return seconds
    return 0


def http_json(url, params=None, headers=None, cookie_header=""):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": ACCEPT_LANGUAGE,
        "Accept": "application/json,text/plain,*/*",
        **(headers or {}),
    }
    cookie_header = str(cookie_header or "").strip()
    if cookie_header:
        request_headers["Cookie"] = cookie_header
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def chzzk_detail_hard_blocked(content):
    optional = (content or {}).get("optionalProperty") or {}
    if optional.get("privateUserBlock") or optional.get("penalty"):
        return True
    return bool((content or {}).get("blindType"))


def chzzk_adult_requires_login(content, cookie_header):
    return bool((content or {}).get("adult")) and not str(cookie_header or "").strip()


def chzzk_clip_detail(clip_uid, cookie_header=""):
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
        cookie_header=cookie_header,
    )


def chzzk_video_detail(video_no, cookie_header=""):
    return http_json(
        f"https://api.chzzk.naver.com/service/v3/videos/{video_no}",
        headers={
            "Referer": f"https://chzzk.naver.com/video/{video_no}",
            "Origin": "https://chzzk.naver.com",
            "Front-Client-Product-Type": "web",
            "Front-Client-Platform-Type": "PC",
        },
        cookie_header=cookie_header,
    )


def chzzk_video_playback(video_id, in_key, video_no, cookie_header=""):
    return http_json(
        f"https://apis.naver.com/neonplayer/vodplay/v1/playback/{video_id}",
        params={
            "key": in_key,
            "env": "real",
            "lc": "en_US",
            "cpl": "en_US",
        },
        headers={
            "Referer": f"https://chzzk.naver.com/video/{video_no}",
            "Origin": "https://chzzk.naver.com",
        },
        cookie_header=cookie_header,
    )


def chzzk_shortform_card(clip_uid, video_id, rec_id, cookie_header=""):
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
        cookie_header=cookie_header,
    )


def extract_chzzk_media_urls(card_payload):
    mp4_candidates = []
    hls_candidates = []

    def media_url(value):
        if isinstance(value, dict):
            for key in ("value", "url", "path", "#text"):
                text = value.get(key)
                if isinstance(text, str) and text.startswith("http"):
                    return text
            return ""
        return value

    def add_url(url, width=0, height=0, bandwidth=0, fps=0):
        url = media_url(url)
        if not isinstance(url, str) or not url.startswith("http"):
            return
        item = {
            "url": url,
            "width": safe_int(width),
            "height": safe_int(height),
            "bandwidth": safe_int(bandwidth),
            "fps": safe_int(fps),
        }
        lower = url.lower()
        if ".mp4" in lower:
            mp4_candidates.append(item)
        elif ".m3u8" in lower:
            hls_candidates.append(item)

    def walk(value):
        if isinstance(value, dict):
            width = value.get("@width") or value.get("width")
            height = value.get("@height") or value.get("height")
            bandwidth = value.get("@bandwidth") or value.get("bandwidth")
            fps = value.get("@frameRate") or value.get("frameRate") or value.get("fps")
            for base_key in ("BaseURL", "baseURL"):
                base_urls = value.get(base_key)
                if isinstance(base_urls, list):
                    for base_url in base_urls:
                        add_url(base_url, width, height, bandwidth, fps)
                else:
                    add_url(base_urls, width, height, bandwidth, fps)
            bitrate = value.get("bitrate") if isinstance(value.get("bitrate"), dict) else {}
            add_url(value.get("@nvod:m3u"), width, height, bandwidth, fps)
            add_url(value.get("source"), width, height, bitrate.get("video") or bandwidth, fps)
            add_url(value.get("path"), width, height, bandwidth, fps)
            other_attrs = value.get("otherAttributes")
            if isinstance(other_attrs, dict):
                add_url(other_attrs.get("m3u"), width, height, bandwidth, fps)
                add_url(other_attrs.get("m3u8"), width, height, bandwidth, fps)
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


def chzzk_effective_bandwidth_bps(bandwidth, average_bandwidth=0):
    average = safe_int(average_bandwidth)
    peak = safe_int(bandwidth)
    if average > 0:
        return average
    if peak > 0:
        return max(1, int(peak * CHZZK_PEAK_BANDWIDTH_SIZE_FACTOR))
    return 0


def chzzk_media_size_bytes(item, duration):
    seconds = safe_int(duration)
    effective = chzzk_effective_bandwidth_bps(
        (item or {}).get("bandwidth"),
        (item or {}).get("average_bandwidth"),
    )
    if effective > 0 and seconds > 0:
        return int(effective * seconds / 8), "bitrate"
    return 0, "unknown"


def hls_stream_inf_bitrate_bps(stream_inf_line):
    average_match = re.search(r"AVERAGE-BANDWIDTH=(\d+)", str(stream_inf_line or ""))
    bandwidth_match = re.search(r"BANDWIDTH=(\d+)", str(stream_inf_line or ""))
    return chzzk_effective_bandwidth_bps(
        safe_int(bandwidth_match.group(1)) if bandwidth_match else 0,
        safe_int(average_match.group(1)) if average_match else 0,
    )


def hls_master_playlist_bandwidth(url, headers, height=0):
    request = urllib.request.Request(str(url or ""), headers=dict(headers or {}))
    try:
        with parallel_http_urlopen(request, timeout=20) as response:
            playlist_text = response.read().decode("utf-8", errors="replace")
    except Exception:
        return 0
    if "#EXT-X-STREAM-INF" not in playlist_text:
        return 0
    best = 0
    best_for_height = 0
    lines = playlist_text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        resolution_match = re.search(r"RESOLUTION=\d+x(\d+)", line)
        bandwidth = hls_stream_inf_bitrate_bps(line)
        variant_height = safe_int(resolution_match.group(1)) if resolution_match else 0
        if height and variant_height == height:
            best_for_height = max(best_for_height, bandwidth)
        best = max(best, bandwidth)
    return best_for_height or best


def enrich_chzzk_candidate_sizes(candidates, limit=3):
    checked = 0
    for candidate in candidates:
        if safe_int(candidate.get("sort_bytes")):
            continue
        media_url = str(candidate.get("url") or "")
        if ".m3u8" not in media_url.lower():
            continue
        if checked >= limit:
            break
        checked += 1
        bandwidth = hls_master_playlist_bandwidth(
            media_url,
            direct_media_request_headers(candidate),
            height=safe_int(candidate.get("height")),
        )
        duration = safe_int(candidate.get("duration"))
        if bandwidth > 0 and duration > 0:
            size = int(bandwidth * duration / 8)
            candidate["sort_bytes"] = size
            candidate["filesize_approx"] = size
            candidate["size_source"] = "bitrate"
            candidate["tbr"] = max(1, bandwidth // 1000)
    return candidates


def chzzk_candidates_from_media(media_items, source_url, title, thumbnail, duration):
    candidates = []
    for index, item in enumerate(media_items, start=1):
        url = str(item.get("url") or "")
        ext = "mp4" if ".mp4" in url.lower() else "m3u8"
        sort_bytes, size_source = chzzk_media_size_bytes(item, duration)
        fmt = {"url": url, "ext": ext, "tbr": max(1, safe_int(item.get("bandwidth")) // 1000) if safe_int(item.get("bandwidth")) else 0}
        filesize, filesize_approx = candidate_filesize_fields(fmt, sort_bytes, size_source)
        candidates.append(
            {
                "id": f"chzzk-{index}",
                "format_id": f"chzzk-{item.get('height') or index}",
                "format_selector": "best",
                "url": url,
                "title": title,
                "display_title": title,
                "thumbnail": thumbnail,
                "duration": duration,
                "ext": ext,
                "output_ext": "mp4",
                "resolution": f"{item.get('width')}x{item.get('height')}" if item.get("width") and item.get("height") else (f"{item.get('height')}p" if item.get("height") else "unknown"),
                "height": safe_int(item.get("height")),
                "fps": safe_int(item.get("fps")),
                "tbr": safe_int(fmt.get("tbr")),
                "vcodec": "unknown",
                "acodec": "unknown",
                "filesize": filesize,
                "filesize_approx": filesize_approx,
                "sort_bytes": sort_bytes,
                "size_source": size_source,
                "source": source_url,
                "note": "CHZZK direct MP4" if ext == "mp4" else "CHZZK HLS",
            }
        )
    return candidates


def analyze_chzzk_clip(url, on_event=None, cookie_source="없음"):
    clip_uid = find_chzzk_clip_uid(url)
    if not clip_uid:
        return None

    emit_event(on_event, "status", message=f"CHZZK 클립 분석 중: {clip_uid}")
    cookie_header = cookie_header_for_source(cookie_source)
    detail = chzzk_clip_detail(clip_uid, cookie_header=cookie_header)
    content = detail.get("content") or {}
    if chzzk_detail_hard_blocked(content):
        raise RuntimeError("CHZZK clip is not publicly playable in this session.")
    if chzzk_adult_requires_login(content, cookie_header):
        raise RuntimeError("CHZZK 성인 콘텐츠는 로그인 쿠키가 필요합니다. 쿠키 소스를 선택하세요.")

    video_id = content.get("videoId")
    if not video_id:
        raise RuntimeError("CHZZK clip detail did not include a videoId.")

    card = chzzk_shortform_card(clip_uid, video_id, content.get("recId"), cookie_header=cookie_header)
    mp4_candidates, hls_candidates = extract_chzzk_media_urls(card)
    raw_title = content.get("clipTitle") or content.get("title") or f"CHZZK clip {clip_uid}"
    title = chzzk_display_title(raw_title, chzzk_channel_name(content, card))
    duration = chzzk_duration(
        content.get("duration"),
        content.get("durationSeconds"),
        content.get("playTime"),
    )
    thumbnail = (
        content.get("thumbnailImageUrl")
        or content.get("clipImageUrl")
        or content.get("imageUrl")
        or content.get("previewImageUrl")
        or ""
    )
    source_url = f"https://chzzk.naver.com/clips/{clip_uid}"
    candidates = chzzk_candidates_from_media(mp4_candidates + hls_candidates, source_url, title, thumbnail, duration)
    candidates = sort_candidates(enrich_chzzk_candidate_sizes(enrich_missing_sizes(candidates)))
    return {
        "url": url,
        "webpage_url": source_url,
        "title": candidates[0]["title"] if candidates else f"CHZZK clip {clip_uid}",
        "candidates": candidates,
        "warnings": [],
    }


def analyze_chzzk_video(url, on_event=None, cookie_source="없음"):
    video_no = find_chzzk_video_no(url)
    if not video_no:
        return None

    emit_event(on_event, "status", message=f"CHZZK 동영상 분석 중: {video_no}")
    if cookie_source and cookie_source != "없음":
        emit_event(on_event, "status", message="로그인 쿠키 확인 중")
    cookie_header = cookie_header_for_source(cookie_source)
    detail = chzzk_video_detail(video_no, cookie_header=cookie_header)
    content = detail.get("content") or {}
    if chzzk_detail_hard_blocked(content):
        raise RuntimeError("CHZZK video is not publicly playable in this session.")
    if chzzk_adult_requires_login(content, cookie_header):
        raise RuntimeError("CHZZK 성인 콘텐츠는 로그인 쿠키가 필요합니다. 쿠키 소스를 선택하세요.")

    raw_title = content.get("videoTitle") or content.get("title") or f"CHZZK video {video_no}"
    title = chzzk_display_title(raw_title, chzzk_channel_name(content))
    duration = chzzk_duration(content.get("duration"))
    thumbnail = content.get("thumbnailImageUrl") or content.get("imageUrl") or ""
    source_url = f"https://chzzk.naver.com/video/{video_no}"

    playback = None
    if content.get("videoId") and content.get("inKey"):
        playback = chzzk_video_playback(content.get("videoId"), content.get("inKey"), video_no, cookie_header=cookie_header)
    elif content.get("liveRewindPlaybackJson"):
        playback = json.loads(content.get("liveRewindPlaybackJson") or "{}")
    if not playback:
        raise RuntimeError("CHZZK video playback information was not available.")

    mp4_candidates, hls_candidates = extract_chzzk_media_urls(playback)
    candidates = chzzk_candidates_from_media(mp4_candidates + hls_candidates, source_url, title, thumbnail, duration)
    candidates = sort_candidates(enrich_chzzk_candidate_sizes(enrich_missing_sizes(candidates)))
    return {
        "url": url,
        "webpage_url": source_url,
        "title": candidates[0]["title"] if candidates else title,
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


def should_try_browser_dom_fallback(message):
    lower = str(message or "").lower()
    if "ip address is blocked" in lower or "your ip address is blocked" in lower:
        return False
    if classify_error(message) == "로그인/권한 필요":
        return False
    return classify_error(message) in {
        "브라우저 지문/TLS 차단 가능성",
        "지원되지 않는 스트림",
        "네트워크/추출 오류",
    }


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


def is_hls_manifest_format(fmt):
    protocol = format_protocol(fmt).lower()
    url = str(fmt.get("url") or "").lower()
    return "m3u8" in protocol or ".m3u8" in url


def youtube_direct_download_risk(fmt, video_info=None, root_info=None):
    protocol = format_protocol(fmt).lower()
    if protocol != "https" or is_manifest_format(fmt):
        return ""
    source = " ".join(
        str(value or "")
        for value in (
            (video_info or {}).get("webpage_url"),
            (video_info or {}).get("original_url"),
            (root_info or {}).get("webpage_url"),
            (root_info or {}).get("original_url"),
        )
    ).lower()
    if "youtube.com" not in source and "youtu.be" not in source:
        return ""
    url = str(fmt.get("url") or "")
    if "googlevideo.com" not in url:
        return ""
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    client = next((value for value in query.get("c", []) if value), "")
    has_video = str(fmt.get("vcodec") or "none").lower() != "none" or safe_int(fmt.get("height")) > 0
    if has_video and client.upper() == "TVHTML5":
        return "youtube_tv_https_po_token"
    return ""


def bitrate_duration_size(fmt, duration=0):
    bitrate_kbps = safe_int(fmt.get("tbr") or fmt.get("vbr") or fmt.get("abr"))
    seconds = safe_int(fmt.get("duration") or duration)
    if not bitrate_kbps or not seconds:
        return 0
    return int(bitrate_kbps * 1000 * seconds / 8)


def manifest_clen_size(fmt):
    url = urllib.parse.unquote(str((fmt or {}).get("url") or ""))
    values = [safe_int(match) for match in re.findall(r"(?:^|[;/&?])clen=(\d+)(?:[;/&]|$)", url)]
    return sum(value for value in values if value > 0)


def manifest_bitrate_size_is_unreliable(fmt):
    if not is_manifest_format(fmt):
        return False
    url = str(fmt.get("url") or "").lower()
    protocol = format_protocol(fmt).lower()
    return "googlevideo.com" in url and ("m3u8" in protocol or "hls_playlist" in url or ".m3u8" in url)


def media_size_for_format(fmt, duration=0, extra_size=0):
    if is_manifest_format(fmt):
        clen_size = manifest_clen_size(fmt)
        if clen_size:
            return clen_size + safe_int(extra_size), "clen_estimate"
        if manifest_bitrate_size_is_unreliable(fmt):
            return 0, "unknown"
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
        if size_source in {"bitrate", "clen_estimate"}:
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
        page_url = video_info.get("webpage_url") or video_info.get("original_url") or info.get("webpage_url") or ""
        thumbnail = resolve_analysis_thumbnail(page_url, video_info) or thumbnail_from_info(info)
        duration = safe_int(video_info.get("duration") or info.get("duration"))
        formats = video_info.get("formats") or []
        audio = best_audio_format(formats)
        for fmt in formats:
            format_id = str(fmt.get("format_id") or "")
            ext = str(fmt.get("ext") or "").lower()
            vcodec = str(fmt.get("vcodec") or "unknown")
            acodec = str(fmt.get("acodec") or "unknown")
            if audio_output_exts and is_audio_format(fmt):
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
                            "_download_info_key": download_info_key(video_info, info),
                            "download_risk": youtube_direct_download_risk(fmt, video_info, info),
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
                    "dynamic_range": str(fmt.get("dynamic_range") or video_info.get("dynamic_range") or ""),
                    "color_transfer": str(fmt.get("color_transfer") or video_info.get("color_transfer") or ""),
                    "filesize": filesize,
                    "filesize_approx": filesize_approx,
                    "sort_bytes": sort_bytes,
                    "size_source": size_source,
                    "source": source,
                    "_download_info_key": download_info_key(video_info, info),
                    "download_risk": youtube_direct_download_risk(fmt, video_info, info),
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
                    "dynamic_range": str(video_info.get("dynamic_range") or ""),
                    "color_transfer": str(video_info.get("color_transfer") or ""),
                    "filesize": filesize,
                    "filesize_approx": filesize_approx,
                    "sort_bytes": size,
                    "size_source": size_source,
                    "source": video_info.get("webpage_url") or video_info["url"],
                    "_download_info_key": download_info_key(video_info, info),
                    "download_risk": youtube_direct_download_risk(video_info, video_info, info),
                    "protocol": format_protocol(video_info),
                    "is_manifest": is_manifest_format(video_info),
                    "media_type": "video",
                    "note": "direct",
                }
            )
    return sort_candidates(candidates)


def download_info_key(video_info, root_info=None):
    if not isinstance(video_info, dict):
        return ""
    root_info = root_info if isinstance(root_info, dict) else {}
    return str(
        video_info.get("webpage_url")
        or video_info.get("original_url")
        or root_info.get("webpage_url")
        or root_info.get("original_url")
        or video_info.get("url")
        or video_info.get("id")
        or ""
    )


def json_ready_download_info(info):
    if not isinstance(info, dict):
        return {}
    cleaned = json.loads(json.dumps(info, ensure_ascii=False, default=str))
    for key in (
        "automatic_captions",
        "subtitles",
        "requested_subtitles",
        "comments",
        "heatmap",
    ):
        cleaned.pop(key, None)
    return cleaned


def download_infos_from_info(info):
    if not isinstance(info, dict):
        return {}
    infos = {}
    for video_info in iter_video_infos(info):
        key = download_info_key(video_info, info)
        if key:
            infos[key] = json_ready_download_info(video_info)
    return infos


def is_youtube_url(value):
    parsed = urllib.parse.urlparse(str(value or ""))
    host = parsed.netloc.lower().removeprefix("www.")
    return host in {"youtube.com", "m.youtube.com", "youtu.be"} or host.endswith(".youtube.com")


def download_info_reuse_supported(candidate):
    candidate = candidate or {}
    if str(candidate.get("format_id") or "").startswith("chzzk-"):
        return False
    for value in (candidate.get("source"), candidate.get("webpage_url"), candidate.get("url")):
        if is_youtube_url(value):
            return False
        if is_chzzk_page_url(value):
            return False
    return True


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
    cookie_file = cookiesfile_from_env()
    if cookie_file:
        options["cookiefile"] = cookie_file
    else:
        spec = cookiesfrombrowser_spec(cookie_source)
        if spec:
            options["cookiesfrombrowser"] = spec
    proxy = effective_proxy_url(proxy_url)
    if proxy:
        options["proxy"] = proxy
    bundled_ffmpeg = ffmpeg_path()
    if bundled_ffmpeg:
        options["ffmpeg_location"] = ffmpeg_path_for_yt_dlp(bundled_ffmpeg)
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
            "overwrites": True,
            "continuedl": True,
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": YTDLP_CONCURRENT_FRAGMENT_DOWNLOADS,
            "http_chunk_size": YTDLP_HTTP_CHUNK_SIZE,
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
            }
        )
        if output_ext != "mp4":
            options["postprocessors"] = [{"key": "FFmpegVideoConvertor", "preferedformat": output_ext}]
        elif is_hls_manifest_format(candidate):
            options["fixup"] = "never"
    clip_range = clip_range_from_candidate(candidate)
    if clip_range:
        ffmpeg_exe = ffmpeg_path() or shutil.which("ffmpeg")
        if not ffmpeg_exe:
            raise RuntimeError("ffmpeg is required for segment downloads")
        from yt_dlp.utils import download_range_func

        end = clip_range.get("end")
        options["download_ranges"] = download_range_func([], [(float(clip_range["start"]), float(end) if end is not None else float("inf"))])
        options["external_downloader"] = options.get("ffmpeg_location") or ffmpeg_path_for_yt_dlp(ffmpeg_exe)
        options["force_keyframes_at_cuts"] = bool((candidate or {}).get("force_keyframes_at_cuts", False)) or clip_cut_mode(candidate) == "accurate"
    return options


def progress_hook(on_event=None):
    last_emit = [0.0]
    unknown_total_reported = [False]

    def hook(data):
        status = data.get("status")
        if status == "downloading":
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            percent = max(0, min(100, downloaded * 100 / total)) if total else 0
            # Throttle to ~4 events/sec. yt-dlp fires this callback dozens of
            # times per second; with concurrent downloads the cross-thread signal
            # flood can starve the UI thread. Always let the final tick through.
            now = time.monotonic()
            if percent < 100 and now - last_emit[0] < 0.25:
                return
            last_emit[0] = now
            if total:
                speed = (data.get("_speed_str") or "").strip()
                eta = (data.get("_eta_str") or "").strip()
                emit_event(
                    on_event,
                    "progress",
                    percent=percent,
                    downloaded=downloaded,
                    total=total,
                    speed=data.get("speed") or 0,
                    eta=data.get("eta"),
                    speed_text=speed,
                    eta_text=eta,
                    message=f"{percent:.1f}% {speed} ETA {eta}".strip(),
                )
                unknown_total_reported[0] = False
            else:
                if not unknown_total_reported[0]:
                    emit_event(on_event, "status", message="Downloading")
                    unknown_total_reported[0] = True
        elif status == "finished":
            unknown_total_reported[0] = False
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


def dom_html_looks_usable(html):
    text = str(html or "")
    if len(text) < 500:
        return False
    markers = (
        "mediaDefinitions",
        "setVideoHLS",
        "setVideoUrl",
        "window.initials",
        "flashvars",
        "<video",
    )
    lower = text.lower()
    return any(marker.lower() in lower for marker in markers)


def fetch_dom_html_with_urllib(url, timeout=20, max_bytes=MAX_HTML_BYTES):
    request = urllib.request.Request(
        str(url or ""),
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": ACCEPT_LANGUAGE,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = read_limited(response, max_bytes)
    except urllib.error.HTTPError as exc:
        if exc.code not in {403, 451, 503}:
            raise
        body = read_limited(exc, max_bytes)
    if not body:
        return ""
    return clean_browser_dom(body.decode("utf-8", errors="replace"))


def fetch_dom_for_fallback(url, on_event=None, timeout=90):
    emit_event(on_event, "status", message="페이지 HTML 분석 중")
    urllib_failed_fast = False
    try:
        html = fetch_dom_html_with_urllib(url, timeout=min(20, timeout))
    except (OSError, urllib.error.URLError, ValueError, TimeoutError):
        html = ""
        urllib_failed_fast = True
    if dom_html_looks_usable(html):
        remember_browser_dom_html(url, html)
        return html
    chrome_timeout = 35 if urllib_failed_fast or (html and len(html) > 200) else timeout
    dom = dump_dom_with_browser(url, on_event=on_event, timeout=chrome_timeout)
    remember_browser_dom_html(url, dom)
    return dom


def dump_dom_with_browser(url, on_event=None, timeout=90):
    browser = find_browser_executable()
    if not browser:
        raise RuntimeError("Chrome/Edge browser was not found for browser DOM fallback.")
    emit_event(on_event, "status", message="브라우저 DOM 분석 중")
    command = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--disable-extensions",
        "--incognito",
        "--disable-blink-features=AutomationControlled",
        "--virtual-time-budget=20000",
        "--dump-dom",
        url,
    ]
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
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
    except subprocess.TimeoutExpired as exc:
        dom = clean_browser_dom(exc.stdout or "")
        if dom_html_looks_usable(dom):
            return dom
        raise RuntimeError(f"Browser DOM fallback timed out after {timeout} seconds") from exc
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
    return _extract_balanced_json_fragment(text, start, "[", "]")


def extract_json_object_after(text, marker):
    idx = text.find(marker)
    if idx < 0:
        return None
    start = text.find("{", idx)
    if start < 0:
        return None
    return _extract_balanced_json_fragment(text, start, "{", "}")


def _extract_balanced_json_fragment(text, start, open_char, close_char):
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
        elif char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _parse_embedded_json_object(raw):
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def embedded_script_objects_from_html(dom):
    text = html_lib.unescape(str(dom or ""))
    objects = {}
    markers = (
        ("flashvars", ("flashvars",)),
        ("model_profile", ("MODEL_PROFILE",)),
        ("initials", ("window.initials",)),
    )
    for key, names in markers:
        for name in names:
            idx = 0
            while True:
                idx = text.find(name, idx)
                if idx < 0:
                    break
                brace = text.find("{", idx)
                if brace < 0:
                    idx += len(name)
                    continue
                parsed = _parse_embedded_json_object(_extract_balanced_json_fragment(text, brace, "{", "}"))
                if parsed:
                    objects[key] = parsed
                    break
                idx += len(name)
    sources_match = re.search(r"sources\s*:\s*(\{)", text)
    if sources_match:
        parsed = _parse_embedded_json_object(
            _extract_balanced_json_fragment(text, sources_match.start(1), "{", "}")
        )
        if parsed:
            objects["sources_map"] = parsed
    return objects


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


def script_map_media_from_html(dom, base_url):
    objects = embedded_script_objects_from_html(dom)
    items = []
    initials = objects.get("initials") or {}
    video_model = initials.get("videoModel") if isinstance(initials.get("videoModel"), dict) else {}
    sources = video_model.get("sources") if isinstance(video_model.get("sources"), dict) else {}
    duration = safe_int(video_model.get("duration"))
    poster = str(video_model.get("thumbURL") or "")
    download_sizes = {}
    download_sources = sources.get("download") if isinstance(sources.get("download"), dict) else {}
    for quality, format_dict in download_sources.items():
        if isinstance(format_dict, dict):
            download_sizes[str(quality)] = safe_int(format_dict.get("size"))
    for source_kind, formats_dict in sources.items():
        if source_kind == "download" or not isinstance(formats_dict, dict):
            continue
        for quality, format_url in formats_dict.items():
            media_url = str(format_url or "").strip()
            if not media_url.startswith(("http://", "https://")):
                continue
            absolute_url = urllib.parse.urljoin(base_url, media_url)
            height = height_from_media_url(str(quality)) or height_from_media_url(absolute_url)
            size = download_sizes.get(str(quality), 0)
            items.append(
                {
                    "videoUrl": absolute_url,
                    "format": str(source_kind),
                    "quality": quality,
                    "height": height,
                    "duration": duration,
                    "filesize": size,
                    "poster": poster,
                    "source": "page-script",
                }
            )
    for quality, format_url in (objects.get("sources_map") or {}).items():
        media_url = str(format_url or "").strip()
        if not media_url.startswith(("http://", "https://")):
            continue
        absolute_url = urllib.parse.urljoin(base_url, media_url)
        height = height_from_media_url(str(quality)) or height_from_media_url(absolute_url)
        items.append(
            {
                "videoUrl": absolute_url,
                "format": "mp4",
                "quality": quality,
                "height": height,
                "source": "page-script",
            }
        )
    return items


def first_html_match(dom, patterns, compact_limit=90):
    text = str(dom or "")
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            value = html_lib.unescape(match.group(1)).strip()
            if compact_limit is None:
                return value
            return compact_text(value, limit=compact_limit)
    return ""


def title_from_browser_dom(dom):
    objects = embedded_script_objects_from_html(dom)
    flashvars = objects.get("flashvars") or {}
    initials = objects.get("initials") or {}
    video_model = initials.get("videoModel") if isinstance(initials.get("videoModel"), dict) else {}
    for title in (
        first_html_match(
            dom,
            [
                r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)["\']',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:title["\']',
                r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
            ],
        ),
        first_html_match(dom, [r'<h1[^>]+class=["\']title["\'][^>]*>(.+?)</h1>']),
        first_html_match(dom, [r'data-video-title=(?:["\'])([^"\']+)(?:["\'])']),
        first_html_match(dom, [r'shareTitle["\']\s*[=:]\s*(?:["\'])([^"\']+)(?:["\'])']),
        first_html_match(dom, [r'setVideoTitle\s*\(\s*(?:["\'])([^"\']+)(?:["\'])']),
        clean_video_title(video_model.get("title")),
        clean_video_title(flashvars.get("video_title")),
        clean_video_title(first_html_match(dom, [r"<title[^>]*>(.*?)</title>"])),
    ):
        if title:
            return title
    return "Browser video"


def uploader_from_browser_dom(dom):
    objects = embedded_script_objects_from_html(dom)
    model_profile = objects.get("model_profile") or {}
    initials = objects.get("initials") or {}
    video_model = initials.get("videoModel") if isinstance(initials.get("videoModel"), dict) else {}
    author = video_model.get("author") if isinstance(video_model.get("author"), dict) else {}
    for name in (
        clean_video_title(model_profile.get("username")),
        clean_video_title(author.get("name")),
        first_html_match(
            dom,
            [
                r'itemprop=["\']author["\'][^>]*><a[^>]+><span[^>]+>([^<]+)',
                r'From:&nbsp;.+?<(?:a|span)\b[^>]+>([^<]+)<',
                r'href=["\']/(?:profiles|users|channels|model|pornstar)/[^"\']+["\'][^>]*>([^<]+)<',
            ],
        ),
    ):
        if name and name.casefold() not in {"anonymous", "unknown"}:
            return name
    return ""


def display_title_from_browser_dom(dom):
    return prefix_title_with_uploader(title_from_browser_dom(dom), uploader_from_browser_dom(dom))


def thumbnail_from_browser_dom(dom):
    return first_html_match(
        dom,
        [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<video[^>]+poster=["\']([^"\']+)["\']',
            r'setThumbUrl(?:169)?\(\s*["\']([^"\']+)["\']\s*\)',
        ],
        compact_limit=None,
    )


def thumbnail_from_page_url(page_url, page_fetch=fetch_dom_html_with_urllib, timeout=PAGE_THUMBNAIL_TIMEOUT):
    page_url = str(page_url or "").strip()
    if not page_url.lower().startswith(("http://", "https://")):
        return ""
    try:
        html = page_fetch(page_url, timeout=timeout)
    except Exception:
        return ""
    return str(thumbnail_from_browser_dom(html) or "").strip()


def resolve_analysis_thumbnail(page_url, info, page_fetch=fetch_dom_html_with_urllib):
    page_thumb = thumbnail_from_page_url(page_url, page_fetch=page_fetch)
    if page_thumb:
        return page_thumb
    if isinstance(info, dict):
        return thumbnail_from_info(info)
    return ""


def duration_from_browser_dom(dom):
    objects = embedded_script_objects_from_html(dom)
    flashvars = objects.get("flashvars") or {}
    initials = objects.get("initials") or {}
    video_model = initials.get("videoModel") if isinstance(initials.get("videoModel"), dict) else {}
    for value in (
        flashvars.get("video_duration"),
        video_model.get("duration"),
        first_html_match(
            dom,
            [
                r'<meta[^>]+property=["\']og:video:duration["\'][^>]+content=["\'](\d+)["\']',
                r'<meta[^>]+content=["\'](\d+)["\'][^>]+property=["\']og:video:duration["\']',
                r'<meta[^>]+property=["\']video:duration["\'][^>]+content=["\'](\d+)["\']',
                r'<meta[^>]+content=["\'](\d+)["\'][^>]+property=["\']video:duration["\']',
            ],
        ),
        first_html_match(dom, [r'<span[^>]+class=["\']duration["\'][^>]*>.*?(\d[^<]+)']),
        first_html_match(
            dom,
            [
                r'itemprop=["\']duration["\'][^>]+content=["\']([^"\']+)["\']',
                r'content=["\']([^"\']+)["\'][^>]+itemprop=["\']duration["\']',
            ],
        ),
        first_html_match(dom, [r'"duration"\s*:\s*(\d{1,7})', r"'duration'\s*:\s*(\d{1,7})"]),
        first_html_match(dom, [r'<video\b[^>]*\bduration=["\'](\d+)["\']', r'<video\b[^>]*\bdata-duration=["\'](\d+)["\']']),
    ):
        seconds = seconds_from_duration_value(value)
        if seconds:
            return seconds
    text = compact_text(html_lib.unescape(str(dom or "")), limit=20000)
    patterns = [
        r"(?:video\s*)?duration\s*[:：]\s*(\d{1,2}:\d{2}(?::\d{2})?)",
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


def absolute_browser_media_url(media_url, page_url):
    media_url = html_lib.unescape(str(media_url or "")).replace("\\/", "/").strip()
    if not media_url:
        return ""
    if media_url.startswith(("http://", "https://")):
        return media_url
    return urllib.parse.urljoin(str(page_url or ""), media_url)


def is_browser_remote_media_api_url(media_url):
    lower = str(media_url or "").lower()
    if not lower:
        return False
    if "/video/get_media" in lower or "/media/mp4" in lower or "/media/hls" in lower:
        return True
    parsed = urllib.parse.urlparse(lower)
    return parsed.path.rstrip("/") in {"/video/get_media", "/media/mp4", "/media/hls"}


def json_text_from_browser_dump(dom):
    text = clean_browser_dom(dom)
    match = re.search(r"<pre[^>]*>(.*)</pre>", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return html_lib.unescape(match.group(1)).strip()
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        return stripped
    return ""


def needs_browser_profile_for_remote_media(media_url):
    lower = str(media_url or "").lower()
    parsed = urllib.parse.urlparse(lower)
    path = parsed.path.rstrip("/")
    return path.endswith("/video/get_media") or path.endswith("/get_media")


def _browser_dump_dom_base_args(browser, profile_dir=None):
    args = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--disable-extensions",
        "--disable-blink-features=AutomationControlled",
        "--virtual-time-budget=20000",
    ]
    if profile_dir:
        args.append(f"--user-data-dir={profile_dir}")
    else:
        args.append("--incognito")
    return args


def _run_browser_dump_dom_command(command, timeout=45):
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
    if completed.returncode != 0 and not (completed.stdout or "").strip():
        raise RuntimeError((completed.stderr or "Browser dump-dom failed.").strip())
    return completed.stdout or ""


def _browser_remote_media_payload_from_dom(dom):
    raw = json_text_from_browser_dump(dom)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Browser remote media resolution returned invalid JSON.") from exc


def _browser_remote_media_payload_is_empty(payload):
    if payload is None:
        return True
    if isinstance(payload, list):
        return not payload
    if isinstance(payload, dict):
        return not payload
    return True


def _pick_refreshed_browser_dom_candidate(candidates, target_height=0, prefer_direct=True, prefer_remote_api=False):
    candidates = list(candidates or [])
    if not candidates:
        return None
    direct = [
        candidate
        for candidate in candidates
        if not candidate.get("is_manifest")
        and not is_browser_remote_media_api_url(candidate.get("url"))
        and str(candidate.get("url") or "").lower().startswith(("http://", "https://"))
    ]
    remote_api = [
        candidate
        for candidate in candidates
        if not candidate.get("is_manifest") and is_browser_remote_media_api_url(candidate.get("url"))
    ]
    manifest = [candidate for candidate in candidates if candidate.get("is_manifest")]
    pools = []
    if prefer_remote_api and remote_api:
        pools.append(remote_api)
    if prefer_direct and direct:
        pools.append(direct)
    if manifest:
        pools.append(manifest)
    if remote_api and not prefer_remote_api:
        pools.append(remote_api)
    if not pools:
        pools.append(candidates)
    for pool in pools:
        if target_height:
            exact = [candidate for candidate in pool if safe_int(candidate.get("height")) == target_height]
            if exact:
                return exact[0]
        return pool[0]
    return None


def refresh_browser_dom_candidate_media(page_url, candidate, on_event=None):
    candidate = dict(candidate or {})
    media_url = absolute_browser_media_url(candidate.get("url"), page_url)
    needs_refresh = (
        is_browser_remote_media_api_url(media_url)
        or candidate.get("is_manifest")
        or ".m3u8" in media_url.lower()
        or ".mpd" in media_url.lower()
    )
    if not needs_refresh:
        return candidate
    emit_event(on_event, "status", message="브라우저 DOM 미디어 URL 새로고침 중")
    dom = browser_dom_html_cached(page_url, max_age=BROWSER_DOM_HTML_CACHE_DOWNLOAD_MAX_AGE) or ""

    def apply_refreshed_candidate(analysis):
        original_is_remote_api = is_browser_remote_media_api_url(media_url) and not candidate.get("is_manifest")
        prefer_manifest_refresh = original_is_remote_api and needs_browser_profile_for_remote_media(media_url)
        refreshed = _pick_refreshed_browser_dom_candidate(
            analysis.get("candidates") or [],
            safe_int(candidate.get("height")),
            prefer_direct=not original_is_remote_api or prefer_manifest_refresh,
            prefer_remote_api=original_is_remote_api and not prefer_manifest_refresh,
        )
        if not refreshed or not refreshed.get("url"):
            return False
        for key in ("url", "height", "is_manifest", "protocol", "ext", "source_ext", "output_ext", "resolution", "duration", "sort_bytes"):
            if key in refreshed and refreshed.get(key) not in (None, ""):
                candidate[key] = refreshed[key]
        if refreshed.get("title") and not candidate.get("title"):
            candidate["title"] = refreshed["title"]
        if refreshed.get("display_title") and not candidate.get("display_title"):
            candidate["display_title"] = refreshed["display_title"]
        return True

    if dom_html_looks_usable(dom):
        analysis = analyze_browser_dom_media(
            page_url,
            dom,
            output_ext=candidate.get("output_ext"),
            on_event=on_event,
        )
        if apply_refreshed_candidate(analysis):
            emit_event(on_event, "status", message="캐시된 브라우저 DOM 미디어 URL 사용")
            return candidate
    if not dom_html_looks_usable(dom):
        try:
            dom = fetch_dom_html_with_urllib(page_url, timeout=20)
        except (OSError, urllib.error.URLError, ValueError, TimeoutError):
            dom = ""
        if dom_html_looks_usable(dom):
            remember_browser_dom_html(page_url, dom)
        else:
            dom = fetch_dom_for_fallback(page_url, on_event=on_event, timeout=45)
    analysis = analyze_browser_dom_media(
        page_url,
        dom,
        output_ext=candidate.get("output_ext"),
        on_event=on_event,
    )
    if not apply_refreshed_candidate(analysis):
        return candidate
    return candidate


def fetch_json_via_browser(media_url, page_url=None, on_event=None, timeout=45):
    browser = find_browser_executable()
    if not browser:
        raise RuntimeError("Chrome/Edge browser was not found for remote media resolution.")
    media_url = absolute_browser_media_url(media_url, page_url)
    if not media_url.startswith(("http://", "https://")):
        raise RuntimeError(f"Remote media URL is invalid: {media_url}")
    emit_event(on_event, "status", message="브라우저로 미디어 URL 확인 중")

    def load_payload(profile_dir=None, include_page_prime=False):
        profile_timeout = max(timeout, 90) if profile_dir else timeout
        commands = []
        if include_page_prime and page_url and profile_dir:
            commands.append([*_browser_dump_dom_base_args(browser, profile_dir), "--dump-dom", str(page_url)])
        commands.append([*_browser_dump_dom_base_args(browser, profile_dir), "--dump-dom", media_url])
        dom = ""
        for index, command in enumerate(commands):
            command_timeout = profile_timeout if profile_dir and index == 0 and include_page_prime else timeout
            try:
                dom = _run_browser_dump_dom_command(command, timeout=command_timeout)
            except subprocess.TimeoutExpired as exc:
                if profile_dir and index == 0 and include_page_prime:
                    continue
                raise RuntimeError("Browser remote media resolution timed out.") from exc
        return _browser_remote_media_payload_from_dom(dom)

    payload = load_payload()
    if _browser_remote_media_payload_is_empty(payload) and needs_browser_profile_for_remote_media(media_url):
        profile_dir = tempfile.mkdtemp(prefix="clipflow-browser-profile-")
        try:
            payload = load_payload(profile_dir=profile_dir, include_page_prime=True)
        finally:
            shutil.rmtree(profile_dir, ignore_errors=True)
    if payload is None:
        raise RuntimeError("Browser remote media resolution returned an empty response.")
    if _browser_remote_media_payload_is_empty(payload):
        raise RuntimeError("Browser remote media resolution returned no playable entries.")
    return payload


def prepare_browser_dom_candidate(page_url, candidate, on_event=None):
    candidate = dict(candidate or {})
    if not str(candidate.get("format_id") or "").startswith("browser-"):
        return candidate
    candidate = refresh_browser_dom_candidate_media(page_url, candidate, on_event=on_event)
    media_url = absolute_browser_media_url(candidate.get("url"), page_url)
    if candidate.get("is_manifest") or ".m3u8" in media_url.lower() or ".mpd" in media_url.lower():
        candidate["url"] = media_url
        return candidate
    if not is_browser_remote_media_api_url(media_url):
        if media_url and media_url != candidate.get("url"):
            candidate["url"] = media_url
        return candidate
    payload = fetch_json_via_browser(media_url, page_url=page_url, on_event=on_event)
    entries = payload if isinstance(payload, list) else ([payload] if isinstance(payload, dict) else [])
    if not entries:
        raise RuntimeError("Browser remote media resolution returned no playable entries.")
    target_height = safe_int(candidate.get("height"))
    picked = None
    if target_height:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if safe_int(entry.get("quality") or entry.get("height")) == target_height:
                picked = entry
                break
    if not picked:
        valid_entries = [entry for entry in entries if isinstance(entry, dict)]
        if target_height:
            at_or_below = [
                entry
                for entry in valid_entries
                if safe_int(entry.get("quality") or entry.get("height")) <= target_height
            ]
            pool = at_or_below or valid_entries
        else:
            pool = valid_entries
        picked = max(
            pool,
            key=lambda entry: safe_int(entry.get("quality") or entry.get("height") or 0),
            default=None,
        )
    if not picked:
        raise RuntimeError("Browser remote media resolution returned no playable entries.")
    fresh_url = absolute_browser_media_url(picked.get("videoUrl") or picked.get("url"), page_url)
    if not fresh_url:
        raise RuntimeError("Browser remote media resolution returned an empty media URL.")
    candidate["url"] = fresh_url
    candidate["height"] = safe_int(picked.get("height") or picked.get("quality") or candidate.get("height"))
    candidate["is_manifest"] = ".m3u8" in fresh_url.lower() or ".mpd" in fresh_url.lower()
    candidate["protocol"] = "m3u8" if ".m3u8" in fresh_url.lower() else ("dash" if ".mpd" in fresh_url.lower() else "https")
    return candidate


def analyze_browser_dom_media(url, dom, output_ext=None, on_event=None):
    requested_ext = normalized_output_ext(output_ext)
    if requested_ext in AUDIO_OUTPUT_EXTENSIONS:
        raise RuntimeError("Browser DOM fallback does not expose audio-only candidates.")
    if requested_ext == ALL_OUTPUT_EXT:
        requested_ext = None
    title = display_title_from_browser_dom(dom)
    uploader = uploader_from_browser_dom(dom)
    thumbnail = thumbnail_from_browser_dom(dom)
    fallback_duration = duration_from_browser_dom(dom)
    fallback_size = size_from_browser_dom(dom)
    parsed = urllib.parse.urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    candidates = []
    seen = set()
    for item in [
        *media_definitions_from_html(dom),
        *player_script_media_from_html(dom),
        *generic_video_media_from_html(dom, url),
        *script_map_media_from_html(dom, url),
    ]:
        media_url = item.get("videoUrl") or item.get("url")
        if not media_url:
            continue
        media_url = absolute_browser_media_url(media_url, url)
        lower_url = media_url.lower()
        item_format = str(item.get("format") or "").lower()
        is_hls = ".m3u8" in lower_url or item_format == "hls" or "/media/hls" in lower_url
        is_dash = ".mpd" in lower_url or item_format == "dash"
        is_mp4 = (
            ".mp4" in lower_url
            or "/media/mp4" in lower_url
            or "/video/get_media" in lower_url
            or item_format == "mp4"
            or is_hls
        )
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
        size = safe_int(item.get("filesize") or item.get("filesize_approx") or fallback_size)
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
                "uploader": uploader,
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
    candidates = sort_candidates(enrich_missing_sizes(enrich_missing_durations(candidates)))
    if not candidates:
        raise RuntimeError("Browser DOM fallback found no downloadable media entries.")
    return {
        "url": url,
        "webpage_url": url,
        "title": title,
        "source": "browser-dom",
        "favicon_urls": favicon_candidate_urls(url, dom),
        "candidates": candidates,
        "warnings": [],
    }


def emit_playlist_analysis_events(result, on_event=None):
    if not on_event or not result.get("is_playlist"):
        return
    source_url = result.get("webpage_url") or result.get("url") or ""
    parent_id = result.get("playlist_id") or "playlist"
    count = safe_int(result.get("playlist_count")) or len(result.get("candidates") or [])
    emit_event(
        on_event,
        "playlist_parent",
        parent_id=parent_id,
        title=result.get("playlist_title") or result.get("title") or "Playlist",
        count=count,
        source_url=source_url,
        url=source_url,
    )
    for index, candidate in enumerate(result.get("candidates") or [], start=1):
        emit_event(on_event, "playlist_entry_loading", parent_id=parent_id, index=index, source_url=source_url, url=source_url)
        emit_event(
            on_event,
            "playlist_entry",
            parent_id=parent_id,
            index=index,
            candidate=candidate,
            candidates=[candidate],
            source_url=source_url,
            url=source_url,
        )
    emit_event(on_event, "playlist_complete", parent_id=parent_id, count=count, source_url=source_url, url=source_url)


def playlist_entry_url(entry, playlist_url=""):
    if not isinstance(entry, dict):
        return ""
    for key in ("webpage_url", "original_url", "url"):
        value = str(entry.get(key) or "").strip()
        if not value:
            continue
        if re.match(r"^https?://", value, re.IGNORECASE):
            return strip_playlist_query(value)
    entry_id = str(entry.get("id") or "").strip()
    parsed = urllib.parse.urlparse(str(playlist_url or ""))
    if entry_id and "youtube." in parsed.netloc.lower():
        return f"https://www.youtube.com/watch?v={urllib.parse.quote(entry_id)}"
    return ""


def playlist_extraction_url(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    query = urllib.parse.parse_qs(parsed.query)
    playlist_id = next((str(value or "").strip() for value in query.get("list", []) if str(value or "").strip()), "")
    host = parsed.netloc.lower().removeprefix("www.")
    if playlist_id and host in {"youtube.com", "m.youtube.com"}:
        return urllib.parse.urlunparse((parsed.scheme or "https", "www.youtube.com", "/playlist", "", urllib.parse.urlencode({"list": playlist_id}), ""))
    return url


def strip_playlist_query(url):
    parsed = urllib.parse.urlparse(str(url or ""))
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key.lower() not in {"list", "index", "pp", "start_radio"}]
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))


def analyze_playlist_progressively(
    url,
    cookie_source,
    ydl_factory,
    on_event=None,
    proxy_url=None,
    output_ext=None,
    browser_dom_fetcher=None,
    _force_single=False,
):
    options = build_ydl_options(
        cookie_source=cookie_source,
        on_event=on_event,
        quiet=True,
        proxy_url=proxy_url,
        allow_playlist=True,
    )
    options.update({"simulate": True, "skip_download": True, "check_formats": False, "extract_flat": "in_playlist"})
    emit_event(on_event, "status", message="Analyzing playlist")
    extract_url = playlist_extraction_url(url)
    with ydl_factory(options) as ydl:
        info = ydl.extract_info(extract_url, download=False)
    entries = [entry for entry in (info.get("entries") if isinstance(info, dict) else []) or [] if entry]
    if not entries:
        return None

    source_url = url
    playlist_title = clean_video_title(info.get("title") or info.get("playlist_title") or "") or "Playlist"
    count = safe_int(info.get("playlist_count") or info.get("n_entries") or len(entries))
    parent_id = info.get("id") or playlist_identity_key(url) or "playlist"
    emit_event(on_event, "playlist_parent", parent_id=parent_id, title=playlist_title, count=count, source_url=source_url, url=source_url)

    candidates = []
    download_infos = {}
    warnings = []
    for index, entry in enumerate(entries, start=1):
        entry_title = clean_video_title(entry.get("title") or "") or f"Video {index}"
        entry_url = playlist_entry_url(entry, playlist_url=url)
        emit_event(
            on_event,
            "playlist_entry_loading",
            parent_id=parent_id,
            index=index,
            title=entry_title,
            source_url=entry_url or source_url,
            url=entry_url or source_url,
        )
        if not entry_url:
            message = f"Playlist entry has no URL: {entry_title}"
            warnings.append(message)
            emit_event(on_event, "playlist_failed_entry", parent_id=parent_id, index=index, title=entry_title, source_url=source_url, url=source_url, message=message)
            continue
        try:
            child = analyze_url(
                entry_url,
                cookie_source=cookie_source,
                ydl_factory=ydl_factory,
                on_event=on_event,
                proxy_url=proxy_url,
                output_ext=output_ext,
                browser_dom_fetcher=browser_dom_fetcher,
                _force_single=True,
            )
            child_candidates = child.get("candidates") or []
            candidates.extend(child_candidates)
            download_infos.update(child.get("_download_infos") or {})
            emit_event(
                on_event,
                "playlist_entry",
                parent_id=parent_id,
                index=index,
                title=entry_title,
                analysis=child,
                candidates=child_candidates,
                candidate=child_candidates[0] if child_candidates else {},
                source_url=entry_url,
                url=entry_url,
            )
        except Exception as exc:
            message = strip_ansi(str(exc))
            warnings.append(f"{entry_title}: {message}")
            emit_event(on_event, "playlist_failed_entry", parent_id=parent_id, index=index, title=entry_title, source_url=entry_url, url=entry_url, message=message)

    emit_event(on_event, "playlist_complete", parent_id=parent_id, count=count, source_url=source_url, url=source_url)
    return {
        "url": url,
        "webpage_url": source_url,
        "title": playlist_title,
        "is_playlist": True,
        "playlist_title": playlist_title,
        "playlist_count": count,
        "candidates": sort_candidates(enrich_missing_sizes(candidates)),
        "_download_infos": download_infos,
        "warnings": warnings,
    }


def analyze_url(
    url,
    cookie_source="없음",
    ydl_factory=None,
    on_event=None,
    proxy_url=None,
    output_ext=None,
    browser_dom_fetcher=None,
    _force_single=False,
):
    if not str(url or "").strip():
        raise ValueError("URL is required.")
    url = str(url).strip()
    warnings = []

    if is_chzzk_page_url(url):
        chzzk = analyze_chzzk_clip(url, on_event=on_event, cookie_source=cookie_source)
        if chzzk:
            return chzzk
        chzzk = analyze_chzzk_video(url, on_event=on_event, cookie_source=cookie_source)
        if chzzk:
            return chzzk
        raise RuntimeError("CHZZK URL 분석에 실패했습니다. Firefox 로그인 쿠키를 선택하고 다시 시도하세요.")

    if ydl_factory is None:
        ydl_factory = youtube_dl_factory()

    allow_playlist = looks_like_playlist_url(url) and not _force_single
    analysis_url = strip_playlist_query(url) if is_youtube_radio_watch_url(url) else url

    if allow_playlist:
        progressive = analyze_playlist_progressively(
            url,
            cookie_source,
            ydl_factory,
            on_event=on_event,
            proxy_url=proxy_url,
            output_ext=output_ext,
            browser_dom_fetcher=browser_dom_fetcher,
        )
        if progressive:
            return progressive
        raise RuntimeError("Playlist analysis returned no entries.")

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
            return ydl.extract_info(analysis_url, download=False)

    def try_browser_dom_fallback(reason):
        try:
            fetcher = browser_dom_fetcher or fetch_dom_for_fallback
            dom = fetcher(analysis_url, on_event=on_event)
            result = analyze_browser_dom_media(analysis_url, dom, output_ext=output_ext, on_event=on_event)
            warning = "브라우저 DOM fallback 사용: " + str(reason)
            result["warnings"] = [*warnings, warning, *(result.get("warnings") or [])]
            emit_event(on_event, "log", message=warning)
            return result
        except Exception as browser_exc:
            warning = "브라우저 DOM fallback 실패: " + str(browser_exc)
            warnings.append(warning)
            emit_event(on_event, "log", message=warning)
            return None

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
        elif should_retry_with_browser_cookies(str(exc)):
            original_error = exc
            for browser_source in browser_cookie_sources_for_retry(cookie_source):
                warning = f"브라우저 쿠키로 재시도 ({browser_source}): " + str(exc)
                warnings.append(warning)
                emit_event(on_event, "log", message=warning)
                try:
                    info = extract_with(browser_source)
                    break
                except Exception as retry_exc:
                    pending_error = retry_exc
                    if browser_cookie_error(retry_exc):
                        continue
                    if should_retry_with_impersonation(str(retry_exc)) and chrome_impersonation_target():
                        try:
                            info = extract_with(browser_source, impersonate=True)
                            break
                        except Exception as impersonate_exc:
                            pending_error = impersonate_exc
                            if browser_cookie_error(impersonate_exc):
                                continue
            if info is None:
                pending_error = original_error
        elif cookie_spec(cookie_source) and browser_cookie_error(exc):
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
        if pending_error and should_try_browser_dom_fallback(str(pending_error)):
            result = try_browser_dom_fallback(pending_error)
            if result:
                return result
        if pending_error:
            raise pending_error
        raise RuntimeError("URL analysis failed.")

    candidates = sort_candidates(enrich_missing_sizes(candidates_from_info(info, output_ext=output_ext)))
    if not candidates:
        reason = RuntimeError("No downloadable non-audio video formats were found.")
        result = try_browser_dom_fallback(reason)
        if result:
            return result
        raise reason
    entries = info.get("entries") if isinstance(info, dict) else None
    is_playlist = bool(allow_playlist and entries)
    playlist_title = clean_video_title(info.get("title") or info.get("playlist_title") or "") if isinstance(info, dict) else ""
    webpage_url = info.get("webpage_url") or url
    result = {
        "url": url,
        "webpage_url": webpage_url,
        "title": clean_video_title(info.get("title") or candidates[0].get("title")) or "video",
        "is_playlist": is_playlist,
        "playlist_title": playlist_title,
        "playlist_count": safe_int(info.get("playlist_count") or info.get("n_entries") or (len(entries) if entries else 0)),
        "candidates": candidates,
        "_download_infos": {} if is_youtube_url(webpage_url) else download_infos_from_info(info),
        "warnings": warnings,
    }
    emit_playlist_analysis_events(result, on_event=on_event)
    return result


def is_direct_https_mp4_candidate(candidate):
    format_id = str((candidate or {}).get("format_id") or "")
    if not format_id.startswith("browser-"):
        return False
    if (candidate or {}).get("is_manifest"):
        return False
    media_url = str((candidate or {}).get("url") or "").lower()
    if not media_url.startswith(("http://", "https://")):
        return False
    if ".m3u8" in media_url or ".mpd" in media_url:
        return False
    return media_url.endswith(".mp4") or ".mp4?" in media_url or ".mp4&" in media_url


def chzzk_source_hint(*values):
    for value in values:
        text = str(value or "")
        if "chzzk.naver.com/" in text:
            return text
    return ""


def is_chzzk_page_url(url):
    return bool(find_chzzk_clip_uid(url) or find_chzzk_video_no(url) or chzzk_source_hint(url))


def candidate_looks_chzzk(candidate, page_url=""):
    candidate = candidate or {}
    if str(candidate.get("format_id") or "").startswith("chzzk-"):
        return True
    return bool(
        chzzk_source_hint(
            candidate.get("source"),
            candidate.get("webpage_url"),
            candidate.get("source_url"),
            page_url,
        )
    ) or is_chzzk_page_url(page_url)


def is_chzzk_direct_mp4_candidate(candidate, page_url=""):
    candidate = candidate or {}
    if not candidate_looks_chzzk(candidate, page_url):
        return False
    media_url = str(candidate.get("url") or "").lower()
    return media_url.startswith(("http://", "https://")) and ".mp4" in media_url


def is_chzzk_hls_candidate(candidate, page_url=""):
    candidate = candidate or {}
    if not candidate_looks_chzzk(candidate, page_url):
        return False
    media_url = str(candidate.get("url") or "").lower()
    return media_url.startswith(("http://", "https://")) and ".m3u8" in media_url


def merge_chzzk_analysis_candidate(base, fresh):
    merged = dict(fresh or {})
    for key in (
        "clip_range",
        "clip_cut_mode",
        "title",
        "display_title",
        "source_duration",
        "source_filesize",
        "_clipflow_row_id",
    ):
        value = (base or {}).get(key)
        if value is not None and value != "":
            merged[key] = value
    if merged.get("clip_range"):
        merged = candidate_with_clip_range_metadata(merged)
    return merged


def chzzk_auto_route_enabled(candidate, total):
    if not candidate_looks_chzzk(candidate, candidate.get("source") or ""):
        return False
    if clip_range_from_candidate(candidate):
        return False
    return safe_int(total) >= CHZZK_AUTO_ROUTE_MIN_BYTES


def chzzk_probe_direct_speed(url, headers, probe_bytes=None, offset=0):
    probe_bytes = max(1, safe_int(probe_bytes or CHZZK_ROUTE_PROBE_BYTES))
    offset = max(0, safe_int(offset))
    range_headers = {**dict(headers or {}), "Range": f"bytes={offset}-{offset + probe_bytes - 1}"}
    request = urllib.request.Request(str(url or ""), headers=range_headers)
    started = time.monotonic()
    try:
        with parallel_http_urlopen(request, timeout=CHZZK_ROUTE_PROBE_TIMEOUT) as response:
            if safe_int(getattr(response, "status", 206)) not in {200, 206}:
                return 0.0
            data = response.read()
    except (OSError, urllib.error.URLError, RuntimeError, ValueError):
        return 0.0
    elapsed = time.monotonic() - started
    if not data or elapsed <= 0:
        return 0.0
    return len(data) / elapsed


def chzzk_probe_hls_speed(url, headers, segment_count=None):
    segment_count = max(1, safe_int(segment_count or CHZZK_ROUTE_PROBE_HLS_SEGMENTS))
    try:
        playlist_url, playlist_text = resolve_hls_media_playlist(url, headers)
        playlist_meta = parse_hls_media_playlist(playlist_text, playlist_url)
        segment_urls = list(playlist_meta.get("segment_urls") or [])[:segment_count]
        if not segment_urls:
            return 0.0
        started = time.monotonic()
        downloaded = 0
        for segment_url in segment_urls:
            request = urllib.request.Request(segment_url, headers=dict(headers or {}))
            with parallel_http_urlopen(request, timeout=CHZZK_ROUTE_PROBE_TIMEOUT) as response:
                while True:
                    chunk = response.read(HLS_SEGMENT_READ_CHUNK)
                    if not chunk:
                        break
                    downloaded += len(chunk)
        elapsed = time.monotonic() - started
        if downloaded <= 0 or elapsed <= 0:
            return 0.0
        return downloaded / elapsed
    except (OSError, urllib.error.URLError, RuntimeError, ValueError):
        return 0.0


def chzzk_media_url_host(url):
    try:
        return urllib.parse.urlparse(str(url or "")).netloc or ""
    except ValueError:
        return ""


def chzzk_probe_direct_speed_profile(url, headers, total):
    total = max(1, safe_int(total))
    probe_bytes = CHZZK_ROUTE_PROBE_BYTES
    mid_offset = min(max(probe_bytes, total // 2), max(0, total - probe_bytes))
    start_bps = chzzk_probe_direct_speed(url, headers, probe_bytes=probe_bytes, offset=0)
    mid_bps = 0.0
    if total > probe_bytes * 2:
        mid_bps = chzzk_probe_direct_speed(url, headers, probe_bytes=probe_bytes, offset=mid_offset)
    throttle_ratio = (mid_bps / start_bps) if start_bps > 0 and mid_bps > 0 else 0.0
    throttle_detected = bool(
        start_bps > 0
        and mid_bps > 0
        and throttle_ratio < CHZZK_DIRECT_RANGE_THROTTLE_RATIO
    )
    return {
        "start_bps": start_bps,
        "mid_bps": mid_bps,
        "mid_offset": mid_offset,
        "throttle_ratio": throttle_ratio,
        "throttle_detected": throttle_detected,
    }


def chzzk_hls_route_profile(url, headers):
    profile = {
        "segment_count": 0,
        "probe_bps": 0.0,
        "encrypted": False,
        "fmp4": False,
    }
    try:
        playlist_url, playlist_text = resolve_hls_media_playlist(url, headers)
        playlist_meta = parse_hls_media_playlist(playlist_text, playlist_url)
        segment_urls = list(playlist_meta.get("segment_urls") or [])
        profile["segment_count"] = len(segment_urls)
        profile["fmp4"] = bool(playlist_meta.get("init_map_url"))
        profile["encrypted"] = hls_playlist_parallel_encryption(playlist_text) == "aes-128"
        profile["probe_bps"] = chzzk_probe_hls_speed(url, headers)
    except (OSError, urllib.error.URLError, RuntimeError, ValueError):
        pass
    return profile


def chzzk_route_signal_scores(direct_profile, hls_profile, direct_candidate, total, duration):
    direct_score = 0.0
    hls_score = 0.0
    reasons = []

    if direct_profile.get("throttle_detected"):
        hls_score += 4.0
        reasons.append(f"direct-range-throttle(ratio={direct_profile.get('throttle_ratio', 0):.2f})")
    elif float(direct_profile.get("throttle_ratio") or 0) >= 0.85:
        direct_score += 2.0
        reasons.append("direct-range-stable")

    start_bps = float(direct_profile.get("start_bps") or 0)
    hls_bps = float(hls_profile.get("probe_bps") or 0)
    if hls_bps > 0 and start_bps > 0:
        if hls_bps > start_bps * 1.15:
            hls_score += 3.0
            reasons.append(f"hls-probe-faster({display_size(hls_bps)}/s)")
        elif start_bps > hls_bps * 1.15:
            direct_score += 3.0
            reasons.append(f"direct-probe-faster({display_size(start_bps)}/s)")

    total = safe_int(total)
    duration = safe_int(duration)
    if total >= CHZZK_ROUTE_LARGE_VOD_BYTES and duration >= CHZZK_ROUTE_LONG_VOD_SECONDS:
        hls_score += 2.0
        reasons.append("large-long-vod")

    segment_count = safe_int(hls_profile.get("segment_count"))
    if segment_count >= 300:
        hls_score += 1.0
        reasons.append(f"hls-many-segments({segment_count})")

    workers = direct_media_worker_count(direct_candidate)
    part_size = direct_media_part_size_for_candidate(total, direct_candidate, workers)
    range_count = len(list(direct_media_ranges(total, part_size=part_size)))
    if range_count <= workers * 2 and direct_profile.get("throttle_detected"):
        hls_score += 1.0
        reasons.append(f"direct-few-ranges({range_count})")

    if hls_profile.get("encrypted"):
        hls_score += 0.5
        reasons.append("hls-encrypted")

    return direct_score, hls_score, reasons


def chzzk_alternative_direct_candidate(candidate, page_url, cookie_source, on_event=None):
    hint = chzzk_source_hint(
        candidate.get("source"),
        candidate.get("webpage_url"),
        candidate.get("source_url"),
        page_url,
    )
    if not hint:
        return None
    analysis = analyze_chzzk_clip(hint, on_event=on_event, cookie_source=cookie_source)
    if not analysis:
        analysis = analyze_chzzk_video(hint, on_event=on_event, cookie_source=cookie_source)
    if not analysis:
        return None
    target_height = safe_int(candidate.get("height"))
    picks = analysis.get("candidates") or []
    for item in picks:
        if is_chzzk_direct_mp4_candidate(item, hint) and safe_int(item.get("height")) == target_height:
            return merge_chzzk_analysis_candidate(candidate, item)
    for item in picks:
        if is_chzzk_direct_mp4_candidate(item, hint):
            return merge_chzzk_analysis_candidate(candidate, item)
    return None


def chzzk_alternative_hls_candidate(candidate, page_url, cookie_source, on_event=None):
    hint = chzzk_source_hint(
        candidate.get("source"),
        candidate.get("webpage_url"),
        candidate.get("source_url"),
        page_url,
    )
    if not hint:
        return None
    analysis = analyze_chzzk_clip(hint, on_event=on_event, cookie_source=cookie_source)
    if not analysis:
        analysis = analyze_chzzk_video(hint, on_event=on_event, cookie_source=cookie_source)
    if not analysis:
        return None
    target_height = safe_int(candidate.get("height"))
    picks = analysis.get("candidates") or []
    for item in picks:
        if is_chzzk_hls_candidate(item, hint) and safe_int(item.get("height")) == target_height:
            return merge_chzzk_analysis_candidate(candidate, item)
    for item in picks:
        if is_chzzk_hls_candidate(item, hint):
            return merge_chzzk_analysis_candidate(candidate, item)
    return None


def chzzk_paired_route_candidates(candidate, page_url, cookie_source, on_event=None):
    candidate = dict(candidate or {})
    hint = page_url
    direct_candidate = candidate if is_chzzk_direct_mp4_candidate(candidate, hint) else None
    hls_candidate = candidate if is_chzzk_hls_candidate(candidate, hint) else None
    if not direct_candidate:
        direct_candidate = chzzk_alternative_direct_candidate(candidate, page_url, cookie_source, on_event=on_event)
    if not hls_candidate:
        hls_candidate = chzzk_alternative_hls_candidate(candidate, page_url, cookie_source, on_event=on_event)
    return direct_candidate, hls_candidate


def chzzk_choose_download_route(direct_candidate, hls_candidate, total=0, duration=0, on_event=None):
    direct_candidate = dict(direct_candidate or {})
    hls_candidate = dict(hls_candidate or {})
    direct_url = str(direct_candidate.get("url") or "")
    hls_url = str(hls_candidate.get("url") or "")
    if not direct_url:
        return "hls", hls_candidate
    if not hls_url:
        return "direct", direct_candidate

    total = safe_int(total) or candidate_expected_size(direct_candidate)
    duration = safe_int(duration) or safe_int(direct_candidate.get("duration")) or safe_int(hls_candidate.get("duration"))

    emit_event(on_event, "status", message="CHZZK direct/HLS 경로 분석 중")
    direct_headers = direct_media_request_headers(direct_candidate)
    hls_headers = direct_media_request_headers(hls_candidate)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        direct_future = executor.submit(chzzk_probe_direct_speed_profile, direct_url, direct_headers, total)
        hls_future = executor.submit(chzzk_hls_route_profile, hls_url, hls_headers)
        direct_profile = direct_future.result()
        hls_profile = hls_future.result()

    direct_score, hls_score, reasons = chzzk_route_signal_scores(
        direct_profile,
        hls_profile,
        direct_candidate,
        total,
        duration,
    )

    emit_event(
        on_event,
        "log",
        message=(
            f"CHZZK route signals direct_host={chzzk_media_url_host(direct_url)} "
            f"start={display_size(direct_profile.get('start_bps'))}/s "
            f"mid@{direct_profile.get('mid_offset')}={display_size(direct_profile.get('mid_bps'))}/s "
            f"throttle={'yes' if direct_profile.get('throttle_detected') else 'no'}"
        ),
    )
    emit_event(
        on_event,
        "log",
        message=(
            f"CHZZK route signals hls_host={chzzk_media_url_host(hls_url)} "
            f"segments={hls_profile.get('segment_count')} "
            f"probe={display_size(hls_profile.get('probe_bps'))}/s "
            f"fmp4={'yes' if hls_profile.get('fmp4') else 'no'} "
            f"encrypted={'yes' if hls_profile.get('encrypted') else 'no'}"
        ),
    )
    emit_event(
        on_event,
        "log",
        message=(
            f"CHZZK route signals vod total={display_size(total)} "
            f"duration={display_duration(duration) if duration else 'unknown'}"
        ),
    )

    if direct_score <= 0 and hls_score <= 0:
        emit_event(on_event, "log", message="CHZZK route signals inconclusive; defaulting to direct")
        return "direct", direct_candidate

    if hls_score > direct_score:
        route = "hls"
        chosen = hls_candidate
    elif direct_score > hls_score:
        route = "direct"
        chosen = direct_candidate
    else:
        start_bps = float(direct_profile.get("start_bps") or 0)
        hls_bps = float(hls_profile.get("probe_bps") or 0)
        if hls_bps > start_bps:
            route = "hls"
            chosen = hls_candidate
        else:
            route = "direct"
            chosen = direct_candidate

    emit_event(
        on_event,
        "log",
        message=(
            f"CHZZK auto-route: selected {route} "
            f"(score direct={direct_score:.1f} hls={hls_score:.1f}; {', '.join(reasons) or 'tie-break'})"
        ),
    )
    return route, chosen


def refresh_chzzk_candidate_media(candidate, page_url, cookie_source, on_event=None):
    candidate = dict(candidate or {})
    if is_chzzk_direct_mp4_candidate(candidate, page_url) or is_chzzk_hls_candidate(candidate, page_url):
        return candidate
    hint = chzzk_source_hint(
        candidate.get("source"),
        candidate.get("webpage_url"),
        candidate.get("source_url"),
        page_url,
    )
    if not hint:
        return candidate
    analysis = analyze_chzzk_clip(hint, on_event=on_event, cookie_source=cookie_source)
    if not analysis:
        analysis = analyze_chzzk_video(hint, on_event=on_event, cookie_source=cookie_source)
    if not analysis:
        return candidate
    wanted_id = str(candidate.get("format_id") or "")
    picks = analysis.get("candidates") or []
    for item in picks:
        if wanted_id and item.get("format_id") == wanted_id:
            return merge_chzzk_analysis_candidate(candidate, item)
    for item in picks:
        if is_chzzk_direct_mp4_candidate(item, hint):
            return merge_chzzk_analysis_candidate(candidate, item)
    for item in picks:
        if is_chzzk_hls_candidate(item, hint):
            return merge_chzzk_analysis_candidate(candidate, item)
    return candidate


def download_chzzk_candidate(page_url, candidate, output_dir, cookie_source="없음", on_event=None):
    if not candidate_looks_chzzk(candidate, page_url):
        return None
    candidate = refresh_chzzk_candidate_media(candidate, page_url, cookie_source, on_event=on_event)
    candidate = dict(candidate or {})
    candidate.pop("_download_info", None)
    candidate.pop("_download_info_key", None)
    chzzk_source = chzzk_source_hint(
        candidate.get("source"),
        candidate.get("webpage_url"),
        candidate.get("source_url"),
        page_url,
    )
    if chzzk_source and "chzzk.naver.com/" not in str(candidate.get("source") or ""):
        candidate["source"] = chzzk_source
    if not is_chzzk_direct_mp4_candidate(candidate, page_url) and not is_chzzk_hls_candidate(candidate, page_url):
        raise RuntimeError(
            "CHZZK 미디어 URL을 찾지 못했습니다. Firefox 로그인 쿠키를 선택하고 다시 분석하세요."
        )
    target_url = candidate.get("url") or page_url
    if candidate.get("format_selector") == "best" and candidate.get("url"):
        target_url = candidate["url"]
    candidate = candidate_with_request_cookies(candidate, cookie_source)
    media_url = str(candidate.get("url") or "").strip()
    if media_url:
        target_url = media_url
    if clip_range_from_candidate(candidate):
        if is_chzzk_direct_mp4_candidate(candidate, page_url):
            return download_direct_media_segment(target_url, candidate, output_dir, on_event=on_event)
        emit_event(
            on_event,
            "log",
            message=(
                f"CHZZK route=hls workers={HLS_PARALLEL_WORKERS} "
                f"max_in_flight={HLS_PARALLEL_MAX_IN_FLIGHT} url_ext=hls"
            ),
        )
        return download_hls_parallel(target_url, candidate, output_dir, on_event=on_event)

    headers = direct_media_request_headers(candidate)
    total = resolve_direct_media_total(target_url, headers, candidate) if is_chzzk_direct_mp4_candidate(candidate, page_url) else 0
    if not total:
        total = candidate_expected_size(candidate)
    if chzzk_auto_route_enabled(candidate, total):
        direct_candidate, hls_candidate = chzzk_paired_route_candidates(
            candidate,
            page_url,
            cookie_source,
            on_event=on_event,
        )
        if direct_candidate:
            direct_candidate = candidate_with_request_cookies(direct_candidate, cookie_source)
        if hls_candidate:
            hls_candidate = candidate_with_request_cookies(hls_candidate, cookie_source)
        if direct_candidate and hls_candidate:
            route, chosen = chzzk_choose_download_route(
                direct_candidate,
                hls_candidate,
                total=total,
                duration=safe_int(candidate.get("duration")),
                on_event=on_event,
            )
            if route == "hls":
                hls_url = str(chosen.get("url") or "").strip() or target_url
                emit_event(
                    on_event,
                    "log",
                    message=(
                        f"CHZZK route=hls workers={HLS_PARALLEL_WORKERS} "
                        f"max_in_flight={HLS_PARALLEL_MAX_IN_FLIGHT} url_ext=hls"
                    ),
                )
                return download_hls_parallel(hls_url, chosen, output_dir, on_event=on_event)
            direct_url = str(chosen.get("url") or "").strip() or target_url
            return download_direct_media(direct_url, chosen, output_dir, on_event=on_event)
        if direct_candidate:
            direct_url = str(direct_candidate.get("url") or "").strip() or target_url
            return download_direct_media(direct_url, direct_candidate, output_dir, on_event=on_event)
        if hls_candidate:
            hls_url = str(hls_candidate.get("url") or "").strip() or target_url
            emit_event(
                on_event,
                "log",
                message=(
                    f"CHZZK route=hls workers={HLS_PARALLEL_WORKERS} "
                    f"max_in_flight={HLS_PARALLEL_MAX_IN_FLIGHT} url_ext=hls"
                ),
            )
            return download_hls_parallel(hls_url, hls_candidate, output_dir, on_event=on_event)

    if is_chzzk_direct_mp4_candidate(candidate, page_url):
        return download_direct_media(target_url, candidate, output_dir, on_event=on_event)
    emit_event(
        on_event,
        "log",
        message=(
            f"CHZZK route=hls workers={HLS_PARALLEL_WORKERS} "
            f"max_in_flight={HLS_PARALLEL_MAX_IN_FLIGHT} url_ext=hls"
        ),
    )
    return download_hls_parallel(target_url, candidate, output_dir, on_event=on_event)


def is_browser_dom_manifest_candidate(candidate):
    format_id = str((candidate or {}).get("format_id") or "")
    if not format_id.startswith("browser-"):
        return False
    media_url = str((candidate or {}).get("url") or "").lower()
    return bool((candidate or {}).get("is_manifest")) or ".m3u8" in media_url or ".mpd" in media_url


def direct_media_request_headers(candidate):
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": ACCEPT_LANGUAGE,
    }
    source = str((candidate or {}).get("source") or "")
    if source.startswith(("http://", "https://")):
        headers["Referer"] = source
    cookie_header = str((candidate or {}).get("_cookie_header") or "").strip()
    if cookie_header:
        headers["Cookie"] = cookie_header
    return headers


def manifest_progress_total_bytes(candidate, part_size, current_sec, duration_sec):
    expected = candidate_expected_size(candidate)
    if expected > 0:
        return expected
    if not part_size or not current_sec or not duration_sec:
        return 0
    if current_sec < max(3.0, duration_sec * 0.15):
        return 0
    extrapolated = int(part_size * duration_sec / current_sec)
    if duration_sec <= 900:
        return min(extrapolated, 16 * 1024 * 1024)
    return extrapolated


def browser_dom_manifest_movflags(candidate):
    expected = candidate_expected_size(candidate)
    if 0 < expected < 16 * 1024 * 1024:
        return None
    duration = safe_int((candidate or {}).get("duration"))
    if duration and duration <= 180 and not expected:
        return None
    return "+faststart"


def byte_download_eta_seconds(downloaded_bytes, total_bytes, speed_bps):
    total_bytes = safe_int(total_bytes)
    downloaded_bytes = max(0, safe_int(downloaded_bytes))
    speed_bps = float(speed_bps or 0)
    if total_bytes <= 0 or speed_bps <= 0 or downloaded_bytes >= total_bytes:
        return 0
    return max(0, int((total_bytes - downloaded_bytes) / speed_bps))


def emit_byte_download_progress(on_event, downloaded_bytes, total_bytes, speed_bps, percent=None):
    total_bytes = safe_int(total_bytes)
    downloaded_bytes = max(0, safe_int(downloaded_bytes))
    if not total_bytes:
        return
    if percent is None:
        percent = max(0, min(100, downloaded_bytes * 100 / total_bytes))
    speed_label = f"{display_size(speed_bps)}/s" if speed_bps > 0 else ""
    eta = byte_download_eta_seconds(downloaded_bytes, total_bytes, speed_bps)
    eta_text = display_duration(eta) if eta > 0 else ""
    message = f"{percent:.1f}%"
    if speed_label:
        message = f"{message} · {speed_label}"
    if eta_text:
        message = f"{message} · ETA {eta_text}"
    emit_event(
        on_event,
        "progress",
        percent=percent,
        downloaded=downloaded_bytes,
        total=total_bytes,
        speed=speed_bps,
        speed_text=speed_label,
        eta_text=eta_text,
        message=message,
    )


def emit_manifest_download_progress(
    on_event,
    current_sec,
    duration_sec,
    downloaded_bytes=0,
    total_bytes=0,
    started_at=None,
    last_bytes=0,
    last_emit_at=None,
):
    if not duration_sec:
        return
    percent = max(0, min(100, current_sec * 100 / duration_sec))
    if total_bytes and downloaded_bytes:
        percent = max(percent, min(100, downloaded_bytes * 100 / total_bytes))
    speed_bps = 0.0
    now = time.monotonic()
    if last_emit_at is not None and downloaded_bytes > last_bytes:
        elapsed = max(0.001, now - float(last_emit_at))
        speed_bps = max(0.0, (downloaded_bytes - last_bytes) / elapsed)
    elif started_at is not None and downloaded_bytes > 0:
        elapsed = max(0.001, now - float(started_at))
        speed_bps = downloaded_bytes / elapsed
    speed_label = f"{display_size(speed_bps)}/s" if speed_bps > 0 else ""
    eta_text = ""
    if speed_bps > 0 and safe_int(total_bytes) > 0:
        eta = byte_download_eta_seconds(downloaded_bytes, total_bytes, speed_bps)
        eta_text = display_duration(eta) if eta > 0 else ""
    if speed_label and eta_text:
        message = f"{percent:.1f}% · {speed_label} · ETA {eta_text}"
    elif speed_label:
        message = f"{percent:.1f}% · {speed_label}"
    elif eta_text:
        message = f"{percent:.1f}% · ETA {eta_text}"
    else:
        message = f"{percent:.1f}%"
    emit_event(
        on_event,
        "progress",
        percent=percent,
        downloaded=downloaded_bytes,
        total=total_bytes,
        speed=speed_bps,
        speed_text=speed_label,
        eta_text=eta_text,
        message=message,
    )


def emit_direct_download_progress(on_event, downloaded, total, started_at, last_bytes=0, last_emit_at=None):
    if not total:
        return
    now = time.monotonic()
    speed = 0.0
    if last_emit_at is not None and downloaded > last_bytes:
        speed = max(0.0, (downloaded - last_bytes) / max(0.001, now - float(last_emit_at)))
    elif started_at is not None and downloaded > 0:
        speed = downloaded / max(0.001, now - float(started_at))
    emit_byte_download_progress(on_event, downloaded, total, speed)


def download_direct_media_single(url, output_path, headers, total=0, on_event=None):
    part_path = output_path.with_name(output_path.name + ".part")
    existing_size = part_path.stat().st_size if part_path.exists() else 0
    if total and existing_size >= total:
        return part_path
    request_headers = dict(headers or {})
    append = existing_size > 0
    if append:
        request_headers["Range"] = f"bytes={existing_size}-"
    request = urllib.request.Request(url, headers=request_headers)
    downloaded = existing_size if append else 0
    started_at = time.monotonic()
    last_progress = {"time": 0.0, "bytes": 0}
    with parallel_http_urlopen(request, timeout=30) as response:
        if append and safe_int(getattr(response, "status", 200)) != 206:
            append = False
            downloaded = 0
        content_length = safe_int(response.headers.get("Content-Length"))
        total = total or (existing_size + content_length if append and content_length else content_length)
        with part_path.open("ab" if append else "wb") as file:
            if downloaded and total:
                emit_direct_download_progress(on_event, downloaded, total, started_at)
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                file.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if total and (now - last_progress["time"] >= 0.25 or downloaded >= total):
                    emit_direct_download_progress(
                        on_event,
                        downloaded,
                        total,
                        started_at,
                        last_bytes=last_progress["bytes"],
                        last_emit_at=last_progress["time"] or None,
                    )
                    last_progress["time"] = now
                    last_progress["bytes"] = downloaded
    if total and downloaded != total:
        raise RuntimeError(f"Direct media download incomplete: downloaded {downloaded} bytes, expected {total}.")
    return part_path


def direct_media_parallel_part_size(total, workers=None):
    workers = max(1, safe_int(workers or DIRECT_MEDIA_PARALLEL_WORKERS))
    total = max(1, safe_int(total))
    if total < DIRECT_MEDIA_PARALLEL_MIN_SIZE:
        return total
    if total < DIRECT_MEDIA_PARALLEL_THRESHOLD:
        target_parts = max(workers * 4, workers * 2, workers)
        adaptive = (total + target_parts - 1) // target_parts
        return max(1, min(DIRECT_MEDIA_PARALLEL_PART_SIZE, adaptive))
    # Large files: one range per worker lane, not thousands of 16 MB shards.
    return max(DIRECT_MEDIA_PARALLEL_PART_SIZE, (total + workers - 1) // workers)


def direct_media_worker_count(candidate):
    if candidate_looks_chzzk(candidate, candidate.get("source") or ""):
        return max(1, min(16, safe_int(CHZZK_DIRECT_MEDIA_WORKERS)))
    return DIRECT_MEDIA_PARALLEL_WORKERS


def direct_media_part_size_for_candidate(total, candidate, workers):
    workers = max(1, safe_int(workers))
    total = max(1, safe_int(total))
    if candidate_looks_chzzk(candidate, candidate.get("source") or ""):
        return max(
            DIRECT_MEDIA_PARALLEL_PART_SIZE,
            min(
                CHZZK_DIRECT_MEDIA_PART_SIZE,
                (total + workers * 4 - 1) // (workers * 4),
            ),
        )
    return direct_media_parallel_part_size(total, workers=workers)


def should_use_parallel_direct_download(url, headers, total):
    total = safe_int(total)
    if total <= 0:
        return False
    if total >= DIRECT_MEDIA_PARALLEL_THRESHOLD:
        return True
    if total < DIRECT_MEDIA_PARALLEL_MIN_SIZE:
        return False
    return direct_media_range_supported(url, headers)


def direct_media_ranges(total, part_size=None):
    part_size = max(1, safe_int(part_size or direct_media_parallel_part_size(total)))
    start = 0
    index = 0
    while start < total:
        end = min(total - 1, start + part_size - 1)
        yield index, start, end
        index += 1
        start = end + 1


def direct_media_range_supported(url, headers):
    range_headers = {**headers, "Range": "bytes=0-0"}
    request = urllib.request.Request(url, headers=range_headers)
    with parallel_http_urlopen(request, timeout=30) as response:
        if safe_int(getattr(response, "status", 206)) != 206:
            return False
        content_range = str(getattr(response, "headers", {}).get("Content-Range", "") or "")
        return not content_range or content_range.lower().startswith("bytes ")


def parse_http_range_header(range_header, total):
    text = str(range_header or "").strip()
    if not text:
        return 0, max(0, total - 1), False
    match = re.match(r"^bytes=(\d*)-(\d*)$", text)
    if not match:
        raise ValueError("Unsupported range header")
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        raise ValueError("Unsupported range header")
    if start_text:
        start = safe_int(start_text)
        end = safe_int(end_text) if end_text else total - 1
    else:
        suffix = safe_int(end_text)
        start = max(0, total - suffix)
        end = total - 1
    if start < 0 or end < start or start >= total:
        raise ValueError("Invalid range")
    return start, min(end, total - 1), True


@contextlib.contextmanager
def direct_media_parallel_proxy_url(url, headers, total, workers=None, part_size=None):
    total = safe_int(total)
    if total <= 0:
        yield url
        return
    workers = max(1, safe_int(workers or DIRECT_MEDIA_PARALLEL_WORKERS))
    part_size = max(1, safe_int(part_size or DIRECT_MEDIA_PROXY_PART_SIZE))
    remote_headers = dict(headers or {})
    stop_event = threading.Event()

    def fetch_range(start, end):
        if stop_event.is_set():
            return b""
        request = urllib.request.Request(url, headers={**remote_headers, "Range": f"bytes={start}-{end}"})
        with parallel_http_urlopen(request, timeout=30) as response:
            if safe_int(getattr(response, "status", 206)) != 206:
                raise DirectMediaRangeUnsupported("Direct media proxy range request was not honored.")
            data = response.read()
        expected = end - start + 1
        if len(data) != expected:
            raise RuntimeError(f"Direct media proxy range returned {len(data)} bytes, expected {expected}.")
        return data

    class RangeProxyHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format, *args):
            return

        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(total))
            self.send_header("Content-Type", "video/mp4")
            self.end_headers()

        def do_GET(self):
            try:
                start, end, ranged = parse_http_range_header(self.headers.get("Range"), total)
            except ValueError:
                self.send_error(416)
                return
            length = end - start + 1
            self.send_response(206 if ranged else 200)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(length))
            if ranged:
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
            self.end_headers()
            self.stream_range(start, end)

        def stream_range(self, start, end):
            chunk_ranges = []
            cursor = start
            while cursor <= end:
                chunk_end = min(end, cursor + part_size - 1)
                chunk_ranges.append((cursor, chunk_end))
                cursor = chunk_end + 1
            next_index = 0
            pending = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                def submit_more():
                    nonlocal next_index
                    while next_index < len(chunk_ranges) and len(pending) < workers and not stop_event.is_set():
                        chunk_start, chunk_end = chunk_ranges[next_index]
                        pending[next_index] = executor.submit(fetch_range, chunk_start, chunk_end)
                        next_index += 1

                submit_more()
                current = 0
                try:
                    while current < len(chunk_ranges) and not stop_event.is_set():
                        future = pending.pop(current)
                        data = future.result()
                        if not data:
                            break
                        self.wfile.write(data)
                        submit_more()
                        current += 1
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    return
                finally:
                    executor.shutdown(wait=False, cancel_futures=True)

    class ThreadingHTTPServer(http.server.ThreadingHTTPServer):
        daemon_threads = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), RangeProxyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/media"
    finally:
        stop_event.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def download_direct_media_parallel(url, output_path, headers, total, on_event=None, part_size=None, workers=None, slow_check=None):
    worker_count = max(1, safe_int(workers or DIRECT_MEDIA_PARALLEL_WORKERS))
    part_path = output_path.with_name(output_path.name + ".part")
    resolved_part_size = max(
        1,
        safe_int(part_size or direct_media_parallel_part_size(total, workers=worker_count)),
    )
    downloaded = 0
    downloaded_lock = threading.Lock()
    progress_lock = threading.Lock()
    started_at = time.monotonic()
    last_progress = {"value": 0.0, "bytes": 0}
    abort_event = threading.Event()

    def report(delta):
        nonlocal downloaded
        now = time.monotonic()
        with downloaded_lock:
            downloaded += delta
            current = downloaded
        if abort_event.is_set():
            raise ChzzkDirectSlowFallback("CHZZK direct download aborted for HLS fallback")
        if slow_check:
            slow_check(current, now - started_at)
        with progress_lock:
            if now - last_progress["value"] >= 0.25 or current >= total:
                emit_direct_download_progress(
                    on_event,
                    current,
                    total,
                    started_at,
                    last_bytes=last_progress["bytes"],
                    last_emit_at=last_progress["value"] or None,
                )
                last_progress["value"] = now
                last_progress["bytes"] = current

    def download_range(range_info):
        index, start, end, segment_path = range_info
        expected = end - start + 1
        existing_size = segment_path.stat().st_size if segment_path.exists() else 0
        if existing_size == expected:
            report(expected)
            return index, segment_path
        resume_start = start + existing_size if 0 < existing_size < expected else start
        mode = "ab" if resume_start > start else "wb"
        range_headers = {**headers, "Range": f"bytes={resume_start}-{end}"}
        request = urllib.request.Request(url, headers=range_headers)
        written = existing_size if mode == "ab" else 0
        with parallel_http_urlopen(request, timeout=30) as response:
            if safe_int(getattr(response, "status", 206)) != 206:
                raise DirectMediaRangeUnsupported("Direct media range request was not honored.")
            with segment_path.open(mode) as file:
                if mode == "ab":
                    report(existing_size)
                while True:
                    if abort_event.is_set():
                        raise ChzzkDirectSlowFallback("CHZZK direct download aborted for HLS fallback")
                    chunk = response.read(1024 * 512)
                    if not chunk:
                        break
                    file.write(chunk)
                    written += len(chunk)
                    report(len(chunk))
        if written != expected:
            raise RuntimeError(f"Direct media range returned {written} bytes, expected {expected}.")
        return index, segment_path

    with tempfile.TemporaryDirectory(prefix="clipflow-direct-") as temp_dir:
        temp_root = Path(temp_dir)
        ranges = [
            (index, start, end, temp_root / f"seg_{index:08d}.part")
            for index, start, end in direct_media_ranges(total, part_size=resolved_part_size)
        ]
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
                completed = sorted(executor.map(download_range, ranges), key=lambda item: item[0])
        except ChzzkDirectSlowFallback:
            abort_event.set()
            if part_path.exists():
                part_path.unlink()
            raise
        emit_event(on_event, "status", message="Finalizing direct download")
        with part_path.open("wb") as output_file:
            for _index, segment_path in completed:
                with segment_path.open("rb") as segment_file:
                    shutil.copyfileobj(segment_file, output_file, 1024 * 1024)
    return part_path


def resolve_direct_media_total(url, headers, candidate):
    estimated = candidate_expected_size(candidate)
    probed = http_content_length(url, headers=headers)
    return probed or estimated


def download_direct_media(url, candidate, output_dir, on_event=None, slow_check=None):
    output_dir = Path(output_dir).expanduser()
    output_path = final_output_path_for_candidate(candidate, output_dir)
    if output_path is None:
        raise RuntimeError("Direct media output path could not be determined.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    headers = direct_media_request_headers(candidate)
    estimated = candidate_expected_size(candidate)
    probed = http_content_length(url, headers=headers)
    total = probed or estimated
    if estimated and probed and estimated != probed:
        emit_event(
            on_event,
            "log",
            message=f"Direct size: estimated={display_size(estimated)}, probed={display_size(probed)}",
        )
    worker_count = direct_media_worker_count(candidate)
    part_size = direct_media_part_size_for_candidate(total, candidate, worker_count)
    if candidate_looks_chzzk(candidate, candidate.get("source") or ""):
        emit_event(
            on_event,
            "log",
            message=(
                f"CHZZK route=direct workers={worker_count} "
                f"part_size={display_size(part_size)} total={display_size(total)} url_ext=mp4"
            ),
        )
    use_parallel = should_use_parallel_direct_download(url, headers, total)
    emit_event(on_event, "status", message="Starting parallel direct download" if use_parallel else "Starting direct download")
    if use_parallel:
        try:
            part_path = download_direct_media_parallel(
                url,
                output_path,
                headers,
                total,
                on_event=on_event,
                part_size=part_size,
                workers=worker_count,
                slow_check=slow_check,
            )
        except ChzzkDirectSlowFallback:
            raise
        except DirectMediaRangeUnsupported:
            emit_event(on_event, "status", message="Range download unsupported; retrying direct download")
            part_path = download_direct_media_single(url, output_path, headers, total=total, on_event=on_event)
    else:
        try:
            part_path = download_direct_media_single(url, output_path, headers, total=total, on_event=on_event)
        except ChzzkDirectSlowFallback:
            part_path = output_path.with_name(output_path.name + ".part")
            if part_path.exists():
                part_path.unlink()
            raise
    part_path.replace(output_path)
    emit_event(on_event, "file", path=str(output_path))
    emit_event(on_event, "done", path=str(output_dir))
    return {
        "ok": True,
        "output_dir": str(output_dir),
        "output_path": str(output_path),
        "target_url": url,
    }


class _PersistentHttpResponse:
    def __init__(self, response):
        self._response = response
        self.status = response.status
        self.headers = {key: value for key, value in response.getheaders()}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        self.close()
        return False

    def read(self, size=-1):
        if size is None or size < 0:
            return self._response.read()
        return self._response.read(size)

    def close(self):
        try:
            while self._response.read(64 * 1024):
                pass
        except Exception:
            pass


def _reset_parallel_http_connection(connection_key):
    state = _PARALLEL_HTTP_STATE
    connections = getattr(state, "connections", None)
    if not connections:
        return
    connection = connections.pop(connection_key, None)
    if connection is not None:
        try:
            connection.close()
        except Exception:
            pass


def _reset_parallel_http_connections_for_thread():
    state = _PARALLEL_HTTP_STATE
    connections = getattr(state, "connections", None)
    if not connections:
        return
    for connection_key in list(connections.keys()):
        _reset_parallel_http_connection(connection_key)


def parallel_http_urlopen(request, timeout=30):
    # Thread-local HTTP keep-alive: curl_cffi is not safe under ThreadPoolExecutor on Windows.
    url = request.full_url if hasattr(request, "full_url") else request.get_full_url()
    if hasattr(request, "header_items"):
        headers = dict(request.header_items())
    else:
        headers = dict(getattr(request, "headers", {}) or {})
    parsed = urllib.parse.urlparse(url)
    if not parsed.hostname:
        return urllib.request.urlopen(request, timeout=timeout)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    connection_key = (parsed.scheme, parsed.hostname, port)
    state = _PARALLEL_HTTP_STATE
    if not hasattr(state, "connections"):
        state.connections = {}
    last_exc = None
    for attempt in range(2):
        connection = state.connections.get(connection_key)
        try:
            if connection is None:
                if parsed.scheme == "https":
                    connection = http.client.HTTPSConnection(
                        parsed.hostname,
                        port,
                        timeout=timeout,
                        context=ssl.create_default_context(),
                    )
                else:
                    connection = http.client.HTTPConnection(parsed.hostname, port, timeout=timeout)
                state.connections[connection_key] = connection
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            if response.status >= 400:
                body = response.read()
                raise urllib.error.HTTPError(
                    url,
                    response.status,
                    response.reason,
                    response.getheaders(),
                    body,
                )
            return _PersistentHttpResponse(response)
        except Exception as exc:
            last_exc = exc
            _reset_parallel_http_connection(connection_key)
            if attempt == 0:
                continue
            break
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_hls_playlist_text(url, headers, timeout=30):
    request = urllib.request.Request(str(url or ""), headers=dict(headers or {}))
    with parallel_http_urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def hls_playlist_is_encrypted(playlist_text):
    return hls_playlist_parallel_encryption(playlist_text) not in {None, "none"}


def hls_playlist_parallel_encryption(playlist_text):
    methods = set()
    for line in str(playlist_text or "").splitlines():
        upper = line.upper()
        if not upper.startswith("#EXT-X-KEY"):
            continue
        method_match = re.search(r"METHOD=([^,]+)", upper)
        if not method_match:
            continue
        methods.add(method_match.group(1).strip())
    if any(method in {"SAMPLE-AES", "SAMPLE-AES-CTR", "SAMPLE-AES-CENC"} for method in methods):
        return None
    if "AES-128" in methods:
        return "aes-128"
    if methods and methods != {"NONE"}:
        return None
    return "none"


def hls_absolute_media_url(playlist_url, media_ref):
    absolute = urllib.parse.urljoin(str(playlist_url or ""), str(media_ref or "").strip())
    playlist = urllib.parse.urlparse(str(playlist_url or ""))
    media = urllib.parse.urlparse(absolute)
    if playlist.query and not media.query:
        absolute = urllib.parse.urlunparse(media._replace(query=playlist.query))
    return absolute


def parse_hls_media_playlist(playlist_text, playlist_url):
    media_sequence = 0
    key_url = ""
    key_iv = None
    init_map_url = ""
    segment_urls = []
    segment_durations = []
    pending_duration = None
    for line in str(playlist_text or "").splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            media_sequence = safe_int(line.split(":", 1)[1])
        elif line.startswith("#EXT-X-MAP:"):
            uri_match = re.search(r'URI="([^"]+)"', line)
            if uri_match:
                init_map_url = hls_absolute_media_url(playlist_url, uri_match.group(1))
        elif line.startswith("#EXT-X-KEY:"):
            uri_match = re.search(r'URI="([^"]+)"', line)
            if uri_match:
                key_url = hls_absolute_media_url(playlist_url, uri_match.group(1))
            iv_match = re.search(r"IV=0x([0-9a-fA-F]+)", line)
            if iv_match:
                key_iv = bytes.fromhex(iv_match.group(1))
        elif line.startswith("#EXTINF:"):
            value = line.split(":", 1)[1].split(",", 1)[0].strip()
            try:
                pending_duration = float(value)
            except ValueError:
                pending_duration = None
        elif line and not line.startswith("#"):
            segment_urls.append(hls_absolute_media_url(playlist_url, line))
            segment_durations.append(float(pending_duration or 0.0))
            pending_duration = None
    return {
        "media_sequence": media_sequence,
        "key_url": key_url,
        "key_iv": key_iv,
        "init_map_url": init_map_url,
        "segment_urls": segment_urls,
        "segment_durations": segment_durations,
    }


def hls_segment_indices_for_clip_range(segment_durations, clip_start, clip_end=None):
    durations = [float(value or 0.0) for value in (segment_durations or [])]
    if not durations:
        return []
    start = max(0.0, float(clip_start or 0.0))
    end = float(clip_end) if clip_end is not None else None
    indices = []
    timeline = 0.0
    for index, seg_duration in enumerate(durations):
        seg_start = timeline
        seg_end = timeline + max(0.0, seg_duration)
        timeline = seg_end
        if end is not None and seg_start >= end:
            break
        if end is not None and seg_end <= start:
            continue
        if seg_end > start and (end is None or seg_start < end):
            indices.append(index)
    return indices


def hls_segment_urls_for_clip_range(playlist_meta, clip_range):
    segment_urls = list((playlist_meta or {}).get("segment_urls") or [])
    durations = list((playlist_meta or {}).get("segment_durations") or [])
    if not isinstance(clip_range, dict) or not segment_urls:
        return segment_urls
    if len(durations) != len(segment_urls):
        raise RuntimeError("HLS segment durations were unavailable for clipped download.")
    indices = hls_segment_indices_for_clip_range(
        durations,
        clip_range.get("start"),
        clip_range.get("end"),
    )
    if not indices:
        raise RuntimeError("Selected clip range did not match any HLS segments.")
    return [segment_urls[index] for index in indices]


def hls_clip_trim_params(playlist_meta, clip_range):
    normalized = clip_range_from_candidate({"clip_range": clip_range}) if isinstance(clip_range, dict) else None
    if not normalized:
        return None
    durations = [float(value or 0.0) for value in ((playlist_meta or {}).get("segment_durations") or [])]
    if not durations:
        return None
    indices = hls_segment_indices_for_clip_range(
        durations,
        normalized.get("start"),
        normalized.get("end"),
    )
    if not indices:
        return None
    clip_start = float(normalized.get("start") or 0.0)
    clip_end = normalized.get("end")
    media_start = sum(durations[: indices[0]])
    in_file_start = max(0.0, clip_start - media_start)
    out_duration = max(0.0, float(clip_end) - clip_start) if clip_end is not None else None
    if in_file_start <= 0.01 and out_duration is None:
        return None
    return {
        "in_file_start": in_file_start,
        "out_duration": out_duration,
        "clip_start": clip_start,
        "clip_end": clip_end,
    }


def trim_downloaded_media_to_clip_range(output_path, trim_params, candidate=None, ffmpeg_exe=None, on_event=None):
    output_path = Path(output_path).expanduser()
    if not output_path.is_file() or not trim_params:
        return output_path
    in_file_start = max(0.0, float(trim_params.get("in_file_start") or 0.0))
    out_duration = trim_params.get("out_duration")
    if out_duration is not None:
        out_duration = max(0.0, float(out_duration))
    if in_file_start <= 0.01 and out_duration is None:
        return output_path
    ffmpeg_exe = ffmpeg_exe or ffmpeg_path() or shutil.which("ffmpeg")
    if not ffmpeg_exe:
        raise RuntimeError("ffmpeg is required to trim downloaded clip ranges")
    trimmed_path = output_path.with_name(output_path.stem + ".trim.part" + output_path.suffix)
    output_format = normalized_output_ext((candidate or {}).get("output_ext")) or output_path.suffix.lstrip(".") or "mp4"
    command = [str(ffmpeg_exe), "-y", "-hide_banner", "-i", str(output_path)]
    if in_file_start > 0.01:
        command += ["-ss", str(in_file_start)]
    if out_duration is not None:
        command += ["-t", str(out_duration)]
    command += ["-c", "copy", "-movflags", "+faststart", "-f", output_format, str(trimmed_path)]
    emit_event(on_event, "log", message="Trimming downloaded clip range")
    try:
        run_ffmpeg_command(command, error_label="ffmpeg clip trim failed")
    except RuntimeError:
        try:
            trimmed_path.unlink()
        except OSError:
            pass
        raise
    if not trimmed_path.is_file() or trimmed_path.stat().st_size <= 0:
        raise RuntimeError("ffmpeg clip trim produced an empty file.")
    trimmed_path.replace(output_path)
    return output_path


def hls_aes128_iv(media_sequence, segment_index, fixed_iv=None):
    if fixed_iv is not None:
        return fixed_iv
    sequence = int(media_sequence) + int(segment_index)
    return sequence.to_bytes(16, byteorder="big")


def fetch_hls_aes128_key(key_url, headers):
    request = urllib.request.Request(str(key_url or ""), headers=dict(headers or {}))
    with parallel_http_urlopen(request, timeout=30) as response:
        key = response.read()
    if len(key) != 16:
        raise RuntimeError(f"HLS AES-128 key must be 16 bytes, got {len(key)}")
    return key


def iter_hls_cipher_blocks(chunk_iter):
    buffer = bytearray()
    for chunk in chunk_iter:
        if not chunk:
            continue
        buffer.extend(chunk)
        while len(buffer) >= 16:
            yield bytes(buffer[:16])
            del buffer[:16]
    if buffer:
        raise RuntimeError("Encrypted HLS segment size is not a multiple of 16.")


def decrypt_hls_aes128_cbc_stream(cipher_block_iter, output_file, key, iv):
    try:
        from Cryptodome.Cipher import AES
    except ImportError as exc:
        raise RuntimeError("PyCryptodome is required for encrypted HLS downloads.") from exc
    cipher = AES.new(key, AES.MODE_ECB)
    prev_cipher_block = iv
    last_plain = b""
    for cipher_block in cipher_block_iter:
        plain_block = bytes(a ^ b for a, b in zip(cipher.decrypt(cipher_block), prev_cipher_block))
        prev_cipher_block = cipher_block
        if last_plain:
            output_file.write(last_plain)
        last_plain = plain_block
    if not last_plain:
        return
    pad = last_plain[-1]
    if 1 <= pad <= 16 and last_plain.endswith(bytes([pad]) * pad):
        last_plain = last_plain[:-pad]
    output_file.write(last_plain)


def decrypt_hls_aes128_segment(encrypted, key, iv):
    try:
        from Cryptodome.Cipher import AES
    except ImportError as exc:
        raise RuntimeError("PyCryptodome is required for encrypted HLS downloads.") from exc
    if len(encrypted) % 16:
        raise RuntimeError("Encrypted HLS segment size is not a multiple of 16.")
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(encrypted)
    pad = decrypted[-1] if decrypted else 0
    if 1 <= pad <= 16 and decrypted.endswith(bytes([pad]) * pad):
        decrypted = decrypted[:-pad]
    return decrypted


def resolve_hls_media_playlist(url, headers, max_depth=4):
    playlist_url = str(url or "")
    for _ in range(max(1, max_depth)):
        playlist_text = fetch_hls_playlist_text(playlist_url, headers)
        if "#EXT-X-STREAM-INF" not in playlist_text:
            return playlist_url, playlist_text
        best_url = ""
        best_bandwidth = -1
        lines = playlist_text.splitlines()
        for index, line in enumerate(lines):
            if not line.startswith("#EXT-X-STREAM-INF"):
                continue
            bandwidth_match = re.search(r"BANDWIDTH=(\d+)", line)
            bandwidth = safe_int(bandwidth_match.group(1)) if bandwidth_match else 0
            stream_url = ""
            for next_line in lines[index + 1 :]:
                next_line = next_line.strip()
                if not next_line or next_line.startswith("#"):
                    continue
                stream_url = next_line
                break
            if stream_url and bandwidth >= best_bandwidth:
                best_bandwidth = bandwidth
                best_url = urllib.parse.urljoin(playlist_url, stream_url)
        if not best_url:
            raise RuntimeError("HLS master playlist had no media streams.")
        playlist_url = best_url
    raise RuntimeError("HLS master playlist nesting was too deep.")


def iter_hls_segment_urls(playlist_text, playlist_url):
    segment_urls = []
    for line in str(playlist_text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        segment_urls.append(hls_absolute_media_url(playlist_url, line))
    return segment_urls


def browser_dom_hls_prefers_parallel_download(candidate, playlist_text, segment_urls):
    if ".m3u8" not in str((candidate or {}).get("url") or "").lower():
        return False
    if hls_playlist_parallel_encryption(playlist_text) is None:
        return False
    if not segment_urls:
        return False
    if len(segment_urls) > BROWSER_DOM_HLS_PARALLEL_MAX_SEGMENTS:
        return False
    expected = candidate_expected_size(candidate)
    if expected and expected > BROWSER_DOM_HLS_PARALLEL_MAX_BYTES:
        return False
    duration = safe_int((candidate or {}).get("duration"))
    if duration and duration > 1800:
        return False
    return True


def remux_ts_concat_to_mp4(ts_paths, output_path, ffmpeg_exe, output_format="mp4"):
    concat_path = output_path.with_suffix(output_path.suffix + ".concat.txt")
    lines = []
    for ts_path in ts_paths:
        escaped = str(ts_path).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    command = [
        str(ffmpeg_exe),
        "-y",
        "-hide_banner",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c",
        "copy",
        "-f",
        output_format,
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_hidden_subprocess_kwargs(),
    )
    try:
        concat_path.unlink()
    except OSError:
        pass
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "HLS remux failed.").strip())


def stream_hls_url_to_file(url, headers, output_file, timeout=45):
    request = urllib.request.Request(str(url or ""), headers=dict(headers or {}))
    with parallel_http_urlopen(request, timeout=timeout) as response:
        while True:
            chunk = response.read(HLS_SEGMENT_READ_CHUNK)
            if not chunk:
                break
            output_file.write(chunk)


def remux_fmp4_file_to_mp4(fmp4_path, output_path, ffmpeg_exe, output_format="mp4"):
    command = [
        str(ffmpeg_exe),
        "-y",
        "-hide_banner",
        "-f",
        "mp4",
        "-i",
        str(fmp4_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-f",
        output_format,
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_hidden_subprocess_kwargs(),
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "fMP4 remux failed.").strip())


def remux_ts_file_to_mp4(ts_path, output_path, ffmpeg_exe, output_format="mp4"):
    command = [
        str(ffmpeg_exe),
        "-y",
        "-hide_banner",
        "-i",
        str(ts_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-f",
        output_format,
        str(output_path),
    ]
    run_ffmpeg_command(command, error_label="HLS remux failed")


def hls_parallel_aes_key(playlist_text, playlist_meta, headers):
    encryption = hls_playlist_parallel_encryption(playlist_text)
    if encryption is None:
        raise RuntimeError("HLS encryption method is not supported for parallel download.")
    if encryption != "aes-128":
        return None
    if not playlist_meta["key_url"]:
        raise RuntimeError("Encrypted HLS playlist is missing an AES-128 key URL.")
    return fetch_hls_aes128_key(playlist_meta["key_url"], headers)


def download_hls_segment_to_path(index, segment_url, segment_path, aes_key, playlist_meta, headers):
    segment_path = Path(segment_path)
    request = urllib.request.Request(segment_url, headers=dict(headers))
    with parallel_http_urlopen(request, timeout=45) as response:
        if aes_key is None:
            with segment_path.open("wb") as segment_file:
                while True:
                    chunk = response.read(HLS_SEGMENT_READ_CHUNK)
                    if not chunk:
                        break
                    segment_file.write(chunk)
            return index, segment_path

        def chunk_iter():
            while True:
                chunk = response.read(HLS_SEGMENT_READ_CHUNK)
                if not chunk:
                    break
                yield chunk

        iv = hls_aes128_iv(playlist_meta["media_sequence"], index, playlist_meta["key_iv"])
        with segment_path.open("wb") as segment_file:
            decrypt_hls_aes128_cbc_stream(iter_hls_cipher_blocks(chunk_iter()), segment_file, aes_key, iv)
    return index, segment_path


def append_hls_segment_file(output_file, segment_path):
    with segment_path.open("rb") as segment_file:
        shutil.copyfileobj(segment_file, output_file, HLS_SEGMENT_READ_CHUNK)


def set_hls_parallel_pipeline_observer(callback):
    global _HLS_PARALLEL_PIPELINE_OBSERVER
    _HLS_PARALLEL_PIPELINE_OBSERVER = callback


def clear_hls_parallel_pipeline_observer():
    global _HLS_PARALLEL_PIPELINE_OBSERVER
    _HLS_PARALLEL_PIPELINE_OBSERVER = None


def _notify_hls_parallel_pipeline(in_flight_count, pending_count):
    observer = _HLS_PARALLEL_PIPELINE_OBSERVER
    if not observer:
        return
    with _HLS_PARALLEL_PIPELINE_OBSERVER_LOCK:
        observer(in_flight_count, pending_count)


def emit_hls_parallel_progress(
    on_event,
    candidate,
    completed_segments,
    total_segments,
    downloaded_bytes,
    duration,
    started_at,
    last_emit_at,
    last_emit_bytes,
    force=False,
):
    if not force and completed_segments < total_segments:
        now = time.monotonic()
        if now - float(last_emit_at or 0.0) < HLS_PARALLEL_PROGRESS_INTERVAL:
            return last_emit_at, last_emit_bytes
    expected_total = candidate_expected_size(candidate)
    if duration:
        if completed_segments >= total_segments:
            current_sec = max(0, duration - 1)
        else:
            current_sec = int(duration * completed_segments / total_segments)
        emit_manifest_download_progress(
            on_event,
            current_sec,
            duration,
            downloaded_bytes=downloaded_bytes,
            total_bytes=expected_total or manifest_progress_total_bytes(
                candidate,
                downloaded_bytes,
                max(1, current_sec),
                duration,
            ),
            started_at=started_at,
            last_bytes=last_emit_bytes,
            last_emit_at=last_emit_at,
        )
    else:
        percent = completed_segments * 100 / total_segments
        if completed_segments >= total_segments:
            percent = min(percent, 99)
        now = time.monotonic()
        if last_emit_at is not None and downloaded_bytes > last_emit_bytes:
            speed = max(0.0, (downloaded_bytes - last_emit_bytes) / max(0.001, now - float(last_emit_at)))
        else:
            speed = downloaded_bytes / max(0.001, now - float(started_at))
        speed_text = f"{display_size(speed)}/s"
        emit_event(
            on_event,
            "progress",
            percent=percent,
            downloaded=downloaded_bytes,
            total=expected_total or downloaded_bytes,
            speed=speed,
            speed_text=speed_text,
            message=f"{percent:.1f}% · {speed_text}",
        )
    return time.monotonic(), downloaded_bytes


def download_hls_parallel(url, candidate, output_dir, on_event=None, ffmpeg_exe=None, segment_limit=None):
    output_dir = Path(output_dir).expanduser()
    output_path = final_output_path_for_candidate(candidate, output_dir)
    if output_path is None:
        raise RuntimeError("HLS output path could not be determined.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = output_path.with_name(output_path.name + ".part")
    part_media_path = part_path.with_suffix(part_path.suffix + ".media")
    ffmpeg_exe = ffmpeg_exe or ffmpeg_path() or shutil.which("ffmpeg")
    if not ffmpeg_exe:
        raise RuntimeError("ffmpeg is required for parallel HLS downloads")
    headers = direct_media_request_headers(candidate)
    duration = safe_int((candidate or {}).get("duration"))
    playlist_url, playlist_text = resolve_hls_media_playlist(url, headers)
    playlist_meta = parse_hls_media_playlist(playlist_text, playlist_url)
    init_map_url = str(playlist_meta.get("init_map_url") or "")
    is_fmp4 = bool(init_map_url)
    clip_range = clip_range_from_candidate(candidate)
    clip_trim_params = hls_clip_trim_params(playlist_meta, clip_range) if clip_range else None
    if clip_range:
        segment_urls = hls_segment_urls_for_clip_range(playlist_meta, clip_range)
        emit_event(on_event, "status", message=f"Downloading {len(segment_urls)} HLS segments for selected range")
    else:
        segment_urls = playlist_meta["segment_urls"]
        if not segment_urls:
            raise RuntimeError("HLS media playlist had no segments.")
        limit = safe_int(segment_limit)
        if limit > 0:
            segment_urls = segment_urls[:limit]
        emit_event(on_event, "status", message=f"Downloading {len(segment_urls)} HLS segments in parallel")
    if not segment_urls:
        raise RuntimeError("HLS media playlist had no segments.")
    aes_key = hls_parallel_aes_key(playlist_text, playlist_meta, headers)
    workers = max(1, min(HLS_PARALLEL_WORKERS, len(segment_urls)))
    max_in_flight = max(workers, min(HLS_PARALLEL_MAX_IN_FLIGHT, len(segment_urls)))
    total_segments = len(segment_urls)
    started_at = time.monotonic()
    last_emit_at = started_at
    last_emit_bytes = 0
    downloaded_bytes = 0
    completed_segments = 0
    next_write_index = 0
    next_submit_index = 0
    pending_paths = {}
    in_flight = {}

    try:
        with tempfile.TemporaryDirectory(prefix="clipflow-hls-") as temp_dir, part_media_path.open("wb") as output_file:
            temp_root = Path(temp_dir)
            if init_map_url:
                emit_event(on_event, "status", message="Downloading HLS init segment")
                stream_hls_url_to_file(init_map_url, headers, output_file)

            def fetch_segment(index, segment_url):
                segment_path = temp_root / f"seg_{index:08d}.ts"
                last_exc = None
                for attempt in range(max(1, HLS_SEGMENT_RETRIES)):
                    try:
                        if segment_path.exists():
                            try:
                                segment_path.unlink()
                            except OSError:
                                pass
                        return download_hls_segment_to_path(
                            index,
                            segment_url,
                            segment_path,
                            aes_key,
                            playlist_meta,
                            headers,
                        )
                    except Exception as exc:
                        last_exc = exc
                        _reset_parallel_http_connections_for_thread()
                        if attempt + 1 < HLS_SEGMENT_RETRIES:
                            time.sleep(0.2 * (attempt + 1))
                raise last_exc

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                while next_submit_index < total_segments and len(in_flight) < max_in_flight:
                    index = next_submit_index
                    future = executor.submit(fetch_segment, index, segment_urls[index])
                    in_flight[future] = index
                    next_submit_index += 1
                    _notify_hls_parallel_pipeline(len(in_flight), len(pending_paths))

                while in_flight:
                    done, _pending = concurrent.futures.wait(
                        in_flight,
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )
                    for future in done:
                        del in_flight[future]
                        index, segment_path = future.result()
                        pending_paths[index] = segment_path
                        _notify_hls_parallel_pipeline(len(in_flight), len(pending_paths))
                        while next_write_index in pending_paths:
                            segment_file = pending_paths[next_write_index]
                            segment_size = segment_file.stat().st_size
                            append_hls_segment_file(output_file, segment_file)
                            downloaded_bytes += segment_size
                            completed_segments += 1
                            pending_paths.pop(next_write_index)
                            try:
                                segment_file.unlink()
                            except OSError:
                                pass
                            next_write_index += 1
                        while next_submit_index < total_segments and len(in_flight) < max_in_flight:
                            submit_index = next_submit_index
                            new_future = executor.submit(fetch_segment, submit_index, segment_urls[submit_index])
                            in_flight[new_future] = submit_index
                            next_submit_index += 1
                        _notify_hls_parallel_pipeline(len(in_flight), len(pending_paths))
                        last_emit_at, last_emit_bytes = emit_hls_parallel_progress(
                            on_event,
                            candidate,
                            completed_segments,
                            total_segments,
                            downloaded_bytes,
                            duration,
                            started_at,
                            last_emit_at,
                            last_emit_bytes,
                        )
        emit_event(on_event, "log", message="Finalizing HLS output")
        output_format = normalized_output_ext((candidate or {}).get("output_ext")) or "mp4"
        if is_fmp4:
            # CMAF init + fragment concat is already MP4; skip ffmpeg remux for throughput.
            part_media_path.replace(part_path)
        else:
            remux_ts_file_to_mp4(part_media_path, part_path, ffmpeg_exe, output_format=output_format)
    except BaseException:
        cleanup_partial_output_files(output_path, on_event=on_event)
        raise
    finally:
        try:
            part_media_path.unlink()
        except OSError:
            pass
    if not part_path.exists() or part_path.stat().st_size <= 0:
        cleanup_partial_output_files(output_path, on_event=on_event)
        raise RuntimeError("Parallel HLS download produced an empty file.")
    part_path.replace(output_path)
    if clip_trim_params:
        trim_downloaded_media_to_clip_range(
            output_path,
            clip_trim_params,
            candidate=candidate,
            ffmpeg_exe=ffmpeg_exe,
            on_event=on_event,
        )
    emit_event(on_event, "progress", percent=100, message="100%")
    emit_event(on_event, "file", path=str(output_path))
    emit_event(on_event, "done", path=str(output_path))
    return {
        "ok": True,
        "output_dir": str(output_dir),
        "output_path": str(output_path),
        "target_url": url,
    }


def download_browser_dom_hls_parallel(url, candidate, output_dir, on_event=None, ffmpeg_exe=None):
    headers = direct_media_request_headers(candidate)
    playlist_url, playlist_text = resolve_hls_media_playlist(url, headers)
    playlist_meta = parse_hls_media_playlist(playlist_text, playlist_url)
    segment_urls = playlist_meta["segment_urls"]
    if not browser_dom_hls_prefers_parallel_download(candidate, playlist_text, segment_urls):
        raise RuntimeError("HLS stream is not eligible for parallel segment download.")
    return download_hls_parallel(url, candidate, output_dir, on_event=on_event, ffmpeg_exe=ffmpeg_exe)


def download_browser_dom_manifest(url, candidate, output_dir, on_event=None, ffmpeg_exe=None, runner=None, no_progress_timeout=None):
    output_dir = Path(output_dir).expanduser()
    output_path = final_output_path_for_candidate(candidate, output_dir)
    if output_path is None:
        raise RuntimeError("Browser DOM manifest output path could not be determined.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = output_path.with_name(output_path.name + ".part")
    ffmpeg_exe = ffmpeg_exe or ffmpeg_path() or shutil.which("ffmpeg")
    if not ffmpeg_exe:
        raise RuntimeError("ffmpeg is required for browser DOM manifest downloads")
    headers = direct_media_request_headers(candidate)
    header_arg = "".join(f"{key}: {value}\r\n" for key, value in headers.items())
    duration = safe_int((candidate or {}).get("duration"))
    if not duration:
        duration = probe_stream_duration(url, candidate)
    if ".m3u8" in str(url or "").lower():
        try:
            return download_browser_dom_hls_parallel(url, candidate, output_dir, on_event=on_event, ffmpeg_exe=ffmpeg_exe)
        except Exception as exc:
            emit_event(on_event, "log", message=f"Parallel HLS download unavailable: {exc}")
    output_format = normalized_output_ext((candidate or {}).get("output_ext")) or "mp4"
    command = [
        str(ffmpeg_exe),
        "-y",
        "-hide_banner",
        "-progress",
        "pipe:1",
        "-nostats",
        "-headers",
        header_arg,
        "-allowed_extensions",
        "ALL",
        "-i",
        url,
        "-c",
        "copy",
    ]
    movflags = browser_dom_manifest_movflags(candidate)
    if movflags:
        command += ["-movflags", movflags]
    command += [
        "-f",
        output_format,
        str(part_path),
    ]
    emit_event(on_event, "status", message="Downloading browser manifest stream")
    process = (runner or subprocess.Popen)(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **_hidden_subprocess_kwargs(),
    )
    progress_values = {}
    line_queue = queue.Queue()

    def read_stdout():
        stream = getattr(process, "stdout", None)
        try:
            if hasattr(stream, "readline"):
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    line_queue.put(line)
            elif stream is not None:
                for line in stream:
                    line_queue.put(line)
        finally:
            line_queue.put(None)

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    timeout = BROWSER_DOM_MANIFEST_NO_PROGRESS_TIMEOUT if no_progress_timeout is None else float(no_progress_timeout)
    started_at = time.monotonic()
    last_progress = time.monotonic()
    last_emit_at = started_at
    last_emit_bytes = 0
    reader_done = False
    stderr_text = ""

    while True:
        try:
            line = line_queue.get(timeout=0.2)
        except queue.Empty:
            line = None
        if line is None and reader_done:
            break
        if line is None:
            if process.poll() is not None:
                reader_done = True
            if time.monotonic() - last_progress > timeout:
                process.kill()
                raise RuntimeError(f"Browser DOM manifest download stalled for {int(timeout)} seconds.")
            continue
        if line is None:
            reader_done = True
            continue
        stderr_text += line
        key, _, value = line.partition("=")
        if key:
            progress_values[key.strip()] = value.strip()
        if progress_values.get("progress") == "continue" or progress_values.get("out_time_ms"):
            last_progress = time.monotonic()
            raw_time = progress_values.get("out_time_ms") or progress_values.get("out_time_us")
            current = safe_int(raw_time) / 1_000_000 if raw_time is not None else 0
            if duration and current > 0:
                part_size = part_path.stat().st_size if part_path.exists() else 0
                total_bytes = manifest_progress_total_bytes(candidate, part_size, current, duration)
                emit_manifest_download_progress(
                    on_event,
                    current,
                    duration,
                    downloaded_bytes=part_size,
                    total_bytes=total_bytes,
                    started_at=started_at,
                    last_bytes=last_emit_bytes,
                    last_emit_at=last_emit_at,
                )
                if part_size != last_emit_bytes:
                    last_emit_bytes = part_size
                    last_emit_at = time.monotonic()
            elif current > 0:
                emit_event(on_event, "progress", percent=0, message=display_duration(int(current)))
        if process.poll() is not None:
            reader_done = True

    return_code = process.wait()
    reader.join(timeout=1)
    if return_code != 0:
        raise RuntimeError((stderr_text or "Browser DOM manifest download failed.").strip())
    if not part_path.exists() or part_path.stat().st_size <= 0:
        raise RuntimeError("Browser DOM manifest download produced an empty file.")
    part_path.replace(output_path)
    emit_event(on_event, "file", path=str(output_path))
    emit_event(on_event, "done", path=str(output_path))
    return {
        "ok": True,
        "output_dir": str(output_dir),
        "output_path": str(output_path),
        "target_url": url,
    }


def download_direct_media_segment(url, candidate, output_dir, on_event=None, ffmpeg_exe=None, runner=None, no_progress_timeout=None):
    output_dir = Path(output_dir).expanduser()
    output_path = final_output_path_for_candidate(candidate, output_dir)
    if output_path is None:
        raise RuntimeError("Direct media segment output path could not be determined.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = output_path.with_name(output_path.name + ".part")
    clip_range = clip_range_from_candidate(candidate)
    if not clip_range:
        raise RuntimeError("Clip range is required for segment downloads")
    ffmpeg_exe = ffmpeg_exe or ffmpeg_path() or shutil.which("ffmpeg")
    if not ffmpeg_exe:
        raise RuntimeError("ffmpeg is required for segment downloads")
    headers = direct_media_request_headers(candidate)
    header_arg = "".join(f"{key}: {value}\r\n" for key, value in headers.items())
    start = float(clip_range["start"])
    end = clip_range.get("end")
    duration = float(end - start) if end is not None else 0
    cut_mode = clip_cut_mode(candidate)
    media_url = str((candidate or {}).get("url") or "").strip()
    if media_url.lower().startswith(("http://", "https://")):
        url = media_url
    input_url = url
    proxy_cm = None
    is_hls_input = ".m3u8" in str(url or "").lower()
    if runner is None and not is_hls_input:
        total = safe_int((candidate or {}).get("source_filesize")) or candidate_expected_size(candidate)
        if should_use_parallel_direct_download(url, headers, total):
            try:
                proxy_cm = direct_media_parallel_proxy_url(
                    url,
                    headers,
                    total,
                    part_size=min(1024 * 1024, direct_media_parallel_part_size(total)),
                )
                input_url = proxy_cm.__enter__()
                emit_event(on_event, "status", message="Preparing segment stream")
            except Exception as exc:
                if proxy_cm is not None:
                    proxy_cm.__exit__(*sys.exc_info())
                    proxy_cm = None
                input_url = url
                emit_event(on_event, "log", message=f"Segment stream proxy unavailable: {exc}")
    command = [
        str(ffmpeg_exe),
        "-y",
        "-hide_banner",
        "-progress",
        "pipe:1",
        "-nostats",
        "-headers",
        header_arg,
    ]
    if is_hls_input:
        command += ["-allowed_extensions", "ALL"]
    if cut_mode == "accurate":
        preseek = max(0.0, start - 5.0)
        if preseek:
            command += ["-ss", str(preseek)]
        command += ["-i", input_url]
        offset = start - preseek
        if offset:
            command += ["-ss", str(offset)]
    else:
        command += ["-ss", str(start), "-i", input_url]
    if duration:
        command += ["-t", str(duration)]
    output_format = normalized_output_ext((candidate or {}).get("output_ext")) or "mp4"
    command += ["-map", "0"]
    if cut_mode == "accurate":
        command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k"]
    else:
        command += ["-c", "copy"]
    command += ["-movflags", "+faststart", "-f", output_format, str(part_path)]
    emit_event(on_event, "status", message="Downloading selected segment" if cut_mode == "fast" else "Processing accurate segment")
    process = (runner or subprocess.Popen)(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **_hidden_subprocess_kwargs(),
    )
    output_lines = []
    progress_values = {}
    line_queue = queue.Queue()

    def read_stdout():
        stream = getattr(process, "stdout", None)
        try:
            if hasattr(stream, "readline"):
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    line_queue.put(line)
            elif stream is not None:
                for line in stream:
                    line_queue.put(line)
        finally:
            line_queue.put(None)

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    timeout = DIRECT_MEDIA_SEGMENT_NO_PROGRESS_TIMEOUT if no_progress_timeout is None else float(no_progress_timeout)
    segment_started_at = time.monotonic()
    last_progress = time.monotonic()
    reader_done = False
    last_percent = -1.0
    stderr_text = ""
    clip_bytes = candidate_expected_size(candidate)
    last_output_size = 0
    last_output_emit_at = 0.0

    def emit_ffmpeg_progress():
        nonlocal last_progress, last_percent, last_output_size, last_output_emit_at
        raw_time = progress_values.get("out_time_ms") or progress_values.get("out_time_us")
        current = safe_int(raw_time) / 1_000_000 if raw_time is not None else 0
        if duration:
            percent = max(0, min(100, current * 100 / duration))
        else:
            percent = 0
        output_size = safe_int(progress_values.get("total_size"))
        if clip_bytes and output_size:
            percent = max(percent, min(99.0, output_size * 100 / clip_bytes))
        if percent <= last_percent and percent < 99:
            return
        percent = min(percent, 99.0)
        last_percent = percent
        now = time.monotonic()
        speed_bps = 0.0
        if last_output_emit_at and output_size > last_output_size:
            speed_bps = max(0.0, (output_size - last_output_size) / max(0.001, now - last_output_emit_at))
        elif output_size > 0:
            speed_bps = output_size / max(0.001, now - segment_started_at)
        last_progress = now
        last_output_size = output_size
        last_output_emit_at = now
        speed_label = f"{display_size(speed_bps)}/s" if speed_bps > 0 else ""
        eta = byte_download_eta_seconds(output_size, clip_bytes, speed_bps) if clip_bytes else 0
        eta_text = display_duration(eta) if eta > 0 else ""
        message = f"{percent:.1f}%"
        if speed_label:
            message = f"{message} · {speed_label}"
        if eta_text:
            message = f"{message} · ETA {eta_text}"
        emit_event(
            on_event,
            "progress",
            percent=percent,
            downloaded=output_size,
            total=clip_bytes,
            speed=speed_bps,
            speed_text=speed_label,
            eta_text=eta_text,
            message=message,
        )

    try:
        while True:
            try:
                line = line_queue.get(timeout=0.1)
            except queue.Empty:
                poll = getattr(process, "poll", None)
                process_done = poll() is not None if callable(poll) else False
                if reader_done and (process_done or not callable(poll)):
                    break
                if timeout >= 0 and time.monotonic() - last_progress >= timeout:
                    kill = getattr(process, "kill", None)
                    if callable(kill):
                        kill()
                    raise RuntimeError("ffmpeg segment download timed out without progress")
                continue
            if line is None:
                reader_done = True
                poll = getattr(process, "poll", None)
                if not callable(poll) or poll() is not None:
                    break
                continue
            line = str(line).strip()
            if not line:
                continue
            output_lines.append(line)
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            progress_values[key] = value
            if key in {"progress", "out_time_ms", "out_time_us"}:
                emit_ffmpeg_progress()
        returncode = process.wait()
        communicate = getattr(process, "communicate", None)
        if callable(communicate):
            _stdout, stderr_text = communicate(timeout=1)
    except Exception:
        try:
            part_path.unlink()
        except OSError:
            pass
        raise
    finally:
        if proxy_cm is not None:
            proxy_cm.__exit__(*sys.exc_info())
    if returncode != 0:
        try:
            part_path.unlink()
        except OSError:
            pass
        message = (stderr_text or "\n".join(output_lines) or "ffmpeg segment download failed").strip()
        raise RuntimeError(message)
    if not completed_output_exists(part_path, candidate):
        raise RuntimeError("ffmpeg segment download produced no output")
    part_path.replace(output_path)
    emit_event(on_event, "progress", percent=100, message="100.0%")
    emit_event(on_event, "file", path=str(output_path))
    emit_event(on_event, "done", path=str(output_path))
    return {
        "ok": True,
        "output_dir": str(output_dir),
        "output_path": str(output_path),
        "target_url": url,
    }


def download_candidate(page_url, candidate, output_dir, cookie_source="없음", ydl_factory=None, on_event=None, proxy_url=None):
    existing_output_path = existing_output_path_for_candidate(candidate, output_dir)
    if existing_output_path:
        emit_event(on_event, "status", message=f"File already exists: {existing_output_path.name}")
        return {
            "ok": True,
            "skipped_existing": True,
            "output_dir": str(Path(output_dir).expanduser()),
            "output_path": str(existing_output_path),
            "target_url": candidate.get("source") or page_url or candidate.get("url"),
        }
    remove_too_small_existing_output(candidate, output_dir, on_event=on_event)
    output_target = final_output_path_for_candidate(candidate, output_dir)
    if output_target:
        cleanup_partial_output_files(output_target, on_event=on_event)

    chzzk_result = download_chzzk_candidate(
        page_url,
        candidate,
        output_dir,
        cookie_source=cookie_source,
        on_event=on_event,
    )
    if chzzk_result is not None:
        return chzzk_result

    target_url = candidate.get("source") or page_url or candidate.get("url")
    if str((candidate or {}).get("format_id") or "").startswith("browser-"):
        candidate = prepare_browser_dom_candidate(page_url or target_url, candidate, on_event=on_event)
    if candidate.get("format_selector") == "best" and candidate.get("url"):
        target_url = candidate["url"]
    if is_browser_dom_manifest_candidate(candidate):
        return download_browser_dom_manifest(target_url, candidate, output_dir, on_event=on_event)
    if is_direct_https_mp4_candidate(candidate):
        return download_direct_media(target_url, candidate, output_dir, on_event=on_event)

    if ydl_factory is None:
        ydl_factory = youtube_dl_factory()
    options = build_download_options(candidate, output_dir, cookie_source=cookie_source, on_event=on_event, proxy_url=proxy_url)

    def run_ydl_download(run_options, run_candidate):
        with yt_dlp_ffmpeg_path_context(run_options):
            with ydl_factory(run_options) as ydl:
                download_info = run_candidate.get("_download_info") if isinstance(run_candidate, dict) else None
                if isinstance(download_info, dict) and download_info and download_info_reuse_supported(run_candidate):
                    ydl.process_video_result(json_ready_download_info(download_info), download=True)
                else:
                    ydl.download([target_url])

    emit_event(on_event, "status", message="Starting download")
    try:
        run_ydl_download(options, candidate)
        emit_event(on_event, "progress", percent=100, message="100.0%")
    except Exception as exc:
        if cookie_spec(cookie_source) and browser_cookie_error(exc):
            emit_event(on_event, "status", message="브라우저 쿠키를 읽지 못해 쿠키 없이 다시 시도합니다")
            no_cookie_options = build_download_options(
                candidate,
                output_dir,
                cookie_source="없음",
                on_event=on_event,
                proxy_url=proxy_url,
            )
            try:
                run_ydl_download(no_cookie_options, candidate)
                emit_event(on_event, "progress", percent=100, message="100.0%")
                emit_event(on_event, "done", path=str(output_dir))
                return {"ok": True, "output_dir": str(output_dir), "target_url": target_url}
            except Exception as no_cookie_exc:
                exc = no_cookie_exc
        if not should_retry_progressive_mp4(candidate, exc):
            raise
        fallback_candidate = dict(candidate)
        fallback_candidate["format_selector"] = "18/best[ext=mp4]/best"
        fallback_candidate["output_ext"] = "mp4"
        fallback_candidate["ext"] = "mp4"
        emit_event(on_event, "status", message="Retrying with progressive MP4")
        fallback_options = build_download_options(
            fallback_candidate,
            output_dir,
            cookie_source=cookie_source,
            on_event=on_event,
            proxy_url=proxy_url,
        )
        try:
            run_ydl_download(fallback_options, fallback_candidate)
            emit_event(on_event, "progress", percent=100, message="100.0%")
        except Exception as fallback_exc:
            if not (cookie_spec(cookie_source) and should_retry_progressive_mp4(fallback_candidate, fallback_exc, allow_progressive=True)):
                raise
            emit_event(on_event, "status", message="Retrying progressive MP4 without cookies")
            no_cookie_options = build_download_options(
                fallback_candidate,
                output_dir,
                cookie_source="없음",
                on_event=on_event,
                proxy_url=proxy_url,
            )
            run_ydl_download(no_cookie_options, fallback_candidate)
            emit_event(on_event, "progress", percent=100, message="100.0%")
    emit_event(on_event, "done", path=str(output_dir))
    return {"ok": True, "output_dir": str(output_dir), "target_url": target_url}


DOWNLOAD_WORKER_IDLE_SECONDS = 30.0
ANALYSIS_WORKER_IDLE_SECONDS = 20.0
_DOWNLOAD_PROCESS_POOL = None
_DOWNLOAD_PROCESS_POOL_LOCK = threading.Lock()
_ANALYSIS_PROCESS_POOL = None
_ANALYSIS_PROCESS_POOL_LOCK = threading.Lock()


def reset_clipflow_worker_pools():
    global _DOWNLOAD_PROCESS_POOL, _ANALYSIS_PROCESS_POOL
    with _DOWNLOAD_PROCESS_POOL_LOCK:
        if _DOWNLOAD_PROCESS_POOL is not None:
            _DOWNLOAD_PROCESS_POOL.close_all()
        _DOWNLOAD_PROCESS_POOL = None
    with _ANALYSIS_PROCESS_POOL_LOCK:
        if _ANALYSIS_PROCESS_POOL is not None:
            _ANALYSIS_PROCESS_POOL.close_all()
        _ANALYSIS_PROCESS_POOL = None


def terminate_stale_clipflow_worker_processes():
    if getattr(sys, "frozen", False):
        return
    pattern = "clipflow_(download|analysis)_process"
    if sys.platform == "win32":
        script = (
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            f"Where-Object {{ $_.CommandLine -match '{pattern}' }} | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            pass


def _download_worker_request(page_url, candidate, output_dir, cookie_source="없음", proxy_url=None):
    return {
        "request_id": str((candidate or {}).get("_clipflow_row_id") or ""),
        "page_url": page_url,
        "candidate": candidate or {},
        "output_dir": str(output_dir),
        "cookie_source": cookie_source,
        "proxy_url": proxy_url,
    }


def download_worker_command(request_path):
    request_path = str(request_path)
    if getattr(sys, "frozen", False):
        return [sys.executable, "--clipflow-download-worker", request_path]
    return [sys.executable, "-u", "-m", "tools.clipflow_download_process", request_path]


def persistent_download_worker_command():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--clipflow-download-worker", "--persistent"]
    return [sys.executable, "-u", "-m", "tools.clipflow_download_process", "--persistent"]


def _analysis_worker_request(url, cookie_source="없음", output_ext=None, proxy_url=None):
    return {
        "url": url,
        "cookie_source": cookie_source,
        "output_ext": output_ext,
        "proxy_url": proxy_url,
    }


def analysis_worker_command(request_path):
    request_path = str(request_path)
    if getattr(sys, "frozen", False):
        return [sys.executable, "--clipflow-analysis-worker", request_path]
    return [sys.executable, "-u", "-m", "tools.clipflow_analysis_process", request_path]


def persistent_analysis_worker_command():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--clipflow-analysis-worker", "--persistent"]
    return [sys.executable, "-u", "-m", "tools.clipflow_analysis_process", "--persistent"]


def _download_worker_environment():
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    return env


def _download_worker_creationflags():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def _hidden_subprocess_kwargs():
    kwargs = {"creationflags": _download_worker_creationflags()}
    if os.name == "nt" and hasattr(subprocess, "STARTUPINFO") and hasattr(subprocess, "STARTF_USESHOWWINDOW"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = startupinfo
    return kwargs


class PersistentDownloadProcess:
    def __init__(self, command=None):
        self.command = command or persistent_download_worker_command()
        self.process = subprocess.Popen(
            self.command,
            cwd=str(Path(__file__).resolve().parents[1]),
            env=_download_worker_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_download_worker_creationflags(),
        )
        self.last_used = time.monotonic()
        self._closed = False

    def is_alive(self):
        return not self._closed and self.process.poll() is None

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except Exception:
            pass
        try:
            terminate_process_tree(self.process)
        except Exception:
            pass
        try:
            if self.process.stdout:
                self.process.stdout.close()
        except Exception:
            pass

    def run(self, request, on_event=None):
        if not self.is_alive() or not self.process.stdin or not self.process.stdout:
            raise RuntimeError("Download worker is not running.")

        result = None
        failed_message = ""
        side_output = []

        def handle_line(line):
            nonlocal result, failed_message
            text = str(line or "").strip()
            if not text:
                return False
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                side_output.append(strip_ansi(text))
                return False
            payload_type = payload.get("type")
            if payload_type == "event":
                event = payload.get("event")
                if isinstance(event, dict) and on_event:
                    on_event(event)
            elif payload_type == "finished":
                result_value = payload.get("result")
                result = result_value if isinstance(result_value, dict) else {}
                return True
            elif payload_type == "failed":
                failed_message = strip_ansi(payload.get("message") or "Download worker failed.")
                return True
            return False

        try:
            self.process.stdin.write(json.dumps(request, ensure_ascii=False, default=str) + "\n")
            self.process.stdin.flush()
            while True:
                line = self.process.stdout.readline()
                if line == "":
                    break
                if handle_line(line):
                    break
        except BrokenPipeError as exc:
            failed_message = strip_ansi(exc)

        self.last_used = time.monotonic()
        if failed_message:
            raise RuntimeError(strip_ansi(failed_message))
        if result is None:
            code = self.process.poll()
            suffix = f" with code {code}" if code is not None else ""
            detail = "\n".join(side_output[-20:]) or f"Download worker exited unexpectedly{suffix}."
            raise RuntimeError(strip_ansi(detail))
        return result


class DownloadProcessPool:
    def __init__(self, idle_seconds=DOWNLOAD_WORKER_IDLE_SECONDS, max_idle=1, command_factory=None):
        self.idle_seconds = idle_seconds
        self.max_idle = max_idle
        self.command_factory = command_factory or persistent_download_worker_command
        self._idle = []
        self._active = {}
        self._lock = threading.Lock()
        self._trim_timer = None

    def _new_process(self):
        return PersistentDownloadProcess(command=self.command_factory())

    def _schedule_trim_locked(self):
        if not self._idle:
            return
        if self._trim_timer and self._trim_timer.is_alive():
            return
        self._trim_timer = threading.Timer(self.idle_seconds + 0.1, self._trim_from_timer)
        self._trim_timer.daemon = True
        self._trim_timer.start()

    def _trim_from_timer(self):
        with self._lock:
            self._trim_locked()
            if self._idle:
                self._schedule_trim_locked()

    def _trim_locked(self):
        now = time.monotonic()
        alive = [
            worker
            for worker in self._idle
            if worker.is_alive() and now - worker.last_used <= self.idle_seconds
        ]
        alive.sort(key=lambda worker: worker.last_used, reverse=True)
        survivors = alive[:self.max_idle]
        survivor_ids = {id(worker) for worker in survivors}
        for worker in self._idle:
            if id(worker) not in survivor_ids:
                worker.close()
        self._idle = survivors

    def warm(self):
        with self._lock:
            self._trim_locked()
            if self._idle:
                self._schedule_trim_locked()
                return
            self._idle.append(self._new_process())
            self._schedule_trim_locked()

    def run(self, request, on_event=None):
        request_id = str((request or {}).get("request_id") or "")
        with self._lock:
            self._trim_locked()
            worker = self._idle.pop() if self._idle else self._new_process()
            if request_id:
                self._active[request_id] = worker
        try:
            return worker.run(request, on_event=on_event)
        finally:
            with self._lock:
                if request_id and self._active.get(request_id) is worker:
                    self._active.pop(request_id, None)
                if worker.is_alive():
                    self._idle.append(worker)
                    self._trim_locked()
                    self._schedule_trim_locked()
                else:
                    worker.close()

    def cancel(self, request_id):
        request_id = str(request_id or "")
        if not request_id:
            return False
        with self._lock:
            worker = self._active.pop(request_id, None)
        if not worker:
            return False
        worker.close()
        return True

    def close_all(self):
        with self._lock:
            if self._trim_timer:
                self._trim_timer.cancel()
                self._trim_timer = None
            workers = list(self._idle) + list(self._active.values())
            self._idle = []
            self._active = {}
        for worker in workers:
            worker.close()


class PersistentAnalysisProcess:
    def __init__(self, command=None):
        self.command = command or persistent_analysis_worker_command()
        self.process = subprocess.Popen(
            self.command,
            cwd=str(Path(__file__).resolve().parents[1]),
            env=_download_worker_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_download_worker_creationflags(),
        )
        self.last_used = time.monotonic()
        self._closed = False

    def is_alive(self):
        return not self._closed and self.process.poll() is None

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except Exception:
            pass
        try:
            terminate_process_tree(self.process)
        except Exception:
            pass
        try:
            if self.process.stdout:
                self.process.stdout.close()
        except Exception:
            pass

    def run(self, request, on_event=None):
        if not self.is_alive() or not self.process.stdin or not self.process.stdout:
            raise RuntimeError("Analysis worker is not running.")

        result = None
        failed_message = ""
        side_output = []

        def handle_line(line):
            nonlocal result, failed_message
            text = str(line or "").strip()
            if not text:
                return False
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                side_output.append(strip_ansi(text))
                return False
            payload_type = payload.get("type")
            if payload_type == "event":
                event = payload.get("event")
                if isinstance(event, dict) and on_event:
                    on_event(event)
            elif payload_type == "finished":
                result_value = payload.get("result")
                result = result_value if isinstance(result_value, dict) else {}
                return True
            elif payload_type == "failed":
                failed_message = strip_ansi(payload.get("message") or "Analysis worker failed.")
                return True
            return False

        try:
            self.process.stdin.write(json.dumps(request, ensure_ascii=False, default=str) + "\n")
            self.process.stdin.flush()
            while True:
                line = self.process.stdout.readline()
                if line == "":
                    break
                if handle_line(line):
                    break
        except BrokenPipeError as exc:
            failed_message = strip_ansi(exc)

        self.last_used = time.monotonic()
        if failed_message:
            raise RuntimeError(strip_ansi(failed_message))
        if result is None:
            code = self.process.poll()
            suffix = f" with code {code}" if code is not None else ""
            detail = "\n".join(side_output[-20:]) or f"Analysis worker exited unexpectedly{suffix}."
            raise RuntimeError(strip_ansi(detail))
        return result


class AnalysisProcessPool:
    def __init__(self, idle_seconds=ANALYSIS_WORKER_IDLE_SECONDS, max_idle=1, command_factory=None):
        self.idle_seconds = idle_seconds
        self.max_idle = max_idle
        self.command_factory = command_factory or persistent_analysis_worker_command
        self._idle = []
        self._lock = threading.Lock()
        self._trim_timer = None

    def _new_process(self):
        return PersistentAnalysisProcess(command=self.command_factory())

    def _schedule_trim_locked(self):
        if not self._idle:
            return
        if self._trim_timer and self._trim_timer.is_alive():
            return
        self._trim_timer = threading.Timer(self.idle_seconds + 0.1, self._trim_from_timer)
        self._trim_timer.daemon = True
        self._trim_timer.start()

    def _trim_from_timer(self):
        with self._lock:
            self._trim_locked()
            if self._idle:
                self._schedule_trim_locked()

    def _trim_locked(self):
        now = time.monotonic()
        alive = [
            worker
            for worker in self._idle
            if worker.is_alive() and now - worker.last_used <= self.idle_seconds
        ]
        alive.sort(key=lambda worker: worker.last_used, reverse=True)
        survivors = alive[:self.max_idle]
        survivor_ids = {id(worker) for worker in survivors}
        for worker in self._idle:
            if id(worker) not in survivor_ids:
                worker.close()
        self._idle = survivors

    def warm(self):
        with self._lock:
            self._trim_locked()
            if self._idle:
                self._schedule_trim_locked()
                return
            self._idle.append(self._new_process())
            self._schedule_trim_locked()

    def run(self, request, on_event=None):
        with self._lock:
            self._trim_locked()
            worker = self._idle.pop() if self._idle else self._new_process()
        try:
            return worker.run(request, on_event=on_event)
        finally:
            with self._lock:
                if worker.is_alive():
                    self._idle.append(worker)
                    self._trim_locked()
                    self._schedule_trim_locked()
                else:
                    worker.close()

    def close_all(self):
        with self._lock:
            if self._trim_timer:
                self._trim_timer.cancel()
                self._trim_timer = None
            workers = list(self._idle)
            self._idle = []
        for worker in workers:
            worker.close()


def download_process_pool():
    global _DOWNLOAD_PROCESS_POOL
    with _DOWNLOAD_PROCESS_POOL_LOCK:
        if _DOWNLOAD_PROCESS_POOL is None:
            _DOWNLOAD_PROCESS_POOL = DownloadProcessPool()
            atexit.register(_DOWNLOAD_PROCESS_POOL.close_all)
        return _DOWNLOAD_PROCESS_POOL


def warm_download_worker():
    download_process_pool().warm()


def cancel_download_request(request_id):
    return download_process_pool().cancel(request_id)


def analysis_process_pool():
    global _ANALYSIS_PROCESS_POOL
    with _ANALYSIS_PROCESS_POOL_LOCK:
        if _ANALYSIS_PROCESS_POOL is None:
            _ANALYSIS_PROCESS_POOL = AnalysisProcessPool()
            atexit.register(_ANALYSIS_PROCESS_POOL.close_all)
        return _ANALYSIS_PROCESS_POOL


def warm_analysis_worker():
    analysis_process_pool().warm()


def _analyze_url_in_one_shot_worker(request, on_event=None, process_command=None):
    temp_root = Path(tempfile.mkdtemp(prefix="clipflow-analysis-"))
    request_path = temp_root / "request.json"
    result = None
    failed_message = ""
    side_output = []

    def handle_payload(payload):
        nonlocal result, failed_message
        if not isinstance(payload, dict):
            return
        payload_type = payload.get("type")
        if payload_type == "event":
            event = payload.get("event")
            if isinstance(event, dict) and on_event:
                on_event(event)
        elif payload_type == "finished":
            result_value = payload.get("result")
            result = result_value if isinstance(result_value, dict) else {}
        elif payload_type == "failed":
            failed_message = strip_ansi(payload.get("message") or "Analysis worker failed.")

    def handle_line(line):
        text = str(line or "").strip()
        if not text:
            return
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            side_output.append(strip_ansi(text))
            return
        handle_payload(payload)

    request_path.write_text(json.dumps(dict(request or {}), ensure_ascii=False, default=str), encoding="utf-8")
    command = process_command or analysis_worker_command(request_path)
    env = _download_worker_environment()
    cwd = str(Path(__file__).resolve().parents[1])
    creationflags = _download_worker_creationflags()

    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        if process.stdout:
            try:
                for line in process.stdout:
                    handle_line(line)
            finally:
                process.stdout.close()
        return_code = process.wait()
        if failed_message or return_code:
            detail = failed_message or "\n".join(side_output[-20:]) or f"Analysis worker exited with code {return_code}."
            raise RuntimeError(strip_ansi(detail))
        if result is None:
            detail = "\n".join(side_output[-20:]) or "Analysis worker did not return a result."
            raise RuntimeError(strip_ansi(detail))
        return result
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def analyze_url_in_subprocess(
    url,
    cookie_source="없음",
    output_ext=None,
    on_event=None,
    proxy_url=None,
    process_command=None,
):
    request = _analysis_worker_request(
        url,
        cookie_source=cookie_source,
        output_ext=output_ext,
        proxy_url=proxy_url,
    )
    if process_command is not None:
        return _analyze_url_in_one_shot_worker(request, on_event=on_event, process_command=process_command)
    return analysis_process_pool().run(request, on_event=on_event)


def _download_candidate_in_one_shot_worker(request, on_event=None, process_command=None):
    temp_root = Path(tempfile.mkdtemp(prefix="clipflow-download-"))
    request_path = temp_root / "request.json"
    event_path = temp_root / "events.jsonl"
    stderr_path = temp_root / "stderr.log"
    result = None
    failed_message = ""
    side_output = []

    def handle_payload(payload):
        nonlocal result, failed_message
        if not isinstance(payload, dict):
            return
        payload_type = payload.get("type")
        if payload_type == "event":
            event = payload.get("event")
            if isinstance(event, dict) and on_event:
                on_event(event)
        elif payload_type == "finished":
            result_value = payload.get("result")
            result = result_value if isinstance(result_value, dict) else {}
        elif payload_type == "failed":
            failed_message = strip_ansi(payload.get("message") or "Download worker failed.")

    def handle_line(line):
        text = str(line or "").strip()
        if not text:
            return
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            side_output.append(strip_ansi(text))
            return
        handle_payload(payload)

    request = dict(request or {})
    use_event_file = process_command is None
    if use_event_file:
        request["event_path"] = str(event_path)
    request_path.write_text(json.dumps(request, ensure_ascii=False, default=str), encoding="utf-8")

    command = process_command or download_worker_command(request_path)
    env = _download_worker_environment()
    cwd = str(Path(__file__).resolve().parents[1])
    creationflags = _download_worker_creationflags()

    try:
        if use_event_file:
            with stderr_path.open("w", encoding="utf-8", errors="replace") as stderr_file:
                process = subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=stderr_file,
                    text=True,
                    creationflags=creationflags,
                )
                consumed_length = 0
                pending_line = ""
                def consume_event_file(final=False):
                    nonlocal consumed_length, pending_line
                    if not event_path.exists():
                        return
                    text = event_path.read_text(encoding="utf-8", errors="replace")
                    if len(text) < consumed_length:
                        consumed_length = 0
                        pending_line = ""
                    new_text = text[consumed_length:]
                    consumed_length = len(text)
                    if new_text:
                        pending_line += new_text
                    while True:
                        newline_index = pending_line.find("\n")
                        if newline_index < 0:
                            break
                        line = pending_line[:newline_index].removesuffix("\r")
                        pending_line = pending_line[newline_index + 1:]
                        handle_line(line)
                    if final and pending_line.strip():
                        handle_line(pending_line)
                        pending_line = ""

                while process.poll() is None:
                    consume_event_file()
                    time.sleep(0.05)
                consume_event_file(final=True)
                return_code = process.wait()
            if stderr_path.exists():
                stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
                if stderr_text.strip():
                    side_output.extend(strip_ansi(line) for line in stderr_text.splitlines() if line.strip())
        else:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
            if process.stdout:
                try:
                    for line in process.stdout:
                        handle_line(line)
                finally:
                    process.stdout.close()
            return_code = process.wait()

        if failed_message or return_code:
            detail = failed_message or "\n".join(side_output[-20:]) or f"Download worker exited with code {return_code}."
            raise RuntimeError(strip_ansi(detail))
        if result is None:
            detail = "\n".join(side_output[-20:]) or "Download worker did not return a result."
            raise RuntimeError(strip_ansi(detail))
        return result
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def download_candidate_in_subprocess(
    page_url,
    candidate,
    output_dir,
    cookie_source="없음",
    on_event=None,
    proxy_url=None,
    process_command=None,
):
    request = _download_worker_request(
        page_url,
        candidate,
        output_dir,
        cookie_source=cookie_source,
        proxy_url=proxy_url,
    )
    if process_command is not None:
        return _download_candidate_in_one_shot_worker(request, on_event=on_event, process_command=process_command)
    return download_process_pool().run(request, on_event=on_event)


def should_retry_progressive_mp4(candidate, exc, allow_progressive=False):
    output_ext = normalized_output_ext((candidate or {}).get("output_ext"))
    if output_ext in AUDIO_OUTPUT_EXTENSIONS:
        return False
    selector = str((candidate or {}).get("format_selector") or "")
    if selector == "18/best[ext=mp4]/best" and not allow_progressive:
        return False
    message = str(exc).lower()
    if "unable to download video data" not in message:
        return False
    return "http error 403" in message or "http error 404" in message


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
