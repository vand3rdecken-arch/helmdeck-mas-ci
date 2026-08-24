// HelmDeck desktop OTA client (Electron-shell side) - Paseo's desktop
// auto-update mechanism, taken from the REAL Paseo source (_paseo_src), not
// invented. Same engine as desktop_update.py, same feed, same evidence rules:
//
//   update-callout-source.tsx   silent automatic check at start + every 30 min
//   desktop-app-updater.ts      10 s re-check while found-but-not-downloaded;
//                               silent-check errors are logged, never surfaced
//   auto-updater.ts             autoDownload=true; install-on-quit revalidates
//                               the manifest itself, silent, no forced relaunch
//   main.ts                     UPDATE_QUIT_DEADLINE_MS = 5s on that quit path
//
// Feed: the relay's existing /updates/assets?path=...&channel=desktop route
// (published by ops/deploy/push_update.sh). "Update available" == manifest id !=
// installed marker id - the relay is the source of truth, phone-OTA rule.
// A staged dir is swappable only after every file re-hashes to its manifest
// sha256; the previous bundle stays as app-dist.old (manual recovery reserve).
// Dependency-free (Node builtins only) so plain `node` can drive it in tests.
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const CHECK_INTERVAL_MS = 30 * 60 * 1000;   // Paseo CHECK_INTERVAL_MS
const PENDING_RECHECK_MS = 10 * 1000;       // Paseo PENDING_RECHECK_MS
const UPDATE_QUIT_DEADLINE_MS = 5 * 1000;   // Paseo UPDATE_QUIT_DEADLINE_MS

const MANIFEST_NAME = "desktop.json";
const MARKER_NAME = ".hd-update.json";
const CHANNEL = "desktop";

// Manifest paths become filesystem writes - refuse traversal/absolute/drive.
function normRel(rel) {
  const s = path.posix.normalize(String(rel || "").replace(/\\/g, "/"));
  if (!s || s === "." || s.startsWith("..") || s.startsWith("/") || s.includes(":")) return null;
  return s;
}

// The feed base is the paired relay from the daemon's settings.json; without
// one the updater stays dormant (Paseo's "not available in dev" case).
function readRelayUrl(settingsPath) {
  try {
    const rel = (JSON.parse(fs.readFileSync(settingsPath, "utf8")).relay || {});
    const url = String(rel.url || "").trim().replace(/\/+$/, "");
    return url || null;
  } catch { return null; }
}

function assetUrl(base, rel, cacheBust) {
  return base.replace(/\/+$/, "") + "/updates/assets?path=" + encodeURIComponent(rel)
    + "&channel=" + CHANNEL + (cacheBust ? "&v=" + encodeURIComponent(cacheBust) : "");
}

async function fetchBuf(url, timeoutMs) {
  const r = await fetch(url, { signal: AbortSignal.timeout(timeoutMs || 20000) });
  if (!r.ok) throw new Error("HTTP " + r.status + " for " + url);
  return Buffer.from(await r.arrayBuffer());
}

async function fetchManifest(base, timeoutMs) {
  const buf = await fetchBuf(assetUrl(base, MANIFEST_NAME, String(Date.now())), timeoutMs || 10000);
  const man = JSON.parse(buf.toString("utf8"));
  if (!man.id || !Array.isArray(man.files)) throw new Error("malformed desktop manifest");
  return man;
}

function readMarker(dir) {
  try { return JSON.parse(fs.readFileSync(path.join(dir, MARKER_NAME), "utf8")); }
  catch { return null; }
}

// null for a fresh/bundled install predating the marker - then the next
// published manifest counts as an update and the state converges.
function installedId(appDist) {
  return (readMarker(appDist) || {}).id || null;
}

async function checkFeed(base, appDist, timeoutMs) {
  const man = await fetchManifest(base, timeoutMs);
  return man.id !== installedId(appDist) ? man : null;
}

function sha256File(fp) {
  return crypto.createHash("sha256").update(fs.readFileSync(fp)).digest("hex");
}

// Download every manifest file into pending, verifying each sha256; the
// marker is written LAST so a torn dir is never swappable.
async function stage(base, manifest, pending) {
  if ((readMarker(pending) || {}).id === manifest.id && verifyStaged(pending)) return;
  fs.rmSync(pending, { recursive: true, force: true });
  fs.mkdirSync(pending, { recursive: true });
  for (const spec of manifest.files) {
    const rel = normRel(spec.path);
    if (!rel) throw new Error("manifest path rejected: " + spec.path);
    const blob = await fetchBuf(assetUrl(base, rel, String(manifest.id).slice(0, 13)));
    if (crypto.createHash("sha256").update(blob).digest("hex") !== spec.sha256) {
      throw new Error("sha256 mismatch for " + rel);
    }
    const dst = path.join(pending, ...rel.split("/"));
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.writeFileSync(dst, blob);
  }
  fs.writeFileSync(path.join(pending, MARKER_NAME), JSON.stringify(manifest));
}

function verifyStaged(pending) {
  const man = readMarker(pending);
  if (!man || !man.id || !Array.isArray(man.files) || !man.files.length) return false;
  try {
    for (const spec of man.files) {
      const rel = normRel(spec.path);
      if (!rel) return false;
      const fp = path.join(pending, ...rel.split("/"));
      if (!fs.existsSync(fp) || sha256File(fp) !== spec.sha256) return false;
    }
  } catch { return false; }
  return true;
}

// Swap the verified staged bundle in, keeping the previous one as .old.
function applyStaged(appDist, pending) {
  if (!verifyStaged(pending)) throw new Error("staged dir failed verification - not applying");
  const old = appDist + ".old";
  fs.rmSync(old, { recursive: true, force: true });
  if (fs.existsSync(appDist)) fs.renameSync(appDist, old);
  fs.renameSync(pending, appDist);
}

// The long-lived updater the Electron main process runs. All checks are the
// silent/automatic intent: failures are logged and retried, never dialogs.
function createUpdater({ feedBase, appDistDir, log }) {
  const pending = appDistDir + ".pending";
  const say = (m) => { try { log("update", m + "\n"); } catch { /* never fatal */ } };
  let timer = null, busy = false, pendingRetry = false;

  async function cycle() {
    if (busy) return;
    busy = true;
    try {
      const man = await checkFeed(feedBase, appDistDir);
      if (!man) {
        if ((readMarker(pending) || {}).id === installedId(appDistDir)) {
          fs.rmSync(pending, { recursive: true, force: true });
        }
        pendingRetry = false;
        return;
      }
      say("version " + (man.version || "?") + " (" + String(man.id).slice(0, 8) + ") found - downloading");
      await stage(feedBase, man, pending);
      pendingRetry = false;
      say("downloaded + verified - will be applied silently on quit (Paseo install-on-quit)");
    } catch (e) {
      // Paseo: "[DesktopUpdater] Silent update check failed" - log only, and
      // while an update is mid-download re-check on the 10s cadence.
      pendingRetry = true;
      say("silent update check failed: " + (e && e.message ? e.message : e));
    } finally {
      busy = false;
      schedule();
    }
  }

  function schedule() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(cycle, pendingRetry ? PENDING_RECHECK_MS : CHECK_INTERVAL_MS);
    if (timer.unref) timer.unref();
  }

  return {
    // Crash-path/tray-staged catch-up: a verified staged bundle is applied
    // before the local web server starts, so the window always loads the
    // freshest bundle (the launch half of expo-updates' behaviour the phone
    // already has; electron-updater equally finishes a missed install at the
    // next opportunity).
    applyStagedAtStartup() {
      try {
        if (fs.existsSync(pending) && verifyStaged(pending)
            && (readMarker(pending) || {}).id !== installedId(appDistDir)) {
          applyStaged(appDistDir, pending);
          say("staged update applied at startup");
          return true;
        }
      } catch (e) { say("startup apply skipped: " + e.message); }
      return false;
    },

    start() { void cycle(); },

    hasStage() { return Boolean((readMarker(pending) || {}).id); },

    // Paseo installUpdateOnQuit: revalidate the manifest against the feed
    // first (a superseded download must not install), bounded by the 5s
    // deadline; unreachable feed -> defer, the staged dir keeps for later.
    async applyOnQuit() {
      const t0 = Date.now();
      try {
        const man = await fetchManifest(feedBase, UPDATE_QUIT_DEADLINE_MS - 500);
        const stagedId = (readMarker(pending) || {}).id;
        if (!stagedId || man.id === installedId(appDistDir)) return false;
        if (man.id !== stagedId) {
          say("staged update superseded - a newer one will be installed later");
          fs.rmSync(pending, { recursive: true, force: true });
          return false;
        }
        if (Date.now() - t0 > UPDATE_QUIT_DEADLINE_MS) return false;
        applyStaged(appDistDir, pending);
        say("update applied on quit - next launch runs " + (man.version || man.id));
        return true;
      } catch (e) {
        say("quit-time update validation failed - deferred: " + e.message);
        return false;
      }
    },
  };
}

module.exports = {
  CHECK_INTERVAL_MS, PENDING_RECHECK_MS, UPDATE_QUIT_DEADLINE_MS,
  MANIFEST_NAME, MARKER_NAME, CHANNEL,
  normRel, readRelayUrl, fetchManifest, readMarker, installedId, checkFeed,
  stage, verifyStaged, applyStaged, createUpdater,
};
