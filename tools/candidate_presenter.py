from dataclasses import dataclass

try:
    from tools import downloader_engine as engine
except ImportError:
    import downloader_engine as engine


VIDEO_FORMATS = ["mp4", "webm"]
AUDIO_FORMATS = ["mp3", "wav", "aac"]


@dataclass(frozen=True)
class DownloadPreferences:
    quality: str = "자동"
    output_format: str = "MP4"
    codec: str = "자동"
    frame_rate: str = "자동"


def candidate_group_key(candidate):
    media_type = candidate.get("media_type") or "video"
    group_media_type = "video" if media_type == "audio" else media_type
    return (
        candidate.get("source") or candidate.get("url") or "",
        candidate.get("display_title") or candidate.get("title") or "video",
        candidate.get("thumbnail") or "",
        group_media_type,
    )


def candidate_quality_key(candidate):
    vcodec = str(candidate.get("vcodec") or "").lower()
    acodec = str(candidate.get("acodec") or "").lower()
    return (
        engine.safe_int(candidate.get("height")),
        1 if vcodec.startswith(("avc", "h264")) else 0,
        1 if acodec.startswith(("mp4a", "aac")) else 0,
        engine.safe_int(candidate.get("sort_bytes")),
        engine.safe_int(candidate.get("fps")),
    )


def candidate_visible_quality_key(candidate):
    ext = str(candidate.get("output_ext") or candidate.get("ext") or "").lower()
    media_type = candidate.get("media_type") or "video"
    if media_type == "audio" or ext == "wav":
        return ("audio", ext, candidate.get("note") or "")
    return (
        "video",
        ext,
        engine.safe_int(candidate.get("height")),
        engine.safe_int(candidate.get("fps")),
    )


def quality_label(candidate):
    ext = str(candidate.get("output_ext") or candidate.get("ext") or "").upper()
    size = engine.display_size(candidate.get("sort_bytes"))
    if candidate.get("media_type") == "audio" or ext == "WAV":
        note = candidate.get("note") or "audio"
        return f"{ext} · {size} · {note}"
    resolution = candidate.get("resolution") or "unknown"
    return f"{resolution} · {ext} · {size}"


def _normalized_format(candidate):
    return str(candidate.get("output_ext") or candidate.get("ext") or "").strip().lower()


def _format_family(format_label):
    normalized = str(format_label or "").strip().lower()
    return "audio" if normalized in AUDIO_FORMATS else "video"


def _format_order(format_label):
    normalized = str(format_label or "").strip().lower()
    if normalized in AUDIO_FORMATS:
        return [normalized] + [item for item in AUDIO_FORMATS if item != normalized]
    preferred = normalized if normalized in VIDEO_FORMATS else VIDEO_FORMATS[0]
    return [preferred] + [item for item in VIDEO_FORMATS if item != preferred]


def _candidate_family(candidate):
    media_type = str(candidate.get("media_type") or "").lower()
    return "audio" if media_type == "audio" or _normalized_format(candidate) in AUDIO_FORMATS else "video"


def _codec_name(candidate):
    codec = str(candidate.get("vcodec") or "").lower()
    if codec.startswith(("avc", "h264")):
        return "H264"
    if codec.startswith(("hev", "h265")):
        return "H265"
    if codec.startswith(("av01", "av1")):
        return "AV1"
    if codec.startswith(("vp9", "vp09")):
        return "VP9"
    return codec.upper()


def _target_height(quality):
    text = str(quality or "").strip().lower()
    if text in {"", "자동", "auto"}:
        return 0
    digits = "".join(char for char in text if char.isdigit())
    return int(digits) if digits else 0


def _target_fps(frame_rate):
    text = str(frame_rate or "").strip().lower()
    if text in {"", "자동", "auto"}:
        return 0
    digits = "".join(char for char in text if char.isdigit())
    return int(digits) if digits else 0


def _best_candidate(candidates, preferences):
    candidates = list(candidates or [])
    target_height = _target_height(preferences.quality)
    target_fps = _target_fps(preferences.frame_rate)
    target_codec = str(preferences.codec or "").strip().upper()
    codec_auto = target_codec in {"", "자동", "AUTO"}
    if target_height and any(engine.safe_int(candidate.get("height")) <= target_height for candidate in candidates):
        candidates = [
            candidate
            for candidate in candidates
            if engine.safe_int(candidate.get("height")) <= target_height
        ]
    if target_fps and any(engine.safe_int(candidate.get("fps")) <= target_fps for candidate in candidates):
        candidates = [
            candidate
            for candidate in candidates
            if engine.safe_int(candidate.get("fps")) <= target_fps
        ]

    def score(candidate):
        height = engine.safe_int(candidate.get("height"))
        fps = engine.safe_int(candidate.get("fps"))
        size = engine.safe_int(candidate.get("sort_bytes"))
        codec = _codec_name(candidate)
        codec_score = 1 if codec_auto or codec == target_codec else 0
        return (codec_score, height, fps, size)

    return max(candidates, key=score) if candidates else None


def select_candidate_for_preferences(candidates, preferences):
    preferences = preferences or DownloadPreferences()
    family = _format_family(preferences.output_format)
    family_candidates = [
        candidate
        for candidate in candidates or []
        if _candidate_family(candidate) == family
    ]
    for output_format in _format_order(preferences.output_format):
        matching = [
            candidate
            for candidate in family_candidates
            if _normalized_format(candidate) == output_format
        ]
        selected = _best_candidate(matching, preferences)
        if selected:
            return selected
    return _best_candidate(family_candidates, preferences)


def filter_manifest_duplicates(candidates):
    has_sized_direct = any(
        not candidate.get("is_manifest") and engine.safe_int(candidate.get("sort_bytes")) > 0
        for candidate in candidates
    )
    if not has_sized_direct:
        return candidates

    filtered = []
    for candidate in candidates:
        note = str(candidate.get("note") or "").lower()
        if candidate.get("is_manifest"):
            continue
        if note in {"original", "default", "(original)", "(default)"}:
            continue
        filtered.append(candidate)
    return filtered or candidates


def filter_visible_quality_duplicates(candidates):
    filtered = []
    seen = set()
    for candidate in candidates:
        key = candidate_visible_quality_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        filtered.append(candidate)
    return filtered


def group_candidates(candidates):
    groups = {}
    order = []
    for candidate in candidates:
        key = candidate_group_key(candidate)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(candidate)

    rows = []
    for index, key in enumerate(order, start=1):
        qualities = sorted(filter_manifest_duplicates(groups[key]), key=candidate_quality_key, reverse=True)
        qualities = filter_visible_quality_duplicates(qualities)
        if not qualities:
            continue
        rows.append({"id": f"group-{index}", "candidate": qualities[0], "qualities": qualities})
    return rows
