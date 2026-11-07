/**
 * One shop-aisle scan across the phone's sensors. Runs the requested modalities in a
 * fixed sensible order with the stillness monitor spanning all of them, skips
 * modalities the phone can't run, and releases every sensor on finish, error or abort.
 * Features are computed on the phone; raw audio and video never leave it.
 */
import { captureAcoustic, support as acousticSupport } from "./acoustic";
import { captureScreenlight, STANDARD_SEQUENCE, support as screenlightSupport } from "./screenlight";
import { captureTorch, support as torchSupport } from "./torch";
import { captureVibration, support as vibrationSupport } from "./vibration";
import { startMotionMonitor, support as motionSupport, type MotionMonitor } from "./motion";
import type { Capture, Modality, MotionCapture, OnProgress, SensorSupport } from "./types";

/** Scan order: light-based captures first (they need the screen), then sound, then shake. */
const MODALITY_ORDER: Modality[] = ["screenlight", "torch", "acoustic", "vibration"];

/** Feature detection per modality. Prompts for nothing; safe to call on page load. */
export function support(): Record<Modality, SensorSupport> {
  return {
    torch: torchSupport(),
    screenlight: screenlightSupport(),
    acoustic: acousticSupport(),
    vibration: vibrationSupport(),
    motion: motionSupport(),
  };
}

export interface ScanOptions {
  /** Screen colours for the screenlight sweep (default: the standard 12-colour set). */
  screenSequence?: string[];
  /** Time per screen colour in ms (default 450). */
  frameMs?: number;
  onProgress?: OnProgress;
  signal?: AbortSignal;
}

/**
 * Runs the requested modalities, skipping ones the phone can't run. The motion
 * monitor spans the whole scan and is included only when the sensor actually sent
 * data. Throws on abort, when nothing could run, or when a running sensor fails;
 * every sensor is released either way.
 */
export async function runScan(modalities: Modality[], opts: ScanOptions = {}): Promise<Capture> {
  const { screenSequence = STANDARD_SEQUENCE, frameMs, onProgress, signal } = opts;
  signal?.throwIfAborted();
  const sup = support();
  const capture: Capture = {};
  let monitor: MotionMonitor | null = null;
  let motion: MotionCapture | null = null;
  let motionSamples = 0;
  try {
    if (modalities.includes("motion") && sup.motion.available) monitor = startMotionMonitor();
    for (const modality of MODALITY_ORDER) {
      if (!modalities.includes(modality) || !sup[modality].available) continue;
      signal?.throwIfAborted();
      onProgress?.(modality, 0);
      const forward = (fraction: number) => onProgress?.(modality, fraction);
      if (modality === "screenlight") {
        capture.screenlight = await captureScreenlight({
          sequence: screenSequence, frameMs, signal, onProgress: forward,
        });
      } else if (modality === "torch") {
        capture.torch = await captureTorch({ signal, onProgress: forward });
      } else if (modality === "acoustic") {
        capture.acoustic = await captureAcoustic({ signal, onProgress: forward });
      } else if (modality === "vibration") {
        capture.vibration = await captureVibration({ signal, onProgress: forward });
      }
      onProgress?.(modality, 1);
    }
    signal?.throwIfAborted();
  } finally {
    if (monitor) {
      motion = monitor.stop();
      motionSamples = monitor.sampleCount;
    }
  }
  if (motion && motionSamples >= 10) capture.motion = motion;
  if (!capture.torch && !capture.screenlight && !capture.acoustic && !capture.vibration) {
    throw new Error("None of the requested sensors can run on this phone. Try a phone with a camera and microphone.");
  }
  return capture;
}
