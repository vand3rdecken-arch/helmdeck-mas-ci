import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, type LoopMap, type RepoTemplates, type RepoView } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { RepoPipeline } from "@/ui/repo_pipeline";
import { useResponsive } from "@/ui/responsive";

/**
 * REPO ONBOARDING - one choice instead of twenty switches.
 *
 * The owner's complaint was "Settings zu komplex, muss idiot-proof sein", and
 * the decree's answer was *sehen statt konfigurieren*. So this screen asks
 * exactly one question - what KIND of repo is this - and then SHOWS the
 * pipeline that answer produces, rather than listing the eight keys it set.
 *
 * It is the ONE place a repo's type is chosen, and it holds no other knob: a
 * second edit place for any key is a binding non-goal of the settings redesign.
 * Everything else about the repo is changed by telling Henry, which is why the
 * pipeline below is read-only and says so.
 */
export default function RepoScreen() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const { wide } = useResponsive();

  const { data, isLoading, error } = useQuery<RepoTemplates>({
    queryKey: ["repoTemplates"], queryFn: api.repoTemplates,
  });
  const [repo, setRepo] = useState("");
  const [err, setErr] = useState("");

  // Land on the repo that still needs a decision. A repo with no type is the
  // only thing on this screen that is actually outstanding, so preferring it
  // over "the first one" means the screen opens on the work.
  useEffect(() => {
    if (repo || !data?.repos?.length) return;
    setRepo((data.repos.find((r) => !r.template) ?? data.repos[0]).repo);
  }, [data, repo]);

  const current: RepoView | undefined = data?.repos.find((r) => r.repo === repo);

  // The pipeline is fetched for THIS repo, not assembled here: same payload the
  // loop map renders, so the two screens cannot drift apart.
  const { data: map } = useQuery<LoopMap>({
    queryKey: ["loopmap", repo], queryFn: () => api.loopMap(repo), enabled: !!repo,
  });

  const apply = useMutation({
    mutationFn: (template: string) => api.applyRepoTemplate(repo, template),
    onSuccess: (r) => {
      if (r?.error) { setErr(r.error); return; }
      setErr("");
      // Both queries, because both are now stale: the record changed AND the
      // pipeline it produces changed.
      qc.invalidateQueries({ queryKey: ["repoTemplates"] });
      qc.invalidateQueries({ queryKey: ["loopmap"] });
    },
    onError: (e: Error) => setErr(e.message),
  });

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: insets.top }}>
      <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 8, gap: 8 }}>
        <Pressable onPress={() => router.back()} hitSlop={10}>
          <Ionicons name="chevron-back" size={24} color={t.txtSecondary} />
        </Pressable>
        <Text style={{ color: t.txtPrimary, fontSize: 17, fontWeight: "700", flex: 1 }}>
          {tr("repo.title")}
        </Text>
      </View>

      {isLoading ? <ActivityIndicator color={t.accent} style={{ marginTop: 40 }} /> :
       error || !data ? <Text style={{ color: t.danger, padding: 16 }}>{tr("health.unreachable")}</Text> : (
        <ScrollView contentContainerStyle={{ padding: 14, paddingBottom: 60, gap: 16,
          width: "100%", maxWidth: wide ? 860 : undefined, alignSelf: "center" }}>
          <Text style={{ color: t.txtSecondary, fontSize: 12.5, lineHeight: 18 }}>{tr("repo.intro")}</Text>

          {/* ---- which repo ---- */}
          <View style={{ gap: 8 }}>
            <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontWeight: "700", letterSpacing: 0.6 }}>
              {tr("repo.which").toUpperCase()}
            </Text>
            {data.repos.length ? (
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 7 }}>
                {data.repos.map((r) => {
                  const on = r.repo === repo;
                  return (
                    // testID by NAME, not by path: a Windows path is full of
                    // backslashes, and `[data-testid="C:\Users\..."]` reads \U
                    // as a CSS escape - the shot driver matched 0 nodes and the
                    // screenshots silently showed an unclicked screen.
                    <Pressable key={r.repo} testID={"repo-" + (r.project?.name || r.repo)}
                      onPress={() => { setRepo(r.repo); setErr(""); }}
                      style={{ flexDirection: "row", alignItems: "center", gap: 6,
                        backgroundColor: on ? t.accent : t.surface1,
                        borderColor: r.template ? t.glassBorder : t.warn, borderWidth: 1,
                        borderRadius: 999, paddingHorizontal: 11, paddingVertical: 7 }}>
                      <Text numberOfLines={1} style={{ color: on ? t.canvas : t.txtPrimary,
                        fontSize: 12, fontWeight: on ? "800" : "600", maxWidth: 260 }}>
                        {r.project?.name || r.repo}
                      </Text>
                      {/* a repo with no type is the outstanding decision - mark it */}
                      {!r.template ? (
                        <View style={{ backgroundColor: t.warn, borderRadius: 999, paddingHorizontal: 6, paddingVertical: 1 }}>
                          <Text style={{ color: t.canvas, fontSize: 9, fontWeight: "800" }}>{tr("repo.noType")}</Text>
                        </View>
                      ) : null}
                    </Pressable>
                  );
                })}
              </View>
            ) : (
              <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("repo.none")}</Text>
            )}
            <TextInput value={repo} onChangeText={(v) => { setRepo(v); setErr(""); }}
              autoCapitalize="none" autoCorrect={false} placeholder={tr("repo.pathPlaceholder")}
              placeholderTextColor={t.txtTertiary}
              style={{ backgroundColor: t.surface1, borderColor: t.glassBorder, borderWidth: 1,
                borderRadius: 10, paddingHorizontal: 11, paddingVertical: 9, color: t.txtPrimary, fontSize: 12.5 }} />
          </View>

          {/* ---- the one question ---- */}
          <View style={{ gap: 8 }}>
            <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontWeight: "700", letterSpacing: 0.6 }}>
              {tr("repo.pickType").toUpperCase()}
            </Text>
            <View style={{ flexDirection: wide ? "row" : "column", gap: 10 }}>
              {data.templates.map((tpl) => {
                const on = current?.template === tpl.id;
                return (
                  <Pressable key={tpl.id} testID={"tpl-" + tpl.id}
                    disabled={!repo || apply.isPending}
                    onPress={() => apply.mutate(tpl.id)}
                    style={{ flex: wide ? 1 : undefined, backgroundColor: t.surface1,
                      borderColor: on ? t.accent : t.glassBorder, borderWidth: on ? 2 : 1,
                      borderRadius: 14, padding: 13, gap: 6, opacity: repo ? 1 : 0.5 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 7 }}>
                      <Text style={{ color: t.txtPrimary, fontSize: 14, fontWeight: "700", flex: 1 }}>
                        {tpl.label}
                      </Text>
                      {on ? <Ionicons name="checkmark-circle" size={18} color={t.accent} /> : null}
                    </View>
                    <Text style={{ color: t.txtSecondary, fontSize: 11.5, lineHeight: 16 }}>{tpl.who}</Text>
                    {/* `summary`, NOT `body`. The first build rendered the whole
                        markdown file here - asterisks, backticks and all - and
                        the screenshot settled it: the pipeline, which is the
                        entire point of this screen, ended up three screens
                        below the fold. The file's prose is for whoever edits
                        the template; the owner picking a type needs one line
                        and then the picture. */}
                    <Text style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 15.5 }}>
                      {tpl.summary}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
            {apply.isPending ? <ActivityIndicator color={t.accent} /> : null}
            {err ? <Text style={{ color: t.danger, fontSize: 12 }}>{err}</Text> : null}
          </View>

          {/* ---- and here is what that choice DOES ---- */}
          {repo ? (
            <View style={{ gap: 10, backgroundColor: t.surface1, borderColor: t.glassBorder,
              borderWidth: 1, borderRadius: 16, padding: 14, paddingTop: 16 }}>
              <Text style={{ color: t.txtTertiary, fontSize: 10.5, fontWeight: "700", letterSpacing: 0.6 }}>
                {tr("repo.pipeline").toUpperCase()}
              </Text>
              <RepoPipeline map={map} />
            </View>
          ) : null}
        </ScrollView>
      )}
    </View>
  );
}
