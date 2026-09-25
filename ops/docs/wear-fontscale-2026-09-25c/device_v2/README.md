# device_v2: real Xiaomi Watch 5 after the text-vs-button rebuild (2026-09-25)

Real watch only (480 px, no emulator). fs1.0/ and fs2.0/ hold, per screen, the top frame
(`*_00_top.png`), the end frame (`*_99_end.png`), every scroll step and a `sheet_*.png`.
Screens: `2henry`, `2b_henry_msg_detail` (text detail), `3board`, `4card`, `4b/4c/4d_*_detail`
(text detail of task, answer, question). `1pairing` shows Henry: the watch is already paired,
so the pairing screen cannot be reached on it (fs1.0 only; not re-shot at 2.0).
The fixture APK (fake chat/board data) was used; the release AAB contains none of it.

Cause of the old look: in Wear M3 Card, Button, FilledTonalButton share one shape; only colour and
slots tell them apart. surfaceContainer (#141515) and primaryContainer (grey) vanished on black.
Now surfaceContainer = #222425 (Neutral20-like), primaryContainer = blue-tinted dark #05304E.

Hierarchy: messages/tasks/questions/board entries = TitleCard; "Sprechen" = EdgeButton (mic only);
"Stimme" = SwitchButton; answers = Button under ListHeader "Antworten"; "Board"/"Henry" =
FilledTonalButton with icon; "Zurück"/"Neu laden"/"Adresse" = ChildButton.
Own messages: dark blue (primaryContainer), one switch point: `ownMessageColor()` in HenryScreen.kt.

Judged: at rest no text is clipped at 1.0 or 2.0; clipped edges only appear mid-scroll (list
transformation). Long text ends in an ellipsis, full text on the detail screen. Cards and buttons
are clearly distinct. Known: "Wartet …" state of Sprechen is gone (icon-only edge button).
