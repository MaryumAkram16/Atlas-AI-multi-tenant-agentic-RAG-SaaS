// UI hints only: they decide which controls to show. The backend enforces
// every rule (role checks in the API and Postgres RLS) regardless.
import type { DocumentItem, Member, Role } from "./types";

const ASSIGNABLE: Record<Role, Role[]> = {
  owner: ["admin", "member", "viewer"],
  admin: ["member", "viewer"],
  member: [],
  viewer: [],
};

export const can = {
  upload: (role: Role) => role !== "viewer",
  manageMembers: (role: Role) => role === "owner" || role === "admin",
  inviteRoles: (role: Role): Role[] => ASSIGNABLE[role],
  changeRole(actor: Role, actorUserId: string, target: Member): Role[] {
    if (target.user_id === actorUserId || target.status !== "active") return [];
    return ASSIGNABLE[actor].includes(target.role) ? ASSIGNABLE[actor] : [];
  },
  revoke(actor: Role, actorUserId: string, target: Member): boolean {
    if (target.user_id === actorUserId || target.status !== "active") return false;
    return ASSIGNABLE[actor].includes(target.role);
  },
  /** Organization-visible documents: owners/admins, or the uploader (not viewers). */
  writeDocument(role: Role, userId: string, ownerId: string): boolean {
    if (role === "viewer") return false;
    return role === "owner" || role === "admin" || ownerId === userId;
  },
  /** Prefer the server's answer (it includes document ACLs) over the role guess. */
  editDocument(role: Role, userId: string, doc: DocumentItem): boolean {
    if (doc.access !== undefined) return doc.access === "write";
    return can.writeDocument(role, userId, doc.owner_id);
  },
  /** Members a document can be shared with, and the levels each can get. */
  shareTargets(members: Member[], doc: DocumentItem, alreadyShared: string[]): Member[] {
    return members.filter(
      (m) => m.status === "active" && m.user_id !== doc.owner_id && !alreadyShared.includes(m.user_id),
    );
  },
  grantLevels: (target: Role): ("read" | "write")[] => (target === "viewer" ? ["read"] : ["read", "write"]),
};

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
}
