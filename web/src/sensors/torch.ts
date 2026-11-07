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

  let stream: MediaStream | null = null;
  let video: HTMLVideoElement | null = null;
  let torchOn = false;
  const releaseTorch = async (track: MediaStreamTrack | undefined) => {
    if (torchOn && track) {
      torchOn = false;
      try {
        await track.applyConstraints({ advanced: [{ torch: false } as MediaTrackConstraintSet] });
      } catch { /* best effort */ }
    }
  };
  try {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
      });
    } catch {
      throwIfAborted(signal);
      throw new Error("The rear camera didn't open. Allow camera access and try again.");
    }
    const track = stream.getVideoTracks()[0];
    if (!track) throw new Error("The rear camera didn't open. Allow camera access and try again.");
    // Lock exposure and white balance where allowed, so off/on frames are comparable.
    try {
      const lock = { exposureMode: "manual", whiteBalanceMode: "manual" } as MediaTrackConstraintSet;
      await track.applyConstraints({ advanced: [lock] });
    } catch { /* unsupported */ }
    let torchSupported = false;
    try {
      const caps = track.getCapabilities?.() as (MediaTrackCapabilities & { torch?: boolean }) | undefined;
      torchSupported = caps?.torch === true;
    } catch { /* assume unsupported */ }

    video = document.createElement("video");
    video.playsInline = true;
    video.muted = true;
    video.srcObject = stream;
    try {
      await video.play();
    } catch {
      throwIfAborted(signal);
      throw new Error("The camera preview didn't start. Close other apps using the camera and try again.");
    }
    await waitForVideo(video, signal);

    const canvas = document.createElement("canvas");
    canvas.width = 96; canvas.height = 72;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) throw new Error("This browser can't read camera frames. Try another browser.");
    const grab = (acc: RgbAccumulator) => {
      ctx.drawImage(video as HTMLVideoElement, 0, 0, canvas.width, canvas.height);
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

    if (!torchSupported) return { off: offStats, on: null, torch_available: false };
    try {
      await track.applyConstraints({ advanced: [{ torch: true } as MediaTrackConstraintSet] });
      torchOn = true;
    } catch {
      return { off: offStats, on: null, torch_available: false }; // advertised but refused
    }
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
    const track = stream?.getVideoTracks()[0];
    await releaseTorch(track);
    stream?.getTracks().forEach((t) => t.stop());
    if (video) video.srcObject = null;
  }
}

/** Waits until the video has a sized frame, so draws never read a blank element. */
async function waitForVideo(video: HTMLVideoElement, signal?: AbortSignal): Promise<void> {
  const end = Date.now() + 3000;
  while (!video.videoWidth) {
    signal?.throwIfAborted();
    if (Date.now() > end) {
      throw new Error("The camera didn't send any frames. Close other apps using the camera and try again.");
    }
    await wait(60, signal);
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
