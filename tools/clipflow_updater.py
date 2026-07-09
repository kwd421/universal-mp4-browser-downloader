"""Auto-update bridge for packaged ClipFlow builds."""

import atexit
import ctypes
import os
import plistlib
import re
import sys
import threading
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"
SPARKLE_VERSION_TAG = f"{{{SPARKLE_NS}}}version"
SPARKLE_SHORT_VERSION_TAG = f"{{{SPARKLE_NS}}}shortVersionString"
SPARKLE_RELEASE_NOTES_TAG = f"{{{SPARKLE_NS}}}releaseNotesLink"

_MAX_APPCAST_BYTES = 1024 * 1024

DEFAULT_WINDOWS_FEED_URL = "https://kwd421.github.io/ClipFlow/appcast-windows.xml"
FALLBACK_WINDOWS_FEED_URL = "https://raw.githubusercontent.com/kwd421/ClipFlow/main/docs/appcast-windows.xml"

APP_VENDOR = "ClipFlow"
APP_NAME = "ClipFlow"


def _updater_env(name, fallback_name=None):
    value = os.environ.get(name) or ""
    if value:
        return value.strip()
    if fallback_name:
        return (os.environ.get(fallback_name) or "").strip()
    return ""


def _frozen_build_config():
    if not getattr(sys, "frozen", False):
        return None
    try:
        from tools import clipflow_build_config as config
    except ImportError:
        try:
            import clipflow_build_config as config
        except ImportError:
            return None
    return config


def _frozen_build_value(attr):
    config = _frozen_build_config()
    if config is None:
        return ""
    return str(getattr(config, attr, "") or "").strip()


def updater_feed_url():
    if sys.platform == "darwin":
        return _updater_env("CLIPFLOW_SPARKLE_FEED_URL")
    value = _updater_env("CLIPFLOW_WINSPARKLE_FEED_URL", "CLIPFLOW_SPARKLE_FEED_URL")
    return value or _frozen_build_value("FEED_URL")


def updater_feed_url_candidates():
    candidates = []
    for value in (
        updater_feed_url(),
        DEFAULT_WINDOWS_FEED_URL if sys.platform == "win32" else "",
        FALLBACK_WINDOWS_FEED_URL if sys.platform == "win32" else "",
    ):
        text = str(value or "").strip()
        if text and text not in candidates:
            candidates.append(text)
    return candidates


def updater_public_ed_key():
    return _updater_env("CLIPFLOW_SPARKLE_PUBLIC_ED_KEY") or _frozen_build_value("PUBLIC_ED_KEY")


def updater_app_version():
    return (
        _updater_env("CLIPFLOW_VERSION", "CLIPFLOW_APP_VERSION")
        or _frozen_build_value("VERSION")
        or "0.0.0"
    )


def updater_build_number():
    return _updater_env("CLIPFLOW_BUILD_NUMBER") or _frozen_build_value("BUILD_NUMBER") or updater_app_version()


def updater_configured():
    return bool(updater_feed_url_candidates())


def winsparkle_installer_ready():
    return bool(updater_feed_url() and updater_public_ed_key())


def _build_number_int(value):
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", text)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2))
        patch = int(match.group(3))
        if major < 10 and minor < 10 and patch < 10:
            return major * 100 + minor * 10 + patch
    return None


def _latest_appcast_item(feed_url):
    request = urllib.request.Request(feed_url, headers={"User-Agent": "ClipFlow-Updater"})
    with urllib.request.urlopen(request, timeout=15) as response:
        chunks = []
        total = 0
        while True:
            block = response.read(64 * 1024)
            if not block:
                break
            total += len(block)
            if total > _MAX_APPCAST_BYTES:
                raise RuntimeError("Appcast feed too large")
            chunks.append(block)
        root = ET.fromstring(b"".join(chunks))
    item = root.find("channel/item")
    if item is None:
        return None
    version_el = item.find(SPARKLE_VERSION_TAG)
    if version_el is None or not version_el.text:
        return None
    try:
        build = int(version_el.text.strip())
    except ValueError:
        return None
    short_el = item.find(SPARKLE_SHORT_VERSION_TAG)
    short_version = (short_el.text or "").strip() if short_el is not None else ""
    if not short_version:
        title_el = item.find("title")
        short_version = (title_el.text or "").strip() if title_el is not None else ""
    notes_el = item.find(SPARKLE_RELEASE_NOTES_TAG)
    if notes_el is None:
        notes_el = item.find("link")
    notes_url = (notes_el.text or "").strip() if notes_el is not None else ""
    return {
        "build": build,
        "version": short_version or str(build),
        "release_notes_url": notes_url,
    }


def _latest_appcast_build_number(feed_url):
    item = _latest_appcast_item(feed_url)
    if not item:
        return None
    return item.get("build")


def fetch_startup_update_info():
    """Return latest update info dict if newer than current, else None."""
    current = _build_number_int(updater_build_number())
    if current is None:
        return None
    for feed_url in updater_feed_url_candidates():
        try:
            item = _latest_appcast_item(feed_url)
        except Exception:
            continue
        if not item:
            continue
        latest = item.get("build")
        if latest is None or latest <= current:
            continue
        return item
    return None


def startup_update_is_available():
    return fetch_startup_update_info() is not None


class _MainThreadDispatcher:
    def __init__(self):
        try:
            from PySide6.QtCore import QObject, Signal, Slot, Qt
        except ImportError:
            self._qt = None
            return
        self._qt = True

        class _Bridge(QObject):
            callback_requested = Signal(object)

            def __init__(self):
                super().__init__()
                self.callback_requested.connect(self._run_callback, Qt.QueuedConnection)

            @Slot(object)
            def _run_callback(self, callback):
                if callable(callback):
                    callback()

        self._bridge = _Bridge()

    def dispatch(self, callback):
        if callback is None:
            return
        if self._qt is None:
            callback()
            return
        self._bridge.callback_requested.emit(callback)


_MAIN_THREAD_DISPATCHER = None


def ensure_main_thread_dispatcher():
    global _MAIN_THREAD_DISPATCHER
    if _MAIN_THREAD_DISPATCHER is None:
        _MAIN_THREAD_DISPATCHER = _MainThreadDispatcher()
    return _MAIN_THREAD_DISPATCHER


def _main_thread_dispatcher():
    return ensure_main_thread_dispatcher()


def _dispatch_to_main_thread(callback):
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        if callable(callback):
            callback()
        return
    if QApplication.instance() is None:
        if callable(callback):
            callback()
        return
    _main_thread_dispatcher().dispatch(callback)


class SparkleUpdater:
    def __init__(self, controller, delegate=None):
        self.controller = controller
        self.delegate = delegate

    def schedule_startup_check(self, on_found):
        if self.delegate is not None and hasattr(self.delegate, "set_on_found_"):
            self.delegate.set_on_found_(on_found)
        try:
            self.controller.updater().checkForUpdatesInBackground()
        except Exception:
            pass

    def check_for_updates(self):
        self.controller.checkForUpdates_(None)


def _running_app_bundle():
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    contents_dir = executable.parent.parent
    if contents_dir.name != "Contents":
        return None
    app_bundle = contents_dir.parent
    if app_bundle.suffix != ".app":
        return None
    return app_bundle


def _sparkle_configured(app_bundle):
    plist_path = app_bundle / "Contents" / "Info.plist"
    try:
        with plist_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        return False
    return bool(info.get("SUFeedURL") and info.get("SUPublicEDKey"))


def _create_sparkle_delegate():
    try:
        import objc
        from Foundation import NSObject
    except ImportError:
        return None

    class ClipFlowSparkleDelegate(NSObject):
        def init(self):
            self = objc.super(ClipFlowSparkleDelegate, self).init()
            if self is None:
                return None
            self._on_found = None
            return self

        def set_on_found_(self, callback):
            self._on_found = callback

        def updater_didFindValidUpdate_(self, updater, item):
            del updater, item
            _dispatch_to_main_thread(self._on_found)

    return ClipFlowSparkleDelegate.alloc().init()


def start_sparkle_updater():
    app_bundle = _running_app_bundle()
    if not app_bundle or not _sparkle_configured(app_bundle):
        return None

    framework_path = app_bundle / "Contents" / "Frameworks" / "Sparkle.framework"
    if not framework_path.exists():
        return None

    try:
        import objc
        from Foundation import NSBundle
    except ImportError:
        return None

    bundle = NSBundle.bundleWithPath_(str(framework_path))
    if not bundle or not bundle.load():
        return None

    delegate = _create_sparkle_delegate()
    try:
        updater_class = objc.lookUpClass("SPUStandardUpdaterController")
        controller = updater_class.alloc().initWithStartingUpdater_updaterDelegate_userDriverDelegate_(False, delegate, None)
    except (objc.error, AttributeError):
        return None

    return SparkleUpdater(controller, delegate)


def _winsparkle_dll_candidates():
    arch = "x64" if sys.maxsize > 2**32 else "x86"
    root = Path(__file__).resolve().parent.parent
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "WinSparkle.dll")
        candidates.append(Path(sys.executable).resolve().parent / "WinSparkle.dll")
    candidates.extend(
        [
            root / "build-helper" / "third_party" / "winsparkle" / "WinSparkle-0.9.3" / arch / "Release" / "WinSparkle.dll",
            root / "build-helper" / "third_party" / "winsparkle" / arch / "WinSparkle.dll",
        ]
    )
    return candidates


def _load_winsparkle_library():
    if sys.platform != "win32":
        return None
    for candidate in _winsparkle_dll_candidates():
        if candidate.is_file():
            try:
                return ctypes.WinDLL(str(candidate))
            except OSError:
                continue
    return None


class WinSparkleUpdater:
    def __init__(self, library):
        self._library = library
        self._callbacks = []
        self._on_found = None
        self._winsparkle_ready = False

    def _ensure_winsparkle_ready(self):
        if self._winsparkle_ready:
            return self._library is not None
        if self._library is None:
            self._library = _load_winsparkle_library()
        if self._library is None:
            return False
        library, callbacks = _init_winsparkle_library(self._library)
        if library is None:
            self._library = None
            self._callbacks = []
            return False
        self._library = library
        self._callbacks = callbacks
        self._winsparkle_ready = True
        return True

    def schedule_startup_check(self, on_found):
        self._on_found = on_found

        def worker():
            try:
                info = fetch_startup_update_info()
                if info:
                    callback = self._on_found
                    _dispatch_to_main_thread(lambda: callback(info) if callable(callback) else None)
            except Exception:
                pass

        threading.Thread(target=worker, name="clipflow-update-check", daemon=True).start()

    def check_for_updates(self):
        if not self._ensure_winsparkle_ready():
            return
        self._library.win_sparkle_check_update_with_ui()


def _winsparkle_void_callback_type():
    return ctypes.WINFUNCTYPE(None)


def _winsparkle_int_callback_type():
    return ctypes.WINFUNCTYPE(ctypes.c_int)


def _bind_winsparkle_api(library):
    library.win_sparkle_set_appcast_url.argtypes = [ctypes.c_char_p]
    library.win_sparkle_set_appcast_url.restype = None
    library.win_sparkle_set_eddsa_public_key.argtypes = [ctypes.c_char_p]
    library.win_sparkle_set_eddsa_public_key.restype = ctypes.c_int
    library.win_sparkle_set_app_details.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
    library.win_sparkle_set_app_details.restype = None
    library.win_sparkle_set_app_build_version.argtypes = [ctypes.c_wchar_p]
    library.win_sparkle_set_app_build_version.restype = None
    library.win_sparkle_set_automatic_check_for_updates.argtypes = [ctypes.c_int]
    library.win_sparkle_set_automatic_check_for_updates.restype = None
    library.win_sparkle_set_can_shutdown_callback.argtypes = [_winsparkle_int_callback_type()]
    library.win_sparkle_set_can_shutdown_callback.restype = None
    library.win_sparkle_set_shutdown_request_callback.argtypes = [_winsparkle_void_callback_type()]
    library.win_sparkle_set_shutdown_request_callback.restype = None
    library.win_sparkle_set_did_find_update_callback.argtypes = [_winsparkle_void_callback_type()]
    library.win_sparkle_set_did_find_update_callback.restype = None
    library.win_sparkle_init.argtypes = []
    library.win_sparkle_init.restype = None
    library.win_sparkle_cleanup.argtypes = []
    library.win_sparkle_cleanup.restype = None
    library.win_sparkle_check_update_with_ui.argtypes = []
    library.win_sparkle_check_update_with_ui.restype = None
    library.win_sparkle_check_update_without_ui.argtypes = []
    library.win_sparkle_check_update_without_ui.restype = None


def _request_app_shutdown():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is not None:
        app.quit()


def _init_winsparkle_library(library):
    if not winsparkle_installer_ready():
        return None, []

    _bind_winsparkle_api(library)
    feed_url = updater_feed_url().encode("utf-8")
    public_key = updater_public_ed_key().encode("ascii")
    if not library.win_sparkle_set_eddsa_public_key(public_key):
        return None, []

    library.win_sparkle_set_appcast_url(feed_url)
    library.win_sparkle_set_app_details(APP_VENDOR, APP_NAME, updater_app_version())
    library.win_sparkle_set_app_build_version(updater_build_number())
    library.win_sparkle_set_automatic_check_for_updates(0)

    callbacks = []

    @_winsparkle_int_callback_type()
    def can_shutdown():
        return 1

    @_winsparkle_void_callback_type()
    def shutdown_request():
        _request_app_shutdown()

    callbacks.extend([can_shutdown, shutdown_request])
    library.win_sparkle_set_can_shutdown_callback(can_shutdown)
    library.win_sparkle_set_shutdown_request_callback(shutdown_request)
    library.win_sparkle_init()
    atexit.register(library.win_sparkle_cleanup)
    return library, callbacks


def start_winsparkle_updater():
    if not getattr(sys, "frozen", False):
        return None
    if not updater_configured():
        return None

    updater = WinSparkleUpdater(None)
    updater._callbacks = []
    return updater


def start_app_updater():
    if sys.platform == "darwin":
        return start_sparkle_updater()
    if sys.platform == "win32":
        return start_winsparkle_updater()
    return None