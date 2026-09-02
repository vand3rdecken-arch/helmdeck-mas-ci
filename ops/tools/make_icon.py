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
    ops/deploy/waitlist/src/logo.js                                  (helmdeck.de brand mark)

The website is the one surface that cannot consume a PNG from this repo - it is a
single-file Cloudflare Worker with no static asset binding, so it carried its own
hand-written copy of the mark. That copy silently went stale through the
2026-08-26 redesign and helmdeck.de served the superseded "glass H" for a week.
So the site's mark is now GENERATED here too: the same mask is traced to an SVG
path (see trace_mask_loops) and written as src/logo.js. Same source, one command,
no second place to forget.
"""
import json
import os
import math
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DESK = os.path.join(ROOT, "surfaces", "desktop", "assets")
APPIMG = os.path.join(ROOT, "surfaces", "app", "assets", "images")
EXPOICON = os.path.join(ROOT, "surfaces", "app", "assets", "expo.icon")
SITE_LOGO = os.path.join(ROOT, "ops", "deploy", "waitlist", "src", "logo.js")
MASK_PATH = os.path.join(HERE, "assets", "logo_h_mask.png")

SIZE = 1024
CORNER_RATIO = 0.225   # rounded-square radius, shared by the tile and the site SVG

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
    mask = Image.open(MASK_PATH).convert("L")
    if mask.size != (SIZE, SIZE):
        # PIL's alpha_composite does NOT error on a mismatched size - it
        # silently composites into the top-left corner only, producing a
        # tiny misplaced glyph on every output with no warning (measured
        # 2026-08-26: feeding a 512x512 mask through this script exited 0
        # and wrote 8 broken files before the mismatch was caught by eye).
        raise ValueError(
            f"logo_h_mask.png is {mask.size}, expected ({SIZE}, {SIZE}) - "
            "resize it before regenerating icons, or every output below "
            "will silently be wrong.")
    return mask


def binary_rows(mask):
    """The 'L' mask as rows of bools, thresholded the same way alpha
    compositing reads it: >127 is glyph."""
    w, h = mask.size
    data = mask.tobytes()
    return [[data[y * w + x] > 127 for x in range(w)] for y in range(h)]


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


def rounded_mask(size, radius_ratio=CORNER_RATIO):
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


# --- mask -> SVG path (for the website, which cannot ship a PNG) -----------
#
# Deliberately written against nothing but PIL + stdlib. An OpenCV/potrace
# dependency here would mean "regenerate the icons" fails on a machine that
# happens not to have it, halfway through writing eight files - and the whole
# point of this script is that one command always leaves every surface in sync.
# Verified against cv2.findContours during development: identical loop count,
# and both rasterise back to the source mask within 0.2% of its area.


def trace_mask_loops(mask):
    """Trace the exact pixel boundary of a binary mask.

    `mask` is a 2-D sequence of truthy/falsy values (numpy bool array or list
    of lists). Returns a list of closed loops of integer lattice points, each
    wound clockwise in SVG screen coordinates (y down) around filled area.

    Method: every filled pixel contributes a unit edge for each of its four
    sides whose neighbour is empty, oriented so the interior stays on the same
    hand. Those edges then stitch head-to-tail into closed loops. This is
    exact - no thresholded curve fitting, no ambiguity about what the shape is
    - and the smoothing happens afterwards in simplify_loop, where it can be
    measured.
    """
    h = len(mask)
    w = len(mask[0])

    def filled(x, y):
        return 0 <= x < w and 0 <= y < h and bool(mask[y][x])

    succ = {}
    for y in range(h):
        row = mask[y]
        for x in range(w):
            if not row[x]:
                continue
            if not filled(x, y - 1):
                succ.setdefault((x, y), []).append((x + 1, y))
            if not filled(x + 1, y):
                succ.setdefault((x + 1, y), []).append((x + 1, y + 1))
            if not filled(x, y + 1):
                succ.setdefault((x + 1, y + 1), []).append((x, y + 1))
            if not filled(x - 1, y):
                succ.setdefault((x, y + 1), []).append((x, y))

    def step(cur, outs, heading):
        # At a vertex where two regions touch corner-to-corner there are two
        # ways out. Prefer the tightest (clockwise) turn, which keeps the loop
        # hugging the region it is already tracing instead of jumping across
        # the diagonal. Order: right, straight, left, back.
        if heading is None or len(outs) == 1:
            return outs[0]
        dx, dy = heading
        for ddx, ddy in ((-dy, dx), (dx, dy), (dy, -dx), (-dx, -dy)):
            cand = (cur[0] + ddx, cur[1] + ddy)
            if cand in outs:
                return cand
        return outs[0]

    loops = []
    while succ:
        start = next(iter(succ))
        loop, cur, heading = [], start, None
        while True:
            outs = succ.get(cur)
            if not outs:
                break
            nxt = step(cur, outs, heading)
            outs.remove(nxt)
            if not outs:
                del succ[cur]
            loop.append(cur)
            heading = (nxt[0] - cur[0], nxt[1] - cur[1])
            cur = nxt
            if cur == start:
                break
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def _dp_keep(pts, eps):
    """Douglas-Peucker over an open chain; returns the indices to keep.

    Iterative on purpose: the raw chains here run to thousands of points and
    the textbook recursive form blows Python's stack on the worst case.
    """
    n = len(pts)
    if n < 3:
        return list(range(n))
    keep = [False] * n
    keep[0] = keep[n - 1] = True
    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        ax, ay = pts[i0]
        bx, by = pts[i1]
        dx, dy = bx - ax, by - ay
        norm = dx * dx + dy * dy
        imax, dmax = i0, -1.0
        for i in range(i0 + 1, i1):
            px, py = pts[i]
            if norm == 0:
                dist = math.hypot(px - ax, py - ay)
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / norm
                t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
                dist = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if dist > dmax:
                imax, dmax = i, dist
        if dmax > eps:
            keep[imax] = True
            stack.append((i0, imax))
            stack.append((imax, i1))
    return [i for i in range(n) if keep[i]]


def simplify_loop(loop, eps):
    """Douglas-Peucker for a CLOSED loop.

    A closed ring has no natural endpoints, so anchor it on two points that
    are certainly corners of the outline - the first point and the point
    farthest from it - and simplify the two arcs between them independently.
    """
    n = len(loop)
    if n < 4:
        return list(loop)
    x0, y0 = loop[0]
    far = max(range(n), key=lambda i: (loop[i][0] - x0) ** 2 + (loop[i][1] - y0) ** 2)
    arc_a = loop[:far + 1]
    arc_b = loop[far:] + [loop[0]]
    kept_a = [arc_a[i] for i in _dp_keep(arc_a, eps)]
    kept_b = [arc_b[i] for i in _dp_keep(arc_b, eps)]
    return kept_a[:-1] + kept_b[:-1]


def glyph_path_d(mask, eps=0.8):
    """The mask as one SVG path `d`.

    eps is in mask pixels (the glyph is drawn on a 1024 grid). 0.8 was chosen
    by rendering the traced mark against the shipped master PNG at 32/48/96/
    180/320px and looking: 0.8 is indistinguishable from the master at every
    one of them (IoU 0.9988) while cutting the raw pixel staircase from 5190
    points to ~690. At 2.0 the inner curve of the sweep visibly flattens where
    it meets the right stem, so the cheap end of the range is not free.
    """
    parts = []
    for loop in trace_mask_loops(mask):
        pts = simplify_loop(loop, eps)
        if len(pts) < 3:
            continue
        head = f"M{pts[0][0]} {pts[0][1]}"
        rest = "".join(f"L{x} {y}" for x, y in pts[1:])
        parts.append(head + rest + "Z")
    return "".join(parts)


def site_logo_svg(mask):
    """The website's brand mark: the same gradient tile and the same glyph as
    every other surface, as scalable SVG."""
    tr = "#%02X%02X%02X" % GRADIENT_TOP_RIGHT
    bl = "#%02X%02X%02X" % GRADIENT_BOTTOM_LEFT
    ink = "#%02X%02X%02X" % GLYPH_COLOR
    radius = round(SIZE * CORNER_RATIO)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" '
        f'role="img" aria-label="HelmDeck">'
        f'<defs><linearGradient id="hd-tile" x1="{SIZE}" y1="0" x2="0" y2="{SIZE}" '
        f'gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{tr}"/><stop offset="1" stop-color="{bl}"/>'
        f'</linearGradient></defs>'
        f'<rect width="{SIZE}" height="{SIZE}" rx="{radius}" fill="url(#hd-tile)"/>'
        f'<path fill="{ink}" d="{glyph_path_d(mask)}"/>'
        f'</svg>'
    )


def write_site_logo(mask):
    svg = site_logo_svg(mask)
    # The worker embeds this in a JS template literal.
    escaped = svg.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    body = (
        "// GENERATED FILE - do not edit by hand.\n"
        "// Source of truth: ops/tools/assets/logo_h_mask.png\n"
        "// Regenerate:      py -3.12 ops/tools/make_icon.py\n"
        "//\n"
        "// The site used to keep its own hand-drawn copy of the brand mark, which\n"
        "// went stale the moment the logo was redesigned. It is derived now.\n"
        "\n"
        f"export const ICON_SVG = `{escaped}`;\n"
    )
    os.makedirs(os.path.dirname(SITE_LOGO), exist_ok=True)
    with open(SITE_LOGO, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    print("wrote", SITE_LOGO)


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

    # helmdeck.de: the mark as SVG, traced from this same mask.
    write_site_logo(binary_rows(mask))


if __name__ == "__main__":
    main()
