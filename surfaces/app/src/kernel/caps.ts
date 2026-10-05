// Capability check (ops/docs/backlog/rbac-gxp card 4) - the ONE place that
// answers "may `me` reach a `cap`-gated surface", so the ~9 scattered
// `me.role === "owner"` / `me?.role !== "client"` checks across the app stop
// being independently maintained copies of the same question.
//
// `me.caps` is served fresh by GET /me (spine/http/routes/routes_misc.py),
// derived live from spine/auth/permissions.py's matrix() - never recomputed
// from `role` here. A stale `me` (e.g. after a role change) is fixed by
// re-fetching `/me` (React Query invalidation on ["me"]), not by this
// function trying to be smarter than its input.
import type { Me } from "../data/types";

/** Interim stand-in for the old `teamOnly` flag (client excluded), for
 * surfaces whose daemon route doesn't have a real permissions.py capability
 * yet - see keys.ts's Surface.nav.cap doc. NOT a real capability string (no
 * daemon-side CAPS entry named this); `can()` special-cases it below. */
export const TEAM_MEMBER_CAP = "team.member";

/** Roles that work only on what is THEIRS or ASSIGNED to them (owner decree
 *  2026-10-05, mirrors spine/auth/auth.py is_restricted): client and operator.
 *  They have no private Henry chat, no dashboard, no board-wide lists. */
export function isRestricted(me: Me | null | undefined): boolean {
  return me?.role === "client" || me?.role === "operator";
}

export function can(me: Me | null | undefined, cap: string | undefined): boolean {
  if (!cap) return true; // no cap declared -> every authenticated role sees it
  if (!me) return false;
  // "not a restricted role": since the assignment model that is the owner (and
  // the read-only roles) - the operator no longer reads the board as a whole
  if (cap === TEAM_MEMBER_CAP) return !isRestricted(me);
  return !!me.caps?.includes(cap);
}
