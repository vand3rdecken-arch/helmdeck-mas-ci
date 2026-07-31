# -*- coding: utf-8 -*-
"""Generate app/src/theme/tokens.ts from the web design system.

React Native cannot parse OKLCH or resolve CSS var() chains, so we pre-resolve
the token graph in web/app/globals.css (the :root light block + the
[data-theme="dark"] overrides) into flat hex / rgba() maps, one per theme. The
OKLCH->sRGB math is the same as tools/make_icon.py. Re-run after touching the
palette:  py -3.12 tools/gen_tokens.py
"""
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "app", "src", "theme", "tokens.ts")


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


# --- primitives per theme (OKLCH triples / hex), copied from globals.css -------
LIGHT_PRIM = {
    "neutral-white": (1, 0, 0), "neutral-100": (.9848, .0003, 230.66), "neutral-200": (.9696, .0007, 230.67),
    "neutral-300": (.9543, .001, 230.67), "neutral-400": (.9389, .0014, 230.68), "neutral-500": (.9235, .0017, 230.69),
    "neutral-600": (.8925, .0024, 230.7), "neutral-700": (.8612, .0032, 230.71), "neutral-800": (.6668, .0079, 230.82),
    "neutral-900": (.6161, .0092, 230.87), "neutral-1000": (.5288, .0083, 230.88), "neutral-1100": (.4377, .0066, 230.87),
    "neutral-1200": (.2378, .0029, 230.83), "neutral-black": (.1482, .0034, 196.79),
    "brand-default": (.4799, .1158, 242.91), "brand-700": (.6766, .1665, 243.91),
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
    "brand-default": (.6311, .1263, 238.01), "brand-700": (.7408, .1003, 233.89),
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


def theme(prim, alias):
    return {k: css(prim[p]) for k, p in alias.items()}


def emit(d):
    return "{\n" + "".join("    %s: '%s',\n" % (k, v) for k, v in d.items()) + "  }"


def main():
    light = theme(LIGHT_PRIM, LIGHT_ALIAS)
    dark = theme(DARK_PRIM, DARK_ALIAS)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    ts = ("// AUTO-GENERATED by tools/gen_tokens.py from web/app/globals.css. Do not edit by hand.\n"
          "// The web design system is OKLCH + CSS var() chains; these are the pre-resolved\n"
          "// sRGB values React Native can use directly. Re-run the generator to refresh.\n\n"
          "export const tokens = {\n  light: %s,\n  dark: %s,\n} as const;\n\n"
          "export type ThemeName = keyof typeof tokens;\n"
          "export type ThemeTokens = Record<keyof typeof tokens.dark, string>;\n" % (emit(light), emit(dark)))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(ts)
    print("wrote", OUT, "(%d tokens/theme)" % len(dark))


if __name__ == "__main__":
    main()
