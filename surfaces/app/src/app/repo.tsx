import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, type LoopMap } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { RepoPipeline } from "@/ui/repo_pipeline";
import { RepoTypePicker } from "@/ui/repo_type_picker";
import { useResponsive } from "@/ui/responsive";

/**
 * REPO ONBOARDING - one choice instead of twenty switches.
 *
 * The owner's complaint was "Settings zu komplex, muss idiot-proof sein", and
 * the decree's answer was *sehen statt konfigurieren*. So this screen asks
 * exactly one question - what KIND of repo is this - and then SHOWS the
 * pipeline that answer produces, rather than listing the eight keys it set.
 *
 * It holds no other knob: a second edit place for any key is a binding non-goal
 * of the settings redesign. Everything else about the repo is changed by telling
 * Henry, which is why the pipeline below is read-only and says so.
 *
 * The QUESTION moved to @/ui/repo_type_picker when first-run onboarding had to
 * ask it too. That is not a second edit place - it is the same component in a
 * second context, the way onboard.tsx renders LoginScreen rather than restating
 * sign-in. One question, one implementation, two hosts.
 */
export default function RepoScreen() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { wide } = useResponsive();

  // The QUESTION itself lives in @/ui/repo_type_picker, because first-run
  // onboarding has to ask exactly the same thing - and a second copy of it
  // would drift. This screen is that component plus the answer's consequence:
  // the pipeline picture below.
  const [repo, setRepo] = useState("");

  // The pipeline is fetched for THIS repo, not assembled here: same payload the
  // loop map renders, so the two screens cannot drift apart.
  const { data: map } = useQuery<LoopMap>({
    queryKey: ["loopmap", repo], queryFn: () => api.loopMap(repo), enabled: !!repo,
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

      <ScrollView contentContainerStyle={{ padding: 14, paddingBottom: 60, gap: 16,
        width: "100%", maxWidth: wide ? 860 : undefined, alignSelf: "center" }}>
        <RepoTypePicker onRepoChange={setRepo} wide={wide} />

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
    </View>
  );
}
