/**
 * Wire format for instant scans. Mirrors api/sift/scan/schemas.py; see docs/scanner.md.
 * Every reading is a summary computed on the phone. Raw audio and video never leave it.
 */

export type Modality = "torch" | "screenlight" | "acoustic" | "vibration" | "motion";
export type RGB = [number, number, number]; // sRGB 0..1

export interface RGBStats { mean: RGB; std: RGB; clipped: number }

export interface TorchCapture { off: RGBStats; on: RGBStats | null; torch_available: boolean }
export interface ScreenlightCapture { frames: Record<string, RGB[]> }
export interface AcousticCapture { sample_rate: number; bins_hz: number[]; response_db: number[]; noise_db: number[] }
export interface VibrationCapture { rate_hz: number; rms_on: number; rms_off: number; spectrum: number[]; vibrate_available: boolean }
export interface MotionCapture { max_rotation_dps: number; accel_jitter: number }

export interface Capture {
  torch?: TorchCapture;
  screenlight?: ScreenlightCapture;
  acoustic?: AcousticCapture;
  vibration?: VibrationCapture;
  motion?: MotionCapture;
}

export type ReferenceLabel = "genuine" | "adulterated" | "cultured" | "conventional";

export interface ScanRequest {
  food: string;
  product?: { barcode?: string };
  device: string;
  mode: "check" | "reference";
  reference?: { label: ReferenceLabel; target?: string; value?: number; note?: string };
  capture: Capture;
}

export interface ScanProblem { modality: Modality | "scan"; code: string; severity: "reject" | "warn"; message: string; fix: string }

export interface ScanResult {
  scan_id: string;
  food: string;
  mode: "check" | "reference";
  status: "ok" | "rejected" | "stored";
  quality: { ok: boolean; problems: ScanProblem[] };
  match: { status: "no_reference" | "matches" | "differs"; distance: number | null; threshold: number | null; n_genuine: number; modalities: string[] };
  findings: {
    target: string; kind: "adulteration" | "cultured" | "freshness" | "identity";
    status: "no_model" | "model" | "research"; label: string; confidence: number | null;
    model: Record<string, unknown> | null;
  }[];
  report: { agent: string; text: string };
}

/** What each sensor module exports. Implementations live next to this file. */
export interface SensorSupport { available: boolean; reason?: string }

/** Progress callback for the scan UI: which sensor is running and how far along (0..1). */
export type OnProgress = (modality: Modality, fraction: number, hint?: string) => void;
