import { expect, test } from "@playwright/test";
import { watchErrors } from "./hardware";

test("landing page: hero, sensors, live food status, evidence", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Check the food");
  await expect(page.locator(".sensor")).toHaveCount(6);
  await expect(page.locator(".food-tile .status").first()).toBeVisible();     // statuses come from the API
  await expect(page.locator(".fact")).toHaveCount(4);
  await expect(page.getByRole("link", { name: /Open the scanner/ }).first()).toHaveAttribute("href", "/scan");
  expect(errors()).toEqual([]);
});

test("every photo loads", async ({ page }) => {
  await page.goto("/credits");
  const imgs = page.locator(".credit-list img");
  await expect(imgs).toHaveCount(8);
  for (const img of await imgs.all()) {
    await img.scrollIntoViewIfNeeded();
    await expect.poll(() => img.evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth > 0)).toBe(true);
  }
});

test("what it checks: list and a food page with sources", async ({ page }) => {
  await page.goto("/foods");
  await expect(page.locator(".food-index > li")).toHaveCount(9);
  await page.getByRole("link", { name: /Honey/ }).click();
  await expect(page).toHaveURL(/\/foods\/honey$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Honey");
  await expect(page.getByText("Bubble rise").first()).toBeVisible();
  await page.getByText(/^Sources \(\d+\)$/).first().click();
  await expect(page.locator(".sources a").first()).toHaveAttribute("href", /^https:\/\//);
});

test("deep links load directly (SPA fallback)", async ({ page }) => {
  for (const path of ["/foods/beef", "/lab-tests", "/developers", "/credits"]) {
    const res = await page.goto(path);
    expect(res?.status(), path).toBe(200);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  }
});

test("unknown pages show the 404 page", async ({ page }) => {
  await page.goto("/no-such-page");
  await expect(page.getByRole("link", { name: /scan/i }).first()).toBeVisible();
});

test("API page documents keys and the scan endpoint", async ({ page }) => {
  await page.goto("/developers");
  await expect(page.getByText("X-Sift-Key").first()).toBeVisible();
  await expect(page.getByText("/v1/scans").first()).toBeVisible();
});

test("security headers are sent", async ({ request }) => {
  const res = await request.get("/");
  const h = res.headers();
  expect(h["content-security-policy"]).toContain("default-src 'self'");
  expect(h["x-frame-options"]).toBe("DENY");
  expect(h["permissions-policy"]).toContain("camera=(self)");
});

test.describe("API", () => {
  test("health and foods", async ({ request }) => {
    const health = await (await request.get("/api/health")).json();
    expect(health.ok).toBe(true);
    const foods = await (await request.get("/api/v1/foods")).json();
    expect(foods.map((f: { id: string }) => f.id)).toEqual(expect.arrayContaining(["honey", "olive-oil", "beef"]));
  });

  test("bad input is rejected with a clean error", async ({ request }) => {
    const res = await request.post("/api/v1/scans", { data: { food: "honey", capture: {} } });
    expect(res.status()).toBe(422);
    const body = await res.json();
    expect(body.error.code).toBe("invalid_input");
    expect(body.error.request_id).toBeTruthy();
  });
});
