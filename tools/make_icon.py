# -*- coding: utf-8 -*-
"""Render SwarmDeck's app icon - the SAME glyph on desktop and mobile.

The mark is "the board as a glyph": a fanned stack of three cards - a dark
back card, the accent-blue main card carrying three text lines, and a small
green 'done' card on top - on the app's near-black canvas. The mobile adaptive
icon already draws this in vector; this script bakes the identical concept into
the raster assets the Windows/Electron build needs (a rounded dark tile + a
multi-size .ico), so both surfaces share one identity.

Deterministic (Pillow only, 4x supersampled). Re-run after tweaking geometry:
    py -3.12 tools/make_icon.py
Outputs: desktop/assets/icon-1024.png, desktop/assets/icon.ico
"""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "desktop", "assets")

SS = 4                      # supersample factor -> smooth edges
S = 1024 * SS              # working canvas

# brand palette (matches ui/Theme.kt + colors.xml)
CANVAS_TOP = (20, 24, 28)          # subtle top of the tile gradient
CANVAS_BOT = (14, 15, 16)          # #0E0F10 near-black
BACK_CARD = (46, 78, 102)          # lifted from #1E3A4F so the stack reads as TWO cards
MAIN_CARD = (40, 147, 204)         # #2893CC accent
MAIN_GLOW = (102, 182, 225)        # #66B6E1 accentSoft (top edge sheen)
LINES = (14, 15, 16)               # text lines punched out of the main card
GREEN = (76, 184, 106)            # #4CB86A ok


def rounded(size_wh, radius, fill):
    w, h = size_wh
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=fill)
    return img


def with_shadow(card, blur=18 * SS, alpha=150, dy=10 * SS):
    """Soft drop shadow so the fanned cards read as stacked, not flat."""
    from PIL import ImageFilter
    pad = blur * 3
    lay = Image.new("RGBA", (card.width + pad * 2, card.height + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", lay.size, (0, 0, 0, 0))
    a = card.split()[3].point(lambda v: alpha if v > 0 else 0)
    black = Image.new("RGBA", card.size, (0, 0, 0, 255))
    black.putalpha(a)
    sh.alpha_composite(black, (pad, pad + dy))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    sh.alpha_composite(card, (pad, pad))
    return sh


def place(base, card, angle, cx, cy):
    r = card.rotate(angle, resample=Image.BICUBIC, expand=True)
    base.alpha_composite(r, (int(cx - r.width / 2), int(cy - r.height / 2)))


def make_master():
    # --- dark tile with a vertical gradient + a soft accent glow behind cards
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 255))
    px = tile.load()
    for y in range(S):
        t = y / (S - 1)
        r = int(CANVAS_TOP[0] + (CANVAS_BOT[0] - CANVAS_TOP[0]) * t)
        g = int(CANVAS_TOP[1] + (CANVAS_BOT[1] - CANVAS_TOP[1]) * t)
        b = int(CANVAS_TOP[2] + (CANVAS_BOT[2] - CANVAS_TOP[2]) * t)
        for x in range(S):
            px[x, y] = (r, g, b, 255)
    # accent glow
    from PIL import ImageFilter
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([S * 0.28, S * 0.30, S * 0.78, S * 0.80], fill=(40, 147, 204, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(90 * SS))
    tile.alpha_composite(glow)

    # round the tile corners (desktop tile; the phone masks its own shape)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
    tile.putalpha(mask)

    cx, cy = S // 2, int(S * 0.51)
    cw, ch = int(S * 0.45), int(S * 0.58)
    rad = int(S * 0.05)

    # back card - pushed up-left and rotated more so the fan is unmistakable
    place(tile, with_shadow(rounded((cw, ch), rad, BACK_CARD)), 13, cx - int(S*0.055), cy - int(S*0.03))

    # main accent card + top sheen + three text lines
    main = rounded((cw, ch), rad, MAIN_CARD)
    md = ImageDraw.Draw(main)
    md.rounded_rectangle([0, 0, cw - 1, int(ch * 0.16)], radius=rad, fill=MAIN_GLOW)
    md.rectangle([0, int(ch * 0.10), cw - 1, int(ch * 0.16)], fill=MAIN_CARD)
    lx = int(cw * 0.16)
    lh = int(ch * 0.052)
    for i, frac in enumerate((0.66, 0.82, 0.44)):
        ly = int(ch * (0.34 + i * 0.16))
        md.rounded_rectangle([lx, ly, lx + int(cw * frac), ly + lh], radius=lh // 2, fill=LINES)
    place(tile, with_shadow(main), -5, cx + int(S*0.025), cy + int(S*0.01))

    # small green 'done' card, fanned top-right
    gw, gh = int(S * 0.185), int(S * 0.15)
    place(tile, with_shadow(rounded((gw, gh), int(S*0.032), GREEN), blur=12*SS, alpha=120),
          -17, cx + int(S * 0.225), cy - int(S * 0.205))

    return tile.resize((1024, 1024), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    master = make_master()
    master.save(os.path.join(OUT, "icon-1024.png"))
    # multi-resolution .ico for Windows (taskbar/installer/exe)
    ico_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    master.save(os.path.join(OUT, "icon.ico"), sizes=ico_sizes)
    print("wrote", os.path.join(OUT, "icon-1024.png"))
    print("wrote", os.path.join(OUT, "icon.ico"))
    # the web UI shares the same mark in its browser tab
    fav = os.path.join(os.path.dirname(HERE), "web", "app", "favicon.ico")
    master.save(fav, sizes=ico_sizes)
    print("wrote", fav)


if __name__ == "__main__":
    main()
