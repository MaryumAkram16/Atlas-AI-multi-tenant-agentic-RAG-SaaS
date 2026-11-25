import { can, slugify } from "./permissions";
import type { DocumentItem, Member } from "./types";

const member = (over: Partial<Member>): Member => ({
  id: "m", organization_id: "o", user_id: "u2", email: "x@y.z", role: "member",
  status: "active", invited_by: null, created_at: "", revoked_at: null, ...over,
});

describe("role-based UI hints", () => {
  it("mirrors the backend role rules", () => {
    expect(can.upload("viewer")).toBe(false);
    expect(can.upload("member")).toBe(true);
    expect(can.manageMembers("member")).toBe(false);
    expect(can.inviteRoles("admin")).toEqual(["member", "viewer"]);
    expect(can.inviteRoles("owner")).toContain("admin");
    expect(can.changeRole("admin", "u1", member({ role: "admin" }))).toEqual([]);
    expect(can.changeRole("owner", "u1", member({ role: "admin" }))).toContain("viewer");
    expect(can.changeRole("owner", "u1", member({ user_id: "u1", role: "owner" }))).toEqual([]);
    expect(can.revoke("admin", "u1", member({ role: "owner" }))).toBe(false);
    expect(can.revoke("admin", "u1", member({ role: "viewer" }))).toBe(true);
    expect(can.revoke("owner", "u1", member({ status: "revoked" }))).toBe(false);
    expect(can.writeDocument("member", "u1", "u2")).toBe(false);
    expect(can.writeDocument("member", "u1", "u1")).toBe(true);
    expect(can.writeDocument("viewer", "u1", "u1")).toBe(false);
  });

  it("prefers the server's document access and filters share targets", () => {
    const doc = { id: "d", owner_id: "u1", visibility: "restricted" } as DocumentItem;
    expect(can.editDocument("owner", "u9", { ...doc, access: "read" })).toBe(false);
    expect(can.editDocument("member", "u9", { ...doc, access: "write" })).toBe(true);
    expect(can.editDocument("member", "u1", doc)).toBe(true); // falls back to the role rule
    const members = [
      member({ user_id: "u1" }),
      member({ user_id: "u2" }),
      member({ user_id: "u3", status: "revoked" }),
      member({ user_id: "u4", role: "viewer" }),
    ];
    expect(can.shareTargets(members, doc, ["u2"]).map((m) => m.user_id)).toEqual(["u4"]);
    expect(can.grantLevels("viewer")).toEqual(["read"]);
    expect(can.grantLevels("admin")).toEqual(["read", "write"]);
  });

  it("slugifies organization names", () => {
    expect(slugify("Acme Inc. (EU)")).toBe("acme-inc-eu");
    expect(slugify("Ünïcode Café")).toBe("unicode-cafe");
  });
});
