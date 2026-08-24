# -*- coding: utf-8 -*-
"""Render HelmDeck's app icon - one glass 'H' monogram across every surface.

The mark is an abstract 'H' monogram rendered as Apple "Liquid Glass": a
frosted rounded-square tile with an aurora glow (teal top-left -> violet
top-right) blooming through, a crisp specular rim-light on the top edge, and a
soft depth shadow. Centred is a bold minimal 'H' - two posts and a raised
crossbar - cut from a brighter vibrant-white glass so it reads as the same
material lifted toward the light; the crossbar sits slightly high to hint at a
deck/board shelf.

Deterministic (Pillow only, 4x supersampled). Re-run after tweaking geometry:
    py -3.12 ops/tools/make_icon.py
Outputs:
    surfaces/desktop/assets/icon-1024.png, surfaces/desktop/assets/icon.ico   (Windows/Electron)
    surfaces/desktop/assets/icon-mac-1024.png                        (macOS icon grid)
    surfaces/app/assets/images/icon.png                              (Expo unified)
    surfaces/app/assets/images/favicon.png                           (web tab)
    surfaces/app/assets/images/android-icon-background.png           (adaptive bg)
    surfaces/app/assets/images/android-icon-foreground.png           (adaptive fg, H only)
    surfaces/app/assets/images/android-icon-monochrome.png           (themed-icon H)
"""
import os
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DESK = os.path.join(ROOT, "desktop", "assets")
APPIMG = os.path.join(ROOT, "app", "assets", "images")

SS = 4                       # supersample factor -> smooth edges
S = 1024 * SS                # working canvas

# --- brand palette (matches surfaces/app/src/theme/tokens.ts dark theme) -------------
CANVAS_TOP = (18, 22, 26)            # subtle top of the tile gradient
CANVAS_BOT = (12, 13, 14)            # ~#0E0F10 near-black
GLOW_TEAL = (40, 147, 204)           # #2893CC accent  (top-left aurora)
GLOW_VIOLET = (150, 122, 240)        # #967AF0 accent2 (top-right aurora)
GLASS_FILL = (150, 180, 205)         # cool glass body the H is cut from
GLASS_HI = (232, 244, 252)           # vibrant near-white top sheen of the H
RIM = (255, 255, 255)                # specular rim-light on the tile edge


def radial(size, cx, cy, rad, color, a0):
    """A soft radial glow blob centred at (cx,cy) in px, faded to 0 at rad."""
    g = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(g)
    gd.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=color + (a0,))
    return g.filter(ImageFilter.GaussianBlur(rad * 0.55))


def make_tile():
    """The aurora glass tile (no monogram yet)."""
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 255))
    px = tile.load()
    for y in range(S):                       # vertical base gradient
        t = y / (S - 1)
        r = int(CANVAS_TOP[0] + (CANVAS_BOT[0] - CANVAS_TOP[0]) * t)
        g = int(CANVAS_TOP[1] + (CANVAS_BOT[1] - CANVAS_TOP[1]) * t)
        b = int(CANVAS_TOP[2] + (CANVAS_BOT[2] - CANVAS_TOP[2]) * t)
        for x in range(S):
            px[x, y] = (r, g, b, 255)
    # aurora: teal bloom top-left, violet bloom top-right (the app backdrop)
    tile.alpha_composite(radial(S, int(S * 0.20), int(S * 0.14), int(S * 0.55), GLOW_TEAL, 150))
    tile.alpha_composite(radial(S, int(S * 0.86), int(S * 0.12), int(S * 0.50), GLOW_VIOLET, 135))
    tile.alpha_composite(radial(S, int(S * 0.55), int(S * 1.02), int(S * 0.55), GLOW_TEAL, 90))
    return tile


def h_mask():
    """A crisp alpha mask of the 'H' monogram (posts + raised crossbar)."""
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)
    post_w = int(S * 0.135)
    left = int(S * 0.315)
    right = int(S * 0.685) - post_w
    top = int(S * 0.285)
    bot = int(S * 0.715)
    rad = int(post_w * 0.42)
    d.rounded_rectangle([left, top, left + post_w, bot], radius=rad, fill=255)
    d.rounded_rectangle([right, top, right + post_w, bot], radius=rad, fill=255)
    # crossbar sits slightly high (deck/board shelf); rounded caps
    bar_h = int(S * 0.120)
    bar_y = int(S * 0.430)
    d.rounded_rectangle([left, bar_y, right + post_w, bar_y + bar_h],
                        radius=int(bar_h * 0.32), fill=255)
    return m


def glass_H(mask):
    """Fill the H mask with cool glass + a bright top-edge sheen + inner glow."""
    h = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    px = h.load()
    for y in range(S):                        # vertical sheen: bright top -> body
        t = min(1.0, max(0.0, (y / S - 0.26) / 0.48))
        r = int(GLASS_HI[0] + (GLASS_FILL[0] - GLASS_HI[0]) * t)
        g = int(GLASS_HI[1] + (GLASS_FILL[1] - GLASS_HI[1]) * t)
        b = int(GLASS_HI[2] + (GLASS_FILL[2] - GLASS_HI[2]) * t)
        for x in range(S):
            px[x, y] = (r, g, b, 255)
    h.putalpha(mask)
    # drop shadow so the H floats above the glass tile
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    black = Image.new("RGBA", (S, S), (0, 0, 0, 255)); black.putalpha(mask)
    sh.alpha_composite(black, (0, int(S * 0.012)))
    sh = sh.filter(ImageFilter.GaussianBlur(int(S * 0.02)))
    sh.putalpha(sh.split()[3].point(lambda v: int(v * 0.5)))
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.alpha_composite(sh)
    out.alpha_composite(h)
    return out


def rim_light(mask_radius):
    """A thin specular highlight along the top edge of the rounded tile."""
    rim = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rim)
    rd.rounded_rectangle([int(S * 0.06), int(S * 0.05), S - int(S * 0.06), S - int(S * 0.05)],
                         radius=mask_radius, outline=RIM + (150,), width=int(S * 0.006))
    rim = rim.filter(ImageFilter.GaussianBlur(int(S * 0.004)))
    # keep mostly the top arc: fade the lower half out
    fade = Image.new("L", (S, S), 0)
    fd = ImageDraw.Draw(fade)
    for y in range(S):
        fd.line([(0, y), (S, y)], fill=max(0, int(255 * (1 - y / (S * 0.6)))))
    rim.putalpha(Image.composite(rim.split()[3], Image.new("L", (S, S), 0), fade))
    return rim


def make_master(rounded_tile=True):
    tile = make_tile()
    rad = int(S * 0.225)
    if rounded_tile:
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=rad, fill=255)
        tile.putalpha(mask)
        tile.alpha_composite(rim_light(rad))
    tile.alpha_composite(glass_H(h_mask()))
    return tile.resize((1024, 1024), Image.LANCZOS)


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
    # contact shadow: the body's own silhouette, black, nudged down and blurred
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
    master = make_master(rounded_tile=True)        # desktop tile + phone unified
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

    # Android adaptive: full-bleed aurora background (no rounding/rim, the OS
    # masks the shape) + a foreground that is the H monogram alone, inset into
    # the adaptive safe zone.
    bg = make_tile().resize((1024, 1024), Image.LANCZOS)
    save_png(bg, os.path.join(APPIMG, "android-icon-background.png"))

    fg_full = glass_H(h_mask()).resize((1024, 1024), Image.LANCZOS)
    fg = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    inner = fg_full.resize((round(1024 * 0.66), round(1024 * 0.66)), Image.LANCZOS)
    fg.alpha_composite(inner, ((1024 - inner.width) // 2, (1024 - inner.height) // 2))
    save_png(fg, os.path.join(APPIMG, "android-icon-foreground.png"))

    # Monochrome (themed icons): flat white H on transparent, same inset.
    mono_full = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    white = Image.new("RGBA", (S, S), (255, 255, 255, 255)); white.putalpha(h_mask())
    mono_full.alpha_composite(white)
    mono_full = mono_full.resize((round(1024 * 0.66), round(1024 * 0.66)), Image.LANCZOS)
    mono = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    mono.alpha_composite(mono_full, ((1024 - mono_full.width) // 2, (1024 - mono_full.height) // 2))
    save_png(mono, os.path.join(APPIMG, "android-icon-monochrome.png"))


if __name__ == "__main__":
    main()
