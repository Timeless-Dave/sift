/**
 * Screen-light sweep: the screen shows each colour in turn while the front camera
 * samples the centre of the frame. Returns colour -> mean [r,g,b] (sRGB 0..1) per
 * frame. Owns its camera, flash overlay and wake lock, released on finish, error
 * and abort. (Ported from web/src/capture.ts; that file now wraps this module.)
 */
import { meanRgbFromImageData } from "./dsp";
import type { RGB, ScreenlightCapture, SensorSupport } from "./types";

/** Screen colours the sweep may show. Unknown sequence names are skipped, never used as CSS. */
export const SCREENLIGHT_COLOURS: Record<string, string> = {
  white: "#ffffff", black: "#000000", red: "#ff0000", orange: "#ff8000", yellow: "#ffff00",
  lime: "#80ff00", green: "#00ff00", teal: "#00ff80", cyan: "#00ffff", blue: "#0000ff",
  violet: "#8000ff", magenta: "#ff00ff",
};

/** Standard 12-colour sweep order, used when the caller passes no sequence. */
export const STANDARD_SEQUENCE = Object.keys(SCREENLIGHT_COLOURS);

/** Wire limits (api/sift/scan/schemas.py): at most 32 colours, 60 frames each. */
export const MAX_COLOURS = 32;
export const MAX_FRAMES_PER_COLOUR = 60;

export function support(): SensorSupport {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    return { available: false, reason: "This browser can't open the camera. Use a phone browser with camera access." };
  }
  return { available: true };
}

export interface ScreenlightOptions {
  /** Colour names from SCREENLIGHT_COLOURS, in sweep order. */
  sequence: string[];
  /** Time per colour in ms (default 450). */
  frameMs?: number;
  /** Settle after each colour change, ms (default 180). */
  settleMs?: number;
  signal?: AbortSignal;
  onProgress?: (fraction: number, colour?: string) => void;
}

export async function captureScreenlight(opts: ScreenlightOptions): Promise<ScreenlightCapture> {
  const { sequence, frameMs = 450, settleMs = 180, signal, onProgress } = opts;
  signal?.throwIfAborted();
  const sup = support();
  if (!sup.available) throw new Error(sup.reason ?? "The camera isn't available.");
  const colours = sequence.filter((name) => SCREENLIGHT_COLOURS[name]).slice(0, MAX_COLOURS);
  if (colours.length === 0) throw new Error("The light sequence has no colours this phone can show.");

  let stream: MediaStream | null = null;
  let flash: HTMLElement | null = null;
  let lock: { release(): Promise<void> } | null = null;
  try {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: "user" }, width: { ideal: 640 }, height: { ideal: 480 } },
      });
    } catch {
      throwIfAborted(signal);
      throw new Error("The front camera didn't open. Allow camera access and try again.");
    }
    // Lock exposure and white balance where allowed, so each colour is comparable.
    try {
      await stream.getVideoTracks()[0]?.applyConstraints({
        advanced: [{ exposureMode: "manual", whiteBalanceMode: "manual" } as MediaTrackConstraintSet],
      });
    } catch { /* unsupported */ }
    try {
      type Wake = { request(t: string): Promise<{ release(): Promise<void> }> };
      lock = await (navigator as unknown as { wakeLock?: Wake }).wakeLock?.request("screen") ?? null;
    } catch { /* ignore */ }

    const video = document.createElement("video");
    video.playsInline = true;
    video.muted = true;
    video.srcObject = stream;
    try {
      await video.play();
    } catch {
      throwIfAborted(signal);
      throw new Error("The camera preview didn't start. Close other apps using the camera and try again.");
    }

    flash = document.createElement("div");
    flash.className = "flash";
    flash.setAttribute("role", "status");
    document.body.append(flash);
    try { await flash.requestFullscreen?.(); } catch { /* optional */ }

    const canvas = document.createElement("canvas");
    canvas.width = 64; canvas.height = 48;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) throw new Error("This browser can't read camera frames. Try another browser.");

    const frames: Record<string, RGB[]> = {};
    for (let c = 0; c < colours.length; c++) {
      const name = colours[c];
      signal?.throwIfAborted();
      flash.style.background = SCREENLIGHT_COLOURS[name];
      onProgress?.(c / colours.length, name);
      await wait(settleMs, signal);
      const end = performance.now() + Math.max(1, frameMs - settleMs);
      const samples: RGB[] = [];
      do {
        signal?.throwIfAborted();
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        samples.push(meanRgbFromImageData(ctx.getImageData(0, 0, canvas.width, canvas.height)));
        if (samples.length >= MAX_FRAMES_PER_COLOUR) break;
        await wait(60, signal);
      } while (performance.now() < end);
      frames[name] = samples;
    }
    onProgress?.(1);
    return { frames };
  } finally {
    if (typeof document !== "undefined" && document.fullscreenElement) {
      await document.exitFullscreen().catch(() => undefined);
    }
    flash?.remove();
    stream?.getTracks().forEach((t) => t.stop());
    await lock?.release().catch(() => undefined);
  }
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw abortError(signal);
}

function abortError(signal?: AbortSignal): Error {
  return signal?.reason instanceof Error ? signal.reason : new DOMException("The scan was cancelled.", "AbortError");
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  throwIfAborted(signal);
  if (ms <= 0) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError(signal));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
