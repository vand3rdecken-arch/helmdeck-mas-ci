# -*- coding: utf-8 -*-
"""Generate surfaces/app/src/theme/tokens.ts - THE canonical palette source.

The OKLCH primitives + semantic aliases below started as a copy of the web
design system (globals.css :root light block + [data-theme="dark"] overrides,
now retired to archive/web/app/globals.css). Since the Expo app in app/ became
the only frontend, THIS file is where the palette lives: edit the maps here,
re-run, and the flat hex / rgba() tokens React Native can use (it parses
neither OKLCH nor CSS var() chains) are regenerated. The OKLCH->sRGB math is
the same as ops/tools/make_icon.py. Re-run after touching the palette:
py -3.12 ops/tools/gen_tokens.py
"""
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
# ops/tools -> ops -> REPO ROOT. The second dirname is not cosmetic: this file
# used to resolve to `<repo>/ops/app/src/theme/tokens.ts`, a path that stopped
# existing when the owner's 2026-08-24 four-folder decree moved the frontend to
# `surfaces/app/`. Running the generator therefore CREATED a dead tree under
# ops/ and left the real palette untouched - the canonical source had been
# quietly disconnected from its own output (found 2026-08-29 while wiring the
# watch into it). Anything that "regenerates" the palette must land here.
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(REPO, "surfaces", "app", "src", "theme", "tokens.ts")
# SECOND consumer of the same palette (2026-08-29). The Wear OS module is
# Kotlin, so it can read neither tokens.ts nor OKLCH - but hand-copying hex into
# WearTheme.kt is exactly the drift this generator exists to prevent (owner:
# "Ist Farbe nicht zentralisiert?"). One source, two emitters: change the maps
# above, re-run, and phone and watch move together or not at all.
OUT_WEAR = os.path.join(REPO, "surfaces", "app", "plugins", "wear", "WearTokens.kt")


def _oklch_to_rgb(L, C, h):
    hr = math.radians(h)
    a = C * math.cos(hr); b = C * math.sin(hr)
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_**3, m_**3, s_**3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s

    def f(x):
        x = max(0.0, min(1.0, x))
        x = 1.055 * x ** (1 / 2.4) - 0.055 if x > 0.0031308 else 12.92 * x
        return int(round(max(0.0, min(1.0, x)) * 255))
    return f(r), f(g), f(bl)


def css(spec):
    """spec: hex string, or (L,C,h[,alpha]) OKLCH tuple. -> css color string."""
    if isinstance(spec, str):
        return spec
    L, C, h = spec[0], spec[1], spec[2]
    r, g, b = _oklch_to_rgb(L, C, h)
    if len(spec) == 4:
        return "rgba(%d,%d,%d,%s)" % (r, g, b, ("%.3f" % spec[3]).rstrip("0").rstrip("."))
    return "#%02X%02X%02X" % (r, g, b)


# --- primitives per theme (OKLCH triples / hex); originally copied from the
# --- archived globals.css, canonical HERE since the Expo cutover -------------
LIGHT_PRIM = {
    "neutral-white": (1, 0, 0), "neutral-100": (.9848, .0003, 230.66), "neutral-200": (.9696, .0007, 230.67),
    "neutral-300": (.9543, .001, 230.67), "neutral-400": (.9389, .0014, 230.68), "neutral-500": (.9235, .0017, 230.69),
    "neutral-600": (.8925, .0024, 230.7), "neutral-700": (.8612, .0032, 230.71), "neutral-800": (.6668, .0079, 230.82),
    "neutral-900": (.6161, .0092, 230.87), "neutral-1000": (.5288, .0083, 230.88), "neutral-1100": (.4377, .0066, 230.87),
    "neutral-1200": (.2378, .0029, 230.83), "neutral-black": (.1482, .0034, 196.79),
    "brand-default": (.508, .148, 250), "brand-700": (.6766, .1665, 250),
    "green-700": (.64, .15, 149), "amber-600": (.68, .12, 62), "red-700": (.57, .19, 27),
    # blue+violet analogous scheme: AI unified into the blue accent family; human
    # is violet (analogous, was clashing gold); one warm hue (amber) only.
    "accent-2": (.55, .19, 292), "ai": "#1C82B8", "human": "#6E5BC4",
    # final "liquid glass" pass from globals.css (:root override): white, more translucent
    "glass": (1, 0, 0, .52), "glass-border": (1, 0, 0, .55),
    "glow-1": (.62, .12, 238, .30), "glow-2": (.55, .19, 292, .24),
    "backdrop": (.1482, .0034, 196.79, .50), "transparent-hover": (.1482, .0034, 196.79, .10),
}
DARK_PRIM = dict(LIGHT_PRIM)
DARK_PRIM.update({
    "neutral-black": (.1689, .0021, 230.81), "neutral-100": (.1932, .002, 230.81), "neutral-200": (.2158, .0025, 230.82),
    "neutral-300": (.2378, .0029, 230.83), "neutral-400": (.2593, .0033, 230.84), "neutral-500": (.3011, .0041, 230.85),
    "neutral-600": (.3415, .0049, 230.86), "neutral-700": (.3999, .0059, 230.87), "neutral-800": (.5989, .0096, 230.88),
    "neutral-900": (.6835, .0074, 230.81), "neutral-1000": (.7655, .0054, 230.76), "neutral-1100": (.8455, .0035, 230.72),
    "neutral-1200": (.9235, .0017, 230.69), "neutral-white": (.9702, 0, 0),
    "brand-default": (.65, .152, 245), "brand-700": (.7408, .11, 245),
    "green-700": (.7, .13, 150), "amber-600": (.75, .13, 66), "red-700": (.68, .16, 24),
    "accent-2": (.66, .17, 292), "ai": "#3D9BD6", "human": "#9B87E8",
    # final "liquid glass" pass ([data-theme=dark] override): blue-grey plate, white edge.
    # (1,0,0)=white as an OKLCH triple; (1,1,1) was a bug -> C=1 clipped to magenta.
    "glass": (.23, .004, 230, .38), "glass-border": (1, 0, 0, .13),
    "glow-1": (.63, .15, 238, .34), "glow-2": (.66, .19, 292, .26),
    "backdrop": (0, 0, 0, .60), "transparent-hover": (1, 0, 0, .10),
})

# --- semantic aliases: (camelCaseKey -> primitive name), per theme where they differ
COMMON_ALIAS = {
    "layer1": "neutral-200", "layer1Hover": "neutral-300",
    "borderSubtle": "neutral-400", "borderStrong": "neutral-600",
    "txtPrimary": "neutral-1200", "txtSecondary": "neutral-1100",
    "txtTertiary": "neutral-1000", "txtPlaceholder": "neutral-900",
    "accent": "brand-default", "accentTxt": "brand-default", "brand700": "brand-700",
    "accent2": "accent-2", "ok": "green-700", "warn": "amber-600", "danger": "red-700",
    "ai": "ai", "human": "human", "glass": "glass", "glassBorder": "glass-border",
    "glow1": "glow-1", "glow2": "glow-2", "backdrop": "backdrop", "transparentHover": "transparent-hover",
    # raw ramp exposed for gradients / manual tints
    "neutral100": "neutral-100", "neutral200": "neutral-200", "neutral300": "neutral-300",
    "neutral400": "neutral-400", "neutral600": "neutral-600", "neutral900": "neutral-900",
    "neutral1100": "neutral-1100", "neutral1200": "neutral-1200",
}
LIGHT_ALIAS = dict(COMMON_ALIAS, canvas="neutral-300", surface1="neutral-white", surface2="neutral-100",
                   layer2="neutral-white", layer2Hover="neutral-100")
DARK_ALIAS = dict(COMMON_ALIAS, canvas="neutral-black", surface1="neutral-100", surface2="neutral-200",
                  layer2="neutral-300", layer2Hover="neutral-400")


def argb(spec):
    """spec -> Kotlin `0xAARRGGBB` literal for androidx.compose.ui.graphics.Color.

    Deliberately computed from the SAME primitive spec as css(), not parsed back
    out of the css string: a second parser would be a second place to be wrong,
    and the rgba() alpha would have to survive a float round-trip for nothing.
    """
    if isinstance(spec, str):
        return "0xFF" + spec.lstrip("#").upper()
    r, g, b = _oklch_to_rgb(spec[0], spec[1], spec[2])
    a = int(round(spec[3] * 255)) if len(spec) == 4 else 255
    return "0x%02X%02X%02X%02X" % (a, r, g, b)


# --- SEMANTIC maps: which TOKEN a domain value is painted with -----------------
# These used to be hardcoded twice - once in surfaces/app/src/theme/index.tsx
# (laneColor/statusColor) and, for anything the watch wanted, a third time in
# Kotlin. They are pure lookup tables, so they belong with the palette: one
# place decides that a `running` card is AI-blue and a `bounced` one is danger,
# and every surface inherits that. Values are TOKEN NAMES, never colours - the
# theme resolves them, which is what keeps a future light theme possible.
LANE_TOKEN = {"backlog": "txtTertiary", "working": "ai", "review": "human", "done": "ok"}
STATUS_TOKEN = {
    "queued": "txtTertiary", "running": "ai", "needs_you": "warn",
    # `gating` is a REAL status the lane machine publishes while the gate
    # subprocess runs (lanemachine.py:905) and the app already has a label for
    # it - but it had no colour, so it fell through to the grey of `queued`.
    # A card being actively checked looked exactly like a card nobody had
    # touched. accent2 is the gate's own colour on the pipeline map, so the
    # dot and the station now agree.
    "gating": "accent2",
    "submitted": "human", "accepted": "ok", "bounced": "danger",
    "done": "ok", "failed": "danger",
}
SEMANTIC_FALLBACK = "txtTertiary"

# --- Wear Material3 colour ROLES -> brand token --------------------------------
# The MAPPING is a design decision and lives here rather than in Kotlin, for the
# same reason the palette does: it was the last hand-written copy of "which
# HelmDeck colour is the primary action". Roles are Wear Material3's own names
# (androidx.wear.compose.material3.ColorScheme, read off the 1.6.2 artifact).
WEAR_ROLE = {
    "primary": "accent", "primaryDim": "ai", "onPrimary": "neutral100",
    "primaryContainer": "layer2", "onPrimaryContainer": "brand700",
    "secondary": "accent2", "secondaryDim": "human", "onSecondary": "neutral100",
    "secondaryContainer": "layer2", "onSecondaryContainer": "human",
    "tertiary": "ai", "tertiaryDim": "ai", "onTertiary": "neutral100",
    "tertiaryContainer": "layer2", "onTertiaryContainer": "ai",
    # chat-bubble spec, mirroring the phone transcript's surface1 + borderSubtle
    "surfaceContainerLow": "canvas", "surfaceContainer": "surface1",
    "surfaceContainerHigh": "surface2",
    "onSurface": "txtPrimary", "onSurfaceVariant": "txtSecondary",
    "outline": "borderStrong", "outlineVariant": "borderSubtle",
    "onBackground": "txtPrimary",
    "error": "danger", "errorDim": "danger", "onError": "neutral100",
}


def theme(prim, alias):
    return {k: css(prim[p]) for k, p in alias.items()}


def theme_argb(prim, alias):
    return {k: argb(prim[p]) for k, p in alias.items()}


def _kt_when(fn, table):
    """A `when` over the domain values, resolving to WearTokens - the Kotlin
    twin of index.tsx's laneColor/statusColor, from the same table."""
    arms = "".join('        "%s" -> WearTokens.%s\n' % (k, v) for k, v in table.items())
    return ("    fun %s(value: String?): Color = when (value) {\n%s"
            "        else -> WearTokens.%s\n    }\n" % (fn, arms, SEMANTIC_FALLBACK))


def emit_kotlin(dark):
    """The watch is always dark, so only that theme is emitted - a light Wear
    palette would be dead code carrying a promise nothing keeps."""
    lines = "".join("    val %s = Color(%sL)\n" % (k, v) for k, v in dark.items())
    roles = "".join("        %s = WearTokens.%s,\n" % (r, t) for r, t in WEAR_ROLE.items())
    extra = (
        "\n/** Domain value -> brand colour, generated from the SAME table the\n"
        " *  phone's laneColor()/statusColor() use. No surface re-decides this. */\n"
        "object WearSemantics {\n"
        + _kt_when("lane", LANE_TOKEN)
        + "\n"
        + _kt_when("status", STATUS_TOKEN)
        + "}\n\n"
        "/** The brand palette mapped onto Wear Material3's colour roles. The\n"
        " *  mapping itself is data in ops/tools/gen_tokens.py (WEAR_ROLE), so\n"
        " *  \"which HelmDeck colour is the primary action\" is decided in one\n"
        " *  place for every surface.\n"
        " *\n"
        " *  `background` is the one deliberate non-token: pure black, because a\n"
        " *  watch is OLED and an unlit pixel costs nothing. The brand's dark\n"
        " *  surfaces still carry the identity - they paint the cards. */\n"
        "val HelmDeckWearColors = ColorScheme(\n" + roles +
        "    background = Color(0xFF000000L),\n)\n"
    )
    return (
        "// AUTO-GENERATED by ops/tools/gen_tokens.py (the canonical palette). "
        "Do not edit by hand.\n"
        "// The Wear OS module is Kotlin and can read neither tokens.ts nor OKLCH, so the\n"
        "// SAME generator that writes tokens.ts for the phone writes these Color values\n"
        "// for the watch. Editing this file by hand re-creates the drift it exists to\n"
        "// prevent: change ops/tools/gen_tokens.py and re-run\n"
        "//   py -3.12 ops/tools/gen_tokens.py\n"
        "// Only the DARK theme is emitted - a watch has no light mode here.\n\n"
        "package app.helmdeck.wear\n\n"
        "import androidx.compose.ui.graphics.Color\n"
        "import androidx.wear.compose.material3.ColorScheme\n\n"
        "object WearTokens {\n" + lines + "}\n" + extra
    )


def emit(d):
    return "{\n" + "".join("    %s: '%s',\n" % (k, v) for k, v in d.items()) + "  }"


def emit_ts_map(d):
    """Quoted KEYS - unlike the token names above, these are domain values like
    `needs_you`, which is not a bare JS identifier."""
    return "{\n" + "".join("  '%s': '%s',\n" % (k, v) for k, v in d.items()) + "}"


def main():
    light = theme(LIGHT_PRIM, LIGHT_ALIAS)
    dark = theme(DARK_PRIM, DARK_ALIAS)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    ts = ("// AUTO-GENERATED by ops/tools/gen_tokens.py (the canonical palette). Do not edit by hand.\n"
          "// The palette is OKLCH primitives + semantic aliases in the generator; these are\n"
          "// the pre-resolved sRGB values React Native can use directly. Edit the generator\n"
          "// and re-run it to refresh. (Historical source: archive/web/app/globals.css.)\n\n"
          "export const tokens = {\n  light: %s,\n  dark: %s,\n} as const;\n\n"
          "export type ThemeName = keyof typeof tokens;\n"
          "export type ThemeTokens = Record<keyof typeof tokens.dark, string>;\n\n"
          "// Domain value -> TOKEN NAME (never a colour: the theme resolves it, which\n"
          "// is what keeps a light theme possible). theme/index.tsx's laneColor() and\n"
          "// statusColor() read these instead of carrying their own copy, and\n"
          "// WearSemantics in WearTokens.kt is generated from the SAME tables.\n"
          "export const laneTokens: Record<string, keyof ThemeTokens> = %s;\n"
          "export const statusTokens: Record<string, keyof ThemeTokens> = %s;\n"
          "export const semanticFallback: keyof ThemeTokens = '%s';\n"
          % (emit(light), emit(dark), emit_ts_map(LANE_TOKEN),
             emit_ts_map(STATUS_TOKEN), SEMANTIC_FALLBACK))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(ts)
    print("wrote", OUT, "(%d tokens/theme)" % len(dark))
    if os.path.isdir(os.path.dirname(OUT_WEAR)):
        with open(OUT_WEAR, "w", encoding="utf-8") as f:
            f.write(emit_kotlin(theme_argb(DARK_PRIM, DARK_ALIAS)))
        print("wrote", OUT_WEAR, "(%d dark tokens)" % len(dark))
    else:
        # The wear module is optional; say so rather than fail the phone palette.
        print("skipped", OUT_WEAR, "- wear plugin dir not present")


if __name__ == "__main__":
    main()
