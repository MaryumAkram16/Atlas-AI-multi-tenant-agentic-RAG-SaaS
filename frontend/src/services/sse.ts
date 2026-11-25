import { config } from "./config";
import { ApiError } from "./api";

export interface SSEEvent {
  event: string;
  data: unknown;
}

/** Parse complete SSE blocks from a buffer; returns events and the unparsed rest. */
export function parseSSE(buffer: string): { events: SSEEvent[]; rest: string } {
  const events: SSEEvent[] = [];
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (data.length) {
      try {
        events.push({ event, data: JSON.parse(data.join("\n")) });
      } catch {
        events.push({ event, data: data.join("\n") });
      }
    }
  }
  return { events, rest };
}

/** POST a JSON body and yield server-sent events as they arrive. */
export async function* postSSE(
  path: string,
  token: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  const resp = await fetch(`${config.apiUrl}${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok || !resp.body) {
    const data = resp.headers.get("content-type")?.includes("json") ? await resp.json() : null;
    throw new ApiError(resp.status, data?.error ?? null);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseSSE(buffer);
    buffer = rest;
    for (const e of events) yield e;
  }
}
