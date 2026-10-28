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
});

test("catalog shows how to load it when empty", async ({ page }) => {
  await page.goto("/catalog");
  await expect(page.getByText("The catalog is empty")).toBeVisible();
});
