import { useQuery } from "@tanstack/react-query";
import { ActivityIndicator, Platform, Pressable, Text, View } from "react-native";

import { api, type HarnessBrief } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

/**
 * "BRIEF ANSEHEN" (harness-config-ui design doc section 4.3).
 *
 * The rules as a form are one half of making Henry visible. The other half is
 * that the owner can read the WHOLE brief, exactly as Henry receives it -
 * otherwise the mistrust simply moves ("what else is in there that I cannot
 * see?"). So this renders the file in full, including the do/don't examples and
 * the decree derivations, and hides nothing.
 *
 * THE BORROWED PATTERN (section 7.0 - nothing is invented): prose with the
 * adjustable parts highlighted is the merge-tag editor every Mailchimp/HubSpot
 * user has already learned - `*|FIRSTNAME|*` in a paragraph. Highlighted means
 * "this is the part you set"; everything dimmed is fixed. And form <-> prose is
 * a TOGGLE on one state, not a second place to edit - the same relationship VS
 * Code has between its settings UI and settings.json, and GitHub Actions
 * between the pipeline view and "View workflow file". Editing happens in the
 * form; this view is read-only on purpose.
 *
 * The segments come from the daemon, which builds them from the SAME parts
 * brief() uses. ops/tests/test_project_config.py holds the join to brief()
 * byte for byte on every surface - without that, this screen could quietly
 * become a picture of a brief nobody is actually started with.
 */

const MONO = Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }) as string;

export function BriefView({ surface, repo, onOpenRule }: {
  surface: string;
  repo: string;
  /** Tapping a value opens the row that sets it. That is the whole reason the
   *  daemon tags each value with its rule - the alternative is the owner
   *  reading a number in a paragraph and hunting for the switch. */
  onOpenRule: (ruleKey: string) => void;
}) {
  const t = useTheme();
  const tr = useT();
  const { data, isLoading, error } = useQuery<HarnessBrief>({
    queryKey: ["harnessBrief", surface, repo],
    queryFn: () => api.harnessBrief(surface, repo),
    staleTime: 15000, retry: false,
  });

  if (isLoading) return <ActivityIndicator color={t.accent} style={{ marginTop: 20 }} />;
  if (error || !data) {
    return <Text style={{ color: t.danger, fontSize: 12 }}>{tr("health.unreachable")}</Text>;
  }
  return (
    <View testID={"brief-" + surface} style={{ backgroundColor: t.surface1, borderColor: t.glassBorder,
      borderWidth: 1, borderRadius: 14, padding: 14, gap: 8 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Text style={{ color: t.txtPrimary, fontSize: 13.5, fontWeight: "700", flex: 1 }}>
          {data.label}
        </Text>
        <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>
          {tr("loopmap.chars", { n: data.chars })}
        </Text>
      </View>
      <Text style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 16 }}>
        {tr("harness.briefLegend")}
      </Text>
      {/* ONE Text with nested Texts, not a View per segment: the brief is prose
          and has to WRAP as prose. A row of Views would break every line at a
          chip boundary and turn a paragraph into a column. */}
      <Text selectable style={{ color: t.txtTertiary, fontSize: 11.5, lineHeight: 18, fontFamily: MONO }}>
        {data.segments.map((s, i) =>
          s.kind === "rule" && s.rule ? (
            <Text key={i} testID={"briefchip-" + s.rule} onPress={() => onOpenRule(s.rule as string)}
              style={{ color: t.accent, fontWeight: "700",
                backgroundColor: t.surface2, textDecorationLine: "underline" }}>
              {s.text}
            </Text>
          ) : (
            <Text key={i}>{s.text}</Text>
          ))}
      </Text>
    </View>
  );
}

/** Which brief to read. Henry has one per surface and they are deliberately
 *  NOT the same - the length law alone is stated four times with four values -
 *  so the view picks one rather than pretending there is a single brief. The
 *  list comes from the daemon (harness.SURFACES), never from a client array. */
export function BriefSurfacePicker({ surfaces, value, onPick }: {
  surfaces: { key: string; label: string }[];
  value: string;
  onPick: (k: string) => void;
}) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
      {surfaces.map((s) => (
        <Pressable key={s.key} testID={"briefsurface-" + s.key} onPress={() => onPick(s.key)}
          style={{ backgroundColor: value === s.key ? t.accent : t.surface2,
            borderColor: t.glassBorder, borderWidth: 1, borderRadius: 999,
            paddingHorizontal: 10, paddingVertical: 5 }}>
          <Text numberOfLines={1} style={{ color: value === s.key ? t.canvas : t.txtSecondary,
            fontSize: 11, fontWeight: "700" }}>
            {s.label}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}
