// Attachments: pick photos / files and hand them to the daemon.
//
// THE CONTRACT (daemon/turnopts.py save_attachments): [{name, data(base64), mime}].
// The daemon writes them into the card's run_dir/.attachments and appends the
// PATHS to the agent prompt ("Attached files (read them as needed): ..."), which
// is the only shape that works here - HelmDeck drives the Claude Code CLI
// (`claude -p`, see daemon/drivers.py), not an HTTP API, so there is no
// image-block channel. The agent opens the files with its own Read tool.
//
// Expo SDK 57 specifics (checked against the installed .d.ts, not from memory -
// see surfaces/app/AGENTS.md): expo-image-picker's `base64: true` works on every
// platform, but expo-document-picker's is `@platform web` ONLY (types.d.ts on
// both the option and the asset field) - on Android/iOS `asset.base64` is
// always undefined regardless of the option, so pickFiles() below reads the
// cache copy itself. `mediaTypes` takes a MediaType[] ("images"), NOT the
// deprecated MediaTypeOptions enum.
import * as DocumentPicker from "expo-document-picker";
import { EncodingType, readAsStringAsync } from "expo-file-system/legacy";
import { manipulateAsync, SaveFormat } from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";
import { Platform } from "react-native";

import { t } from "@/i18n";

/** What the daemon accepts. `data` is BARE base64 (no data: prefix). */
export interface Attach { name: string; data: string; mime?: string }

// Mirror daemon/turnopts.py MAX_FILES. The daemon SILENTLY SKIPS anything over
// its caps ("an attachment must never crash a turn"), so if we don't check here
// the file just vanishes with no explanation. Enforce + explain.
export const MAX_FILES = 6;
// The byte cap is per MESSAGE, not per file, and it is the RELAY's, not the
// daemon's (turnopts allows 5 MB per file): the relay takes one sealed frame of
// at most 4 MiB (surfaces/relay/worker MAX_BODY), and an attachment rides in it
// base64'd twice - once in the JSON body, again when the frame is sealed - so
// it costs ~1.78x its size. Two full-size phone photos were a "Relay error 413"
// (2026-09-27). 2 MiB of files -> ~3.6 MiB frame, the rest is headroom for text.
export const MAX_BYTES = 2 * 1024 * 1024;
/** Images are shrunk to this long edge before sending. Claude downsamples
 *  anything larger on its side anyway, so a 4000px photo only costs bytes. */
const IMAGE_EDGE = 1568;
/** The cap as the owner reads it - used in the limit hint and the refusal text. */
export const MAX_MB = Math.round(MAX_BYTES / 1024 / 1024);

/** What Claude Code can actually read as an image. Anything else that is still
 *  an image gets transcoded to PNG (iPhone HEIC is the case that matters). */
const AGENT_IMAGE_MIME = ["image/png", "image/jpeg", "image/gif", "image/webp"];

export const isWeb = Platform.OS === "web";

/** Decoded byte size of a bare base64 string (4 chars -> 3 bytes, minus padding). */
export function b64Bytes(b64: string): number {
  const pad = b64.endsWith("==") ? 2 : b64.endsWith("=") ? 1 : 0;
  return Math.floor((b64.length * 3) / 4) - pad;
}

/** Strip a data: URL down to the bare base64 the daemon expects. */
function bare(data: string): string {
  return data.includes(",") && data.startsWith("data:") ? data.split(",").slice(1).join(",") : data;
}

function extFor(mime?: string): string {
  const m = (mime || "").toLowerCase();
  if (m.includes("png")) return "png";
  if (m.includes("jpeg") || m.includes("jpg")) return "jpg";
  if (m.includes("gif")) return "gif";
  if (m.includes("webp")) return "webp";
  return "img";
}

/** Re-encode an image as a JPEG of at most IMAGE_EDGE on the long side - for
 *  one the agent cannot read (HEIC/HEIF/AVIF from an iPhone) and for one too
 *  big to be worth its bytes. w/h unknown (web paste) -> measured first. Uses
 *  manipulateAsync: deprecated in SDK 57 in favour of the context/hook API, but
 *  it is the only non-hook entry point, and picking runs from an event handler
 *  where hooks are not available. */
async function toSendableImage(uri: string, name: string, w?: number, h?: number): Promise<Attach | null> {
  try {
    if (!w || !h) ({ width: w, height: h } = await manipulateAsync(uri, []));
    const resize = Math.max(w, h) <= IMAGE_EDGE ? []
      : [{ resize: w >= h ? { width: IMAGE_EDGE } : { height: IMAGE_EDGE } }];
    const r = await manipulateAsync(uri, resize, { format: SaveFormat.JPEG, compress: 0.8, base64: true });
    if (!r.base64) return null;
    return { name: name.replace(/\.[^.]+$/, "") + ".jpg", data: bare(r.base64), mime: "image/jpeg" };
  } catch {
    return null;   // unreadable image: drop it rather than send something the agent chokes on
  }
}

/** Does this image need toSendableImage? GIFs stay as they are (animation). */
function needsReencode(mime: string, w?: number, h?: number): boolean {
  const m = mime.toLowerCase();
  if (m === "image/gif") return false;
  return !AGENT_IMAGE_MIME.includes(m) || !w || !h || Math.max(w, h) > IMAGE_EDGE;
}

async function fromImageAsset(a: ImagePicker.ImagePickerAsset, i: number): Promise<Attach | null> {
  const mime = a.mimeType || "image/jpeg";
  const name = a.fileName || `bild_${Date.now()}_${i}.${extFor(mime)}`;
  if (needsReencode(mime, a.width, a.height)) return toSendableImage(a.uri, name, a.width, a.height);
  if (!a.base64) return null;
  return { name, data: bare(a.base64), mime };
}

/** Photo library. Multi-select; big photos are shrunk in fromImageAsset. */
export async function pickImages(): Promise<Attach[]> {
  if (!isWeb) {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) throw new Error(t("attach.noPhotoAccess"));
  }
  const res = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"], allowsMultipleSelection: true,
    selectionLimit: MAX_FILES, quality: 0.8, base64: true,
  });
  if (res.canceled) return [];
  const out = await Promise.all(res.assets.map(fromImageAsset));
  return out.filter((x): x is Attach => !!x);
}

/** Camera capture. Paseo has no camera path at all; SDK 57 exposes
 *  launchCameraAsync, and "add a photo" usually means taking one. */
export async function takePhoto(): Promise<Attach[]> {
  const perm = await ImagePicker.requestCameraPermissionsAsync();
  if (!perm.granted) throw new Error(t("attach.noCameraAccess"));
  const res = await ImagePicker.launchCameraAsync({ quality: 0.8, base64: true });
  if (res.canceled) return [];
  const out = await Promise.all(res.assets.map(fromImageAsset));
  return out.filter((x): x is Attach => !!x);
}

/** Any file. copyToCacheDirectory so the uri stays readable after the picker
 *  closes. On web `base64` comes back on the asset directly; on Android/iOS
 *  it never does (see the import comment above), so we read the cache copy
 *  via expo-file-system there. A read failure throws (no silent drop) - it
 *  reaches runPick's catch and shows the owner a real Alert. */
export async function pickFiles(): Promise<Attach[]> {
  const res = await DocumentPicker.getDocumentAsync({
    multiple: true, copyToCacheDirectory: true, base64: true,
  });
  if (res.canceled) return [];
  const out = await Promise.all(res.assets.map(async (a): Promise<Attach | null> => {
    const data = a.base64 ?? await readAsStringAsync(a.uri, { encoding: EncodingType.Base64 });
    return data ? { name: a.name, data: bare(data), mime: a.mimeType } : null;
  }));
  return out.filter((x): x is Attach => !!x);
}

/** Android can kill the app's activity while the system picker is in front.
 *  Without this the user's selection is silently lost on return. */
export async function recoverPendingImages(): Promise<Attach[]> {
  if (isWeb) return [];
  try {
    const res = await ImagePicker.getPendingResultAsync();
    if (!res || !("assets" in res) || res.canceled || !res.assets) return [];
    const out = await Promise.all(res.assets.map(fromImageAsset));
    return out.filter((x): x is Attach => !!x);
  } catch {
    return [];
  }
}

/** Web only: turn pasted/dropped browser File objects into attachments.
 *  Images go through the same shrink as picked photos. */
export function filesToAttachments(files: File[]): Promise<Attach[]> {
  return Promise.all(files.map((f) => new Promise<string>((resolve) => {
    const r = new FileReader();
    r.onload = () => resolve(typeof r.result === "string" ? r.result : "");
    r.onerror = () => resolve("");
    r.readAsDataURL(f);
  }).then((s): Attach | null | Promise<Attach | null> => {
    if (!s) return null;
    const name = f.name || "pasted";
    if (f.type.startsWith("image/") && needsReencode(f.type)) return toSendableImage(s, name);
    return { name, data: bare(s), mime: f.type || undefined };
  }))).then((xs) => xs.filter((x): x is Attach => !!x));
}

/** Merge new picks into the pending list, enforcing the caps (file count, and
 *  bytes per MESSAGE - see MAX_BYTES) and reporting what was refused (silently
 *  dropping is what the daemon does and exactly what we must not do in the UI). */
export function mergeAttachments(cur: Attach[], add: Attach[]): { next: Attach[]; problem?: string } {
  let used = cur.reduce((n, a) => n + b64Bytes(a.data), 0);
  const big: string[] = [];
  const ok: Attach[] = [];
  for (const a of add) {
    const n = b64Bytes(a.data);
    if (used + n > MAX_BYTES) { big.push(a.name); continue; }
    used += n;
    ok.push(a);
  }
  const room = Math.max(0, MAX_FILES - cur.length);
  const taken = ok.slice(0, room);
  const over = ok.length - taken.length;
  const msgs: string[] = [];
  if (big.length) msgs.push(t("attach.tooBig", { names: big.join(", "), mb: MAX_MB }));
  if (over > 0) msgs.push(t("attach.tooMany", { n: over, max: MAX_FILES }));
  return { next: [...cur, ...taken], problem: msgs.join(" · ") || undefined };
}
