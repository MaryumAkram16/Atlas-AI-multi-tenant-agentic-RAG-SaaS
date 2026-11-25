import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

/**
 * The Week 5 acceptance flow, entirely through the UI:
 * a new user signs up, creates an organization, invites a member, uploads a
 * document, restricts it and shares it with the member, and the member chats
 * and gets an answer with citations.
 */

const run = Date.now().toString(36);
const owner = { email: `owner-${run}@example.com`, password: "owner-password-123" };
const invitee = { email: `member-${run}@example.com`, password: "member-password-123" };
const here = path.dirname(fileURLToPath(import.meta.url));
const policy = path.resolve(here, "../../sample-data/acme/refund-policy-2026.md");

async function signUp(page: Page, email: string, password: string) {
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign up" }).click();
}

test("new user: sign up, create org, invite, upload, chat with citations", async ({ browser }) => {
  // 1. Owner signs up and creates a workspace.
  const ownerCtx = await browser.newContext();
  const ownerPage = await ownerCtx.newPage();
  await ownerPage.goto("/signup");
  await signUp(ownerPage, owner.email, owner.password);
  await expect(ownerPage.getByRole("heading", { name: "Create a workspace" })).toBeVisible();
  await ownerPage.getByLabel("Organization name").fill(`E2E Corp ${run}`);
  await ownerPage.getByRole("button", { name: "Create workspace" }).click();
  await expect(ownerPage.getByRole("heading", { name: "Knowledge base" })).toBeVisible();
  const orgUrl = new URL(ownerPage.url()).pathname.split("/").slice(0, 3).join("/");

  // 2. Owner invites a member and gets a one-time link.
  await ownerPage.getByRole("link", { name: "Members" }).click();
  await ownerPage.getByLabel("Invite email").fill(invitee.email);
  await ownerPage.getByLabel("Invite role").selectOption("member");
  await ownerPage.getByRole("button", { name: "Create invitation" }).click();
  const link = await ownerPage.getByLabel("Invitation link").inputValue();
  expect(link).toContain("/invite/");

  // 3. Invitee opens the link, signs up, and accepts.
  const memberCtx = await browser.newContext();
  const memberPage = await memberCtx.newPage();
  await memberPage.goto(link);
  await expect(memberPage).toHaveURL(/\/login\?next=/);
  await memberPage.getByRole("link", { name: "Create an account" }).click();
  await signUp(memberPage, invitee.email, invitee.password);
  await memberPage.getByRole("button", { name: "Accept invitation" }).click();
  await expect(memberPage).toHaveURL(new RegExp(`${orgUrl}/chat`));

  // Owner sees the new member with the right role.
  await ownerPage.reload();
  const memberRow = ownerPage.locator("table").first().locator("tr", { hasText: invitee.email });
  await expect(memberRow.getByRole("combobox")).toHaveValue("member");
  await expect(memberRow).toContainText("active");

  // 4. Owner uploads a document and waits for indexing.
  await ownerPage.getByRole("link", { name: "Knowledge base" }).click();
  await ownerPage.getByLabel("Document file").setInputFiles(policy);
  await ownerPage.getByRole("button", { name: "Upload" }).click();
  const row = ownerPage.getByLabel("Documents").locator("tr.clickable", { hasText: "refund-policy-2026" });
  await expect(row).toContainText("ready", { timeout: 90_000 });

  // Owner restricts the document, then shares it with the member (read only).
  await row.click();
  ownerPage.once("dialog", (d) => void d.accept());
  await ownerPage.getByLabel("Document visibility").selectOption("restricted");
  await expect(row).toContainText("restricted");
  await ownerPage.getByLabel("Member to share with").selectOption({ label: `${invitee.email} (member)` });
  await ownerPage.getByLabel("Access level").selectOption("read");
  await ownerPage.getByRole("button", { name: "Share" }).click();
  await expect(ownerPage.getByLabel("Document permissions")).toContainText(invitee.email);

  // 5. The member asks a question and gets a cited answer.
  await memberPage.getByLabel("Question").fill("How many days do customers have to request a refund?");
  await memberPage.getByRole("button", { name: "Ask" }).click();
  const answer = memberPage.locator(".msg-assistant[data-status='answered']").last();
  await expect(answer).toContainText("7 days", { timeout: 60_000 });
  await expect(answer.getByLabel("Sources")).toContainText("refund-policy-2026");

  // Clicking a citation opens the source preview with the cited text.
  await answer.locator("button.cite").first().click();
  const preview = memberPage.getByLabel("Source preview");
  await expect(preview).toContainText("refund-policy-2026");
  await expect(preview.locator(".excerpt")).toContainText("7 days");

  // The conversation is saved and listed.
  await expect(memberPage.getByLabel("Conversations")).toContainText("How many days");

  await ownerCtx.close();
  await memberCtx.close();
});

test("a question with no evidence shows the abstain state", async ({ page }) => {
  const email = `solo-${run}@example.com`;
  await page.goto("/signup");
  await signUp(page, email, "solo-password-123");
  await page.getByLabel("Organization name").fill(`Solo ${run}`);
  await page.getByRole("button", { name: "Create workspace" }).click();
  await page.getByRole("link", { name: "Chat" }).click();
  await page.getByLabel("Question").fill("What is the stock option vesting schedule?");
  await page.getByRole("button", { name: "Ask" }).click();
  const answer = page.locator(".msg-assistant").last();
  await expect(answer).toHaveAttribute("data-status", "insufficient_evidence", { timeout: 60_000 });
  await expect(answer).toContainText("Not enough evidence");
});
