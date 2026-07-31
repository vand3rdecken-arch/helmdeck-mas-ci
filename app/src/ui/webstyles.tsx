// Web-only global CSS the RN style system can't express: thin custom scrollbars
// (matching the archived web app's `::-webkit-scrollbar{width:8px}` look), font
// smoothing, and killing the outer document scrollbar so only inner ScrollViews
// scroll (no double bars). Injected once; renders nothing. No-op on native.
import { useEffect } from "react";
import { Platform } from "react-native";
import { tokens } from "@/theme/tokens";

const t = tokens.dark;
const CSS = `
html, body, #root { height: 100%; margin: 0; background: ${t.canvas}; overflow: hidden; }
* { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
* { scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.16) transparent; }
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.16); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.28); }
::-webkit-scrollbar-corner { background: transparent; }
`;

export function WebStyles() {
  useEffect(() => {
    if (Platform.OS !== "web" || typeof document === "undefined") return;
    const el = document.createElement("style");
    el.setAttribute("data-swarmdeck", "webstyles");
    el.textContent = CSS;
    document.head.appendChild(el);
    return () => { el.remove(); };
  }, []);
  return null;
}
