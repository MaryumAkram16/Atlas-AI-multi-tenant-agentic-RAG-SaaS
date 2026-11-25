import { parseSSE } from "./sse";

describe("parseSSE", () => {
  it("parses complete events and keeps the partial rest", () => {
    const buf = 'event: step\ndata: {"node":"plan_retrieval"}\n\nevent: delta\ndata: {"text":"Sev';
    const { events, rest } = parseSSE(buf);
    expect(events).toEqual([{ event: "step", data: { node: "plan_retrieval" } }]);
    expect(rest).toBe('event: delta\ndata: {"text":"Sev');
  });

  it("handles CRLF and multi-line data", () => {
    const { events } = parseSSE('event: done\r\ndata: {"status":\r\ndata: "answered"}\r\n\r\n');
    expect(events).toEqual([{ event: "done", data: { status: "answered" } }]);
  });

  it("falls back to raw text for non-JSON data", () => {
    expect(parseSSE("data: hello\n\n").events).toEqual([{ event: "message", data: "hello" }]);
  });
});
