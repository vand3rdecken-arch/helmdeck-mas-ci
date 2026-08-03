import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { api } from "./client";
import { useConfig } from "./config";
import { open } from "./e2ee";

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
export function decryptPush(data?: Record<string, string>): { title: string; body: string; track?: string } | null {
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
    content: { title: m.title, body: m.body, data: { track: m.track ?? "" } },
    trigger: null,
  });
}
