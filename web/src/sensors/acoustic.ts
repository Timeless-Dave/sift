/**
 * Near-ultrasound and audible sweep through the food or container the phone is pressed
 * against. Records room silence (noise floor), then plays a 200 Hz to 20 kHz exponential
 * sine sweep while recording. The mic and audio graph are always released, including
 * on error and abort.
 */
import { logBinPower, welchPower } from "./dsp";
import type { AcousticCapture, SensorSupport } from "./types";

/** Same-origin worklet file (public/ ships verbatim, so the CSP's script-src 'self' allows it). */
const RECORDER_URL = `${import.meta.env.BASE_URL}sift-recorder.worklet.js`;

/** Silence before the sweep (noise floor), seconds. */
export const NOISE_SECONDS = 0.6;
/** Sweep length, seconds. */
export const SWEEP_SECONDS = 2;
/** Sweep range, Hz. */
export const SWEEP_F_LO = 200;
export const SWEEP_F_HI = 20000;
/** Log bands in the returned spectra (wire limit: 128). */
export const ACOUSTIC_BANDS = 64;
/** Sweep loudness: clearly audible through contact, not painful in air. */
export const SWEEP_GAIN = 0.25;
/** Fade in/out at each end of the sweep, seconds. */
export const SWEEP_FADE_SECONDS = 0.05;
/** Dropped from the start of the recorded sweep to cover output latency. */
const SWEEP_TRIM_SECONDS = 0.15;
/** Welch segment for both spectra. */
const SEGMENT_SIZE = 4096;

export function support(): SensorSupport {
  if (typeof window === "undefined" || (!window.AudioContext &&
    !(window as unknown as { webkitAudioContext?: unknown }).webkitAudioContext)) {
    return { available: false, reason: "This browser can't play test tones. Use a recent phone browser." };
  }
  if (typeof AudioWorkletNode === "undefined") {
    return { available: false, reason: "This browser can't record test tones. Update it and try again." };
  }
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    return {
      available: false,
      reason: "This browser can't open the microphone. Use a phone browser with microphone access.",
    };
  }
  return { available: true };
}

let primed: AudioContext | null = null;
/** Contexts that already registered the recorder processor (registering twice throws). */
const recorderLoaded = new WeakSet<BaseAudioContext>();

/**
 * Call synchronously inside the tap that starts a scan. Browsers (iOS Safari strictly) only let
 * audio start from a user gesture, and the sweep runs seconds later, after the light sweep.
 */
export function primeAudio(): void {
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return;
  if (!primed || primed.state === "closed") primed = new Ctor();
  void primed.resume().catch(() => undefined);
}

export interface AcousticOptions {
  signal?: AbortSignal;
  onProgress?: (fraction: number) => void;
}

export async function captureAcoustic(opts: AcousticOptions = {}): Promise<AcousticCapture> {
  const { signal, onProgress } = opts;
  signal?.throwIfAborted();
  const sup = support();
  if (!sup.available) throw new Error(sup.reason ?? "Sound capture isn't available.");

  let stream: MediaStream | null = null;
  try {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        video: false,
      });
    } catch {
      throwIfAborted(signal);
      throw new Error("The microphone didn't open. Allow microphone access and try again.");
    }
    const Ctor = window.AudioContext ??
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ownCtx = !primed || primed.state === "closed";
    const ctx = ownCtx ? new Ctor() : (primed as AudioContext);
    try {
      await ctx.resume().catch(() => undefined);
      if (ctx.state === "suspended") {
        throw new Error("Sound is blocked on this phone. Tap the page once, then start the scan again.");
      }
      try {
        if (!recorderLoaded.has(ctx)) { await ctx.audioWorklet.addModule(RECORDER_URL); recorderLoaded.add(ctx); }
      } catch {
        throwIfAborted(signal);
        throw new Error("This browser blocked the recorder. Try another browser.");
      }
      const sampleRate = ctx.sampleRate;
      const source = ctx.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(ctx, "sift-recorder");
      const chunks: Float32Array[] = [];
      let received = 0;
      node.port.onmessage = (e: MessageEvent) => {
        const data = e.data as Float32Array;
        chunks.push(data);
        received += data.length;
      };
      source.connect(node); // never connected to the speakers: no feedback loop
      try {
        onProgress?.(0.05);
        const noiseTarget = Math.floor(NOISE_SECONDS * sampleRate);
        await waitForSamples(() => received, noiseTarget, signal, 8000,
          "The microphone isn't sending sound. Allow microphone access and try again.");
        startSweep(ctx);
        onProgress?.(0.3);
        const sweepTarget = Math.floor((SWEEP_SECONDS + SWEEP_TRIM_SECONDS) * sampleRate);
        await waitForSamples(() => received, noiseTarget + sweepTarget, signal, 12000,
          "The microphone stopped mid-sweep. Hold the phone still and try again.");
        onProgress?.(0.85);

        const all = concatChunks(chunks, noiseTarget + sweepTarget);
        const noise = all.subarray(0, noiseTarget);
        const trim = Math.floor(SWEEP_TRIM_SECONDS * sampleRate);
        const sweep = all.subarray(noiseTarget + trim, noiseTarget + sweepTarget);

        // response_db is the speaker->container->mic transmission of this phone pressed
        // against this container: relative levels per band, not a calibrated measurement.
        // dB offsets (window gain, mic gain) cancel when scans are compared relatively.
        const fHi = Math.min(SWEEP_F_HI, 0.45 * sampleRate);
        const noiseSpec = welchPower(noise, sampleRate, SEGMENT_SIZE);
        const sweepSpec = welchPower(sweep, sampleRate, SEGMENT_SIZE);
        const binnedNoise = logBinPower(noiseSpec.freqs, noiseSpec.power, ACOUSTIC_BANDS, SWEEP_F_LO, fHi);
        const binnedSweep = logBinPower(sweepSpec.freqs, sweepSpec.power, ACOUSTIC_BANDS, SWEEP_F_LO, fHi);
        onProgress?.(1);
        return {
          sample_rate: Math.round(sampleRate),
          bins_hz: binnedSweep.bins_hz,
          response_db: binnedSweep.levels_db,
          noise_db: binnedNoise.levels_db,
        };
      } finally {
        source.disconnect();
        node.disconnect();
        node.port.close();
      }
    } finally {
      if (ownCtx) await ctx.close().catch(() => undefined);
      else await ctx.suspend().catch(() => undefined); // keep the unlocked context for the next scan
    }
  } finally {
    stream?.getTracks().forEach((t) => t.stop());
  }
}

/** Exponential sine sweep SWEEP_F_LO -> SWEEP_F_HI over SWEEP_SECONDS, with fades, at moderate gain. */
function startSweep(ctx: AudioContext): void {
  const t0 = ctx.currentTime + 0.05;
  const osc = ctx.createOscillator();
  osc.type = "sine";
  osc.frequency.setValueAtTime(SWEEP_F_LO, t0);
  osc.frequency.exponentialRampToValueAtTime(SWEEP_F_HI, t0 + SWEEP_SECONDS);
  const gain = ctx.createGain();
  gain.gain.setValueAtTime(0.0001, t0);
  gain.gain.exponentialRampToValueAtTime(SWEEP_GAIN, t0 + SWEEP_FADE_SECONDS);
  gain.gain.setValueAtTime(SWEEP_GAIN, t0 + SWEEP_SECONDS - SWEEP_FADE_SECONDS);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + SWEEP_SECONDS);
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start(t0);
  osc.stop(t0 + SWEEP_SECONDS + 0.05);
  osc.onended = () => { osc.disconnect(); gain.disconnect(); };
}

function concatChunks(chunks: Float32Array[], target: number): Float32Array {
  const out = new Float32Array(target);
  let at = 0;
  for (const c of chunks) {
    if (at >= target) break;
    const n = Math.min(c.length, target - at);
    out.set(c.subarray(0, n), at);
    at += n;
  }
  return out;
}

async function waitForSamples(
  count: () => number, target: number, signal: AbortSignal | undefined, timeoutMs: number, timeoutMessage: string,
): Promise<void> {
  const end = Date.now() + timeoutMs;
  for (;;) {
    throwIfAborted(signal);
    if (count() >= target) return;
    if (Date.now() > end) throw new Error(timeoutMessage);
    await new Promise((r) => setTimeout(r, 25));
  }
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw abortError(signal);
}

function abortError(signal?: AbortSignal): Error {
  return signal?.reason instanceof Error ? signal.reason : new DOMException("The scan was cancelled.", "AbortError");
}
