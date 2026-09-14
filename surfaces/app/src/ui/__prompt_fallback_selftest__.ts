// Electron prompt() crash fix - the self-test the fix needs: proves
// tryHostCall (the function promptText/confirmAsync in settings_sections.tsx
// now route through before trusting window.prompt/window.confirm) treats a
// THROW as "unsupported", not just absence. Before this fix, settings_sections
// called window.prompt(...) directly and let a throw propagate uncaught -
// exactly Electron's crash ("Uncaught (in promise) Error: prompt() is not
// supported"), because Electron's window.prompt is a real function that
// throws when called; `typeof window.prompt === "function"` alone can't see
// that. Runs under plain node after tsc, same convention as
// kernel/__caps_selftest__.ts:
//   npx tsc -p tsconfig.selftest.json && node ../../.ui-out/__prompt_fallback_selftest__.js
// (both from surfaces/app/src/ui/). Exits non-zero on the first failed check.

import { tryHostCall } from "./prompt_fallback";

let failures = 0;
function ok(cond: boolean, msg: string): void {
  if (cond) console.log(`  ok   - ${msg}`);
  else {
    failures++;
    console.log(`  FAIL - ${msg}`);
  }
}

console.log("prompt-fallback selftest");

// ---- 1. a host function that works: value passes through, marked supported.
{
  const r = tryHostCall(() => "typed value");
  ok(r.supported === true && r.value === "typed value",
    "a function that returns normally is reported as supported, with its value");
}

// ---- 2. Electron's actual failure mode: a function that EXISTS but THROWS. -
{
  const electronWindowPrompt = (): string | null => {
    throw new Error("prompt() is not supported");
  };
  let escaped = false;
  let r: ReturnType<typeof tryHostCall> | undefined;
  try {
    r = tryHostCall(electronWindowPrompt);
  } catch {
    escaped = true;
  }
  ok(!escaped, "the throw from Electron's window.prompt does NOT escape tryHostCall (this is the crash the fix removes)");
  ok(!!r && r.supported === false,
    "a function that throws is reported as unsupported, so the caller falls back instead of crashing");
}

// ---- 3. a legitimate falsy/null return (user cancelled a real prompt) must -
// ---- NOT be confused with "the call was unsupported".                    --
{
  const r = tryHostCall(() => null);
  ok(r.supported === true && r.value === null,
    "a normal null return (user pressed Cancel) still counts as supported, not as a failure");
}

// ---- 4. same contract for window.confirm's boolean return. ----------------
{
  const okResult = tryHostCall(() => false);
  ok(okResult.supported === true && okResult.value === false,
    "confirm() returning false (user declined) is supported, not a failure");

  const throwing = tryHostCall((): boolean => { throw new Error("confirm() is not supported"); });
  ok(throwing.supported === false, "a throwing confirm() is reported as unsupported, same fallback style as prompt");
}

console.log();
if (failures > 0) {
  console.log(`FAILED (${failures})`);
  process.exit(1);
}
console.log("all green");
