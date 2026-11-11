import { expect, test, type Page } from "@playwright/test";
import { fakeHardware, watchErrors } from "./hardware";

/** Opens the scanner with a food already chosen. */
async function openScanner(page: Page, food: string) {
  await page.addInitScript((f) => { localStorage.setItem("sift.food", f); localStorage.setItem("sift.device", "E2E phone"); }, food);
  await page.goto("/scan");
  await expect(page.locator(".food-pick")).not.toHaveText("Choose a food");
}

/** Runs a scan and returns the result id and the capture the phone kept for the result page. */
async function runScan(page: Page) {
  await page.getByRole("button", { name: /^Scan( as reference)?$/ }).click();
  await expect(page.getByRole("dialog", { name: "Scanning" })).toBeVisible();
  await page.waitForURL(/\/scan\/[a-f0-9]{8,}$/, { timeout: 100_000 });
  const id = page.url().split("/").pop() as string;
  const capture = await page.evaluate((k) => JSON.parse(sessionStorage.getItem(`sift.capture.${k}`) ?? "null"), id);
  return { id, capture };
}

const hw = (page: Page) => page.evaluate(() => (window as unknown as { __hw: { torchCalls: boolean[]; torch: boolean; vibrations: number } }).__hw);

test.describe("viewfinder", () => {
  test("the torch button switches the torch on and off", async ({ page }) => {
    const errors = watchErrors(page);
    await fakeHardware(page, { torch: true });
    await openScanner(page, "olive-oil");
    await page.getByRole("button", { name: /Tap to start the camera/ }).click();
    const torch = page.getByRole("button", { name: "Turn the torch on" });
    await expect(torch).toBeVisible();
    await torch.click();
    await expect(page.getByRole("button", { name: "Turn the torch off" })).toHaveAttribute("aria-pressed", "true");
    expect((await hw(page)).torch).toBe(true);
    await page.getByRole("button", { name: "Turn the torch off" }).click();
    await expect(page.getByRole("button", { name: "Turn the torch on" })).toHaveAttribute("aria-pressed", "false");
    expect((await hw(page)).torch).toBe(false);
    expect(errors()).toEqual([]);
  });

  test("no torch button on a camera without a torch", async ({ page }) => {
    await openScanner(page, "olive-oil");
    await page.getByRole("button", { name: /Tap to start the camera/ }).click();
    await expect(page.locator(".viewfinder.live")).toBeVisible();
    await expect(page.getByRole("button", { name: /torch/i })).toHaveCount(0);
  });

  test("a barcode picks the food", async ({ page }) => {
    await fakeHardware(page, { barcode: "6111099000254" });
    await page.route("**/api/v1/products/6111099000254", (r) => r.fulfill({ json: {
      barcode: "6111099000254", name: "Huile d'olive", brands: "oued souss", food: "olive-oil", source: "openfoodfacts" } }));
    await openScanner(page, "honey");
    await page.getByRole("button", { name: /Tap to start the camera/ }).click();
    await expect(page.locator(".food-pick")).toHaveText("Olive oil");
    await expect(page.getByRole("status")).toContainText("oued souss");
  });

  test("“What is this?” asks the Lab Agent and picks the food", async ({ page }) => {
    await page.route("**/api/v1/identify", (r) => r.fulfill({ json: {
      food: "honey", confidence: 0.93, seen: "A jar of honey.", candidates: ["honey"], agent: "muse-spark" } }));
    await openScanner(page, "olive-oil");
    await page.getByRole("button", { name: /Tap to start the camera/ }).click();
    await page.getByRole("button", { name: "What is this?" }).click();
    await expect(page.locator(".food-pick")).toHaveText("Honey");
  });
});

test.describe("scans", () => {
  test("honey: every sensor runs, the torch really fires, and the result is honest", async ({ page }) => {
    const errors = watchErrors(page);
    await fakeHardware(page, { torch: true, vibrate: true, motion: true });
    await openScanner(page, "honey");
    const { capture } = await runScan(page);

    expect(capture.screenlight.frames.white.length).toBeGreaterThan(0);
    expect(capture.torch.torch_available).toBe(true);
    expect(capture.torch.on).not.toBeNull();
    expect(capture.acoustic.bins_hz.length).toBeGreaterThanOrEqual(8);
    expect(capture.bubble.track.length).toBeGreaterThanOrEqual(5);
    expect(capture.motion).toBeTruthy();
    const { torchCalls } = await hw(page);
    expect(torchCalls).toContain(true);
    expect(torchCalls.at(-1)).toBe(false);                      // switched off afterwards

    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/No verdict yet|Matches|Doesn't match|Couldn't read/);
    await expect(page.getByText("What the phone measured")).toBeVisible();
    expect(errors()).toEqual([]);
  });

  test("beef: light through tissue needs the torch and gets it", async ({ page }) => {
    await fakeHardware(page, { torch: true, vibrate: true, motion: true });
    await openScanner(page, "beef");
    const { capture } = await runScan(page);
    expect(capture.contact.torch_available).toBe(true);
    expect(capture.contact.rings.length).toBeGreaterThanOrEqual(4);
  });

  test("beef without a torch: the tissue reading is skipped and the scan still completes", async ({ page }) => {
    const errors = watchErrors(page);
    await openScanner(page, "beef");
    const { capture } = await runScan(page);
    expect(capture.contact).toBeUndefined();
    expect(capture.screenlight).toBeTruthy();
    expect(errors()).toEqual([]);
  });

  test("researcher mode stores a reference scan", async ({ page }) => {
    await fakeHardware(page, { motion: true });
    await openScanner(page, "olive-oil");
    await page.getByRole("button", { name: "Researcher" }).click();
    await page.getByLabel("Add as a reference scan").check();
    await page.getByPlaceholder(/What is it/).fill("E2E genuine sample");
    await runScan(page);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Reference saved|Couldn't read/);
  });
});
