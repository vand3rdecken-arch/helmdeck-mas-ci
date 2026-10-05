// Foreground push display/wake decision - the WhatsApp/Slack fix (owner report
// 2026-09-23: "Push kommt sofort, der offene Chat laedt dieselbe Antwort noch
// per Spinner nach"). Since 2026-09-25 the daemon always sends a Henry reply
// (ops/tests/test_chat_push.py) and the APP alone decides display - this proves
// what it does with a push that lands in the foreground, and that the
// background task stays out of it then.
//
// Runs the REAL src/data/push_present.ts (transpiled with the repo's own
// TypeScript) - not a reimplementation. Import-free, same reason as
// test_push_route.js: no stub tree needed behind it.
//
// Run: node surfaces/app/test_push_present.js

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

const { decideChatPush, backgroundTaskPresents } = loadTsModule(path.join("src", "data", "push_present.ts"), "pushpresent");

console.log("foreground push display/wake decision");

// 1) THE FIX: a Henry reply, owner reading the chat right now -----------------
const reading = decideChatPush("chat", "chat", "chat", true);
ok(reading.present === false,
   "a chat reply is NOT shown as a banner while the owner is looking straight " +
   "at the transcript - the app decides, like WhatsApp/Slack, not the OS");
ok(reading.wake === true,
   "...but it still wakes the chat query, so the open screen pulls the answer " +
   "in immediately instead of waiting out whatever the poll/relay is behind by");

// 2) same reply, chat NOT open -------------------------------------------------
const elsewhere = decideChatPush("chat", null, "chat", true);
ok(elsewhere.present === true, "no one is reading it - show the notification normally");
ok(elsewhere.wake === true, "still a wake-up - the transcript should be fresh the moment he opens it");

// 3) chat open, but the app is BACKGROUNDED (a stale in-memory focus value) --
const backgrounded = decideChatPush("chat", "chat", "chat", false);
ok(backgrounded.present === true,
   "focusedCard can outlive the app going to background - appActive is what " +
   "makes 'reading it right now' true, not a leftover screen id");

// 4) a different screen is focused --------------------------------------------
const otherScreen = decideChatPush("chat", "some-card-id", "chat", true);
ok(otherScreen.present === true, "a card screen open is not the chat - show it");

// 5) a non-chat push (card question/done/etc.) is untouched -------------------
const card = decideChatPush("question", "chat", "chat", true);
ok(card.present === true && card.wake === false,
   "a card push is never suppressed and never treated as a chat wake-up, " +
   "even while the chat happens to be the focused screen");

// 6) the BACKGROUND task must stay out while the app is in the foreground -----
// expo-notifications 57 runs it on EVERY FCM message, foreground included, and
// it presented unconditionally: a Henry reply buzzed the phone showing the chat
// (owner report 2026-09-25). The foreground listener owns display there.
ok(backgroundTaskPresents("active") === false,
   "app in the foreground: the background task does NOT raise the banner - " +
   "the received-listener (decideChatPush) is the one owner of display");
ok(backgroundTaskPresents("background") === true,
   "app backgrounded: the task presents - no listener runs there");
ok(backgroundTaskPresents(null) === true && backgroundTaskPresents(undefined) === true,
   "headless start (killed app, no AppState yet): the task presents");

// 7) TEAM-ROOM pushes ---------------------------------------------------------
const roomElsewhere = decideChatPush("room", null, "chat", true, "r1");
ok(roomElsewhere.wake === true && roomElsewhere.present === true,
   "a room push while you are elsewhere wakes the queries and shows the banner");
const roomReading = decideChatPush("room", "room:r1", "chat", true, "r1");
ok(roomReading.wake === true && roomReading.present === false,
   "reading THAT room: it still wakes, but no banner over the room you are in");
const otherRoom = decideChatPush("room", "room:r2", "chat", true, "r1");
ok(otherRoom.present === true, "reading ANOTHER room does not suppress it");
const roomBg = decideChatPush("room", "room:r1", "chat", false, "r1");
ok(roomBg.present === true, "app backgrounded: shown even if the room was the last focus");
const chatStillSame = decideChatPush("chat", "chat", "chat", true);
ok(chatStillSame.wake === true && chatStillSame.present === false,
   "the Henry chat rule is unchanged by the optional room argument");

console.log();
if (fails.length) {
  console.log(`FAILED (${fails.length}):`);
  fails.forEach((f) => console.log("  - " + f));
  process.exit(1);
}
console.log("all foreground push display/wake checks passed");
