import { actionLabel, bytes, money, parseFacts, percent, usageShare } from "./format";

describe("admin formatting", () => {
  it("formats numbers for people", () => {
    expect(percent(0.8765)).toBe("87.7%");
    expect(percent(null)).toBe("—");
    expect(bytes(512)).toBe("512 B");
    expect(bytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(money(null)).toBe("not priced");
    expect(money("0.12")).toBe("$0.1200");
  });

  it("labels audit actions and parses facts", () => {
    expect(actionLabel("document.permission_granted")).toBe("Document permission granted");
    expect(parseFacts(" 7 days, June 30;\n\n 60 USD ")).toEqual(["7 days", "June 30", "60 USD"]);
  });

  it("computes quota usage only when there is a limit", () => {
    expect(usageShare({ limit: null, used: 4 })).toBeNull();
    expect(usageShare({ limit: 10, used: 4 })).toBe(0.4);
    expect(usageShare({ limit: 10, used: 40 })).toBe(1);
  });
});
