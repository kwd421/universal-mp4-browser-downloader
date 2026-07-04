"""Check whether a packaged build would see a newer appcast version."""

import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import clipflow_updater as updater


def main():
    simulated_build = sys.argv[1] if len(sys.argv) > 1 else "104"
    with mock.patch.object(updater, "updater_build_number", return_value=simulated_build):
        available = updater.startup_update_is_available()
        latest = None
        for feed in updater.updater_feed_url_candidates():
            try:
                latest = updater._latest_appcast_build_number(feed)
                if latest is not None:
                    break
            except Exception:
                continue
    print(f"simulated_build={simulated_build}")
    print(f"latest_appcast={latest}")
    print(f"update_available={available}")
    return 0 if available else 1


if __name__ == "__main__":
    raise SystemExit(main())