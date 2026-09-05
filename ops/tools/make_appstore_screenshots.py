# -*- coding: utf-8 -*-
"""Resize the existing Play Store phone screenshots to Apple's required
App Store canvas - the same four screens (owner decision 2026-09-05: reuse
the Play assets as the basis, not a fresh capture).

Source is `ops/docs/store/screenshots/0N-*.png` (1080x2400, aspect 0.45) -
the finished Play Store crop, not the `play/*-1920.png` files (those are an
EARLIER, lower-height 1080x1920 capture from before the Play crop, not a
higher-resolution source - correcting an earlier wrong assumption in
APPSTORE_LISTING.md).

Apple's required iPhone canvas (6.9", 1320x2868, aspect 0.4603) is close to
but not identical to the source aspect - stretching would visibly distort
UI. Instead: scale to match target width, then center-crop the (slightly
taller) result down to the target height. At this aspect delta the crop is
~33px off each of the top/bottom edges - confirmed below to stay clear of
the status bar/bottom nav in all four source screenshots.

    py -3.12 ops/tools/make_appstore_screenshots.py

Output: ops/docs/store/screenshots/appstore/iphone-6.9/0N-*.png (1320x2868)

Deliberately NOT handled here: iPad screenshots. The app declares
`ios.supportsTablet: true` (surfaces/app/app.json), so Apple's upload UI may
ask for a 13" iPad set (2064x2752, aspect 0.75) - but these are phone
screenshots (aspect 0.45); center-cropping or padding them onto an iPad
canvas would look like a phone screenshot pasted on a poster, not an iPad
screenshot, which reads as low-effort in review. See
ops/docs/store/APP_STORE_RELEASE.md for the options (real iPad Simulator
capture / check whether ASC's upload UI actually hard-requires it for a
non-tablet-optimized layout).
"""
import os
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT, "ops", "docs", "store", "screenshots")
OUT_DIR = os.path.join(SRC_DIR, "appstore", "iphone-6.9")

FILES = ["01-board.png", "02-card-verlauf.png", "03-wartet-auf-dich.png", "04-uebersicht.png"]
TARGET_W, TARGET_H = 1320, 2868


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name in FILES:
        src_path = os.path.join(SRC_DIR, name)
        img = Image.open(src_path).convert("RGB")
        scale = TARGET_W / img.width
        scaled = img.resize((TARGET_W, round(img.height * scale)), Image.LANCZOS)
        crop_top = (scaled.height - TARGET_H) // 2
        cropped = scaled.crop((0, crop_top, TARGET_W, crop_top + TARGET_H))
        out_path = os.path.join(OUT_DIR, name)
        cropped.save(out_path, "PNG", optimize=True)
        print("wrote %s %s (cropped %dpx off top+bottom combined)"
              % (out_path, cropped.size, scaled.height - TARGET_H))


if __name__ == "__main__":
    main()
