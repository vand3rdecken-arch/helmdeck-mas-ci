import * as Notifications from "expo-notifications";
import * as TaskManager from "expo-task-manager";
import { Platform } from "react-native";
import { useBlockerVoice } from "./blocker_voice";
import { api } from "./client";
import { useConfig } from "./config";
import { open } from "./e2ee";
import { speak } from "./voice";

// Foreground presentation of the local notifications we raise from decrypted
// data messages.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true, shouldPlaySound: true, shouldSetBadge: false,
    shouldShowBanner: true, shouldShowList: true,
  }),
});

// The 3 fixed actions every card push carries (owner decree mirrors
// ops/docs/ios-watch-feasibility.md §3.3's W1 scope: generic actions + one
// dictate slot, never per-option buttons - a category's actions are static,
// registered once, not rebuilt per notification). "continue"/"stop" map onto
// real endpoints (steer/cancel), not a guess at what the worker wants.
const CARD_CATEGORY = "helmdeck.card";
const ACTION_CONTINUE = "continue";
const ACTION_STOP = "stop";
const ACTION_REPLY = "reply";

async function registerCardCategory() {
  await Notifications.setNotificationCategoryAsync(CARD_CATEGORY, [
    { identifier: ACTION_CONTINUE, buttonTitle: "Weiter",
      options: { opensAppToForeground: false } },
    { identifier: ACTION_STOP, buttonTitle: "Stopp",
      options: { opensAppToForeground: false, isDestructive: true } },
    { identifier: ACTION_REPLY, buttonTitle: "Antworten…",
      textInput: { submitButtonTitle: "Senden", placeholder: "Antwort…" },
      options: { opensAppToForeground: false } },
  ]);
}

/** Announce this device's raw FCM token to the daemon (daemon seals pushes to
 *  it). No-op on web / when not connected. */
export async function registerForPush() {
  if (Platform.OS === "web") return;
  try {
    const perm = await Notifications.requestPermissionsAsync();
    if (!perm.granted) return;
    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync("default", {
        name: "HelmDeck", importance: Notifications.AndroidImportance.HIGH,
      });
      await registerCardCategory();
      // Persists across process restarts once registered; safe/idempotent to
      // call again on every launch (Notifications.registerTaskAsync no-ops if
      // the task is already registered).
      await Notifications.registerTaskAsync(BACKGROUND_NOTIFICATION_TASK);
    }
    const token = (await Notifications.getDevicePushTokenAsync()).data; // raw FCM token on Android
    await api.post("/push/register", { token });
  } catch { /* not paired / no daemon / no FCM */ }
}

/** Decrypt a sealed data-only push {cipher} -> {title, body, track}. The daemon
 *  (notify.push_fcm) seals with its sk + the pinned phone pub; we open with our
 *  sk + the daemon pub. */
export function decryptPush(data?: Record<string, string>): { title: string; body: string; track?: string; kind?: string } | null {
  const { mySec, daemonPub } = useConfig.getState();
  if (!data?.cipher || !mySec || !daemonPub) return null;
  try { return JSON.parse(open(data.cipher, mySec, daemonPub)); } catch { return null; }
}

/** Content shape shared by the foreground listener and the background task, so
 *  a push looks and acts identically regardless of which one caught it - same
 *  title/body/data AND the same category, so the 3 actions above are always
 *  available on the notification the owner actually sees. */
function notificationContent(m: { title: string; body: string; track?: string; kind?: string }) {
  return {
    title: m.title, body: m.body,
    data: { track: m.track ?? "", kind: m.kind ?? "", body: m.body ?? "" },
    categoryIdentifier: CARD_CATEGORY,
  };
}

/** Present a decrypted push as a local notification carrying the card id, so a
 *  tap can deep-link. Used by the foreground received-listener; the
 *  background task below covers backgrounded/killed. */
export async function presentDecrypted(data?: Record<string, string>) {
  const m = decryptPush(data);
  if (!m) return;
  await Notifications.scheduleNotificationAsync({ content: notificationContent(m), trigger: null });
}

// -- Background delivery (Android) ------------------------------------------
//
// notify.push_fcm now sends a DATA-ONLY FCM message on purpose (see
// spine/comms/notify.py) precisely so this task fires while the app is
// backgrounded or killed, not just when it happens to be open. Must be
// `defineTask`d at module scope - TaskManager invokes it in a headless JS
// context with no React tree, so it cannot rely on anything mounted by
// _layout.tsx and must hydrate its own config (mirrors the cold-start race
// documented at _layout.tsx's usePushWiring, measured 2026-08-24).
const BACKGROUND_NOTIFICATION_TASK = "helmdeck-background-notification";

TaskManager.defineTask(BACKGROUND_NOTIFICATION_TASK, async ({ data, error }) => {
  if (error) return;
  const raw = data as Record<string, unknown> | undefined;
  if (!raw) return;

  // A tap on one of the 3 fixed actions (or the default tap, which _layout.tsx's
  // own foreground listener also handles when it gets the chance - this branch
  // is the one place that ALSO runs when the app never comes to the foreground,
  // i.e. every "continue"/"stop"/"reply" tap, since those actions are
  // deliberately opensAppToForeground:false).
  if ("actionIdentifier" in raw) {
    const actionIdentifier = raw.actionIdentifier as string;
    const userText = raw.userText as string | undefined;
    const content = (raw.notification as { request?: { content?: { data?: Record<string, string> } } } | undefined)
      ?.request?.content?.data;
    const track = content?.track;
    if (!track) return;
    try {
      await useConfig.getState().hydrate();
      if (actionIdentifier === ACTION_STOP) await api.cancel(track);
      else if (actionIdentifier === ACTION_REPLY && userText) await api.steer(track, userText);
      else if (actionIdentifier === ACTION_CONTINUE) await api.steer(track, "Weiter so.");
    } catch { /* best-effort - the app isn't open to show a retry */ }
    return;
  }

  // A data-only FCM message arrived. Shape of `raw` here is the
  // NotificationTaskPayload the docs describe (raw.data.dataString is the JSON-
  // encoded FCM `data` map) - defensively unwrapped since this repo has no
  // node_modules to read the real .d.ts from inside a card worktree; confirm
  // against the installed expo-notifications types at build time.
  let cipher: string | undefined;
  try {
    const inner = raw.data as { dataString?: string } | Record<string, string> | undefined;
    const parsed = typeof inner?.dataString === "string" ? JSON.parse(inner.dataString) : inner;
    cipher = (parsed as Record<string, string> | undefined)?.cipher;
  } catch { /* fall through to the generic fallback below */ }

  await useConfig.getState().hydrate();
  const m = cipher ? decryptPush({ cipher }) : null;
  await Notifications.scheduleNotificationAsync({
    content: m ? notificationContent(m)
      // Same floor as the OLD hybrid message, so a decrypt failure (stale
      // keys, unexpected payload shape) never regresses below today's UX.
      : { title: "HelmDeck", body: "Neue Meldung – zum Ansehen tippen", data: {} },
    trigger: null,
  });
});

/** Speak a decrypted push aloud - the proactive-blocker half of phone voice
 *  (ops/docs/glasses-reference.md §11.8's "what the app still needs", closed with
 *  the native player data/voice.ts already ships for the chat voice mode).
 *  Fires from the SAME foreground received-listener as presentDecrypted, so a
 *  card that needs the owner is announced through whatever audio route the
 *  phone is on right now - ordinary Bluetooth media playback when paired
 *  with the glasses, no DAT, no companion project.
 *
 *  Off by default (useBlockerVoice), and only ever runs while the app process
 *  is alive to receive the event - same structural limit the glasses webapp
 *  itself has (no background execution), not a bug to work around here. A
 *  render failure (offline, no edge-tts) degrades to silence; the visual
 *  notification from presentDecrypted already carries the news. */
export async function announceDecrypted(data?: Record<string, string>) {
  if (!useBlockerVoice.getState().enabled) return;
  const m = decryptPush(data);
  if (!m) return;
  try {
    // Strip the trailing " [card-id]" notify.card_event appends for the
    // human-readable body - useful in a text notification, noise read aloud.
    const body = (m.body || "").replace(/\s*\[[^[\]]*\]\s*$/, "").trim();
    const text = body ? `${m.title}. ${body}` : m.title;
    const { clip } = await api.speak(text);
    if (clip) await speak(clip);
  } catch { /* speech is an enhancement - the visual notification already landed */ }
}
