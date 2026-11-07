/**
 * Stillness monitor for the whole scan (a quality gate, never a verdict). Tracks peak
 * rotation rate and acceleration jitter from DeviceMotionEvent. On iOS 13+ the page
 * must call requestMotionPermission() from a user gesture before the scan.
 */
import { std } from "./dsp";
import type { MotionCapture, SensorSupport } from "./types";

export function support(): SensorSupport {
  if (typeof window === "undefined" || typeof DeviceMotionEvent === "undefined") {
    return { available: false, reason: "This browser can't read the motion sensor. Hold the phone still anyway." };
  }
  return { available: true };
}

export type MotionPermission = "granted" | "denied" | "not-required";

/**
 * Asks for motion access where the browser requires it (iOS 13+). Must run inside a
 * user gesture (a tap handler); elsewhere the browser ignores it and this resolves
 * "denied". Resolves "not-required" where no permission step exists.
 */
export async function requestMotionPermission(): Promise<MotionPermission> {
  const DME = typeof window !== "undefined" ? window.DeviceMotionEvent : undefined;
  const request = (DME as unknown as { requestPermission?: () => Promise<string> } | undefined)?.requestPermission;
  if (typeof request !== "function") return "not-required";
  try {
    return (await request.call(DME)) === "granted" ? "granted" : "denied";
  } catch {
    return "denied";
  }
}

export interface MotionMonitor {
  /** Samples seen so far; near zero means the sensor is silent, not that the phone is still. */
  readonly sampleCount: number;
  /** Stops listening and returns the capture. Idempotent. Zeros when no samples arrived. */
  stop(): MotionCapture;
}

/** Starts the stillness monitor. Throws when the motion sensor is unavailable. */
export function startMotionMonitor(): MotionMonitor {
  const sup = support();
  if (!sup.available) throw new Error(sup.reason ?? "The motion sensor isn't available.");
  const magnitudes: number[] = [];
  let maxRotation = 0;
  const onMotion = (e: DeviceMotionEvent) => {
    const a = e.acceleration ?? e.accelerationIncludingGravity;
    if (a) magnitudes.push(Math.hypot(a.x ?? 0, a.y ?? 0, a.z ?? 0));
    const r = e.rotationRate;
    if (r) maxRotation = Math.max(maxRotation, Math.hypot(r.alpha ?? 0, r.beta ?? 0, r.gamma ?? 0));
  };
  window.addEventListener("devicemotion", onMotion);
  let stopped = false;
  return {
    get sampleCount() { return magnitudes.length; },
    stop() {
      if (!stopped) {
        stopped = true;
        window.removeEventListener("devicemotion", onMotion);
      }
      return { max_rotation_dps: maxRotation, accel_jitter: std(magnitudes) };
    },
  };
}
