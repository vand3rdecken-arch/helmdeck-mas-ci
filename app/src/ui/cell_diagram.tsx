// Cell architecture diagram: Cell -> {Logic, Storage, Harness, API-Routes,
// UI-Surface} -> real files/routes, tap any leaf to read its real source.
// Visual language borrows from github.com/cathrynlavery/diagram-design (owner
// reference, 2026-08-18): hairline 1px strokes, no shadows, ONE accent color,
// grid-aligned coordinates (all divisible by 4), generous whitespace, a
// title/sublabel type-scale split - a style to emulate, not a vendored
// dependency (see daemon/cells.py's engineer Cell.tools for the reference).
//
// v2 layout (owner feedback: v1 "looks ugly" - diagnosed and fixed): each
// category is now a single narrow COLUMN (leaves stacked vertically inside a
// grouped, softly-filled container) instead of a wide 2-per-row grid. That
// keeps the whole diagram close to viewport width instead of sprawling past
// 1800px, which was the real bug behind the ugliness - the Cell box, centered
// over the FULL width, ended up floating alone near the right edge while only
// the leftmost categories were visible without scrolling. Elbow (right-angle)
// connectors replace the raw diagonals, matching the reference's clean
// architecture-diagram convention.
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

const LEAF_W = 152, LEAF_H = 26, LEAF_GAP = 6;
const COL_PAD = 12, COL_GAP = 22;
const COL_W = LEAF_W + COL_PAD * 2;
const LABEL_H = 22;
const CELL_W = 132, CELL_H = 34;
const TOP_PAD = 12, GROUPS_Y_GAP = 28;

function truncate(text: string, max = 24) {
  return text.length > max ? "…" + text.slice(-(max - 1)) : text;
}

export function CellDiagram({ cell }: { cell: CellInfo }) {
  const t = useTheme();
  const [openFile, setOpenFile] = useState<string | null>(null);

  const cats = useMemo(() => categoriesFor(cell), [cell]);

  const cols = cats.map((cat) => ({
    ...cat,
    h: LABEL_H + cat.leaves.length * (LEAF_H + LEAF_GAP) - LEAF_GAP + COL_PAD * 2,
  }));

  const totalW = g(Math.max(CELL_W + 40, cols.length * COL_W + (cols.length - 1) * COL_GAP));
  const groupsY = TOP_PAD + CELL_H + GROUPS_Y_GAP;
  const maxColH = Math.max(...cols.map((c) => c.h), 0);
  const totalH = g(groupsY + maxColH + TOP_PAD);

  const rowW = cols.length * COL_W + (cols.length - 1) * COL_GAP;
  let x = (totalW - rowW) / 2;
  const positioned = cols.map((c) => {
    const bx = g(x);
    x += COL_W + COL_GAP;
    return { ...c, x: bx };
  });

  const cellX = g((totalW - CELL_W) / 2);
  const cellMidX = cellX + CELL_W / 2;
  const cellBottomY = TOP_PAD + CELL_H;
  const elbowY = g(cellBottomY + GROUPS_Y_GAP / 2);

  return (
    <View>
      <ScrollView horizontal showsHorizontalScrollIndicator={totalW > 700} contentContainerStyle={{ paddingVertical: 8 }}>
        {/* Svg + the tap-target overlay share this fixed-size wrapper, so both
            scroll together - an overlay outside the ScrollView would drift
            out of alignment with the diagram as soon as it's wide enough to
            scroll. */}
        <View style={{ width: totalW, height: totalH }}>
        <Svg width={totalW} height={totalH}>
          {/* elbow connectors: cell -> midline -> each column's top-center */}
          {positioned.map((c, i) => {
            const colMidX = c.x + COL_W / 2;
            return (
              <G key={"e" + i}>
                <Line x1={cellMidX} y1={cellBottomY} x2={cellMidX} y2={elbowY} stroke={t.glassBorder} strokeWidth={1} />
                <Line x1={cellMidX} y1={elbowY} x2={colMidX} y2={elbowY} stroke={t.glassBorder} strokeWidth={1} />
                <Line x1={colMidX} y1={elbowY} x2={colMidX} y2={groupsY} stroke={t.glassBorder} strokeWidth={1} />
              </G>
            );
          })}

          {/* the Cell box - the one focal element, accent-filled per the
              reference's "1-2 focal elements, one accent color" rule */}
          <Rect x={cellX} y={TOP_PAD} width={CELL_W} height={CELL_H} rx={8}
            stroke={t.accent} strokeWidth={1.5} fill={t.accent} fillOpacity={0.12} />
          <SvgText x={cellMidX} y={TOP_PAD + CELL_H / 2 + 5} fontSize={14} fontWeight="700"
            fill={t.txtPrimary} textAnchor="middle">{cell.id}</SvgText>

          {positioned.map((c) => (
            <G key={c.label}>
              {/* grouped container: a soft-filled rounded rect behind the
                  label + all its leaves, so each category reads as ONE
                  visual unit instead of loose scattered boxes */}
              <Rect x={c.x} y={groupsY} width={COL_W} height={c.h} rx={10}
                stroke={t.glassBorder} strokeWidth={1} fill={t.surface1} fillOpacity={0.5} />
              <SvgText x={c.x + COL_PAD} y={groupsY + LABEL_H - 7} fontSize={10} fontWeight="700"
                fill={t.accent} letterSpacing={0.8}>{c.label.toUpperCase()}</SvgText>
              {c.leaves.map((leaf, li) => {
                const ly = groupsY + LABEL_H + li * (LEAF_H + LEAF_GAP);
                return (
                  <Rect key={li} x={c.x + COL_PAD} y={ly} width={LEAF_W} height={LEAF_H} rx={6}
                    stroke={t.glassBorder} strokeWidth={1}
                    fill={leaf.file ? t.canvas : "transparent"} />
                );
              })}
              {c.leaves.map((leaf, li) => {
                const ly = groupsY + LABEL_H + li * (LEAF_H + LEAF_GAP);
                return (
                  <SvgText key={"t" + li} x={c.x + COL_PAD + 8} y={ly + LEAF_H / 2 + 4} fontSize={11}
                    fill={leaf.file ? t.txtPrimary : t.txtTertiary}>
                    {truncate(leaf.text)}
                  </SvgText>
                );
              })}
            </G>
          ))}
        </Svg>

        {/* SvgText's onPress works on native but is unreliable on web RN-SVG -
            transparent RN Pressables give every platform a real tap target.
            Rendered as DIRECT siblings of Svg (not wrapped in an
            intermediate pointerEvents="box-none" container - that combo is
            unreliable on react-native-web, confirmed by hand). Each is
            individually absolutely positioned against the same fixed-size
            parent View (RN Views default to position:"relative"). */}
        {positioned.map((c) =>
          c.leaves.map((leaf, li) => {
            if (!leaf.file) return null;
            const ly = groupsY + LABEL_H + li * (LEAF_H + LEAF_GAP);
            return (
              <Pressable key={c.label + li} onPress={() => setOpenFile(leaf.file!)}
                style={{ position: "absolute", left: c.x + COL_PAD, top: ly, width: LEAF_W, height: LEAF_H }} />
              );
            })
          )}
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
