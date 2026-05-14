try:
    from tools import downloader_engine as engine
except ImportError:
    import downloader_engine as engine


def candidate_group_key(candidate):
    return (
        candidate.get("source") or candidate.get("url") or "",
        candidate.get("display_title") or candidate.get("title") or "video",
        candidate.get("thumbnail") or "",
        candidate.get("media_type") or "video",
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
