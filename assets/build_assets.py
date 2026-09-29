"""Build the full logo asset pipeline from logo-master.png.

Pipeline:

    assets/logo-master.png  (1024x1024, transparent)
        |
        +-- assets/icon.iconset/   (macOS .iconset — 11 PNG sizes)
        |       |
        |       +-- assets/icon.icns       (iconutil → final app icon)
        |
        +-- comfy_model_downloader/web/favicon.png       (32x32, opaque bg)
        +-- assets/logo-mark-32.png                     (small UI mark)
        +-- assets/logo-mark-128.png                    (medium UI mark)

Re-run this whenever logo-master.png changes; it regenerates every derived
asset in one shot. PNG iconset is required by macOS / iconutil; .icns is what
PyInstaller's BUNDLE.icon= consumes.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
WEB = ROOT / "comfy_model_downloader" / "web"
MASTER = ASSETS / "logo-master.png"
ICONSET = ASSETS / "icon.iconset"
ICNS = ASSETS / "icon.icns"
FAVICON = WEB / "favicon.png"
MARK_32 = ASSETS / "logo-mark-32.png"
MARK_128 = ASSETS / "logo-mark-128.png"

# macOS .iconset spec — see `iconutil --help`.  Each size gets both a
# regular-density and (where listed) @2x retina variant.
ICONSET_SIZES: list[tuple[int, str]] = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]

# BG used to flatten the icon (macOS expects opaque icons in the .iconset)
ICON_BG_HEX = "0E1116"


def _sips_resize(src: Path, dst: Path, size: int) -> None:
    """Resize a PNG to ``size``x``size`` using macOS sips (no PIL needed)."""
    subprocess.run(
        ["sips", "-z", str(size), str(size), str(src), "--out", str(dst)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _flatten_bg(png_path: Path, bg_hex: str) -> None:
    """macOS .iconset expects opaque PNGs; flatten transparent master onto bg."""
    from PIL import Image

    img = Image.open(png_path).convert("RGBA")
    bg = Image.new("RGBA", img.size, f"#{bg_hex}")
    bg.alpha_composite(img)
    bg.convert("RGB").save(png_path, format="PNG", optimize=True)


def _make_iconset() -> None:
    if ICONSET.exists():
        shutil.rmtree(ICONSET)
    ICONSET.mkdir(parents=True)

    # 1024@2x first so subsequent sips downsamples always start from a clean
    # high-quality source (sips is poor at upscaling).
    high = ICONSET / "icon_512x512@2x.png"
    _sips_resize(MASTER, high, 1024)

    for size, name in ICONSET_SIZES:
        if name == "icon_512x512@2x.png":
            continue  # already produced above
        _sips_resize(high, ICONSET / name, size)
        _flatten_bg(ICONSET / name, ICON_BG_HEX)

    # Ensure the 1024 copy is also opaque
    _flatten_bg(high, ICON_BG_HEX)


def _make_icns() -> None:
    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET), "-o", str(ICNS)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _make_favicon() -> None:
    """Favicon for the web UI. Small + opaque background; reads at 16-32px."""
    WEB.mkdir(parents=True, exist_ok=True)
    if FAVICON.exists():
        FAVICON.unlink()
    # 32x32 is the sweet spot for browser favicons — large enough to read,
    # small enough to stay sharp. Opaque bg matches the dark UI.
    _sips_resize(MASTER, FAVICON, 32)
    _flatten_bg(FAVICON, ICON_BG_HEX)


def _make_brand_marks() -> None:
    """Mid-resolution mark PNGs for use as inline UI marks / README header."""
    if MARK_32.exists():
        MARK_32.unlink()
    if MARK_128.exists():
        MARK_128.unlink()
    _sips_resize(MASTER, MARK_32, 32)
    _sips_resize(MASTER, MARK_128, 128)


def main() -> int:
    if not MASTER.exists():
        print(f"missing master: {MASTER} — run assets/render_logo.py first",
              file=sys.stderr)
        return 1

    print(f"→ iconset ({len(ICONSET_SIZES)} sizes)")
    _make_iconset()
    print(f"→ icns: {ICNS.relative_to(ROOT)}")
    _make_icns()
    print(f"→ favicon: {FAVICON.relative_to(ROOT)}")
    _make_favicon()
    print(f"→ brand marks: {MARK_32.name}, {MARK_128.name}")
    _make_brand_marks()
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())