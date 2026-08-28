import * as Notifications from "expo-notifications";
import * as TaskManager from "expo-task-manager";
import { Platform } from "react-native";
import { useBlockerVoice } from "./blocker_voice";
import { ApiError, TransportError, api } from "./client";
import { useConfig } from "./config";
import { open } from "./e2ee";
import { speak } from "./voice";
import { t } from "@/i18n/core";

// Foreground presentation of the local notifications we raise from decrypted
// data messages.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true, shouldPlaySound: true, shouldSetBadge: false,
    shouldShowBanner: true, shouldShowList: true,
  }),
});

// The 3 fixed actions a NON-question card push carries: generic actions plus one
// dictate slot, mapped onto real endpoints (steer/cancel), not a guess at what
// the worker wants.
const CARD_CATEGORY = "helmdeck.card";
const ACTION_CONTINUE = "continue";
const ACTION_STOP = "stop";
const ACTION_REPLY = "reply";
// W1c: a card with ONE pending single-select question gets the worker's own
// options as buttons instead. Keyed by CARD, not by question id - two cards may
// wait on the owner at the same time, and a per-question key would have made
// every new question delete the other card's still-visible buttons. Re-asking
// on the same card re-registers the same id, which is exactly the intent.
const Q_CATEGORY_PREFIX = "helmdeck.q.";
const ACTION_OPTION = "opt:";           // opt:<index into the notification's own opts>
const qCategoryId = (track: string) => Q_CATEGORY_PREFIX + track;

/** The sealed ask block notify.ask_payload() adds to a question push. */
type Ask = { id: string; header: string; options: string[]; more?: boolean };

// Derived from the function we hand it to, rather than naming an exported type:
// the array below needs an explicit annotation (a bare .map() infers an element
// type without `textInput`, so pushing the dictation action onto it would not
// typecheck), and this way the annotation cannot drift from - or misname - what
// the installed expo-notifications actually expects. This worktree has no
// node_modules to check a type name against; this needs none.
type CardAction = Parameters<typeof Notifications.setNotificationCategoryAsync>[1][number];

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

/** Register this card's question category, whose buttons ARE the options the
 *  worker wrote. Android shows at most three action buttons, which is why
 *  notify.ask_payload() never seals more than three - and why it keeps the last
 *  slot for dictation when it had to truncate (ask.py accepts free text as the
 *  owner's own answer, so a shortened list is never a dead end).
 *
 *  Registering is idempotent and cheap, and it happens on EVERY question push
 *  rather than once at startup, because the options differ per question. */
async function registerQuestionCategory(track: string, ask: Ask): Promise<string> {
  const id = qCategoryId(track);
  const actions: CardAction[] = ask.options.map((label, i) => ({
    identifier: ACTION_OPTION + i,
    buttonTitle: label,
    options: { opensAppToForeground: false },
  }));
  if (ask.more) {
    actions.push({ identifier: ACTION_REPLY, buttonTitle: "Antworten…",
      textInput: { submitButtonTitle: "Senden", placeholder: "Antwort…" },
      options: { opensAppToForeground: false } });
  }
  await Notifications.setNotificationCategoryAsync(id, actions);
  return id;
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
export function decryptPush(data?: Record<string, string>): { title: string; body: string; track?: string; kind?: string; ask?: Ask } | null {
  const { mySec, daemonPub } = useConfig.getState();
  if (!data?.cipher || !mySec || !daemonPub) return null;
  try { return JSON.parse(open(data.cipher, mySec, daemonPub)); } catch { return null; }
}

/** Content shape shared by the foreground listener and the background task, so
 *  a push looks and acts identically regardless of which one caught it - same
 *  title/body/data AND the same category.
 *
 *  A question push (with a sealed `ask`) carries the worker's options as its
 *  buttons; everything else keeps the 3 generic actions. The question's id,
 *  header and labels ride on the NOTIFICATION's own data, so the action handler
 *  resolves a tap from the notification the owner actually pressed and never
 *  has to re-decrypt or trust a category that may since have been re-registered
 *  with a newer question's options. */
async function notificationContent(m: { title: string; body: string; track?: string; kind?: string; ask?: Ask }) {
  const data: Record<string, string> = {
    track: m.track ?? "", kind: m.kind ?? "", body: m.body ?? "",
  };
  let categoryIdentifier = CARD_CATEGORY;
  const ask = m.ask;
  if (m.track && ask?.id && ask.header && (ask.options?.length ?? 0) >= 2) {
    data.qid = ask.id;
    data.qheader = ask.header;
    data.opts = JSON.stringify(ask.options);
    categoryIdentifier = await registerQuestionCategory(m.track, ask);
  }
  return { title: m.title, body: m.body, data, categoryIdentifier };
}

/** Present a decrypted push as a local notification carrying the card id, so a
 *  tap can deep-link. Used by the foreground received-listener; the
 *  background task below covers backgrounded/killed. */
export async function presentDecrypted(data?: Record<string, string>) {
  const m = decryptPush(data);
  if (!m) return;
  await Notifications.scheduleNotificationAsync({ content: await notificationContent(m), trigger: null });
}

/** A notification action runs with opensAppToForeground:false, so a failure has
 *  NO surface: the owner taps "Stopp" or an option, the POST 409s (the question
 *  was already answered or replaced) or the relay is down, and the card simply
 *  carries on as if he had never tapped. Raise the failure as its own
 *  notification - same surface the action came from, and it bridges to the
 *  watch like any other. Silence here was the one place W1b could lie. */
async function reportActionFailure(e: unknown) {
  const msg = (e instanceof ApiError || e instanceof TransportError)
    ? e.message : t("push.actionFailedGeneric");
  try {
    await Notifications.scheduleNotificationAsync({
      content: { title: t("push.actionFailedTitle"), body: msg, data: {} },
      trigger: null,
    });
  } catch { /* nothing left to try */ }
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
    const request = (raw.notification as
      { request?: { identifier?: string; content?: { data?: Record<string, string> } } } | undefined)?.request;
    const content = request?.content?.data;
    const track = content?.track;
    if (!track) return;
    // The question this very notification was raised for. Stale by design when
    // the worker has since moved on: `qid` is posted as request_id and the
    // daemon answers 409 rather than settling a question that no longer exists
    // (routes_track_actions.tracks_answer_post) - which reportActionFailure
    // then makes visible instead of swallowing.
    const qid = content?.qid;
    const qheader = content?.qheader;
    let opts: string[] = [];
    try { opts = content?.opts ? JSON.parse(content.opts) : []; } catch { /* no options on this push */ }
    const answerable = Boolean(qid && qheader);
    try {
      await useConfig.getState().hydrate();
      if (actionIdentifier.startsWith(ACTION_OPTION)) {
        // The label is read from THIS notification's data, never from the
        // category - the category may already carry a newer question's buttons.
        const label = opts[Number(actionIdentifier.slice(ACTION_OPTION.length))];
        if (!label || !answerable) return;
        await api.answer(track, { [qheader as string]: label }, qid as string);
        // The question is settled, so its buttons are spent. Event-time
        // cleanup at exactly one owner - not a periodic sweep guessing which
        // categories are dead.
        try { await Notifications.deleteNotificationCategoryAsync(qCategoryId(track)); } catch { /* hygiene only */ }
      } else if (actionIdentifier === ACTION_STOP) {
        await api.cancel(track);
      } else if (actionIdentifier === ACTION_REPLY && userText) {
        // On a pending question the dictated text IS the answer - ask.py's
        // documented free-text escape hatch ("the owner is the authenticated
        // principal"), which reaches the worker tagged as HIS words. Steering
        // instead would leave the question hanging next to a loose remark.
        if (answerable) await api.answer(track, { [qheader as string]: userText }, qid as string);
        else await api.steer(track, userText);
      } else if (actionIdentifier === ACTION_CONTINUE) {
        await api.steer(track, "Weiter so.");
      }
      // The action was accepted, so the notification that carried it is spent.
      // Leaving it on the lockscreen (or the wrist, where it bridged to) invites
      // a second tap - which the daemon would correctly 409 as an
      // already-answered question, turning a SUCCESSFUL answer into a failure
      // message. Dismissing is the difference between "it worked" and "it
      // worked, then told you it didn't".
      if (request?.identifier) {
        try { await Notifications.dismissNotificationAsync(request.identifier); } catch { /* hygiene only */ }
      }
    } catch (e) { await reportActionFailure(e); }
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
    content: m ? await notificationContent(m)
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
