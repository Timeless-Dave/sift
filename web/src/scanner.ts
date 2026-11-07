/**
 * Scan orchestration. The sensors need two poses, because the screen and the rear camera face
 * opposite ways:
 *   face  the screen side pressed against the food or package: screen-light sweep, sound sweep, vibration
 *   back  the rear camera pointed at the food, close up: torch on/off
 * Each pose runs only the modalities the food profile asks for; between poses the UI asks the
 * user to turn the phone over.
 */
import { runScan, support } from "./sensors";
import type { Capture, Modality, OnProgress } from "./sensors/types";

/** The screen-light colour sequence; matches SCREEN_SEQUENCE on the API. */
export const SCREEN_SEQUENCE = ["white", "black", "red", "orange", "yellow", "lime", "green", "teal", "cyan", "blue", "violet", "magenta"];
export const SCREEN_COLOURS: Record<string, string> = {
  white: "#ffffff", black: "#000000", red: "#ff0000", orange: "#ff8000", yellow: "#ffff00", lime: "#80ff00",
  green: "#00ff00", teal: "#00ff80", cyan: "#00ffff", blue: "#0000ff", violet: "#8000ff", magenta: "#ff00ff",
};

export const POSES: { id: "face" | "back"; modalities: Modality[]; instruction: string }[] = [
  { id: "face", modalities: ["screenlight", "acoustic", "vibration"], instruction: "Screen side against the food. Hold still." },
  { id: "back", modalities: ["torch"], instruction: "Turn the phone over: camera 5 cm from the food." },
];

export const SENSOR_INFO: Record<string, { name: string; what: string }> = {
  screenlight: { name: "Light sweep", what: "The screen flashes 12 colours; the front camera reads what comes back." },
  torch: { name: "Torch", what: "Colour and clarity with the flash off, then on." },
  acoustic: { name: "Sound sweep", what: "200 Hz to 20 kHz, into near-ultrasound most people can't hear." },
  vibration: { name: "Vibration", what: "How the food damps the phone's vibration motor." },
};

export function available(modalities: string[]): { modality: string; ok: boolean; reason?: string }[] {
  const s = support() as Record<string, { available: boolean; reason?: string }>;
  return modalities.map((m) => ({ modality: m, ok: !!s[m]?.available, reason: s[m]?.reason }));
}

export interface ScanStage { pose: "face" | "back"; instruction: string; modality?: Modality; fraction?: number; hint?: string }

/**
 * Run every pose the food needs. `beforePose` lets the UI show the pose instruction and wait for the
 * user (a countdown or a tap) before the sensors start.
 */
export async function scanFood(
  modalities: string[], onStage: (s: ScanStage) => void, beforePose: (instruction: string) => Promise<void>,
  signal: AbortSignal,
): Promise<Capture> {
  const capture: Capture = {};
  const supported = new Set(available(modalities).filter((a) => a.ok).map((a) => a.modality));
  for (const pose of POSES) {
    const mods = pose.modalities.filter((m) => modalities.includes(m) && supported.has(m));
    if (!mods.length) continue;
    if (signal.aborted) throw new DOMException("Scan cancelled", "AbortError");
    await beforePose(pose.instruction);
    onStage({ pose: pose.id, instruction: pose.instruction });
    const onProgress: OnProgress = (modality, fraction, hint) =>
      onStage({ pose: pose.id, instruction: pose.instruction, modality, fraction, hint });
    const part = await runScan(mods, { screenSequence: SCREEN_SEQUENCE, frameMs: 450, onProgress, signal });
    const { motion, ...rest } = part;
    Object.assign(capture, rest);
    // Each pose has its own motion monitor; keep the shakiest reading so the gate sees the worst moment.
    if (motion) capture.motion = capture.motion ? {
      max_rotation_dps: Math.max(capture.motion.max_rotation_dps, motion.max_rotation_dps),
      accel_jitter: Math.max(capture.motion.accel_jitter, motion.accel_jitter),
    } : motion;
  }
  return capture;
}
