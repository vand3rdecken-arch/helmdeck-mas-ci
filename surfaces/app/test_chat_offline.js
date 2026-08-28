// Repro + regression for the two chat defects the owner reported 2026-08-28:
//
//   1) Henry's messages are shown cut off MID-WORD. The client half of that is
//      clampText() in ui/card_transcript.tsx, which sliced at a raw char offset
//      and (on the markdown path) left no marker at all, so a folded message was
//      indistinguishable from one that simply ended there.
//
//   2) With no internet the owner's message is GONE - no error, no bubble. The
//      composer clears its input (and its persisted draft) in the same tick it
//      fires the request, and the optimistic echo lives only in component state,
//      so it dies with the screen. data/outbox.ts is what makes a failed send
//      survive that.
//
// Runs the REAL src/data/outbox.ts (transpiled with the repo's own TypeScript,
// AsyncStorage stubbed) and the REAL clampText source - not reimplementations.
//
// Run: node surfaces/app/test_chat_offline.js

const fs = require("fs");
const path = require("path");
const os = require("os");
const Module = require("module");

const APP = __dirname;
const ROOT = path.dirname(path.dirname(APP));

// typescript lives in the app's node_modules normally; a worktree that only has
// a standalone compiler installed (ops verification) keeps it under .tscheck.
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

// --- fake AsyncStorage: the durable half, in memory ------------------------
let store = new Map();
const STUBS = {
  "@react-native-async-storage/async-storage": {
    __esModule: true,
    default: {
      getItem: async (k) => (store.has(k) ? store.get(k) : null),
      setItem: async (k, v) => { store.set(k, v); },
      removeItem: async (k) => { store.delete(k); },
    },
  },
};
const origResolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
  if (Object.prototype.hasOwnProperty.call(STUBS, request)) return "STUB:" + request;
  return origResolve.call(this, request, ...rest);
};
const origLoad = Module._load;
Module._load = function (request, ...rest) {
  if (Object.prototype.hasOwnProperty.call(STUBS, request)) return STUBS[request];
  return origLoad.call(this, request, ...rest);
};

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

// clampText is pure (no imports), so it is lifted out of the TSX by source
// rather than dragging the whole React Native tree in behind it.
function loadClampText() {
  const src = fs.readFileSync(
    path.join(APP, "src", "ui", "card_transcript.tsx"), "utf8");
  const start = src.indexOf("const COLLAPSE_LINES");
  const endMark = "\nfunction Collapsible(";
  const end = src.indexOf(endMark, start);
  if (start < 0 || end < 0) {
    console.error("could not locate clampText in card_transcript.tsx");
    process.exit(2);
  }
  const chunk = src.slice(start, end)
    .replace(/export function clampText/, "function clampText");
  const js = ts.transpileModule(chunk, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    fileName: "clamp.ts",
  }).outputText;
  // eslint-disable-next-line no-new-func
  return new Function(`${js}; return { clampText, COLLAPSE_CHARS, COLLAPSE_LINES };`)();
}

async function main() {
  // =========================================================================
  console.log("1) a long reply is folded on a WORD boundary, never mid-word");
  const { clampText, COLLAPSE_CHARS } = loadClampText();

  // A word is split exactly when the cut has a word character on BOTH sides.
  // (A cut that lands just after a space is fine - nothing was broken.)
  const splitsAWord = (text, cut) =>
    cut > 0 && cut < text.length && /\S/.test(text[cut - 1]) && /\S/.test(text[cut]);

  // Deliberately offset so the raw 1600-char slice lands INSIDE a word: the
  // 3-char prefix pushes every following 8-char "geprue " cell out of phase
  // with COLLAPSE_CHARS. Without the offset the old code happened to cut on a
  // space and the bug hid.
  const TAIL = "und melde mich sobald der Deploy gruen ist - geprueft (98243a6) ✓";
  const long = "ich" + " pruefen".repeat(400) + " " + TAIL;
  ok(long.length > COLLAPSE_CHARS, "fixture is long enough to overflow the clamp");
  ok(splitsAWord(long, COLLAPSE_CHARS),
     "fixture is built so a RAW slice would split a word (that was the bug)");

  const { clamped, overflow } = clampText(long);
  ok(overflow === true, "overflow is reported so the show-more toggle appears");
  ok(clamped.length <= COLLAPSE_CHARS, "clamped text respects the char budget");

  // THE regression.
  ok(!splitsAWord(long, clamped.length),
     `the cut does not split a word (…${JSON.stringify(long.slice(clamped.length - 6, clamped.length + 4))})`);
  ok(long.startsWith(clamped), "the clamped text is a real prefix of the message");

  // a short message is returned untouched
  const short = clampText("kurz und vollstaendig");
  ok(short.overflow === false && short.clamped === "kurz und vollstaendig",
     "a short message is never clamped and never marked as overflowing");

  // a single unbreakable token (URL/hash) still gets cut - honestly, not never
  const blob = "x".repeat(COLLAPSE_CHARS * 2);
  const b = clampText(blob);
  ok(b.overflow === true && b.clamped.length > 0,
     "an unbreakable blob still clamps (no sensible boundary exists, so it cuts)");

  // line-count overflow keeps working
  const many = Array.from({ length: 40 }, (_, i) => `Zeile ${i}`).join("\n");
  ok(clampText(many).overflow === true, "a 40-line message overflows on line count");

  // =========================================================================
  console.log("\n2) a send that never reached the daemon survives on disk");
  store = new Map();
  const outbox = loadTsModule(path.join("src", "data", "outbox.ts"), "outbox");

  ok((await outbox.pending("board")).length === 0, "outbox starts empty");

  // the owner types, hits send, and the phone has no internet
  const msg = "Henry, bitte deploy die Karte " + "und pruefe den Gate-Report ".repeat(30);
  const row = await outbox.park("board", msg, { model: "auto", to: "henry" },
                                "Direktverbindung (LAN) fehlgeschlagen", 1000);
  ok(!!row.id, "park returns a stored row with an id");

  const p1 = await outbox.pending("board");
  ok(p1.length === 1, "the failed message is queued, not lost");
  ok(p1[0].text === msg,
     "the FULL message text survived - including a body longer than SecureStore's ~2KB ceiling");
  ok(p1[0].error.includes("LAN"), "the reason it failed is kept, to show next to it");
  ok(p1[0].tries === 1, "first attempt counted");

  // THE regression: it must survive the screen being destroyed. A fresh module
  // instance = a remount / app restart reading the same storage.
  const outbox2 = loadTsModule(path.join("src", "data", "outbox.ts"), "outbox2");
  const afterRemount = await outbox2.pending("board");
  ok(afterRemount.length === 1 && afterRemount[0].text === msg,
     "the message is still there after a remount - THIS is the bug that lost it");

  // scoping: a card chat's queue is its own
  await outbox.park("card:abc", "worker, mach weiter", {}, "offline", 1001);
  ok((await outbox.pending("board")).length === 1, "board queue unaffected by a card send");
  ok((await outbox.pending("card:abc")).length === 1, "the card has its own queue");

  console.log("\n   retry fails again -> kept, attempt counted");
  await outbox.retried(row.id, "Relay nicht erreichbar");
  const p2 = await outbox.pending("board");
  ok(p2.length === 1, "a failed retry does NOT duplicate the message");
  ok(p2[0].tries === 2, "the attempt was counted");
  ok(p2[0].error.includes("Relay"), "the newest reason replaced the old one");

  console.log("\n   retry succeeds -> and only THEN is it dropped");
  await outbox.settle(row.id);
  ok((await outbox.pending("board")).length === 0,
     "a delivered message leaves the queue");
  ok((await outbox.pending("card:abc")).length === 1,
     "settling one message did not touch the other surface");

  console.log("\n   attachments are not persisted (base64 blobs), scalars are");
  const withAtt = await outbox.park(
    "board", "mit Bild", { model: "opus", thinking: "high", to: "henry",
                           attachments: [{ name: "a.png", data: "x".repeat(5000) }] },
    "offline", 1002);
  ok(withAtt.opts.attachments === undefined, "attachments dropped rather than silently retried");
  ok(withAtt.opts.model === "opus" && withAtt.opts.thinking === "high"
     && withAtt.opts.to === "henry", "model/thinking/to survive for the retry");
  const raw = store.get("helmdeck.outbox.v1") || "";
  ok(!raw.includes("x".repeat(5000)), "the blob really is not on disk");

  console.log("\n   discard throws it away");
  await outbox.discard(withAtt.id);
  ok((await outbox.pending("board")).length === 0, "discarded message is gone");

  console.log("\n   simultaneous failures do not overwrite each other");
  // Two sends failing at once is the realistic case (board + card, or a retry
  // racing a fresh park) and a naive read-modify-write loses one of them.
  store = new Map();
  const ob3 = loadTsModule(path.join("src", "data", "outbox.ts"), "outbox3");
  await Promise.all([
    ob3.park("board", "erste", {}, "offline", 2001),
    ob3.park("board", "zweite", {}, "offline", 2002),
    ob3.park("card:z", "dritte", {}, "offline", 2003),
  ]);
  const b3 = await ob3.pending("board");
  ok(b3.length === 2, `both concurrent board messages survived (got ${b3.length})`);
  ok((await ob3.pending("card:z")).length === 1, "the concurrent card message survived too");

  console.log("\n   the strip learns of changes at event time, not by polling");
  let notified = 0;
  const unsub = outbox.subscribe(() => { notified += 1; });
  const r2 = await outbox.park("board", "noch eine", {}, "offline", 1003);
  ok(notified === 1, "park notifies subscribers");
  await outbox.retried(r2.id, "immer noch offline");
  ok(notified === 2, "retried notifies subscribers");
  await outbox.settle(r2.id);
  ok(notified === 3, "settle notifies subscribers");
  unsub();
  await outbox.park("board", "danach", {}, "offline", 1004);
  ok(notified === 3, "unsubscribe really detaches (no leak on unmount)");

  console.log("");
  if (fails.length) {
    console.log(`=== ${fails.length} FAILED ===`);
    process.exit(1);
  }
  console.log("chat-offline + clamp: all pinned - PASS");
}

main().catch((e) => { console.error(e); process.exit(1); });
