import { Ionicons } from "@expo/vector-icons";
import { useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { STATIONS, mayEditBoard, useActiveBoard, useBoards } from "@/data/boards";
import { api } from "@/data/client";
import type { Board, BoardColumn } from "@/data/types";
import { useT } from "@/i18n";
import { laneColor, useTheme } from "@/theme";
// The SAME station-name resolver the board renders with (workspace
// policy.lane_labels, then the translated default), so the placeholder in a
// column's label field is literally what leaving it empty will draw.
import { useLaneLabels } from "@/ui/board";
import { useResponsive } from "@/ui/responsive";

/**
 * BOARD EDITOR (accounts-boards-prd phase 2).
 *
 * Jira's split, made touchable: the workflow is the harness's and is not on
 * this screen at all - you cannot add a station, reorder the pipeline or skip
 * the gate here. What you CAN do is decide which of those stations your board
 * draws, in what order, under what name. That is the entire vocabulary.
 *
 * Two things this screen deliberately does NOT do:
 *  - it does not offer a station picker that could produce a station the
 *    daemon would reject. The choices are the stations themselves, so an
 *    invalid board is unreachable rather than merely refused.
 *  - it does not auto-add the stations you left out. Leaving `review` off your
 *    board is a legitimate view; the BOARD screen handles the consequence by
 *    deriving an overflow column when such a station actually holds cards
 *    (data/boards.ts renderColumns), so nothing is hidden and nothing is
 *    silently added behind your back.
 *
 * The default board is visible to everyone and editable by the owner role
 * only - the daemon enforces that (spine/storage/boards.may_edit); this screen
 * just does not show the controls, because a button that always errors is
 * worse than no button.
 */

const emptyColumn = (station: string): BoardColumn =>
  ({ id: "", label: "", station });

export default function BoardsScreen() {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { wide } = useResponsive();
  const qc = useQueryClient();
  const params = useLocalSearchParams<{ board?: string }>();
  const stationName = useLaneLabels();
  const { boards, active, role } = useBoards();
  const setBoardId = useActiveBoard((s) => s.setBoardId);

  const [editing, setEditing] = useState<string>(active.id);
  const [name, setName] = useState("");
  const [columns, setColumns] = useState<BoardColumn[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const current: Board | undefined = boards.find((b) => b.id === editing);
  const editable = mayEditBoard(current, role);

  // ?board=<id> opens straight onto that board - the settings hub's "Boards"
  // door links each row here. Applied ONCE, and only after /me has actually
  // delivered a board with that id: on a cold load this screen renders before
  // the board list exists, so seeding the initial state from the param would
  // silently select an id that is not there yet and land on "pick a board".
  // The one-shot flag is a ref, not state, so tapping a different board in
  // the picker is never dragged back by a re-render.
  const applied = useRef(false);
  useEffect(() => {
    const wanted = Array.isArray(params.board) ? params.board[0] : params.board;
    if (applied.current || !wanted || !boards.some((b) => b.id === wanted)) return;
    applied.current = true;
    setEditing(wanted);
  }, [params.board, boards]);

  // The draft is seeded from the server's board and re-seeded whenever the
  // SELECTED board changes - not on every /me tick. Re-seeding on every tick
  // would wipe what you were typing the moment another device wrote anything
  // at all, which the global stream makes a routine event.
  useEffect(() => {
    const b = boards.find((x) => x.id === editing);
    setName(b?.name ?? "");
    setColumns((b?.columns ?? []).map((c) => ({ ...c })));
    setErr(null);
  }, [editing]);   // eslint-disable-line react-hooks/exhaustive-deps

  async function save() {
    if (!current) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.saveBoard({ id: current.id, name, columns });
      // Land on what you just edited: creating a board and then not being on
      // it is the kind of small lie that makes people press save twice.
      setBoardId(r.board.id);
      await qc.invalidateQueries({ queryKey: ["me"] });
    } catch (e) { setErr(String((e as Error).message)); }
    finally { setBusy(false); }
  }

  async function create() {
    setBusy(true); setErr(null);
    try {
      const r = await api.saveBoard({
        name: tr("boards.newName"),
        // A new board starts as a COPY of the four stations rather than empty:
        // an empty board is one the daemon refuses, and a first-time user
        // should be renaming something, not assembling one from nothing.
        columns: STATIONS.map((s) => emptyColumn(s)),
      });
      await qc.invalidateQueries({ queryKey: ["me"] });
      setEditing(r.board.id);
      setBoardId(r.board.id);
    } catch (e) { setErr(String((e as Error).message)); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!current?.id) return;
    setBusy(true); setErr(null);
    try {
      await api.deleteBoard(current.id);
      await qc.invalidateQueries({ queryKey: ["me"] });
      setBoardId("");
      setEditing("");
    } catch (e) { setErr(String((e as Error).message)); }
    finally { setBusy(false); }
  }

  const field = {
    backgroundColor: t.surface2, borderWidth: 1, borderColor: t.borderSubtle,
    borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8,
    color: t.txtPrimary, fontSize: 14,
  } as const;

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 8, gap: 8 }}>
        <Pressable onPress={() => router.back()} hitSlop={10}>
          <Ionicons name="chevron-back" size={24} color={t.txtSecondary} />
        </Pressable>
        <Text style={{ color: t.txtPrimary, fontSize: 17, fontWeight: "700", flex: 1 }}>
          {tr("boards.title")}
        </Text>
        {busy ? <ActivityIndicator color={t.accent} /> : null}
      </View>

      <ScrollView contentContainerStyle={{ padding: wide ? 20 : 14, gap: 14,
        paddingBottom: 60 + insets.bottom, width: "100%", maxWidth: 760, alignSelf: "center" }}>
        <Text style={{ color: t.txtTertiary, fontSize: 12.5, lineHeight: 18 }}>{tr("boards.intro")}</Text>

        {/* ---- which board ---- */}
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
          {boards.map((b) => {
            const on = b.id === editing;
            return (
              <Pressable key={b.id} onPress={() => setEditing(b.id)}
                style={{ flexDirection: "row", alignItems: "center", gap: 6,
                  borderWidth: 1, borderColor: on ? t.accent : t.borderSubtle,
                  backgroundColor: on ? t.accent + "18" : t.surface1,
                  borderRadius: 10, paddingHorizontal: 11, paddingVertical: 7 }}>
                <Text style={{ color: on ? t.txtPrimary : t.txtSecondary, fontSize: 13, fontWeight: "600" }}>
                  {b.name}
                </Text>
                {/* The shared board is badged, so "why can't I edit this one"
                    is answered before it is asked. */}
                {b.owner === "" ? (
                  <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("boards.shared")}</Text>
                ) : null}
              </Pressable>
            );
          })}
          <Pressable onPress={create} disabled={busy}
            style={{ flexDirection: "row", alignItems: "center", gap: 5,
              borderWidth: 1, borderColor: t.borderSubtle, borderStyle: "dashed",
              borderRadius: 10, paddingHorizontal: 11, paddingVertical: 7, opacity: busy ? 0.5 : 1 }}>
            <Ionicons name="add" size={15} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 13, fontWeight: "600" }}>{tr("boards.new")}</Text>
          </Pressable>
        </View>

        {err ? <Text style={{ color: t.danger, fontSize: 12.5 }}>{err}</Text> : null}

        {!current ? (
          <Text style={{ color: t.txtTertiary, fontSize: 13 }}>{tr("boards.pick")}</Text>
        ) : (
          <>
            {!editable ? (
              <View style={{ flexDirection: "row", gap: 8, alignItems: "center",
                backgroundColor: t.layer1, borderRadius: 10, padding: 10 }}>
                <Ionicons name="lock-closed-outline" size={14} color={t.txtTertiary} />
                <Text style={{ color: t.txtTertiary, fontSize: 12.5, flex: 1 }}>{tr("boards.readonly")}</Text>
              </View>
            ) : null}

            <View style={{ gap: 6 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("boards.name")}</Text>
              <TextInput value={name} onChangeText={setName} editable={editable}
                style={[field, !editable && { opacity: 0.6 }]} />
            </View>

            <Text style={{ color: t.txtTertiary, fontSize: 11.5 }}>{tr("boards.columns")}</Text>
            {columns.map((c, i) => (
              <View key={c.id || "new-" + i}
                style={{ gap: 8, backgroundColor: t.surface1, borderWidth: 1,
                  borderColor: t.borderSubtle, borderRadius: 12, padding: 10 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                  <TextInput
                    value={c.label}
                    // The placeholder is the STATION's own name, because that is
                    // literally what an empty label renders as - so the field
                    // shows the truth instead of the word "optional".
                    placeholder={stationName(c.station)}
                    placeholderTextColor={t.txtPlaceholder}
                    editable={editable}
                    onChangeText={(v) => setColumns((cs) =>
                      cs.map((x, j) => (j === i ? { ...x, label: v } : x)))}
                    style={[field, { flex: 1 }, !editable && { opacity: 0.6 }]} />
                  {editable ? (
                    <Pressable hitSlop={8} onPress={() => setColumns((cs) => cs.filter((_, j) => j !== i))}>
                      <Ionicons name="trash-outline" size={17} color={t.txtTertiary} />
                    </Pressable>
                  ) : null}
                </View>
                {/* WHICH STATION this column shows. Not free text: these are the
                    lanes the machine has, so an unmovable column is impossible
                    to build rather than merely rejected on save. */}
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                  {STATIONS.map((st) => {
                    const on = c.station === st;
                    return (
                      <Pressable key={st} disabled={!editable}
                        onPress={() => setColumns((cs) =>
                          cs.map((x, j) => (j === i ? { ...x, station: st } : x)))}
                        style={{ flexDirection: "row", alignItems: "center", gap: 5,
                          borderWidth: 1, borderColor: on ? laneColor(t, st) : t.borderSubtle,
                          backgroundColor: on ? laneColor(t, st) + "22" : "transparent",
                          borderRadius: 8, paddingHorizontal: 9, paddingVertical: 5,
                          opacity: editable ? 1 : 0.6 }}>
                        <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: laneColor(t, st) }} />
                        <Text style={{ color: on ? t.txtPrimary : t.txtTertiary, fontSize: 12 }}>
                          {stationName(st)}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            ))}

            {editable ? (
              <Pressable onPress={() => setColumns((cs) => [...cs, emptyColumn("backlog")])}
                style={{ flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
                  borderWidth: 1, borderColor: t.borderSubtle, borderStyle: "dashed",
                  borderRadius: 10, paddingHorizontal: 11, paddingVertical: 8 }}>
                <Ionicons name="add" size={15} color={t.accent} />
                <Text style={{ color: t.accent, fontSize: 13, fontWeight: "600" }}>{tr("boards.addColumn")}</Text>
              </Pressable>
            ) : null}

            {editable ? (
              <View style={{ flexDirection: "row", gap: 10, marginTop: 4 }}>
                <Pressable onPress={save} disabled={busy}
                  style={{ backgroundColor: t.accent, borderRadius: 11, paddingHorizontal: 18,
                    paddingVertical: 11, opacity: busy ? 0.5 : 1 }}>
                  <Text style={{ color: "#fff", fontSize: 13.5, fontWeight: "700" }}>{tr("boards.save")}</Text>
                </Pressable>
                {/* The shared board has no delete, at any role - it is where a
                    fresh login lands, so removing it would end setup on an
                    empty screen. The daemon refuses it too. */}
                {current.owner !== "" ? (
                  <Pressable onPress={remove} disabled={busy}
                    style={{ borderWidth: 1, borderColor: t.danger + "77", borderRadius: 11,
                      paddingHorizontal: 18, paddingVertical: 11, opacity: busy ? 0.5 : 1 }}>
                    <Text style={{ color: t.danger, fontSize: 13.5, fontWeight: "600" }}>{tr("boards.delete")}</Text>
                  </Pressable>
                ) : null}
              </View>
            ) : null}
          </>
        )}
      </ScrollView>
    </View>
  );
}
