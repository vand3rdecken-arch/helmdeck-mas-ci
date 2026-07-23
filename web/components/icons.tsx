// One consistent stroke icon set (Lucide-style paths) - replaces the emoji
// mix so chips, pipeline nodes and nav all speak the same visual language.
import React from "react";

function I({ children, size = 13, ...rest }: React.SVGProps<SVGSVGElement> & { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor"
      strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" {...rest}>
      {children}
    </svg>
  );
}

/* execution modes */
export const IconBot = (p: { size?: number }) => (
  <I {...p}><rect x="5" y="8" width="14" height="11" rx="2" /><path d="M12 8V4M8 4h8" /><path d="M9 13h.01M15 13h.01" /></I>
);
export const IconPen = (p: { size?: number }) => (
  <I {...p}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></I>
);
export const IconUsers = (p: { size?: number }) => (
  <I {...p}><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" /><circle cx="17.5" cy="9" r="2.5" /><path d="M21.5 19c0-2.6-1.7-4.4-4-4.9" /></I>
);
export const IconCap = (p: { size?: number }) => (
  <I {...p}><path d="M22 9 12 4 2 9l10 5 10-5Z" /><path d="M6 11.5V16c0 1.7 2.7 3 6 3s6-1.3 6-3v-4.5" /></I>
);
export const IconUser = (p: { size?: number }) => (
  <I {...p}><circle cx="12" cy="8" r="4" /><path d="M4.5 20.5c0-4 3.4-6.5 7.5-6.5s7.5 2.5 7.5 6.5" /></I>
);

/* card properties */
export const IconMonitor = (p: { size?: number }) => (
  <I {...p}><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></I>
);
export const IconChain = (p: { size?: number }) => (
  <I {...p}><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.5 1.5" /><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7L12 19" /></I>
);
export const IconCalendar = (p: { size?: number }) => (
  <I {...p}><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M8 3v4M16 3v4M3 10h18" /></I>
);
export const IconBriefcase = (p: { size?: number }) => (
  <I {...p}><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" /><path d="M3 13h18" /></I>
);
export const IconChat = (p: { size?: number }) => (
  <I {...p}><path d="M21 12a8 8 0 0 1-8 8H4l2-3a8 8 0 1 1 15-5Z" /></I>
);
export const IconCheck = (p: { size?: number }) => (
  <I {...p}><path d="M20 6 9 17l-5-5" /></I>
);

/* composer (ported from Paseo's lucide set, drawn in our house style) */
export const IconPaperclip = (p: { size?: number }) => (
  <I {...p}><path d="M21 11.5 12.5 20a5 5 0 0 1-7-7l9-9a3.3 3.3 0 0 1 4.7 4.7l-9 9a1.7 1.7 0 0 1-2.4-2.4l8-8" /></I>
);
export const IconBrain = (p: { size?: number }) => (
  <I {...p}><path d="M9.5 4.5a2.5 2.5 0 0 0-2.4 3.1A2.5 2.5 0 0 0 5 12a2.5 2.5 0 0 0 1.5 4.3A2.5 2.5 0 0 0 9.5 20a2 2 0 0 0 2-2V6a2 2 0 0 0-2-1.5Z" /><path d="M14.5 4.5a2.5 2.5 0 0 1 2.4 3.1A2.5 2.5 0 0 1 19 12a2.5 2.5 0 0 1-1.5 4.3A2.5 2.5 0 0 1 14.5 20a2 2 0 0 1-2-2V6a2 2 0 0 1 2-1.5Z" /></I>
);
export const IconArrowUp = (p: { size?: number }) => (
  <I {...p}><path d="M12 20V5M6 11l6-6 6 6" /></I>
);
export const IconStop = (p: { size?: number }) => (
  <I {...p}><rect x="6" y="6" width="12" height="12" rx="2" /></I>
);
export const IconSliders = (p: { size?: number }) => (
  <I {...p}><path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h8M16 18h4" /><circle cx="16" cy="6" r="2" /><circle cx="8" cy="12" r="2" /><circle cx="14" cy="18" r="2" /></I>
);
export const IconImage = (p: { size?: number }) => (
  <I {...p}><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="8.5" cy="9" r="1.5" /><path d="m21 16-4.5-4.5L5 20" /></I>
);
export const IconFile = (p: { size?: number }) => (
  <I {...p}><path d="M14 3v5h5" /><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /></I>
);
export const IconX = (p: { size?: number }) => (
  <I {...p}><path d="M6 6l12 12M18 6 6 18" /></I>
);
export const IconTerminal = (p: { size?: number }) => (
  <I {...p}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9l3 3-3 3M13 15h4" /></I>
);
export const IconCopy = (p: { size?: number }) => (
  <I {...p}><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></I>
);
export const IconExpand = (p: { size?: number }) => (
  <I {...p}><path d="M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5" /></I>
);
export const IconShrink = (p: { size?: number }) => (
  <I {...p}><path d="M8 3v5H3M21 8h-5V3M3 16h5v5M16 21v-5h5" /></I>
);

/* new-request examples + view switcher + affordances (lucide, house style) */
export const IconBug = (p: { size?: number }) => (
  <I {...p}><path d="M8 6a4 4 0 0 1 8 0" /><rect x="7" y="8" width="10" height="10" rx="5" /><path d="M3 12h4M17 12h4M4 8l3 2M20 8l-3 2M4 17l3-1.5M20 17l-3-1.5M12 8v10" /></I>
);
export const IconSparkle = (p: { size?: number }) => (
  <I {...p}><path d="M12 3l1.8 4.9L18.7 9l-4.9 1.8L12 15.7l-1.8-4.9L5.3 9l4.9-1.1Z" /><path d="M19 15l.7 2 .8-.7-.7 2 " /></I>
);
export const IconGlobe = (p: { size?: number }) => (
  <I {...p}><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.5 2.5 2.5 15 0 18M12 3c-2.5 2.5-2.5 15 0 18" /></I>
);
export const IconSearch = (p: { size?: number }) => (
  <I {...p}><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></I>
);
export const IconChevron = ({ dir = "right", size }: { dir?: "right" | "down" | "up" | "left"; size?: number }) => {
  const rot = { right: 0, down: 90, up: -90, left: 180 }[dir];
  return <I size={size} style={{ transform: `rotate(${rot}deg)` }}><path d="m9 6 6 6-6 6" /></I>;
};
export const IconGear = (p: { size?: number }) => (
  <I {...p}><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M5 5l2 2M17 17l2 2M2 12h3M19 12h3M5 19l2-2M17 7l2-2" /></I>
);
export const IconWarn = (p: { size?: number }) => (
  <I {...p}><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4M12 17h.01" /></I>
);
export const IconFork = (p: { size?: number }) => (
  <I {...p}><circle cx="6" cy="5" r="2.2" /><circle cx="18" cy="5" r="2.2" /><circle cx="12" cy="19" r="2.2" /><path d="M6 7.2v2a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3v-2M12 12.2v4.6" /></I>
);
export const IconUndo = (p: { size?: number }) => (
  <I {...p}><path d="M9 14 4 9l5-5" /><path d="M4 9h11a5 5 0 0 1 0 10h-5" /></I>
);
export const IconPlay = (p: { size?: number }) => (
  <I {...p}><path d="M7 4.5v15l12-7.5Z" /></I>
);
export const IconGrid = (p: { size?: number }) => (
  <I {...p}><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></I>
);
export const IconList = (p: { size?: number }) => (
  <I {...p}><path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01" /></I>
);
export const IconTimeline = (p: { size?: number }) => (
  <I {...p}><path d="M3 5h11M3 12h16M3 19h8" /><circle cx="17" cy="5" r="2" /><circle cx="13" cy="19" r="2" /></I>
);
export const IconTheme = (p: { size?: number }) => (
  <I {...p}><circle cx="12" cy="12" r="9" /><path d="M12 3a9 9 0 0 0 0 18Z" fill="currentColor" stroke="none" /></I>
);

export const MODE_ICONS: Record<string, (p: { size?: number }) => React.ReactElement> = {
  do: IconBot, prepare: IconPen, cowork: IconUsers, teach: IconCap, human: IconUser,
};
export const MODE_LABEL: Record<string, string> = {
  do: "do", prepare: "prepare", cowork: "cowork", teach: "teach", human: "human",
};
export function ModeIcon({ mode, size }: { mode?: string; size?: number }) {
  const C = mode ? MODE_ICONS[mode] : undefined;
  return C ? <C size={size} /> : null;
}
