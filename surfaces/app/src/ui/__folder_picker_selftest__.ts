// Repo-path folder-browse button - the self-test the fix needs: proves
// getFolderPicker() (repo_type_picker.tsx's onboarding folder button routes
// through this) is present-and-callable only when the desktop preload bridge
// actually exposes pickFolder, and absent everywhere else (phone/web/Mac,
// or a desktop build old enough not to have shipped the channel yet). Runs
// under plain node after tsc, same convention as
// __prompt_fallback_selftest__.ts:
//   npx tsc -p tsconfig.selftest.json && node ../../.ui-out/__folder_picker_selftest__.js
// (both from surfaces/app/src/ui/). Exits non-zero on the first failed check.

import { getFolderPicker } from "./folder_picker";

let failures = 0;
function ok(cond: boolean, msg: string): void {
  if (cond) console.log(`  ok   - ${msg}`);
  else {
    failures++;
    console.log(`  FAIL - ${msg}`);
  }
}

console.log("folder-picker selftest");

// ---- 1. no bridge at all (phone/web, or plain node with no window global). -
{
  (globalThis as unknown as { window?: unknown }).window = undefined;
  ok(getFolderPicker() === null, "no window.helmdeckNative -> no picker, so the caller hides the button");
}

// ---- 2. desktop bridge present but this channel not shipped yet. ----------
{
  (globalThis as unknown as { window: unknown }).window = { helmdeckNative: {} };
  ok(getFolderPicker() === null, "helmdeckNative present without pickFolder -> still no picker");
}

// ---- 3. the real desktop case: mocked pickFolder is returned AND callable, -
// ---- and its resolved path is exactly what the caller would set into the -
// ---- text field.                                                          -
{
  (globalThis as unknown as { window: unknown }).window = {
    helmdeckNative: { pickFolder: async () => "C:\\Users\\owner\\repo" },
  };
  const picker = getFolderPicker();
  ok(typeof picker === "function", "helmdeckNative.pickFolder present -> a callable picker is returned");
  if (picker) {
    picker().then((path) => {
      ok(path === "C:\\Users\\owner\\repo", "calling the picker resolves the exact path pickFolder returned");
      finish();
    });
  } else {
    finish();
  }
}

function finish(): void {
  console.log();
  if (failures > 0) {
    console.log(`FAILED (${failures})`);
    process.exit(1);
  }
  console.log("all green");
}
