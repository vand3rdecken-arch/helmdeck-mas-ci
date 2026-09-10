// Web-only global CSS the RN style system can't express: thin custom scrollbars
// (matching the archived web app's `::-webkit-scrollbar{width:8px}` look), font
// smoothing, killing the outer document scrollbar so only inner ScrollViews
// scroll (no double bars), and `color-scheme: dark` so NATIVE widget internals
// (select/date popups, scrollbar chrome) follow the dark shell - the archived
// web app carried the same rule at :root. Injected once; renders nothing.
// No-op on native.
//
// Also: `forced-color-adjust: none` on elements opting in via
// `dataSet={{ hcGuard: "" }}` (-> data-hc-guard). Chromium (= Electron too)
// repaints filled buttons to OS colors once a Windows contrast theme is on,
// overriding our own background AND the hardcoded white button text - a
// colored button can collapse into a plain white bar with invisible text
// (Windows Settings > Accessibility > Contrast themes; distinct from
// light/dark mode). `none` keeps our colors; `forced-colors` still gets a
// visible outline so the element never becomes a borderless flat area even
// if `none` itself gets ignored.
import { useEffect } from "react";
import { Platform } from "react-native";
import { tokens } from "@/theme/tokens";

const t = tokens.dark;
const CSS = `
html, body, #root { height: 100%; margin: 0; background: ${t.canvas}; overflow: hidden; color-scheme: dark; }
* { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
* { scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.16) transparent; }
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.16); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.28); }
::-webkit-scrollbar-corner { background: transparent; }
[data-hc-guard] { forced-color-adjust: none; }
@media (forced-colors: active) { [data-hc-guard] { outline: 1px solid ButtonText; outline-offset: -1px; } }
`;

export function WebStyles() {
  useEffect(() => {
    if (Platform.OS !== "web" || typeof document === "undefined") return;
    const el = document.createElement("style");
    el.setAttribute("data-helmdeck", "webstyles");
    el.textContent = CSS;
    document.head.appendChild(el);
    return () => { el.remove(); };
  }, []);
  return null;
}
