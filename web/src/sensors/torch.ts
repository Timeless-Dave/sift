/**
 * Rear-camera reflectance with the torch off, then on. Android Chrome can switch the
 * torch; elsewhere the capture still reports the ambient (torch-off) colour with
 * torch_available false and on null. The camera and torch are always released,
 * including on error and cancel.
 */
import {
  addImageDataToAccumulator,
  createRgbAccumulator,
  rgbStatsFromAccumulator,
  type RgbAccumulator,
} from "./dsp";
import { close, openRearCamera, setTorch, type RearCamera } from "./camera";
import type { SensorSupport, TorchCapture } from "./types";

/** Frames pooled per torch state; small enough to stay fast, enough to average noise. */
export const TORCH_FRAMES = 8;

export function support(): SensorSupport {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    return { available: false, reason: "This browser can't open the camera. Use a phone browser with camera access." };
  }
  return { available: true };
}

export interface TorchOptions {
  signal?: AbortSignal;
  /** Frames pooled per torch state (default TORCH_FRAMES). */
  frames?: number;
  /** Settle after opening the camera, ms (default 700). */
  settleMs?: number;
  /** Settle after switching the torch, ms (default 500). */
  torchSettleMs?: number;
  onProgress?: (fraction: number) => void;
}

export async function captureTorch(opts: TorchOptions = {}): Promise<TorchCapture> {
  const { signal, frames = TORCH_FRAMES, settleMs = 700, torchSettleMs = 500, onProgress } = opts;
  signal?.throwIfAborted();
  const sup = support();
  if (!sup.available) throw new Error(sup.reason ?? "The camera isn't available.");

  let cam: RearCamera | null = null;
  let torchOn = false;
  try {
    try {
      cam = await openRearCamera({ needTorch: true, signal });
    } catch (e) {
      throwIfAborted(signal);
      throw new Error((e as Error).message?.startsWith("The camera") ? (e as Error).message
        : "The rear camera didn't open. Allow camera access and try again.");
    }
    const { track, video } = cam;
    // Lock exposure and white balance where allowed, so off/on frames are comparable.
    try {
      const lock = { exposureMode: "manual", whiteBalanceMode: "manual" } as MediaTrackConstraintSet;
      await track.applyConstraints({ advanced: [lock] });
    } catch { /* unsupported */ }

    const canvas = document.createElement("canvas");
    canvas.width = 96; canvas.height = 72;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) throw new Error("This browser can't read camera frames. Try another browser.");
    const grab = (acc: RgbAccumulator) => {
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      addImageDataToAccumulator(acc, ctx.getImageData(0, 0, canvas.width, canvas.height));
    };

    onProgress?.(0.05);
    await wait(settleMs, signal);
    const off = createRgbAccumulator();
    for (let i = 0; i < frames; i++) {
      signal?.throwIfAborted();
      grab(off);
      onProgress?.(0.05 + (0.4 * (i + 1)) / frames);
      await wait(90, signal);
    }
    const offStats = rgbStatsFromAccumulator(off);

    if (!cam.torch) return { off: offStats, on: null, torch_available: false };
    torchOn = await setTorch(track, true);
    if (!torchOn) return { off: offStats, on: null, torch_available: false }; // advertised but didn't come on
    await wait(torchSettleMs, signal);
    const on = createRgbAccumulator();
    for (let i = 0; i < frames; i++) {
      signal?.throwIfAborted();
      grab(on);
      onProgress?.(0.55 + (0.4 * (i + 1)) / frames);
      await wait(90, signal);
    }
    onProgress?.(1);
    return { off: offStats, on: rgbStatsFromAccumulator(on), torch_available: true };
  } finally {
    if (cam && torchOn) await setTorch(cam.track, false);
    close(cam);
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
