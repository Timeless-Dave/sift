import type { Page } from "@playwright/test";

export interface HardwareOptions {
  /** Advertise a torch on the rear camera, the way Android Chrome does: only once frames are flowing. */
  torch?: boolean;
  vibrate?: boolean;
  motion?: boolean;
  /** Code the BarcodeDetector reports (omit for no BarcodeDetector). */
  barcode?: string;
}

/**
 * Fakes the phone hardware that a desktop test browser lacks, at the level of the browser APIs Sift
 * calls, and records what the app does with it on window.__hw for assertions.
 */
export async function fakeHardware(page: Page, opts: HardwareOptions = {}): Promise<void> {
  await page.addInitScript((o: HardwareOptions) => {
    const hw = { torchCalls: [] as boolean[], torch: false, vibrations: 0, framesSeen: new WeakSet<MediaStreamTrack>() };
    (window as unknown as { __hw: typeof hw }).__hw = hw;

    if (o.torch) {
      const proto = MediaStreamTrack.prototype;
      const getCaps = proto.getCapabilities;
      const getSettings = proto.getSettings;
      const apply = proto.applyConstraints;
      const started = new WeakMap<MediaStreamTrack, number>();
      // Like Chrome on Android: `torch` appears in capabilities only once the camera has been running a
      // moment. The clock starts when the camera opens, so code that asks too early sees no torch.
      const gum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = async (c?: MediaStreamConstraints) => {
        const stream = await gum(c);
        for (const t of stream.getVideoTracks()) started.set(t, performance.now());
        return stream;
      };
      proto.getCapabilities = function (this: MediaStreamTrack) {
        const caps = getCaps.call(this) as MediaTrackCapabilities & { torch?: boolean };
        const t0 = started.get(this);
        if (this.kind !== "video" || t0 === undefined) return caps;
        return performance.now() - t0 > 100 ? { ...caps, torch: true } : caps;
      };
      proto.getSettings = function (this: MediaStreamTrack) {
        const s = getSettings.call(this);
        return this.kind === "video" ? { ...s, torch: hw.torch } : s;
      };
      proto.applyConstraints = async function (this: MediaStreamTrack, c?: MediaTrackConstraints) {
        const adv = (c?.advanced ?? []) as (MediaTrackConstraintSet & { torch?: boolean })[];
        const t = adv.find((x) => typeof x.torch === "boolean");
        if (t && this.kind === "video") { hw.torch = t.torch as boolean; hw.torchCalls.push(hw.torch); }
        const rest = adv.map(({ torch: _t, ...x }) => x).filter((x) => Object.keys(x).length);
        try { await apply.call(this, rest.length ? { advanced: rest } : {}); } catch { /* unsupported in the fake camera */ }
      };
      const stop = proto.stop;
      proto.stop = function (this: MediaStreamTrack) { if (this.kind === "video") hw.torch = false; return stop.call(this); };
    }

    if (o.vibrate) {
      Object.defineProperty(navigator, "vibrate", { configurable: true, value: () => { hw.vibrations++; return true; } });
    }

    if (o.motion) {
      setInterval(() => {
        const n = () => (Math.random() - 0.5) * 0.2;
        window.dispatchEvent(new DeviceMotionEvent("devicemotion", {
          acceleration: { x: n(), y: n(), z: n() },
          accelerationIncludingGravity: { x: n(), y: n(), z: 9.81 + n() },
          rotationRate: { alpha: n() * 20, beta: n() * 20, gamma: n() * 20 },
          interval: 16,
        }));
      }, 16);
    }

    if (o.barcode) {
      (window as unknown as { BarcodeDetector: unknown }).BarcodeDetector = class {
        static async getSupportedFormats() { return ["ean_13", "ean_8", "upc_a", "upc_e"]; }
        async detect() { return [{ rawValue: o.barcode }]; }
      };
    }
  }, opts);
}

/** Collects page errors and console errors; call errors() at the end of a test. */
export function watchErrors(page: Page): () => string[] {
  const out: string[] = [];
  page.on("pageerror", (e) => out.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") out.push(`console: ${m.text()}${m.location()?.url ? ` (${m.location().url})` : ""}`);
  });
  page.on("requestfailed", (r) => out.push(`requestfailed: ${r.method()} ${r.url()} ${r.failure()?.errorText ?? ""}`));
  return () => out;
}
