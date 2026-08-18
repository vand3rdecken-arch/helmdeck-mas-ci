// Cell architecture diagram: Cell -> {Logic, Storage, Harness, API-Routes,
// UI-Surface} -> real files/routes, tap any leaf to read its real source.
// Visual language borrows from github.com/cathrynlavery/diagram-design (owner
// reference, 2026-08-18): hairline 1px strokes, no shadows, ONE accent color,
// grid-aligned coordinates (all divisible by 4), generous whitespace, a
// title/sublabel type-scale split - a style to emulate, not a vendored
// dependency (see daemon/cells.py's engineer Cell.tools for the reference).
//
// Layout is computed here in plain JS (no layout library needed at this
// scale): one Cell box, an edge down to N category boxes in a row, an edge
// from each category down to its own leaf boxes, wrapped into rows. A
// category with nothing to show renders ONE muted leaf with the cell's
// `role` text instead of an empty box.
import { useMemo, useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import Svg, { G, Line, Rect, Text as SvgText } from "react-native-svg";

import { api, type CellInfo } from "@/data/client";
import { useTheme } from "@/theme";

const GRID = 4;
const g = (n: number) => Math.round(n / GRID) * GRID;

type Category = { label: string; leaves: { text: string; file?: string }[] };

function categoriesFor(c: CellInfo): Category[] {
  const mk = (label: string, items: string[], fallback: string): Category => ({
    label,
    leaves: items.length ? items.map((text) => ({ text, file: text })) : [{ text: fallback }],
  });
  return [
    mk("Logic", c.logicFiles, "—"),
    { label: "Storage", leaves: [{ text: c.storage || "—" }] },
    mk("Harness", c.harnessFile ? [c.harnessFile] : [], c.role || "—"),
    mk("API-Routes", c.routes, "keine Routen"),
    mk("UI-Surface", c.uiFiles, "—"),
  ];
}

const LEAF_W = 168, LEAF_H = 28, LEAF_GAP = 8, CAT_GAP = 24, CAT_PAD = 10;
const CELL_W = 140, CELL_H = 36;

export function CellDiagram({ cell }: { cell: CellInfo }) {
  const t = useTheme();
  const [openFile, setOpenFile] = useState<string | null>(null);

  const cats = useMemo(() => categoriesFor(cell), [cell]);

  // Each category: leaves wrap at 2 per row (keeps boxes readable at phone
  // width; desktop just gets more whitespace, not smaller text - matches the
  // reference's "editorial, not dense" target).
  const catBlocks = cats.map((cat) => {
    const rows = Math.ceil(cat.leaves.length / 2);
    return { ...cat, w: LEAF_W * 2 + LEAF_GAP, h: rows * (LEAF_H + LEAF_GAP) - LEAF_GAP, rows };
  });

  const totalW = g(Math.max(CELL_W, catBlocks.reduce((s, b) => s + b.w + CAT_GAP, -CAT_GAP)));
  const catsY = 64;
  const labelH = 20;
  const maxCatH = Math.max(...catBlocks.map((b) => b.h), 0);
  const totalH = g(catsY + CAT_PAD + labelH + maxCatH + CAT_PAD + 12);

  let x = (totalW - catBlocks.reduce((s, b) => s + b.w + CAT_GAP, -CAT_GAP)) / 2;
  const positioned = catBlocks.map((b) => {
    const bx = x;
    x += b.w + CAT_GAP;
    return { ...b, x: g(bx) };
  });

  return (
    <View>
      <ScrollView horizontal showsHorizontalScrollIndicator={totalW > 600} contentContainerStyle={{ paddingVertical: 8 }}>
        {/* Svg + the tap-target overlay share this fixed-size wrapper, so both
            scroll together - an overlay outside the ScrollView would drift
            out of alignment with the diagram as soon as it's wide enough to
            scroll (every cell with more than a couple files hits this). */}
        <View style={{ width: totalW, height: totalH }}>
        <Svg width={totalW} height={totalH}>
          {/* the Cell box, top-center */}
          <Rect x={g((totalW - CELL_W) / 2)} y={4} width={CELL_W} height={CELL_H} rx={8}
            stroke={t.accent} strokeWidth={1.5} fill="transparent" />
          <SvgText x={totalW / 2} y={4 + CELL_H / 2 + 5} fontSize={14} fontWeight="700"
            fill={t.txtPrimary} textAnchor="middle">{cell.id}</SvgText>

          {positioned.map((b, i) => (
            <Line key={"e" + i} x1={totalW / 2} y1={4 + CELL_H} x2={b.x + b.w / 2} y2={catsY}
              stroke={t.glassBorder} strokeWidth={1} />
          ))}

          {positioned.map((b, i) => (
            <G key={b.label}>
              <SvgText x={b.x} y={catsY + labelH - 6} fontSize={10.5} fontWeight="700"
                fill={t.txtTertiary} letterSpacing={0.6}>{b.label.toUpperCase()}</SvgText>
              {b.leaves.map((leaf, li) => {
                const col = li % 2, row = Math.floor(li / 2);
                const lx = b.x + col * (LEAF_W + LEAF_GAP);
                const ly = catsY + labelH + row * (LEAF_H + LEAF_GAP);
                return (
                  <Rect key={li} x={lx} y={ly} width={LEAF_W} height={LEAF_H} rx={6}
                    stroke={t.glassBorder} strokeWidth={1}
                    fill={leaf.file ? "transparent" : t.canvas} />
                );
              })}
              {b.leaves.map((leaf, li) => {
                const col = li % 2, row = Math.floor(li / 2);
                const lx = b.x + col * (LEAF_W + LEAF_GAP);
                const ly = catsY + labelH + row * (LEAF_H + LEAF_GAP);
                return (
                  <SvgText key={"t" + li} x={lx + 8} y={ly + LEAF_H / 2 + 4} fontSize={11}
                    fill={leaf.file ? t.txtPrimary : t.txtTertiary}>
                    {leaf.text.length > 22 ? "…" + leaf.text.slice(-21) : leaf.text}
                  </SvgText>
                );
              })}
            </G>
          ))}
        </Svg>

        {/* SvgText's onPress works on native but is unreliable on web RN-SVG -
            a transparent RN Pressable overlay grid gives every platform a
            real tap target. Lives INSIDE the same fixed-size wrapper as the
            Svg (not a sibling of the ScrollView) so it scrolls together with
            the diagram instead of drifting out of alignment once the
            diagram is wide enough to need horizontal scrolling. */}
        <View style={{ position: "absolute", top: 0, left: 0, width: totalW, height: totalH }} pointerEvents="box-none">
          {positioned.map((b) =>
            b.leaves.map((leaf, li) => {
              if (!leaf.file) return null;
              const col = li % 2, row = Math.floor(li / 2);
              const lx = b.x + col * (LEAF_W + LEAF_GAP);
              const ly = catsY + labelH + row * (LEAF_H + LEAF_GAP);
              return (
                <Pressable key={b.label + li} onPress={() => setOpenFile(leaf.file!)}
                  style={{ position: "absolute", left: lx, top: ly, width: LEAF_W, height: LEAF_H }} />
              );
            })
          )}
        </View>
        </View>
      </ScrollView>

      {openFile ? <SourceModal cellId={cell.id} file={openFile} onClose={() => setOpenFile(null)} /> : null}
    </View>
  );
}

function SourceModal({ cellId, file, onClose }: { cellId: string; file: string; onClose: () => void }) {
  const t = useTheme();
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useMemo(() => {
    api.cellSource(cellId, file)
      .then((r) => setText(r.text))
      .catch((e) => setErr(String((e as Error)?.message ?? e)));
  }, [cellId, file]);

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "center", padding: 20 }} onPress={onClose}>
        <Pressable onPress={(e) => e.stopPropagation()}
          style={{ backgroundColor: t.surface1, borderRadius: 12, maxHeight: "80%", borderWidth: 1, borderColor: t.glassBorder }}>
          <View style={{ flexDirection: "row", alignItems: "center", padding: 14, borderBottomWidth: 1, borderBottomColor: t.glassBorder }}>
            <Text style={{ color: t.txtPrimary, fontSize: 13, fontWeight: "600", flex: 1 }}>{file}</Text>
            <Pressable onPress={onClose}><Text style={{ color: t.txtTertiary, fontSize: 18 }}>×</Text></Pressable>
          </View>
          <ScrollView style={{ padding: 14 }}>
            {err ? <Text style={{ color: t.danger, fontSize: 12 }}>{err}</Text> : null}
            {text === null && !err ? <Text style={{ color: t.txtTertiary, fontSize: 12 }}>Lädt…</Text> : null}
            {text !== null ? (
              <Text style={{ color: t.txtSecondary, fontSize: 11.5, fontFamily: "monospace", lineHeight: 16 }}>{text}</Text>
            ) : null}
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
