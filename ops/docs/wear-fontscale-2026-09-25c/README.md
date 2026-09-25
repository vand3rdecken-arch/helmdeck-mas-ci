# Wear OS font-scale evidence, part 3 (versionCode 1000011)

Play rejected vc1000008: text and controls must not be cut by the screen edge at a larger
font. vc1000010 fixed it with hand-made workarounds (chunked rows, `endInset`, `FullText`
clip). vc1000011 replaces them with Google's Wear Compose Material 3 standard.

## What changed (commit 65b8cbf3 + this commit's version bump)

- No more `rememberChunkChars` / `chunkText` / `chunkedRows` / `textRows`. Lists show only short
  entries: `Text(maxLines, overflow = Ellipsis)`. Long text (card title/body/options, a Henry
  answer, a chat message, the pairing address) opens on `TextDetailScreen`:
  `ScreenScaffold` + `TransformingLazyColumn`, the text as ONE `Text` item, a list `Button`
  "Zurueck" as the last item.
- No more `endInset()`: the scaffold's `contentPadding` plus `minimumVerticalContentPadding`
  (`ButtonDefaults` / `CardDefaults.minimumVerticalListContentPadding`) do the spacing.
- No more `FullText`/Clip: the standard M3 ellipsis.
- Buttons use short labels (Code, Koppeln, Adresse, Sprechen, Board, Henry, Neu laden), not a
  smaller font.
- Tried and rejected: `EdgeButton` in the scaffold slot. It wrapped "Zurueck" mid-word at
  font scale 2.0 on Small Round.

## Evidence

- `small_fs2.0/`, `small_fs1.0/`: Wear OS Small Round emulator (384 px), font_scale 2.0 and 1.0.
  Screens: Pairing, Adresse, Henry, Henry message detail, Board, Card, card task / body /
  question detail. `sheet_*.png` = up to 8 frames sampled top to end, `*_00_top` and `*_99_end`
  = the rest position and end position.
- `device_fs2.0/`, `device_fs1.0/`: the owner's real Xiaomi Watch 5 (480 px round), same
  sweep. Its watch was already paired, so the Pairing screen does not appear there (the
  emulator covers Pairing and Adresse).
- Not delivered: Large Round emulator. Two emulators plus the build box hit 100 % CPU and
  0.5 GB free RAM and the run broke off; the owner stopped further emulator runs. The Large
  Round shape is only covered by the 480 px real watch.

## Judgement (honest)

- At rest nothing touches the circle on any screen, at 2.0 and at 1.0; every screen's end
  position shows its last item fully (Board: Neu laden, Card: Sprechen, detail: Zurueck).
- No mid-word break in any button label. Long compound words inside card TITLES that come from
  data ("Schriftgroessen-Uebersicht", "Aktualisierung") still wrap inside the word at 2.0 on
  the narrow Small Round, then end in an ellipsis. That is Compose's default line breaking
  (no hyphenation) on user data, not a label; left as is.
- On Small Round at 2.0 the chat sender in a Henry/Frage row truncates ("Hen...", "Fra...")
  because time and title share one line.

## Sources

- developer.android.com/training/wearables/compose/lists: ScreenScaffold +
  TransformingLazyColumn, `contentPadding`, `minimumVerticalContentPadding`, maxLines/Ellipsis.
- developer.android.com/training/wearables/compose/screen-size and
  .../training/wearables/accessibility (font scale).
- androidx wear compose-material3 samples: `TransformingLazyColumnSample.kt`
  (`TransformingLazyColumnButtonsSample`, `...MinimumVerticalContentPaddingSample`),
  `ScrollIndicatorSample.kt`, `SwitchButtonSample.kt` (maxLines = 3 + Ellipsis).
- androidx version unchanged (build.gradle material3 1.5.0, resolved 1.6.2); all used APIs
  present in the resolved artifacts.
