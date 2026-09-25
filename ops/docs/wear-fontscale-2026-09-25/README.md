# Wear OS font-scale evidence, 2026-09-25 (versionCode 1000009)

Play rejected vc1000008 (Wear OS font-size quality guideline). Fix commit `32b5e7f2`.

## How this was tested

- Emulators `Wear_OS_Small_Round_API_30_w` (384 px = 192 dp) and `Wear_OS_Large_Round_API_30`
  (454 px), `settings put system font_scale 2.0`.
- **before** = HEAD `25b11e3e` (vc1000008), **after** = `32b5e7f2` (vc1000009). Both are *fixture
  builds*: the generated `android/wear` copy (never `plugins/wear`) is patched so Board, Card and
  Henry render canned daemon data offline (`DeviceStore.load` / `RelayClient.authedCall`). The
  release AAB is built from the clean commit and contains no fixture code (checked: no
  `hd_fixture` string in its dex).
- Every screen is swept from the very top, scrolled in steps to the very bottom, screenshots
  masked to the visible circle. `sheet_<device>_<before|after>_<screen>.png` shows 8 evenly
  spaced frames (first = top, last = bottom); the folders hold every frame.
- Screens: 1pairing, 2henry, 3board, 4card. Not tested: the Owner watch (Xiaomi Watch 5).

## Cause

The two earlier fixes only looked at the vertical middle of the screen. A round watch is a short
chord at top and bottom, so a full-width button is wider than the circle there; at fontScale 2.0
the rows are tall enough that this happens on every screen.

## What changed

- Every list row goes through one `rememberTransformationSpec()` (`transformedHeight` +
  `SurfaceTransformation`, `ListHeader` for titles) so rows narrow and shrink toward the edge.
- All text is `FullText` (WearTheme.kt): Wear M3 Button/Card install a `LocalTextConfiguration`
  with maxLines and ellipsis around their content; explicit `maxLines`/`overflow` overrides it.
- Pairing: each field is one Button (label "Code diktieren", value as secondary label);
  "Koppeln" is a list Button directly under the code. EdgeButton was tried first and wraps to
  "Kopp / eln" with the second line cut at 2.0, so it was dropped.
- Library actually resolved: `compose-material3` and `compose-foundation` **1.6.2** (build.gradle
  declares 1.5.0 for material3, Gradle resolves 1.6.2); APIs were checked against that AAR.

## Before / after

- **Pairing**: before, the "Diktieren" and "Koppeln" pills sit on the round edge in the top and
  bottom bands and are cut; after, every row is full-width-transformed, wraps completely (address
  and code fully readable), nothing is cut at rest at top, middle or bottom.
- **Henry / Board / Card**: before, bubbles and buttons at the edges are sliced by the bezel
  ("Aktualisie / ren", "Board" cut at the bottom, titles broken mid-word to a sliver); after, rows
  shrink towards the edge and their text is inside the circle at rest.
- Remaining cosmetics (not clipping): long words still break mid-word at 2.0 ("Henr / y" in a
  chat title with time, "Schriftgro / esse" in a card title), and partially scrolled rows at the
  top and bottom edge are cut while moving, as on any scrolling watch list.
