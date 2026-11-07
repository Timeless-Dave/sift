/**
 * Pure signal and image math for the instant scanner. No DOM, no browser globals:
 * safe to import from Node tests and web workers. All DSP runs on the phone; only
 * the summaries below leave it (see docs/scanner.md).
 */
import type { RGB, RGBStats } from "./types";

/** True when n is a positive power of two (a valid FFT length). */
export function isPowerOfTwo(n: number): boolean {
  return Number.isInteger(n) && n > 0 && (n & (n - 1)) === 0;
}

/** Largest power of two at or below n (0 when n < 1). */
export function floorPowerOfTwo(n: number): number {
  if (!Number.isFinite(n) || n < 1) return 0;
  return 2 ** Math.floor(Math.log2(Math.floor(n)));
}

/**
 * In-place radix-2 Cooley-Tukey forward FFT. re and im must have the same
 * power-of-two length; throws RangeError otherwise.
 */
export function fft(re: Float64Array, im: Float64Array): void {
  const n = re.length;
  if (n !== im.length || !isPowerOfTwo(n)) {
    throw new RangeError(`FFT needs equal power-of-two buffers, got ${re.length} and ${im.length}`);
  }
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j &= ~bit;
    j |= bit;
    if (i < j) {
      const tr = re[i]; re[i] = re[j]; re[j] = tr;
      const ti = im[i]; im[i] = im[j]; im[j] = ti;
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len;
    const wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const ur = re[i + k], ui = im[i + k];
        const vr = re[i + k + len / 2] * cr - im[i + k + len / 2] * ci;
        const vi = re[i + k + len / 2] * ci + im[i + k + len / 2] * cr;
        re[i + k] = ur + vr; im[i + k] = ui + vi;
        re[i + k + len / 2] = ur - vr; im[i + k + len / 2] = ui - vi;
        const nr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = nr;
      }
    }
  }
}

/** Hann window of n samples: 0.5 * (1 - cos(2*pi*i/(n-1))). n = 1 gives [1]. */
export function hannWindow(n: number): Float64Array {
  if (!Number.isInteger(n) || n < 1) throw new RangeError(`Hann window needs n >= 1, got ${n}`);
  const w = new Float64Array(n);
  if (n === 1) { w[0] = 1; return w; }
  for (let i = 0; i < n; i++) w[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (n - 1)));
  return w;
}

/** Arithmetic mean (0 for empty input, so callers never see NaN). */
export function mean(x: ArrayLike<number>): number {
  if (x.length === 0) return 0;
  let s = 0;
  for (let i = 0; i < x.length; i++) s += x[i];
  return s / x.length;
}

/** Population standard deviation (0 for empty input). */
export function std(x: ArrayLike<number>): number {
  if (x.length === 0) return 0;
  const m = mean(x);
  let s = 0;
  for (let i = 0; i < x.length; i++) { const d = x[i] - m; s += d * d; }
  return Math.sqrt(s / x.length);
}

/** Root mean square (0 for empty input). */
export function rms(x: ArrayLike<number>): number {
  if (x.length === 0) return 0;
  let s = 0;
  for (let i = 0; i < x.length; i++) s += x[i] * x[i];
  return Math.sqrt(s / x.length);
}

export interface WelchSpectrum { freqs: number[]; power: number[] }

/**
 * Welch-averaged one-sided power spectrum with Hann windows and 50%-style overlap.
 * Spectrum scaling: a cosine of amplitude A peaks near A^2/2 however long the segment
 * is. Bin totals run ~1.5x the mean square (the Hann window's noise bandwidth); that
 * constant offset cancels in relative dB comparisons. When fewer than segmentSize
 * samples are given, the segment shrinks to the largest fitting power of two
 * (minimum 8); fewer than 8 samples throws RangeError.
 */
export function welchPower(
  samples: ArrayLike<number>, sampleRate: number, segmentSize = 2048, overlap = 0.5,
): WelchSpectrum {
  if (!Number.isFinite(sampleRate) || sampleRate <= 0) {
    throw new RangeError(`sampleRate must be > 0, got ${sampleRate}`);
  }
  if (!isPowerOfTwo(segmentSize) || segmentSize < 8) {
    throw new RangeError(`segmentSize must be a power of two >= 8, got ${segmentSize}`);
  }
  if (!(overlap >= 0 && overlap < 1)) throw new RangeError(`overlap must be in [0, 1), got ${overlap}`);
  let n = segmentSize;
  if (samples.length < n) {
    n = floorPowerOfTwo(samples.length);
    if (n < 8) throw new RangeError(`need at least 8 samples, got ${samples.length}`);
  }
  const window = hannWindow(n);
  let wsum = 0;
  for (let i = 0; i < n; i++) wsum += window[i];
  const norm = wsum * wsum;
  const step = Math.max(1, Math.floor(n * (1 - overlap)));
  const half = n / 2;
  const power = new Float64Array(half + 1);
  const re = new Float64Array(n), im = new Float64Array(n);
  let segments = 0;
  for (let start = 0; start + n <= samples.length; start += step) {
    for (let i = 0; i < n; i++) { re[i] = samples[start + i] * window[i]; im[i] = 0; }
    fft(re, im);
    power[0] += (re[0] * re[0] + im[0] * im[0]) / norm;
    for (let k = 1; k < half; k++) power[k] += (2 * (re[k] * re[k] + im[k] * im[k])) / norm;
    power[half] += (re[half] * re[half] + im[half] * im[half]) / norm;
    segments++;
  }
  if (segments === 0) { // n <= samples.length guarantees one segment; kept for safety.
    for (let i = 0; i < n; i++) { re[i] = samples[i] * window[i]; im[i] = 0; }
    fft(re, im);
    power[0] = (re[0] * re[0] + im[0] * im[0]) / norm;
    for (let k = 1; k < half; k++) power[k] = (2 * (re[k] * re[k] + im[k] * im[k])) / norm;
    power[half] = (re[half] * re[half] + im[half] * im[half]) / norm;
    segments = 1;
  }
  const freqs = new Array<number>(half + 1);
  const out = new Array<number>(half + 1);
  for (let k = 0; k <= half; k++) { freqs[k] = (k * sampleRate) / n; out[k] = power[k] / segments; }
  return { freqs, power: out };
}

export interface LogBands { bins_hz: number[]; means: number[] }

/** Floor for empty or silent log bands, in dB. Inside the wire limit of -200..60 dB. */
export const DB_FLOOR = -120;

/**
 * Mean linear power per log-spaced band. bins_hz holds the geometric band centres,
 * increasing and within [fLo, fHi]. Bands with no FFT bins report 0. Non-finite
 * power bins are ignored, so the output stays finite.
 */
export function logBandMeans(
  freqs: ArrayLike<number>, power: ArrayLike<number>, nBins: number, fLo: number, fHi: number,
): LogBands {
  if (freqs.length !== power.length || freqs.length === 0) {
    throw new RangeError(`freqs and power need the same non-zero length, got ${freqs.length} and ${power.length}`);
  }
  if (!Number.isInteger(nBins) || nBins < 1) throw new RangeError(`nBins must be >= 1, got ${nBins}`);
  if (!(fLo > 0 && fHi > fLo && Number.isFinite(fLo) && Number.isFinite(fHi))) {
    throw new RangeError(`need 0 < fLo < fHi, got ${fLo} and ${fHi}`);
  }
  const span = Math.log(fHi / fLo);
  const bins_hz = new Array<number>(nBins);
  for (let i = 0; i < nBins; i++) bins_hz[i] = fLo * Math.exp((span * (i + 0.5)) / nBins);
  const sums = new Float64Array(nBins), counts = new Float64Array(nBins);
  for (let j = 0; j < freqs.length; j++) {
    const f = freqs[j], p = power[j];
    if (!(f >= fLo && f <= fHi) || !Number.isFinite(p)) continue;
    const i = Math.min(nBins - 1, Math.floor((nBins * Math.log(f / fLo)) / span));
    sums[i] += Math.max(0, p); counts[i]++;
  }
  const means = new Array<number>(nBins);
  for (let i = 0; i < nBins; i++) means[i] = counts[i] > 0 ? sums[i] / counts[i] : 0;
  return { bins_hz, means };
}

/**
 * Mean power per log-spaced band in dB: 10*log10 of logBandMeans, floored at DB_FLOOR
 * and capped at 60 dB (the wire limits in api/sift/scan/schemas.py). Always finite.
 */
export function logBinPower(
  freqs: ArrayLike<number>, power: ArrayLike<number>, nBins: number, fLo: number, fHi: number,
): { bins_hz: number[]; levels_db: number[] } {
  const { bins_hz, means } = logBandMeans(freqs, power, nBins, fLo, fHi);
  const levels_db = means.map((m) => Math.min(60, m > 0 ? 10 * Math.log10(Math.max(m, 1e-12)) : DB_FLOOR));
  return { bins_hz, levels_db };
}

/**
 * Peak-normalised linear power (peak 1, silence or no signal all 0) for shapes that
 * must stay non-negative, like the vibration spectrum. Always finite.
 */
export function normaliseSpectrum(power: ArrayLike<number>): number[] {
  let peak = 0;
  for (let i = 0; i < power.length; i++) if (Number.isFinite(power[i])) peak = Math.max(peak, power[i]);
  const out = new Array<number>(power.length);
  for (let i = 0; i < power.length; i++) out[i] = peak > 0 && Number.isFinite(power[i]) ? power[i] / peak : 0;
  return out;
}

/** Fraction of the frame's width and height kept as the centre region. */
export const CENTRE_FRACTION = 0.4;
/** A pixel counts as clipped when any channel reaches this 8-bit value. */
export const CLIP_LEVEL = 250;

/** The fields rgbStats needs; ImageData satisfies this, as do test doubles. */
export interface ImageLike { readonly data: ArrayLike<number>; readonly width: number; readonly height: number }

function centreRect(image: ImageLike): { x0: number; y0: number; w: number; h: number } {
  if (!Number.isInteger(image.width) || !Number.isInteger(image.height) || image.width < 1 || image.height < 1) {
    throw new RangeError(`bad image size ${image.width}x${image.height}`);
  }
  if (image.data.length < image.width * image.height * 4) {
    throw new RangeError("pixel data is shorter than width*height*4");
  }
  const w = Math.max(1, Math.floor(image.width * CENTRE_FRACTION));
  const h = Math.max(1, Math.floor(image.height * CENTRE_FRACTION));
  return { x0: Math.floor((image.width - w) / 2), y0: Math.floor((image.height - h) / 2), w, h };
}

/** Centre-region mean colour of one frame, sRGB 0..1. */
export function meanRgbFromImageData(image: ImageLike): RGB {
  const { x0, y0, w, h } = centreRect(image);
  let r = 0, g = 0, b = 0;
  for (let y = y0; y < y0 + h; y++) {
    const row = y * image.width * 4;
    for (let x = x0; x < x0 + w; x++) {
      const i = row + x * 4;
      r += image.data[i]; g += image.data[i + 1]; b += image.data[i + 2];
    }
  }
  const n = w * h * 255;
  return [r / n, g / n, b / n];
}

/** Running pixel sums over the centre region of several frames, for pooled stats. */
export interface RgbAccumulator {
  n: number; sum: [number, number, number]; sumSq: [number, number, number]; clipped: number;
}

export function createRgbAccumulator(): RgbAccumulator {
  return { n: 0, sum: [0, 0, 0], sumSq: [0, 0, 0], clipped: 0 };
}

/** Adds the centre region of one frame (sRGB 0..1) to the accumulator. Returns acc. */
export function addImageDataToAccumulator(acc: RgbAccumulator, image: ImageLike): RgbAccumulator {
  const { x0, y0, w, h } = centreRect(image);
  for (let y = y0; y < y0 + h; y++) {
    const row = y * image.width * 4;
    for (let x = x0; x < x0 + w; x++) {
      const i = row + x * 4;
      const r = image.data[i] / 255, g = image.data[i + 1] / 255, b = image.data[i + 2] / 255;
      acc.sum[0] += r; acc.sum[1] += g; acc.sum[2] += b;
      acc.sumSq[0] += r * r; acc.sumSq[1] += g * g; acc.sumSq[2] += b * b;
      const clipped = image.data[i] >= CLIP_LEVEL || image.data[i + 1] >= CLIP_LEVEL || image.data[i + 2] >= CLIP_LEVEL;
      if (clipped) acc.clipped++;
      acc.n++;
    }
  }
  return acc;
}

/** Pooled centre-region stats: mean/std per channel (sRGB 0..1), clipped fraction. Empty input gives zeros. */
export function rgbStatsFromAccumulator(acc: RgbAccumulator): RGBStats {
  if (acc.n === 0) return { mean: [0, 0, 0], std: [0, 0, 0], clipped: 0 };
  const mean: RGB = [acc.sum[0] / acc.n, acc.sum[1] / acc.n, acc.sum[2] / acc.n];
  const std: RGB = [0, 1, 2].map((c) => Math.sqrt(Math.max(0, acc.sumSq[c] / acc.n - mean[c] * mean[c]))) as RGB;
  return { mean, std, clipped: acc.clipped / acc.n };
}

/** Centre-region RGB stats of one frame: mean/std per channel (sRGB 0..1), clipped fraction. */
export function rgbStatsFromImageData(image: ImageLike): RGBStats {
  return rgbStatsFromAccumulator(addImageDataToAccumulator(createRgbAccumulator(), image));
}
