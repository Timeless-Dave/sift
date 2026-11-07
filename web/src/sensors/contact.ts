/**
 * Contact diffuse reflectance: the rear camera and torch pressed flat against meat or fish.
 * The lens can't focus at contact, so this reads diffuse light, not an image: ambient
 * colour with the torch off, then mean colour in rings around the brightest point with
 * the torch on. Without a controllable torch the rings are meaningless, so the capture
 * throws instead of returning them. The camera and torch are always released, including
 * on error and cancel.
 */
import { brightnessCentroid, clippedFraction, meanRgbFullFrame, ringProfile } from "./dsp";
import type { ContactCapture, RGB, SensorSupport } from "./types";

/** Torch-off frames pooled into the dark level. */
export const CONTACT_DARK_FRAMES = 6;
/** Torch-on frames pooled into the ring profile. */
export const CONTACT_LIT_FRAMES = 10;
/** Rings in the profile (wire allows 4..16). */
export const CONTACT_RINGS = 8;
/** Analysis size: small enough to stay fast, enough pixels per ring. */
const FRAME_WIDTH = 128;
const FRAME_HEIGHT = 96;

export function support(): SensorSupport {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    return { available: false, reason: "This browser can't open the camera. Use a phone browser with camera access." };
  }
  // Torch capability needs a live camera track, which needs a permission prompt, so it can't be
  // known here; captureContact throws a clear error on phones without a controllable torch.
  return { available: true, reason: "needs a controllable torch (Android)" };
}

export interface ContactOptions {
  signal?: AbortSignal;
  /** Torch-off frames pooled into the dark level (default CONTACT_DARK_FRAMES). */
  darkFrames?: number;
  /** Torch-on frames pooled into the ring profile (default CONTACT_LIT_FRAMES). */
  litFrames?: number;
  /** Settle after opening the camera, ms (default 700). */
  settleMs?: number;
  /** Settle after switching the torch on, ms (default 600). */
  torchSettleMs?: number;
  onProgress?: (fraction: number) => void;
}

export async function captureContact(opts: ContactOptions = {}): Promise<ContactCapture> {
  const {
    signal, darkFrames = CONTACT_DARK_FRAMES, litFrames = CONTACT_LIT_FRAMES,
    settleMs = 700, torchSettleMs = 600, onProgress,
  } = opts;
  signal?.throwIfAborted();
  const sup = support();
  if (!sup.available) throw new Error(sup.reason ?? "The camera isn't available.");
  const darkN = Math.max(1, Math.floor(darkFrames));
  const litN = Math.max(1, Math.floor(litFrames));

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
    canvas.width = FRAME_WIDTH; canvas.height = FRAME_HEIGHT;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) throw new Error("This browser can't read camera frames. Try another browser.");
    const readFrame = () => {
      ctx.drawImage(video as HTMLVideoElement, 0, 0, canvas.width, canvas.height);
      return ctx.getImageData(0, 0, canvas.width, canvas.height);
    };

    onProgress?.(0.05);
    await wait(settleMs, signal);
    const dark: RGB = [0, 0, 0];
    for (let i = 0; i < darkN; i++) {
      signal?.throwIfAborted();
      const m = meanRgbFullFrame(readFrame());
      dark[0] += m[0]; dark[1] += m[1]; dark[2] += m[2];
      onProgress?.(0.05 + (0.25 * (i + 1)) / darkN);
      await wait(90, signal);
    }
    dark[0] /= darkN; dark[1] /= darkN; dark[2] /= darkN;

    try {
      await track.applyConstraints({ advanced: [{ torch: true } as MediaTrackConstraintSet] });
      torchOn = true;
    } catch {
      throwIfAborted(signal);
      throw new Error("This scan needs a phone with a controllable torch. Use Android Chrome and try again.");
    }
    await wait(torchSettleMs, signal);
    // Lock exposure and white balance where allowed, keeping the torch on.
    try {
      const lock = { torch: true, exposureMode: "manual", whiteBalanceMode: "manual" } as MediaTrackConstraintSet;
      await track.applyConstraints({ advanced: [lock] });
    } catch { /* unsupported */ }

    const n = FRAME_WIDTH * FRAME_HEIGHT;
    const sum = new Float64Array(n * 3);
    let clipped = 0;
    for (let i = 0; i < litN; i++) {
      signal?.throwIfAborted();
      const frame = readFrame();
      const d = frame.data;
      for (let p = 0; p < n; p++) {
        sum[p * 3] += d[p * 4]; sum[p * 3 + 1] += d[p * 4 + 1]; sum[p * 3 + 2] += d[p * 4 + 2];
      }
      clipped += clippedFraction(frame);
      onProgress?.(0.4 + (0.55 * (i + 1)) / litN);
      await wait(90, signal);
    }
    const avg = new Uint8ClampedArray(n * 4);
    for (let p = 0; p < n; p++) {
      avg[p * 4] = sum[p * 3] / litN; avg[p * 4 + 1] = sum[p * 3 + 1] / litN; avg[p * 4 + 2] = sum[p * 3 + 2] / litN;
      avg[p * 4 + 3] = 255;
    }
    const lit = { data: avg, width: FRAME_WIDTH, height: FRAME_HEIGHT };
    const { cx, cy } = brightnessCentroid(lit);
    const rings = ringProfile(lit, cx, cy, CONTACT_RINGS);
    onProgress?.(1);
    return { dark, rings, clipped: clipped / litN, torch_available: true };
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
