# -*- coding: utf-8 -*-
"""Render HelmDeck's app icon - one 'H' monogram across every surface.

SINGLE SOURCE OF TRUTH (2026-08-26, paying debt [make-icon-py-stale-design]):
this script used to hardcode a "glass H" design that had been superseded by
hand-editing every asset file directly during a logo redesign, leaving the
generator silently out of sync - running it would have reverted the ship.
It now derives EVERY target below from one fixed alpha mask,
ops/tools/assets/logo_h_mask.png (1024x1024): the H with a swept diagonal
crossbar, traced from an owner-approved AI concept image via luminance
threshold (see that day's session history - .loop/logo_final/
build_from_reference.py - for the extraction method; the shape has organic
curves with no clean parametric description, which is why it's a fixed
mask asset rather than drawn geometry like the old glass_H()/h_mask()).

The mark is flat (no gradient/shadow/sheen inside the glyph itself) in
#EAF2FB, composited onto a two-stop diagonal gradient tile (violet
top-right #534885 -> dark navy bottom-left #0D1C25 - the exact colors
already live in android-icon-background.png, sampled once during the
redesign and reused here so this script's output matches it exactly).

To change the mark: regenerate ops/tools/assets/logo_h_mask.png (a plain
white-on-transparent or white-on-black 1024x1024 PNG, any source), then:
    py -3.12 ops/tools/make_icon.py
Outputs:
    surfaces/desktop/assets/icon-1024.png, surfaces/desktop/assets/icon.ico   (Windows/Electron)
    surfaces/desktop/assets/icon-mac-1024.png                        (macOS icon grid)
    surfaces/app/assets/images/icon.png                              (Expo unified)
    surfaces/app/assets/images/favicon.png                           (web tab)
    surfaces/app/assets/images/android-icon-background.png           (adaptive bg)
    surfaces/app/assets/images/android-icon-foreground.png           (adaptive fg, H only)
    surfaces/app/assets/images/android-icon-monochrome.png           (themed-icon H)
    surfaces/app/assets/images/splash-icon.png                       (native splash)
    surfaces/app/assets/expo.icon/Assets/helmdeck-h.png              (iOS Liquid Glass layer)
"""
import json
import os
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DESK = os.path.join(ROOT, "surfaces", "desktop", "assets")
APPIMG = os.path.join(ROOT, "surfaces", "app", "assets", "images")
EXPOICON = os.path.join(ROOT, "surfaces", "app", "assets", "expo.icon")
MASK_PATH = os.path.join(HERE, "assets", "logo_h_mask.png")

SIZE = 1024

# --- brand palette - matches the live android-icon-background.png exactly ---
GRADIENT_TOP_RIGHT = (0x53, 0x48, 0x85)     # #534885 violet
GRADIENT_BOTTOM_LEFT = (0x0D, 0x1C, 0x25)   # #0D1C25 dark navy
GLYPH_COLOR = (0xEA, 0xF2, 0xFB)            # #EAF2FB flat light blue-white

SAFE_ZONE = 0.62   # Android adaptive-icon inset so OEM circle/squircle masks never clip


def gradient_tile(size=SIZE):
    """Diagonal gradient: violet top-right -> navy bottom-left."""
    tile = Image.new("RGB", (size, size))
    px = tile.load()
    tr, tg, tb = GRADIENT_TOP_RIGHT
    br, bg, bb = GRADIENT_BOTTOM_LEFT
    denom = 2 * (size - 1)
    for y in range(size):
        for x in range(size):
            t = ((size - 1 - x) + y) / denom
            px[x, y] = (
                round(tr + (br - tr) * t),
                round(tg + (bg - tg) * t),
                round(tb + (bb - tb) * t),
            )
    return tile.convert("RGBA")


def load_glyph_mask():
    return Image.open(MASK_PATH).convert("L")


def flat_glyph(mask, color):
    out = Image.new("RGBA", mask.size, color + (0,))
    out.putalpha(mask)
    return out


def shrink_to_safezone(img, scale=SAFE_ZONE):
    size = img.size[0]
    new_size = round(size * scale)
    small = img.resize((new_size, new_size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset = (size - new_size) // 2
    canvas.paste(small, (offset, offset), small)
    return canvas


def rounded_mask(size, radius_ratio=0.225):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1],
                                         radius=round(size * radius_ratio), fill=255)
    return m


def make_master():
    """Full-bleed gradient + glyph, rounded-square alpha baked in - the
    shared master for the desktop tile, the Expo unified icon, and favicon."""
    tile = gradient_tile(SIZE)
    tile.alpha_composite(flat_glyph(load_glyph_mask(), GLYPH_COLOR))
    tile.putalpha(rounded_mask(SIZE))
    return tile


def mac_master(master):
    """The same tile placed on Apple's macOS icon grid.

    Windows and Android hand the icon to a system that masks or frames it, so
    a full-bleed 1024 tile is right there. macOS does NOT: it draws the PNG as
    given, and every stock icon leaves a transparent margin with a soft contact
    shadow under the squircle. A full-bleed tile in a Dock of inset ones reads
    as oversized and unfinished - so the mac variant is the body at Apple's
    824/1024 grid size, centred, with that shadow.
    """
    BODY, PAD = 824, 100                       # Apple's macOS app-icon grid
    out = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    body = master.resize((BODY, BODY), Image.LANCZOS)
    sil = Image.new("RGBA", (BODY, BODY), (0, 0, 0, 0))
    sil.paste((0, 0, 0, 115), mask=body.split()[3])
    shadow = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    shadow.alpha_composite(sil, (PAD, PAD + 20))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    out.alpha_composite(shadow)
    out.alpha_composite(body, (PAD, PAD))
    return out


def save_png(img, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    print("wrote", path)


def main():
    mask = load_glyph_mask()

    master = make_master()                          # desktop tile + phone unified
    save_png(master, os.path.join(DESK, "icon-1024.png"))
    ico_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    os.makedirs(DESK, exist_ok=True)
    master.save(os.path.join(DESK, "icon.ico"), sizes=ico_sizes)
    print("wrote", os.path.join(DESK, "icon.ico"))

    save_png(mac_master(master), os.path.join(DESK, "icon-mac-1024.png"))

    # Expo unified icon + web favicon share the same rounded tile
    save_png(master, os.path.join(APPIMG, "icon.png"))
    master.resize((48, 48), Image.LANCZOS).save(os.path.join(APPIMG, "favicon.png"))
    print("wrote", os.path.join(APPIMG, "favicon.png"))

    # Android adaptive: full-bleed gradient background (no rounding/rim, the
    # OS masks the shape) + a foreground that is the H monogram alone, inset
    # into the adaptive safe zone.
    save_png(gradient_tile(), os.path.join(APPIMG, "android-icon-background.png"))

    fg = shrink_to_safezone(flat_glyph(mask, GLYPH_COLOR))
    save_png(fg, os.path.join(APPIMG, "android-icon-foreground.png"))

    mono = shrink_to_safezone(flat_glyph(mask, (255, 255, 255)))
    save_png(mono, os.path.join(APPIMG, "android-icon-monochrome.png"))

    # Native splash screen (expo-splash-screen plugin): tight-cropped glyph,
    # transparent, exported at 3x the configured 76pt display width.
    full_glyph = flat_glyph(mask, GLYPH_COLOR)
    bbox = full_glyph.getbbox()
    cropped = full_glyph.crop(bbox)
    target_w = 76 * 3
    scale = target_w / cropped.width
    splash = cropped.resize((target_w, round(cropped.height * scale)), Image.LANCZOS)
    save_png(splash, os.path.join(APPIMG, "splash-icon.png"))

    # iOS Liquid Glass icon bundle: a white silhouette PNG layer (grid.png in
    # the same bundle is already a raster layer, so this follows an existing
    # pattern, not a new one) + the fill color on icon.json.
    white_glyph = flat_glyph(mask, (255, 255, 255))
    save_png(white_glyph, os.path.join(EXPOICON, "Assets", "helmdeck-h.png"))
    icon_json_path = os.path.join(EXPOICON, "icon.json")
    with open(icon_json_path, encoding="utf-8") as f:
        icon_json = json.load(f)
    r, g, b = (c / 255 for c in GRADIENT_TOP_RIGHT)
    icon_json["fill"]["automatic-gradient"] = f"extended-srgb:{r:.5f},{g:.5f},{b:.5f},1.00000"
    with open(icon_json_path, "w", encoding="utf-8") as f:
        json.dump(icon_json, f, indent=2)
        f.write("\n")
    print("wrote", icon_json_path)


if __name__ == "__main__":
    main()
