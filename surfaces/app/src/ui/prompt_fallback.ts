// Some hosts define window.prompt/window.confirm as functions that exist but
// THROW when actually called - Electron's renderer is exactly this case:
// window.prompt is a real function, and calling it throws Electron's own
// "prompt() is not supported" error. `typeof window.prompt === "function"`
// is therefore not proof the call will work; the only way to know is to call
// it and see. No react-native import here on purpose (this direction has to
// stay unit-testable under plain node - see __prompt_fallback_selftest__.ts).

export type HostCallResult<T> = { supported: true; value: T } | { supported: false };

/** Calls `fn`, treating a throw as "this host doesn't really support it" rather
 *  than letting the error surface to the caller. */
export function tryHostCall<T>(fn: () => T): HostCallResult<T> {
  try {
    return { supported: true, value: fn() };
  } catch {
    return { supported: false };
  }
}
