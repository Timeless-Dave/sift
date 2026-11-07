/**
 * Product barcode lookup support: reads a retail barcode from a live <video> frame with
 * BarcodeDetector (Android Chrome). Used at identification time to narrow down the food;
 * never a verdict on its own.
 */
import type { SensorSupport } from "./types";

/** Retail barcode formats Sift asks for. */
export const BARCODE_FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e"] as const;

interface BarcodeDetectorLike { detect(image: CanvasImageSource): Promise<{ rawValue?: string }[]> }
type BarcodeDetectorCtor = new (opts?: { formats?: string[] }) => BarcodeDetectorLike;

function detectorCtor(): BarcodeDetectorCtor | undefined {
  return typeof window !== "undefined"
    ? (window as unknown as { BarcodeDetector?: BarcodeDetectorCtor }).BarcodeDetector
    : undefined;
}

export function support(): SensorSupport {
  if (!detectorCtor()) {
    return { available: false, reason: "This browser can't read barcodes. Type the digits instead." };
  }
  return { available: true };
}

/**
 * Reads one frame from a playing <video> and returns the first barcode value, or null
 * when there is none (or no detector). The caller owns the video element and retries
 * across frames; this call never opens the camera itself.
 */
export async function detectBarcode(
  video: HTMLVideoElement, opts: { signal?: AbortSignal } = {},
): Promise<string | null> {
  opts.signal?.throwIfAborted();
  const Ctor = detectorCtor();
  if (!Ctor || !video.videoWidth) return null;
  let detector: BarcodeDetectorLike;
  try {
    detector = new Ctor({ formats: [...BARCODE_FORMATS] });
  } catch {
    try {
      detector = new Ctor();
    } catch {
      return null;
    }
  }
  const found = await detector.detect(video);
  opts.signal?.throwIfAborted();
  return found?.[0]?.rawValue ?? null;
}
