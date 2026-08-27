import * as Notifications from "expo-notifications";
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

/** Present a decrypted push as a local notification carrying the card id, so a
 *  tap can deep-link. Used by the foreground received-listener; the background
 *  data-message task (Android) is device-verified separately. */
export async function presentDecrypted(data?: Record<string, string>) {
  const m = decryptPush(data);
  if (!m) return;
  await Notifications.scheduleNotificationAsync({
    content: { title: m.title, body: m.body,
      data: { track: m.track ?? "", kind: m.kind ?? "", body: m.body ?? "" } },
    trigger: null,
  });
}

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
