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
