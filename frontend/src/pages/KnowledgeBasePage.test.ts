import type { DocumentItem } from "../services/types";
import { shownStatus } from "./KnowledgeBasePage";

const doc = (over: Partial<DocumentItem>) => ({ status: "processing", job_status: null, ...over }) as DocumentItem;

describe("document status shown in the knowledge base", () => {
  it("refines the status with the latest job", () => {
    expect(shownStatus(doc({ job_status: "queued" }))).toBe("queued");
    expect(shownStatus(doc({ job_status: "running" }))).toBe("processing");
    expect(shownStatus(doc({ status: "failed", job_status: "failed" }))).toBe("failed");
    expect(shownStatus(doc({ status: "failed", job_status: "queued" }))).toBe("queued"); // retrying
    expect(shownStatus(doc({ status: "ready", job_status: "succeeded" }))).toBe("ready");
    expect(shownStatus(doc({ status: "deleting", job_status: "queued" }))).toBe("deleting");
  });
});
