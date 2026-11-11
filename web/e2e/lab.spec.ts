import path from "node:path";
import { expect, test } from "@playwright/test";
import { watchErrors } from "./hardware";

test("lab tests list links to a runnable test", async ({ page }) => {
  await page.goto("/lab-tests");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator('a[href="/lab-tests/run/milk-starch-iodine"]').first()).toBeVisible();
});

test("starch in milk: walk the protocol, upload a card photo, get a result", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/lab-tests/run/milk-starch-iodine");
  // Step through to the capture step: click "Done, next step" until the photo upload appears.
  const upload = page.locator('input[type="file"]');
  const next = page.getByRole("button", { name: /next step/i });
  await expect(next.or(upload)).toBeVisible();
  for (let i = 0; i < 6 && (await upload.count()) === 0; i++) {
    await next.click();
    await expect(next.or(upload.first())).toBeAttached();
  }
  await expect(upload).toHaveCount(1);
  await upload.setInputFiles(path.join(import.meta.dirname, "fixtures", "card-starch.jpg"));
  await page.waitForURL(/\/lab-tests\/result\/[a-f0-9]+$/, { timeout: 60_000 });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Starch|Retake|Calibration/);
  expect(errors()).toEqual([]);
});

test("the Lab Agent answers in the protocol chat", async ({ page }) => {
  await page.route("**/api/v1/agent/turn", (r) => r.fulfill({ json: {
    agent: "muse-spark", reply: "Add one drop of iodine.", step_id: "mix", actions: [] } }));
  await page.goto("/lab-tests/run/milk-starch-iodine");
  await page.getByRole("textbox").first().fill("done, what next?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Add one drop of iodine.")).toBeVisible();
});
