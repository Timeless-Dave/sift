/**
 * Rear camera with a working torch.
 *
 * Three things go wrong on real Android phones, and this module handles each:
 *  1. Chrome reports `torch` in getCapabilities() only once the track is delivering frames, so
 *     checking right after getUserMedia says "no torch" on phones that have one.
 *  2. Phones with several rear lenses can hand back the ultra-wide or telephoto for
 *     facingMode "environment"; only the main lens has the flash. We try the other rear lenses.
 *  3. A constraint inside `advanced` that the camera can't satisfy is silently ignored, not
 *     rejected, so "applyConstraints didn't throw" doesn't mean the torch is on. We read it back.
 */

/** The phone has no torch the browser can switch, so a torch-only reading can't run here. */
export class TorchUnavailableError extends Error {
  constructor() { super("This phone's browser can't switch the torch, so Sift skipped the reading that needs it."); }
}

export interface RearCamera {
  stream: MediaStream;
  track: MediaStreamTrack;
  video: HTMLVideoElement;
  /** The camera advertises a torch (checked after frames arrived). */
  torch: boolean;
}

type Caps = MediaTrackCapabilities & { torch?: boolean };
type Settings = MediaTrackSettings & { torch?: boolean };

const FRONT = /front|user|facetime|selfie/i;

export async function openRearCamera(
  opts: { needTorch?: boolean; video?: MediaTrackConstraints; signal?: AbortSignal } = {},
): Promise<RearCamera> {
  const base: MediaTrackConstraints = { width: { ideal: 1280 }, height: { ideal: 720 }, ...opts.video };
  let cam = await open({ ...base, facingMode: { ideal: "environment" } }, opts.signal);
  if (cam.torch || !opts.needTorch) return cam;

  // Look for another rear lens with the flash. Labels are available now that permission is granted.
  const tried = new Set([cam.track.getSettings().deviceId]);
  const devices = (await navigator.mediaDevices.enumerateDevices?.().catch(() => [])) ?? [];
  const rear = devices.filter((d) => d.kind === "videoinput" && !FRONT.test(d.label) && !tried.has(d.deviceId));
  for (const d of rear) {
    opts.signal?.throwIfAborted();
    close(cam);   // Android allows one open camera at a time
    try {
      const next = await open({ ...base, deviceId: { exact: d.deviceId } }, opts.signal);
      if (next.torch) return next;
      cam = next;
    } catch {
      cam = await open({ ...base, facingMode: { ideal: "environment" } }, opts.signal);
    }
  }
  return cam;
}

/** Switches the torch and reports whether it is now in that state, as far as the browser can tell. */
export async function setTorch(track: MediaStreamTrack, on: boolean): Promise<boolean> {
  try {
    await track.applyConstraints({ advanced: [{ torch: on } as MediaTrackConstraintSet] });
  } catch {
    return false;
  }
  await new Promise((r) => setTimeout(r, 120));
  const settings = track.getSettings() as Settings;
  if (settings.torch !== undefined) return settings.torch === on;
  // Some browsers don't echo torch in settings: then "on" is only plausible with an advertised torch.
  return on ? hasTorch(track) : true;
}

export function hasTorch(track: MediaStreamTrack): boolean {
  try { return (track.getCapabilities?.() as Caps | undefined)?.torch === true; } catch { return false; }
}

export function close(cam: RearCamera | null | undefined): void {
  if (!cam) return;
  cam.stream.getTracks().forEach((t) => t.stop());
  cam.video.srcObject = null;
}

async function open(video: MediaTrackConstraints, signal?: AbortSignal): Promise<RearCamera> {
  signal?.throwIfAborted();
  const stream = await navigator.mediaDevices.getUserMedia({ audio: false, video });
  const track = stream.getVideoTracks()[0];
  const el = document.createElement("video");
  el.playsInline = true; el.muted = true; el.srcObject = stream;
  try {
    await el.play();
    await framesArrived(el, signal);
  } catch (e) {
    stream.getTracks().forEach((t) => t.stop());
    throw e;
  }
  return { stream, track, video: el, torch: hasTorch(track) };
}

/** Resolves once the video has a sized frame (and capabilities are populated). */
async function framesArrived(video: HTMLVideoElement, signal?: AbortSignal): Promise<void> {
  const end = Date.now() + 3000;
  while (!video.videoWidth) {
    signal?.throwIfAborted();
    if (Date.now() > end) throw new Error("The camera didn't send any frames. Close other apps using the camera and try again.");
    await new Promise((r) => setTimeout(r, 50));
  }
  await new Promise((r) => setTimeout(r, 150)); // a beat for Chrome to publish capabilities
}
