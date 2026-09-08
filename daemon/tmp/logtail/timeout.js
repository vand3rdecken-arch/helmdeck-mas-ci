/* Mirrors claudeTask's bounded-spawn pattern: a child that never exits on its
   own must still resolve the promise, once, and reasonably promptly. */
const { spawn } = require("child_process");

/* killTree, verbatim from setup.js */
function killTree(p) {
  try {
    if (process.platform === "win32" && p && p.pid) {
      spawn("taskkill", ["/pid", String(p.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
    } else if (p) {
      p.kill();
    }
  } catch { /* already gone */ }
}

function boundedSpawn(timeoutMs, useShell) {
  return new Promise((resolve) => {
    const started = Date.now();
    let resolves = 0;
    const done = (v) => { resolves++; resolve({ v, ms: Date.now() - started, resolves }); };
    /* a child that sits forever, like a parked agent */
    const p = useShell
      ? spawn("ping", ["-n", "60", "127.0.0.1"], { shell: true, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] })
      : spawn(process.execPath, ["-e", "setTimeout(()=>{},600000)"], { windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      killTree(p);
    }, timeoutMs);
    p.on("close", (code) => { clearTimeout(timer); done(!timedOut && code === 0); });
    p.on("error", () => { clearTimeout(timer); done(false); });
  });
}

(async () => {
  let fails = 0;
  const check = (c, m) => { console.log((c ? "  ok    " : "  FAIL  ") + m); if (!c) fails++; };

  const a = await boundedSpawn(1500, false);
  check(a.v === false, "no-shell: resolves false on timeout");
  check(a.ms < 6000, "no-shell: returns promptly (" + a.ms + "ms, not hung)");
  check(a.resolves === 1, "no-shell: resolved exactly once");

  const b = await boundedSpawn(1500, true);
  check(b.v === false, "shell fallback: resolves false on timeout");
  check(b.ms < 6000, "shell fallback: returns promptly (" + b.ms + "ms, not hung)");

  console.log(fails ? "\nFAILED: " + fails : "\nall checks passed - onboarding cannot hang here");
  process.exit(fails ? 1 : 0);
})();
