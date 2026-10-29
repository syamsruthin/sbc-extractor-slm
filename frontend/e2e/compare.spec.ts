import { expect, test } from "@playwright/test";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

// SBC PDFs come from the local corpus (data/raw is not in git).
const PDFS = ["10091OR0780001-01", "15560MI0350004-00"].map((id) => resolve(here, `../../data/raw/sbc_pdfs/${id}.pdf`));
test.skip(!PDFS.every(existsSync), "local SBC corpus not available");

test("upload two SBCs, compare them and read the explanation", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("No plans yet")).toBeVisible();

  await page.getByLabel("Upload SBC PDFs").setInputFiles(PDFS);
  const list = page.getByRole("list", { name: "Uploaded plans" });
  await expect(list.getByText("Core Gold 1500")).toBeVisible({ timeout: 90_000 });
  await expect(list.getByText("Blue Cross Premier PPO Gold")).toBeVisible({ timeout: 90_000 });
  await expect(list.getByText("Ready")).toHaveCount(2, { timeout: 90_000 });

  // plan detail: section summary and a source popover
  await list.getByRole("link", { name: "Core Gold 1500" }).click();
  await expect(page.getByRole("heading", { name: "Doctor visits" })).toBeVisible();
  await page.getByRole("button", { name: "$50 copay" }).first().click();
  await expect(page.getByRole("dialog", { name: "Source of this value" })).toContainText("page 2");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Add to comparison" }).click();

  await page.getByRole("link", { name: "My plans" }).click();
  await page.getByRole("list", { name: "Uploaded plans" }).getByRole("button", { name: "Compare" }).click();
  await page.getByRole("button", { name: "Compare 2 plans" }).click();

  // builder: validation, then a valid submit
  await page.getByLabel("Monthly premium for Core Gold 1500").fill("abc");
  await page.getByRole("button", { name: "Compare 2 plans" }).first().click();
  await expect(page.getByText(/Enter an amount like 450/)).toBeVisible();
  await page.getByLabel("Monthly premium for Core Gold 1500").fill("620");
  await page.getByLabel("Monthly premium for Blue Cross Premier PPO Gold").fill("585");
  await page.getByRole("button", { name: "Compare 2 plans" }).first().click();

  await expect(page).toHaveURL(/\/comparisons\//);
  await expect(page.getByRole("heading", { name: "Plan comparison" })).toBeVisible();
  await expect(page.getByText("Numbers checked")).toBeVisible();
  await expect(page.getByText("Plan A").first()).toBeVisible();
  await expect(page.getByText("$7,440").first()).toBeVisible(); // 620 x 12
  await expect(page.getByRole("heading", { name: "Side by side" })).toBeVisible();

  // change inputs: every value comes back, and re-running unchanged gives the same result
  const hash = (await page.getByText(/· result [0-9a-f]{16}/).textContent())!.match(/result ([0-9a-f]{16})/)![1];
  const firstUrl = page.url();
  await page.getByRole("link", { name: "Change inputs" }).click();
  await expect(page.getByLabel("Monthly premium for Core Gold 1500")).toHaveValue("620");
  await expect(page.getByLabel("Monthly premium for Blue Cross Premier PPO Gold")).toHaveValue("585");
  await page.getByRole("button", { name: "Compare 2 plans" }).first().click();
  await expect(page).not.toHaveURL(firstUrl);
  await expect(page.getByText(`result ${hash}`)).toBeVisible();

  // describe your year (fake LLM): events are added for review, then used in the comparison.
  // With the LLM off (E2E_LLM_MODE=off) the feature is hidden.
  const health = await (await page.request.get("http://127.0.0.1:8001/api/v1/health")).json();
  await page.getByRole("link", { name: "Change inputs" }).click();
  await expect(page.getByLabel("Monthly premium for Core Gold 1500")).toHaveValue("620");
  if (health.intake_available) {
    await page.getByLabel("Describe your expected care").fill("I expect 3 specialist visits and I'm having a baby. Dental cleanings too.");
    await page.getByRole("checkbox", { name: /sent to an AI service/ }).check();
    await page.getByRole("button", { name: "Interpret" }).click();
    await expect(page.getByText("from your description")).toHaveCount(2);
    await expect(page.getByText(/Dental cleanings.*adult dental/)).toBeVisible();
    await page.getByRole("button", { name: "Compare 2 plans" }).first().click();
    await expect(page.getByRole("cell", { name: /Your usage/ })).toBeVisible();
  } else {
    await expect(page.getByText(/Describe your year/)).toHaveCount(0);
    await page.getByRole("button", { name: "Compare 2 plans" }).first().click();
    await expect(page).toHaveURL(/\/comparisons\//);
  }

  // saved comparisons: listed and deletable
  await page.getByRole("link", { name: "Saved" }).click();
  await expect(page.getByRole("list", { name: "Saved comparisons" }).getByRole("listitem")).toHaveCount(3);
  await page.getByRole("button", { name: "Delete all" }).click();
  await page.getByRole("button", { name: "Delete all" }).last().click();
  await expect(page.getByText("No saved comparisons")).toBeVisible();
});

test("catalog shows how to load it when empty", async ({ page }) => {
  await page.goto("/catalog");
  await expect(page.getByText("The catalog is empty")).toBeVisible();
});
