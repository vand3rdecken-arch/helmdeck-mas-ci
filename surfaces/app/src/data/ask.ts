// The <helmdeck-ask> sentinel, as far as the APP is allowed to know it.
//
// spine/ops/ask.py owns this grammar and is the only thing that PARSES it. The
// block is removed at its one owner, at event time, on every path that produces
// one (cells/copilot/copilot.chat for Henry, cells/engineer/turnrunner for a
// card worker, plus the live readers in spine/agent/claude_sessions). What lives
// here is strictly the net under all of them.
//
// It STRIPS and never parses. Reading the JSON here to build options would put a
// second copy of the protocol on the phone, and the two would drift the first
// time either side changed - so a block that reaches this module is shown as
// nothing at all. That is also the wanted behaviour when the block is malformed,
// and it means the daemon-side owner is what needs fixing, not this.
//
// One module rather than one copy per surface: the board chat rendering raw JSON
// at the owner (screenshot 2026-08-29 17:56) is exactly what happens when a feed
// misses this rule, and a second hand-written regex in a second file is how the
// first one gets forgotten.

export const ASK_OPEN = "<helmdeck-ask";

/** Text with any ask block removed, trimmed. Safe on text that has none. */
export function stripAsk(text: string): string {
  if (!text || !text.toLowerCase().includes(ASK_OPEN)) return text ?? "";
  const out = text.replace(/<helmdeck-ask>[\s\S]*?<\/helmdeck-ask>/gi, "");
  // An UNCLOSED tag - the model is still typing it, or the reply was truncated
  // mid-block. Cut from the tag onward: the half a closing tag never arrives for
  // would otherwise stream in character by character. Mirrors ask.strip_stream.
  const i = out.toLowerCase().indexOf(ASK_OPEN);
  return (i === -1 ? out : out.slice(0, i)).trim();
}

/** True when `text` carries a sentinel and nothing readable survives removing
 *  it - i.e. the row is a block and only a block, so it should not be drawn. */
export function isAskOnly(text: string): boolean {
  return !!text && text.toLowerCase().includes(ASK_OPEN) && !stripAsk(text).trim();
}
