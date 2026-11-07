/**
 * Vibration response: how a pressed-on solid (meat, fruit, a jar) damps the phone's
 * motor, read through the accelerometer. Samples acceleration magnitude with the motor
 * off, then with it on. Android only: without navigator.vibrate there is no excitation,
 * so the capture reports vibrate_available false with zeros and an empty spectrum.
 */
import { floorPowerOfTwo, logBandMeans, mean, normaliseSpectrum, rms, welchPower } from "./dsp";
import type { SensorSupport, VibrationCapture } from "./types";

/** Motor-off baseline, ms. */
export const VIBRATE_OFF_MS = 1000;
/** Motor-on measurement window, ms. */
export const VIBRATE_ON_MS = 1500;
/** Sustained excitation for the on-window (a one-shot vibrate pattern). */
export const VIBRATE_MS = 1500;
/** Spectrum bands (wire limit: 64). */
export const VIBRATION_BANDS = 32;
/** Fewest motion samples accepted; below this there is no measurement. */
const MIN_SAMPLES = 10;

export function support(): SensorSupport {
  if (typeof navigator === "undefined" || typeof navigator.vibrate !== "function") {
    return { available: false, reason: "This phone can't vibrate on command, so the scan skips vibration." };
  }
  if (typeof window === "undefined" || typeof DeviceMotionEvent === "undefined") {
    return { available: false, reason: "This browser can't read the motion sensor, so the scan skips vibration." };
  }
  return { available: true };
}

export interface VibrationOptions {
  signal?: AbortSignal;
  onProgress?: (fraction: number) => void;
}

export async function captureVibration(opts: VibrationOptions = {}): Promise<VibrationCapture> {
  const { signal, onProgress } = opts;
  signal?.throwIfAborted();
  if (typeof window === "undefined" || typeof DeviceMotionEvent === "undefined") {
    throw new Error("This browser can't read the motion sensor. Try a phone browser.");
  }

  const off = await sampleMotion(VIBRATE_OFF_MS, signal);
  const rate_hz = Math.round(off.rate * 10) / 10;
  if (off.magnitudes.length < MIN_SAMPLES) {
    throw new Error("The motion sensor sent no data. Hold the phone in your hand and try again.");
  }
  if (rate_hz < 10) throw new Error("The motion sensor is too slow on this phone. Try another phone.");
  onProgress?.(0.35);

  const vibrate = typeof navigator !== "undefined" ? navigator.vibrate?.bind(navigator) : undefined;
  if (!vibrate) return { rate_hz, rms_on: 0, rms_off: 0, spectrum: [], vibrate_available: false };
  try {
    if (!vibrate(VIBRATE_MS)) return { rate_hz, rms_on: 0, rms_off: 0, spectrum: [], vibrate_available: false };
    const on = await sampleMotion(VIBRATE_ON_MS, signal);
    onProgress?.(0.9);
    if (on.magnitudes.length < MIN_SAMPLES) {
      throw new Error("The motion sensor stopped mid-scan. Hold the phone still and try again.");
    }
    const demeaned = withoutMean(on.magnitudes);
    const segment = Math.max(8, Math.min(256, floorPowerOfTwo(demeaned.length)));
    const spec = welchPower(demeaned, rate_hz, segment);
    const { means } = logBandMeans(spec.freqs, spec.power, VIBRATION_BANDS, 1, 0.45 * rate_hz);
    onProgress?.(1);
    return {
      rate_hz,
      rms_on: rms(demeaned),
      rms_off: rms(withoutMean(off.magnitudes)),
      spectrum: normaliseSpectrum(means),
      vibrate_available: true,
    };
  } finally {
    try { vibrate(0); } catch { /* best effort */ }
  }
}

function withoutMean(x: number[]): number[] {
  const m = mean(x);
  return x.map((v) => v - m);
}

interface MotionSample { magnitudes: number[]; rate: number }

/** Collects acceleration magnitudes for durationMs; rate is samples per wall-clock second. */
function sampleMotion(durationMs: number, signal?: AbortSignal): Promise<MotionSample> {
  return new Promise((resolve, reject) => {
    const magnitudes: number[] = [];
    let firstT = 0, lastT = 0;
    const onMotion = (e: DeviceMotionEvent) => {
      const a = e.acceleration ?? e.accelerationIncludingGravity;
      if (!a) return;
      const t = performance.now();
      if (magnitudes.length === 0) firstT = t;
      lastT = t;
      magnitudes.push(Math.hypot(a.x ?? 0, a.y ?? 0, a.z ?? 0));
    };
    let timer = 0;
    const cleanup = () => {
      clearTimeout(timer);
      window.removeEventListener("devicemotion", onMotion);
      signal?.removeEventListener("abort", onAbort);
    };
    const onAbort = () => {
      cleanup();
      reject(abortError(signal));
    };
    const done = () => {
      cleanup();
      const elapsed = (lastT - firstT) / 1000;
      const rate = magnitudes.length >= 2 && elapsed > 0 ? (magnitudes.length - 1) / elapsed : 0;
      resolve({ magnitudes, rate });
    };
    timer = window.setTimeout(done, durationMs);
    if (signal?.aborted) { onAbort(); return; }
    signal?.addEventListener("abort", onAbort, { once: true });
    window.addEventListener("devicemotion", onMotion);
  });
}

function abortError(signal?: AbortSignal): Error {
  return signal?.reason instanceof Error ? signal.reason : new DOMException("The scan was cancelled.", "AbortError");
}
