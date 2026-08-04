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
// see app/AGENTS.md): both pickers return base64 directly via `base64: true`,
// so no expo-file-system read is needed, and `mediaTypes` takes a MediaType[]
// ("images"), NOT the deprecated MediaTypeOptions enum.
import * as DocumentPicker from "expo-document-picker";
import { manipulateAsync, SaveFormat } from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";
import { Platform } from "react-native";

import { t } from "@/i18n";

/** What the daemon accepts. `data` is BARE base64 (no data: prefix). */
export interface Attach { name: string; data: string; mime?: string }

// Mirror daemon/turnopts.py MAX_FILES / MAX_BYTES. The daemon SILENTLY SKIPS
// anything oversized ("an attachment must never crash a turn"), so if we don't
// check here the file just vanishes with no explanation. Enforce + explain.
export const MAX_FILES = 6;
export const MAX_BYTES = 5 * 1024 * 1024;
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

export function tooBig(a: Attach): boolean { return b64Bytes(a.data) > MAX_BYTES; }

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

/** An image the agent cannot read (HEIC/HEIF/AVIF from an iPhone) is re-encoded
 *  to PNG. Uses manipulateAsync: deprecated in SDK 57 in favour of the
 *  context/hook API, but it is the only non-hook entry point, and picking runs
 *  from an event handler where hooks are not available. */
async function toReadableImage(uri: string, name: string, mime?: string): Promise<Attach | null> {
  try {
    const r = await manipulateAsync(uri, [], { format: SaveFormat.PNG, base64: true });
    if (!r.base64) return null;
    return { name: name.replace(/\.[^.]+$/, "") + ".png", data: bare(r.base64), mime: "image/png" };
  } catch {
    return null;   // unreadable image: drop it rather than send something the agent chokes on
  }
}

async function fromImageAsset(a: ImagePicker.ImagePickerAsset, i: number): Promise<Attach | null> {
  const mime = a.mimeType || "image/jpeg";
  const name = a.fileName || `bild_${Date.now()}_${i}.${extFor(mime)}`;
  if (!AGENT_IMAGE_MIME.includes(mime.toLowerCase())) {
    return toReadableImage(a.uri, name, mime);
  }
  if (!a.base64) return null;
  return { name, data: bare(a.base64), mime };
}

/** Photo library. Multi-select; quality 0.8 keeps a phone photo well under the
 *  5 MB cap without visible loss. */
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
 *  closes; base64 so we never touch the filesystem ourselves. */
export async function pickFiles(): Promise<Attach[]> {
  const res = await DocumentPicker.getDocumentAsync({
    multiple: true, copyToCacheDirectory: true, base64: true,
  });
  if (res.canceled) return [];
  return res.assets
    .map((a): Attach | null => (a.base64 ? { name: a.name, data: bare(a.base64), mime: a.mimeType } : null))
    .filter((x): x is Attach => !!x);
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

/** Web only: turn pasted/dropped browser File objects into attachments. */
export function filesToAttachments(files: File[]): Promise<Attach[]> {
  return Promise.all(files.map((f) => new Promise<Attach | null>((resolve) => {
    const r = new FileReader();
    r.onload = () => {
      const s = typeof r.result === "string" ? r.result : "";
      resolve(s ? { name: f.name || "pasted", data: bare(s), mime: f.type || undefined } : null);
    };
    r.onerror = () => resolve(null);
    r.readAsDataURL(f);
  }))).then((xs) => xs.filter((x): x is Attach => !!x));
}

/** Merge new picks into the pending list, enforcing the daemon's caps and
 *  reporting what was refused (silently dropping is what the daemon does and
 *  exactly what we must not do in the UI). */
export function mergeAttachments(cur: Attach[], add: Attach[]): { next: Attach[]; problem?: string } {
  const big = add.filter(tooBig).map((a) => a.name);
  const ok = add.filter((a) => !tooBig(a));
  const room = Math.max(0, MAX_FILES - cur.length);
  const taken = ok.slice(0, room);
  const over = ok.length - taken.length;
  const msgs: string[] = [];
  if (big.length) msgs.push(t("attach.tooBig", { names: big.join(", "), mb: MAX_MB }));
  if (over > 0) msgs.push(t("attach.tooMany", { n: over, max: MAX_FILES }));
  return { next: [...cur, ...taken], problem: msgs.join(" · ") || undefined };
}
