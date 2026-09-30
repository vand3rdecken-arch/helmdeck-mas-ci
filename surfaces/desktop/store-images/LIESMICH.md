# Store-Bilder für das Partner Center

Erzeugt aus `assets/icon-1024.png` durch `py -3.12 ops/tools/make_icon.py`
(nicht von Hand ändern, sonst wird es beim nächsten Lauf überschrieben).

| Datei | Größe | Feld im Partner Center |
|---|---|---|
| `store-300x300.png` | 300x300 | 300x300 |
| `store-150x150.png` | 150x150 | 150x150 |
| `store-71x71.png`   | 71x71   | 71x71 |

## Hochladen

1. Partner Center > Apps und Spiele > HelmDeck > die laufende Einreichung öffnen
   (oder "Update" für eine neue).
2. **Store listings** > **German (Germany)** (und ggf. English) > **Store display images**.
3. Die drei Dateien in die passenden Felder ziehen (300x300, 150x150, 71x71).
4. Für jede weitere Store-Sprache wiederholen.

Hinweis: Diese Felder sind optional. Ohne Upload nimmt der Store die Logos aus dem
Paket (`build/appx/`). Das neue Paket enthält jetzt das H, das Hochladen der
Bilder macht das Ergebnis unabhängig vom Paket-Update.
