# Wear OS font-scale evidence, part 2 (versionCode 1000010)

Play's second rejection wording: text and controls must not be cut by the screen edge at a
larger system font. My first evidence (`../wear-fontscale-2026-09-25/`, vc1000009) still showed
it: the pairing address button held the full URL and was TALLER than the viewport at font scale
2.0, so the transformation could not shrink it and the bezel cut it.

## Fix (commit 2f3ccb82)

- Pairing shows one short button "Adresse / Standard". The value sits on its own screen
  (`AddressEditor`) as wrapping text rows plus Diktieren / Standard / Fertig; never in a Button.
- `chunkText` / `chunkedRows` / `textRows`: long user text (card titles, bodies, options, chat
  messages, status, hints) becomes several rows of about three lines (48 chars at scale 1.0,
  24 at 2.0), so no list item is taller than the viewport. Applied to Pairing, Board, Card, Henry.
- `endInset()`: space after the last row. Before it, the last button of every screen rested with
  its lower edge cropped flat (visible in the first run of this folder, replaced by this run).
- Henry: the floating "Neueste" pill moved 20dp up, off the short bottom chord.

## Method

Small Round (384 px) and Large Round (454 px) emulators, `font_scale 2.0`, fixture build with
deliberately long data (a card title with a URL, a chat message with a URL, a long card name,
a long option label). Every screen swept from the top in swipe steps to the end; masked to the
circle. `<dev>_after/` holds every frame; `sheet_*` are 8-frame overviews per screen;
`ends_<dev>_top/bottom.png` are the resting positions (top and end) of all five screens
(pairing, address editor, Henry, board, card).

## Judgement

- End positions (all screens, both devices): last button complete and round, clear margin to the
  circle. Top positions: titles and first rows inside the circle, wrapping fully.
- Long URL: readable on the address screen as separate rows, none cut.
- Not perfect, honestly: while a list is at rest the NEXT row is partly visible at the fold
  (normal for a scrolling list, it is fully visible once scrolled); very long words still break
  mid-word at 2.0 ("Aktualisier / en", "Schriftgro / esse"); "Neueste" overlaps the row behind it.
- Not tested: the Owner watch (Xiaomi Watch 5).
