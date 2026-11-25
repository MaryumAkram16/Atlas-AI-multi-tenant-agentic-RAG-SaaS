import { messageFor } from "./api";

describe("messageFor", () => {
  it("prefers server detail strings and messages", () => {
    expect(messageFor(409, "slug already taken")).toBe("slug already taken");
    expect(messageFor(409, { message: "duplicate document" })).toBe("duplicate document");
  });
  it("has friendly fallbacks", () => {
    expect(messageFor(401, null)).toMatch(/sign in again/);
    expect(messageFor(403, null)).toMatch(/permission/);
    expect(messageFor(422, [{ loc: ["body"] }])).toMatch(/check the form/);
    expect(messageFor(422, { code: "validation_error", message: "Request validation failed." }))
      .toMatch(/check the form/);
    expect(messageFor(429, { code: "quota_exceeded", message: "Your plan's documents limit has been reached." }))
      .toMatch(/documents limit/);
  });
});
