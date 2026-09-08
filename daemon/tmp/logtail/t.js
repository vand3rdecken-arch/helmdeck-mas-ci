const fs = require("fs");
const os = require("os");
const path = require("path");
const { daemonLogTail } = require("../../../surfaces/desktop/setup.js");

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "hd-logtail-"));
let fails = 0;
const check = (cond, msg) => { console.log((cond ? "  ok    " : "  FAIL  ") + msg); if (!cond) fails++; };

/* empty dir */
check(daemonLogTail(dir).length === 0, "missing log -> empty, no throw");

/* canonical log */
fs.writeFileSync(path.join(dir, "daemon.out.log"),
  "starting\n\nTraceback (most recent call last):\n  File \"swarm.py\", line 1\nOSError: port in use\n");
let t = daemonLogTail(dir);
check(t.length === 4, "blank lines dropped (got " + t.length + ")");
check(t[t.length - 1] === "OSError: port in use", "last line is the real error");

/* pid-fallback log, NEWER - main.js writes this when the canonical file is pinned */
const pidLog = path.join(dir, "daemon.out.4242.log");
fs.writeFileSync(pidLog, "newer run\nModuleNotFoundError: No module named 'daemon'\n");
const future = new Date(Date.now() + 60000);
fs.utimesSync(pidLog, future, future);
t = daemonLogTail(dir);
check(t[t.length - 1] === "ModuleNotFoundError: No module named 'daemon'", "newest log wins over canonical");

/* unrelated files ignored */
fs.writeFileSync(path.join(dir, "daemon.out.log.bak"), "IGNORE ME\n");
fs.utimesSync(path.join(dir, "daemon.out.log.bak"), future, future);
t = daemonLogTail(dir);
check(!t.join("\n").includes("IGNORE ME"), "daemon.out.log.bak is not picked up");

/* tail bound */
fs.writeFileSync(pidLog, Array.from({ length: 100 }, (_, i) => "line" + i).join("\n") + "\n");
fs.utimesSync(pidLog, future, future);
t = daemonLogTail(dir, 12);
check(t.length === 12 && t[11] === "line99", "tail is bounded to n and keeps the END");

fs.rmSync(dir, { recursive: true, force: true });
console.log(fails ? "\nFAILED: " + fails : "\nall checks passed");
process.exit(fails ? 1 : 0);
