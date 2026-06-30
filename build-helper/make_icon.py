"""Generate ClipFlow.icns from the in-app 'Cf' logo (create_app_icon).

Run: QT_QPA_PLATFORM=offscreen python build-helper/make_icon.py
Produces build-helper/ClipFlow.icns (via a temporary .iconset + iconutil).
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tools.clipflow_theme import configure_app_font, create_app_icon


def main():
    app = QApplication(sys.argv)
    configure_app_font(app)

    out_dir = Path(__file__).resolve().parent
    iconset = out_dir / "ClipFlow.iconset"
    iconset.mkdir(exist_ok=True)

    # (filename, pixel size)
    specs = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]
    for name, size in specs:
        icon = create_app_icon(size)
        pixmap = icon.pixmap(size, size)
        pixmap.save(str(iconset / name), "PNG")

    # Windows .ico (cross-platform via Pillow) from the largest master PNG.
    try:
        from PIL import Image

        master = Image.open(iconset / "icon_512x512@2x.png").convert("RGBA")
        ico = out_dir / "ClipFlow.ico"
        master.save(
            str(ico),
            format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        print("wrote", ico)
    except Exception as exc:  # noqa: BLE001 - icon generation is best-effort
        print("skip .ico:", exc)

    # macOS .icns via iconutil (only available on macOS).
    if sys.platform == "darwin":
        icns = out_dir / "ClipFlow.icns"
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True)
        print("wrote", icns)


if __name__ == "__main__":
    main()
