import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against a running Sift stack (web + API). Default target is the Docker Compose
 * stack on :8080; set E2E_BASE_URL to test a deployment, e.g. https://siftfood.vercel.app.
 * Uses the installed Chrome with a fake camera and microphone; phone-only hardware (torch,
 * vibration, motion, barcode) is faked in e2e/hardware.ts so the app's handling of it is tested.
 */
export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    ...devices["Pixel 7"],
    channel: "chrome",
    permissions: ["camera", "microphone"],
    trace: "retain-on-failure",
    launchOptions: {
      args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
    },
  },
});
