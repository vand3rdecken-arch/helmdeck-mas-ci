// Driven by ops/tests/test_desktop_update.py: exercises the REAL Electron-side
// engine (surfaces/desktop/updater.js) against the REAL relay the python test started.
//   node desktop_updater_harness.cjs <feedBase> <appDistDir>
// Steps: checkFeed -> stage -> verifyStaged -> applyStaged, then the Paseo
// quit rule against a dead feed (revalidation unreachable -> defer, keep the
// staged dir), then the DEFAULT_FEED fallback (missing/empty relay_feed.json
// -> public relay; a configured relay still wins). Prints one JSON line the
// python side asserts on.
const os = require("os");
const path = require("path");
const fs = require("fs");
const up = require(path.join(__dirname, "..", "..", "surfaces", "desktop", "updater.js"));

const [feedBase, appDist] = process.argv.slice(2);
const pending = appDist + ".pending";

// effectiveFeed() mirrors exactly what main.js/tray.py do at startup.
function effectiveFeed(feedPath) { return up.readRelayUrl(feedPath) || up.DEFAULT_FEED; }

(async () => {
  const man = await up.checkFeed(feedBase, appDist);
  if (!man) throw new Error("expected an update on a fresh app-dist");
  await up.stage(feedBase, man, pending);
  if (!up.verifyStaged(pending)) throw new Error("staged dir failed verification");
  up.applyStaged(appDist, pending);

  const again = await up.checkFeed(feedBase, appDist);

  // quit-path deferral: staged update + unreachable feed must NOT install
  await up.stage(feedBase, { ...man, id: "fake-newer-id", files: man.files }, pending);
  const dead = up.createUpdater({ feedBase: "http://127.0.0.1:9", appDistDir: appDist, log: () => {} });
  const installedOnQuit = await dead.applyOnQuit();

  // DEFAULT_FEED fallback: missing file, empty url, and a configured url.
  const feedTmp = fs.mkdtempSync(path.join(os.tmpdir(), "hd-feed-"));
  const missingFeed = path.join(feedTmp, "missing.json");
  const emptyFeed = path.join(feedTmp, "empty.json");
  fs.writeFileSync(emptyFeed, JSON.stringify({ url: "" }));
  const setFeed = path.join(feedTmp, "set.json");
  fs.writeFileSync(setFeed, JSON.stringify({ url: "https://relay.example/  " }));

  const feedFallback = {
    defaultFeedIsHelmdeckRelay: up.DEFAULT_FEED === "https://relay.helmdeck.de",
    missingFileUsesDefault: effectiveFeed(missingFeed) === "https://relay.helmdeck.de",
    emptyUrlUsesDefault: effectiveFeed(emptyFeed) === "https://relay.helmdeck.de",
    configuredUrlWinsOverDefault: effectiveFeed(setFeed) === "https://relay.example",
  };
  fs.rmSync(feedTmp, { recursive: true, force: true });

  console.log(JSON.stringify({
    installedId: up.installedId(appDist),
    manifestId: man.id,
    upToDateAfterApply: again === null,
    deferredOnDeadFeed: installedOnQuit === false && fs.existsSync(pending),
    feedFallback,
  }));
})().catch((e) => { console.error(e.message); process.exit(1); });
