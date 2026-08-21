import { Platform } from "react-native";

// Relative on purpose. The "@/*" alias maps to ./src/*, so reaching the
// sibling modules/ dir through it would mean "@/../modules/glasses" - which
// resolves, but only by walking back out of the alias it just walked into, and
// Metro and tsc do not have to agree on that. A plain relative path is
// unambiguous to both.
import Bridge from "../../modules/glasses";

/** Talking to the Meta glasses — the JS side of the native bridge.
 *
 *  WHAT THIS CLOSES. GlassVoiceService and GlassCameraService were complete,
 *  compiled and present in the APK, and DEAD: nothing in app/src could start an
 *  Android Service, and nothing wrote the daemon target they read from
 *  SharedPreferences. docs/glasses-reference.md §11.6 recorded that for the
 *  voice half ("never started by anything") long before the camera half
 *  repeated it. modules/glasses is the bridge; this is the seam the app uses.
 *
 *  CAPABILITY IS DERIVED, NEVER ASSUMED — the same rule, and for the same
 *  measured reason, as data/voice.ts: an OTA JS bundle always runs against
 *  whatever native binary is already on the phone, so a bundle carrying this
 *  file can land on an APK built before the bridge existed. `modules/glasses`
 *  therefore uses requireOptionalNativeModule (null when absent, never a throw)
 *  and everything here degrades to "this build cannot" instead of white-
 *  screening on a missing native module.
 *
 *  THREE SEPARATE CAPABILITIES, and they do NOT rise and fall together:
 *   - `available`  the bridge is in this binary at all (Android-only today)
 *   - `camera`     the DAT camera, which additionally needs API >= 29, because
 *                  mwdat-core/camera both declare minSdkVersion 29 while the
 *                  app ships 24 (glasses-reference §12.9). Reported by the
 *                  NATIVE side rather than sniffed here, so there is one owner
 *                  of that number.
 *   - the microphone, which needs neither DAT nor API 29 — it is an ordinary
 *     Bluetooth headset mic (§12.3), so it is available whenever the bridge is.
 */

export interface GlassesCaps {
  /** The native bridge is present in this binary. */
  available: boolean;
  /** The DAT camera can run here (bridge present AND API >= 29). */
  camera: boolean;
  /** Why the camera is unavailable, for a UI that must not dead-end. */
  cameraReason?: "no-module" | "api-too-low" | "platform";
}

export function caps(): GlassesCaps {
  // iOS has no bridge today: the services are Android (AudioManager + a typed
  // foreground service). Saying so explicitly beats reporting "no-module",
  // which would read as "your build is old" on a platform that never had it.
  if (Platform.OS !== "android") {
    return { available: false, camera: false, cameraReason: "platform" };
  }
  if (!Bridge) {
    return { available: false, camera: false, cameraReason: "no-module" };
  }
  let camera = false;
  try {
    camera = Bridge.cameraSupported();
  } catch {
    camera = false;
  }
  return {
    available: true,
    camera,
    cameraReason: camera ? undefined : "api-too-low",
  };
}

/** Tell the services where the daemon is. Call once at pairing.
 *
 *  The services run OUTSIDE React and cannot read the app's JS config, which is
 *  precisely why "nothing writes base_url/glance_token" was its own open gap.
 *  Returns false when the bridge is absent so a caller can tell "not
 *  configured" from "cannot configure".
 *
 *  ⚠ WHICH URL, and it is NOT the one the rest of the app uses. The app talks
 *  to the daemon through the E2EE RELAY: every request is sealed and forwarded
 *  as one JSON frame, and in relay mode there is no direct daemon URL at all -
 *  `useConfig.baseUrl` is a LAN address that is meaningless off the LAN. These
 *  services are plain HttpURLConnection clients outside React; they cannot
 *  speak the relay protocol and must not learn to.
 *
 *  The right origin is the PUBLIC GLANCE ORIGIN - the Cloudflare Worker in
 *  glasses/worker that already proxies exactly /glance, /glance/answer,
 *  /glance/talk and /glance/voice to the daemon and nothing else (its README
 *  is explicit that widening that allowlist widens what the internet can reach
 *  on the owner's machine). `/glance/photo` must be added to that allowlist
 *  before a capture can land through it.
 *
 *  So: pass the worker URL and the glance token, NOT baseUrl and the device
 *  token. Passing the LAN address works on the LAN and fails silently
 *  everywhere else, which is the worst of the available failure shapes.
 */
export function configure(baseUrl: string, token: string): boolean {
  if (!Bridge || !baseUrl || !token) return false;
  try {
    return Bridge.configure(baseUrl, token);
  } catch {
    return false;
  }
}

/** Start listening. `useGlassMic` false keeps A2DP so the answer is not 8 kHz.
 *
 *  The trade is the owner's per turn, not a stored setting: the glasses' 5-mic
 *  beamforming array beats a phone in a pocket, but opening it collapses ALL
 *  glasses output to telephone quality until it closes (§3.1). Use the glasses
 *  mic when the phone is away; the phone mic when it is in hand.
 */
export function listen(useGlassMic: boolean): boolean {
  if (!Bridge) return false;
  try {
    return Bridge.listen(useGlassMic);
  } catch {
    return false;
  }
}

export function stopListening(): boolean {
  if (!Bridge) return false;
  try {
    return Bridge.stopListening();
  } catch {
    return false;
  }
}

/** One photo from the glasses, attached to `cardId`.
 *
 *  The card is required at every layer — here, in the service, and in
 *  POST /glance/photo — because silently attaching a photo of the owner's room
 *  to the WRONG card cannot be undone, while a refusal can. Never defaulted to
 *  "the card in focus": that is a heuristic, and this is not a place for one.
 */
export function capture(cardId: string): boolean {
  if (!Bridge || !cardId) return false;
  try {
    return Bridge.capture(cardId);
  } catch {
    return false;
  }
}

export function stopCamera(): boolean {
  if (!Bridge) return false;
  try {
    return Bridge.stopCamera();
  } catch {
    return false;
  }
}
