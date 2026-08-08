# -*- coding: utf-8 -*-
"""Build the Play Store feature graphic (1024x500) - docs/store/LISTING.md.

Rendered, not AI-generated, for two reasons: the banner carries real German
copy (image models mangle text), and the colours must be the app's ACTUAL
tokens (app/src/theme/tokens.ts) rather than an approximation.

    py -3.12 tools/make_feature_graphic.py

Output: docs/store/feature-graphic.png
"""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "store", "feature-graphic.png")
ICON = os.path.join(ROOT, "app", "assets", "images", "icon.png")

W, H = 1024, 500
# app/src/theme/tokens.ts (dark)
CANVAS = (14, 15, 16)
SURFACE = (24, 26, 27)
ACCENT = (35, 150, 229)
TXT = (228, 230, 230)
TXT2 = (202, 205, 206)

# Play crops/overlays the outer edges on some surfaces - keep content inside.
SAFE = 56


def font(size, bold=False):
    for name in (("segoeuib.ttf", "seguisb.ttf") if bold else ("segoeui.ttf",)):
        p = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts", name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def main():
    img = Image.new("RGB", (W, H), CANVAS)

    # 1) diagonal gradient: near-black -> a cool blue-tinted dark
    grad = Image.new("RGB", (W, H))
    gd = ImageDraw.Draw(grad)
    for x in range(W):
        t = x / (W - 1)
        gd.line([(x, 0), (x, H)], fill=(
            int(CANVAS[0] + (20 - CANVAS[0]) * t),
            int(CANVAS[1] + (36 - CANVAS[1]) * t),
            int(CANVAS[2] + (58 - CANVAS[2]) * t)))
    img = Image.blend(img, grad, 0.95)

    # 2) the product itself, whispered: four lanes of frosted cards, blurred so
    #    it reads as texture rather than a screenshot. Lanes must END inside the
    #    safe area - a column bleeding off the right edge reads as a bug.
    board = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(board)
    lane_w, gap = 100, 24
    last = W - SAFE - lane_w
    lane_x = [last - (3 - i) * (lane_w + gap) for i in range(4)]
    heights = [[64, 44, 52], [70, 40], [56, 62, 38], [48, 56]]
    for i, x in enumerate(lane_x):
        y = 120
        for hgt in heights[i]:
            bd.rounded_rectangle([x, y, x + lane_w, y + hgt], radius=12,
                                 fill=(*SURFACE, 200), outline=(70, 78, 84, 140), width=1)
            y += hgt + 16
        bd.rounded_rectangle([x, 96, x + lane_w, 104], radius=4, fill=(*ACCENT, 90))
    board = board.filter(ImageFilter.GaussianBlur(2.2))
    # Fade the texture out towards the copy: a card sitting behind the claim
    # line is a collision, however subtle. Full strength only right of the text.
    ramp = Image.new("L", (W, H), 0)
    rd = ImageDraw.Draw(ramp)
    x0, x1 = 470, 660
    for x in range(W):
        v = 0 if x < x0 else (255 if x > x1 else int(255 * (x - x0) / (x1 - x0)))
        rd.line([(x, 0), (x, H)], fill=v)
    board.putalpha(Image.composite(board.getchannel("A"), Image.new("L", (W, H), 0), ramp))
    img = Image.alpha_composite(img.convert("RGBA"), board).convert("RGB")

    # 3) accent glow behind the mark
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([SAFE - 40, 150, SAFE + 300, 410], fill=(*ACCENT, 60))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    d = ImageDraw.Draw(img)

    # 4) the launcher icon, so store and phone show the same mark
    mark = 148
    if os.path.exists(ICON):
        ic = Image.open(ICON).convert("RGBA").resize((mark, mark), Image.LANCZOS)
        img.paste(ic, (SAFE, (H - mark) // 2), ic)

    # 5) wordmark + claim
    tx = SAFE + mark + 36
    f_title, f_tag = font(70, bold=True), font(25)
    title_y = H // 2 - 62
    d.text((tx, title_y), "HelmDeck", font=f_title, fill=TXT)
    d.text((tx, title_y + 88), "Das Board, auf dem Arbeit", font=f_tag, fill=TXT2)
    d.text((tx, title_y + 122), "sich selbst erledigt", font=f_tag, fill=TXT2)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print("wrote", OUT, img.size, f"{os.path.getsize(OUT)/1024:.0f} KB")


if __name__ == "__main__":
    main()
