// Where a TAPPED notification lands - the client half of the Henry reply push
// (owner report 2026-08-29 18:09: "Henrys Chat-Antworten loesen KEINE
// Notification aus"). The daemon half is pinned by ops/tests/test_chat_push.py,
// which proves the sealed payload the phone decrypts carries kind="chat" and an
// empty track; this proves what the app then DOES with those two fields.
//
// Runs the REAL src/data/push_route.ts (transpiled with the repo's own
// TypeScript) - not a reimplementation. push_route.ts is import-free precisely
// so this test needs no stub tree behind it.
//
// Run: node surfaces/app/test_push_route.js

const fs = require("fs");
const path = require("path");
const os = require("os");

const APP = __dirname;
const ROOT = path.dirname(path.dirname(APP));

function loadTs() {
  for (const p of [path.join(APP, "node_modules", "typescript"),
                   path.join(ROOT, ".tscheck", "node_modules", "typescript")]) {
    try { return require(p); } catch { /* try the next one */ }
  }
  console.error("typescript not found - run npm install in surfaces/app");
  process.exit(2);
}
const ts = loadTs();

const fails = [];
function ok(cond, msg) {
  console.log((cond ? "  ok   - " : "  FAIL - ") + msg);
  if (!cond) fails.push(msg);
}

function loadTsModule(relPath, tag) {
  const src = fs.readFileSync(path.join(APP, relPath), "utf8");
  const js = ts.transpileModule(src, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    fileName: path.basename(relPath),
  }).outputText;
  const out = path.join(os.tmpdir(), `helmdeck-${tag}-test.js`);
  fs.writeFileSync(out, js);
  delete require.cache[out];
  return require(out);
}

const { pushRoute } = loadTsModule(path.join("src", "data", "push_route.ts"), "pushroute");

console.log("push tap routing");

// 1) THE FIX: a Henry answer lands in the Henry chat -------------------------
const chat = pushRoute({ track: "", kind: "chat", body: "Der Deploy laeuft." });
ok(chat && chat.pathname === "/chat",
   "kind='chat' (a finished Henry turn) opens the Henry chat");
ok(chat && !chat.params,
   "...plainly - no vq param, so it does NOT drop into voice mode and start " +
   "talking at whoever is standing next to him");

// and it must not be mistaken for the trackless PM case, which is the branch it
// used to fall through to
const pm = pushRoute({ track: "", kind: "" , body: "x" });
ok(pm === null,
   "a tap with neither field is UNREADABLE and navigates nowhere - Android's " +
   "bundled-summary tap used to land on the dashboard over an open card");
const goal = pushRoute({ track: "", kind: "pmAlert" });
ok(goal && goal.pathname === "/(tabs)",
   "a readable push about no card (goal-level PM escalation) still goes to " +
   "the dashboard - the fix did not steal that fallback");

// 2) card pushes are untouched ----------------------------------------------
const card = pushRoute({ track: "c-7", kind: "question" });
ok(card && card.pathname === "/card/[id]" && card.params.id === "c-7"
   && card.params.tab === "chat",
   "a card question still deep-links into THAT card's chat tab");
const bounced = pushRoute({ track: "c-8", kind: "bounced" });
ok(bounced && bounced.params.id === "c-8", "...and so does a bounce");

const done = pushRoute({ track: "c-9", kind: "done", body: "Karte fertig  [c-9]" });
ok(done && done.pathname === "/chat" && !(done.params && done.params.vq),
   "a DONE push opens the board chat, where the card's result already sits " +
   "(c50097e8), and NO longer injects a synthetic spoken question in the " +
   "owner's name (owner 2026-09-19: 'macht das weg')");

// 3) the shapes the daemon can actually emit ---------------------------------
// notify.chat_reply sends track="" (never null/undefined) and every card push
// sends a real id; both must route, and neither may throw on a missing body.
ok(pushRoute({ kind: "chat" }).pathname === "/chat",
   "an absent track routes like an empty one - the app reads the field from a " +
   "local notification's data map, where a missing key is undefined");
ok(pushRoute({ track: "c-1", kind: "done" }).pathname === "/chat",
   "a DONE push with no body still lands in the chat and does not throw");

console.log();
if (fails.length) {
  console.log(`FAILED (${fails.length}):`);
  fails.forEach((f) => console.log("  - " + f));
  process.exit(1);
}
console.log("all push-tap-routing checks passed");
