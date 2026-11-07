/**
 * Bubble rise: the user holds a sealed bottle upside down in front of the rear camera so the
 * liquid fills the frame, then turns it upright while the camera records; the air bubble
 * climbs through the liquid. Tracks the bubble front per frame and reports the 20%-to-80%
 * rise time, after LiquidHash (MobiSys 2022). The camera is always released, including
 * on error and cancel.
 */
import { bubbleFront, bubbleRiseTime, downsampleEvenly, trackedFraction } from "./dsp";
import type { BubbleCapture, SensorSupport } from "./types";

/** Recording length, seconds. */
export const BUBBLE_SECONDS = 6;
/** Analysis size: the bubble front needs rows, not pixels. */
export const BUBBLE_WIDTH = 48;
export const BUBBLE_HEIGHT = 64;
/** Wire cap on track entries (api/sift/scan/schemas.py). */
export const BUBBLE_MAX_TRACK = 240;

export function support(): SensorSupport {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    return { available: false, reason: "This browser can't open the camera. Use a phone browser with camera access." };
  }
  return { available: true };
}

export interface BubbleOptions {
  signal?: AbortSignal;
  /** Recording length in seconds (default BUBBLE_SECONDS). */
  seconds?: number;
  onProgress?: (fraction: number) => void;
}

export async function captureBubble(opts: BubbleOptions = {}): Promise<BubbleCapture> {
  const { signal, seconds = BUBBLE_SECONDS, onProgress } = opts;
  signal?.throwIfAborted();
  const sup = support();
  if (!sup.available) throw new Error(sup.reason ?? "The camera isn't available.");

  let stream: MediaStream | null = null;
  let video: HTMLVideoElement | null = null;
  try {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: "environment" }, frameRate: { ideal: 60 },
          width: { ideal: 1280 }, height: { ideal: 720 },
        },
      });
    } catch {
      throwIfAborted(signal);
      throw new Error("The rear camera didn't open. Allow camera access and try again.");
    }
    const track = stream.getVideoTracks()[0];
    if (!track) throw new Error("The rear camera didn't open. Allow camera access and try again.");

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
    canvas.width = BUBBLE_WIDTH; canvas.height = BUBBLE_HEIGHT;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) throw new Error("This browser can't read camera frames. Try another browser.");

    const { frames, times } = await recordGrayFrames(video, ctx, seconds, signal, (f) => onProgress?.(0.05 + 0.9 * f));
    if (frames.length < 5) {
      throw new Error("The camera sent too few frames. Close other apps using the camera and try again.");
    }
    const t0 = times[0];
    const timesS = times.map((t) => (t - t0) / 1000);
    const elapsed = (times[times.length - 1] - times[0]) / 1000;
    const fps = elapsed > 0 ? Math.round(((frames.length - 1) / elapsed) * 10) / 10 : 0;
    if (!(fps >= 10)) {
      throw new Error("The camera didn't deliver steady frames. Close other apps using the camera and try again.");
    }

    const fronts: (number | null)[] = [null]; // the first frame has no predecessor to differ from
    for (let i = 1; i < frames.length; i++) {
      fronts.push(bubbleFront(frames[i - 1], frames[i], BUBBLE_WIDTH, BUBBLE_HEIGHT));
    }
    const trackHeights: number[] = [0];
    for (let i = 1; i < frames.length; i++) {
      const f = fronts[i];
      trackHeights.push(f === null ? trackHeights[i - 1] : Math.min(1, Math.max(0, f)));
    }
    onProgress?.(1);
    return {
      fps,
      track: downsampleEvenly(trackHeights, BUBBLE_MAX_TRACK),
      rise_time_s: bubbleRiseTime(timesS, fronts),
      tracked_fraction: trackedFraction(fronts.slice(1)),
    };
  } finally {
    stream?.getTracks().forEach((t) => t.stop());
    if (video) video.srcObject = null;
  }
}

interface GrayRecording { frames: Float64Array[]; times: number[] }

/**
 * Records small grey frames for the given seconds. Frame callbacks come from
 * requestVideoFrameCallback where available, else one grab per animation frame; the
 * reported fps is measured from the frame timestamps either way.
 */
async function recordGrayFrames(
  video: HTMLVideoElement, ctx: CanvasRenderingContext2D, seconds: number,
  signal: AbortSignal | undefined, onProgress: (fraction: number) => void,
): Promise<GrayRecording> {
  const w = BUBBLE_WIDTH, h = BUBBLE_HEIGHT;
  const frames: Float64Array[] = [];
  const times: number[] = [];
  const grab = (): Float64Array => {
    ctx.drawImage(video, 0, 0, w, h);
    const d = ctx.getImageData(0, 0, w, h).data;
    const gray = new Float64Array(w * h);
    for (let p = 0; p < gray.length; p++) gray[p] = 0.299 * d[p * 4] + 0.587 * d[p * 4 + 1] + 0.114 * d[p * 4 + 2];
    return gray;
  };
  const start = performance.now();
  const deadline = start + Math.max(1, seconds) * 1000;
  const progress = () => onProgress(Math.min(0.99, (performance.now() - start) / (deadline - start)));
  const hasRvc = typeof video.requestVideoFrameCallback === "function";
  const rvc = hasRvc ? video.requestVideoFrameCallback.bind(video) : null;

  if (rvc) {
    await new Promise<void>((resolve, reject) => {
      const stalled = "The camera stopped sending frames mid-scan. Close other apps using the camera and try again.";
      const watchdog = setTimeout(() => {
        cleanup();
        reject(new Error(stalled));
      }, deadline - performance.now() + 3000);
      const cleanup = () => {
        clearTimeout(watchdog);
        signal?.removeEventListener("abort", onAbort);
      };
      const onAbort = () => {
        cleanup();
        reject(abortError(signal));
      };
      const step = (now: number) => {
        if (signal?.aborted) return; // onAbort rejects
        try {
          frames.push(grab());
          times.push(now);
        } catch (e) {
          cleanup();
          reject(e);
          return;
        }
        progress();
        if (performance.now() >= deadline) {
          cleanup();
          resolve();
        } else {
          rvc(step);
        }
      };
      if (signal?.aborted) {
        cleanup();
        reject(abortError(signal));
        return;
      }
      signal?.addEventListener("abort", onAbort, { once: true });
      rvc(step);
    });
  } else {
    while (performance.now() < deadline) {
      signal?.throwIfAborted();
      frames.push(grab());
      times.push(performance.now());
      progress();
      await nextFrame(signal);
    }
  }
  return { frames, times };
}

/** One animation frame (or ~16 ms where rAF is missing), abort-aware. */
function nextFrame(signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.reject(abortError(signal));
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(abortError(signal));
    signal?.addEventListener("abort", onAbort, { once: true });
    const done = () => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    };
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => done());
    else setTimeout(done, 16);
  });
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
