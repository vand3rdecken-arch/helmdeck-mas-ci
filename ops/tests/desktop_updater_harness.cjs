// Driven by ops/tests/test_desktop_update.py: exercises the REAL Electron-side
// engine (surfaces/desktop/updater.js) against the REAL relay the python test started.
//   node desktop_updater_harness.cjs <feedBase> <appDistDir>
// Steps: checkFeed -> stage -> verifyStaged -> applyStaged, then the Paseo
// quit rule against a dead feed (revalidation unreachable -> defer, keep the
// staged dir). Prints one JSON line the python side asserts on.
const path = require("path");
const fs = require("fs");
const up = require(path.join(__dirname, "..", "desktop", "updater.js"));

const [feedBase, appDist] = process.argv.slice(2);
const pending = appDist + ".pending";

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

  console.log(JSON.stringify({
    installedId: up.installedId(appDist),
    manifestId: man.id,
    upToDateAfterApply: again === null,
    deferredOnDeadFeed: installedOnQuit === false && fs.existsSync(pending),
  }));
})().catch((e) => { console.error(e.message); process.exit(1); });
