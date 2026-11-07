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

function assertImage(image: ImageLike): void {
  if (!Number.isInteger(image.width) || !Number.isInteger(image.height) || image.width < 1 || image.height < 1) {
    throw new RangeError(`bad image size ${image.width}x${image.height}`);
  }
  if (image.data.length < image.width * image.height * 4) {
    throw new RangeError("pixel data is shorter than width*height*4");
  }
}

function centreRect(image: ImageLike): { x0: number; y0: number; w: number; h: number } {
  assertImage(image);
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

/** Mean colour of the whole frame, sRGB 0..1 (contact mode has no centre crop: the lens is covered). */
export function meanRgbFullFrame(image: ImageLike): RGB {
  assertImage(image);
  let r = 0, g = 0, b = 0;
  const n = image.width * image.height;
  for (let p = 0; p < n; p++) { r += image.data[p * 4]; g += image.data[p * 4 + 1]; b += image.data[p * 4 + 2]; }
  return [r / n / 255, g / n / 255, b / n / 255];
}

/** Fraction of all frame pixels with any channel at or above CLIP_LEVEL. */
export function clippedFraction(image: ImageLike): number {
  assertImage(image);
  let clipped = 0;
  const n = image.width * image.height;
  for (let p = 0; p < n; p++) {
    if (image.data[p * 4] >= CLIP_LEVEL || image.data[p * 4 + 1] >= CLIP_LEVEL || image.data[p * 4 + 2] >= CLIP_LEVEL) {
      clipped++;
    }
  }
  return clipped / n;
}

/**
 * Brightness-weighted centroid of the full frame (the torch side in contact mode).
 * Falls back to the frame centre when the frame is black, so callers always get a point.
 */
export function brightnessCentroid(image: ImageLike): { cx: number; cy: number } {
  assertImage(image);
  let wsum = 0, xsum = 0, ysum = 0;
  for (let y = 0; y < image.height; y++) {
    const row = y * image.width * 4;
    for (let x = 0; x < image.width; x++) {
      const i = row + x * 4;
      const b = image.data[i] + image.data[i + 1] + image.data[i + 2];
      wsum += b; xsum += x * b; ysum += y * b;
    }
  }
  if (wsum === 0) return { cx: (image.width - 1) / 2, cy: (image.height - 1) / 2 };
  return { cx: xsum / wsum, cy: ysum / wsum };
}

/**
 * Mean sRGB colour in nRings concentric rings of equal width around (cx, cy), out to the
 * farthest corner so every pixel lands in exactly one ring. Empty rings report black.
 */
export function ringProfile(image: ImageLike, cx: number, cy: number, nRings: number): RGB[] {
  assertImage(image);
  if (!Number.isInteger(nRings) || nRings < 1) throw new RangeError(`nRings must be >= 1, got ${nRings}`);
  if (!Number.isFinite(cx) || !Number.isFinite(cy)) throw new RangeError(`centroid must be finite, got ${cx},${cy}`);
  const maxR = Math.max(
    Math.hypot(cx, cy), Math.hypot(cx - (image.width - 1), cy),
    Math.hypot(cx, cy - (image.height - 1)), Math.hypot(cx - (image.width - 1), cy - (image.height - 1)),
  );
  const width = maxR / nRings;
  const sumR = new Float64Array(nRings), sumG = new Float64Array(nRings), sumB = new Float64Array(nRings);
  const count = new Float64Array(nRings);
  for (let y = 0; y < image.height; y++) {
    const row = y * image.width * 4;
    for (let x = 0; x < image.width; x++) {
      const ring = width > 0 ? Math.min(nRings - 1, Math.floor(Math.hypot(x - cx, y - cy) / width)) : 0;
      const i = row + x * 4;
      sumR[ring] += image.data[i]; sumG[ring] += image.data[i + 1]; sumB[ring] += image.data[i + 2];
      count[ring]++;
    }
  }
  const out: RGB[] = [];
  for (let r = 0; r < nRings; r++) {
    out.push(count[r] > 0 ? [sumR[r] / count[r] / 255, sumG[r] / count[r] / 255, sumB[r] / count[r] / 255] : [0, 0, 0]);
  }
  return out;
}

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const s = [...values].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export interface BubbleFrontOptions {
  /** Share of frame width kept as the centre column band (default 0.5). */
  bandFraction?: number;
  /** Threshold is median + k * MAD of the row profile (default 3). */
  k?: number;
  /** Absolute floor for the threshold in grey levels (default 3): calmer frames report no front. */
  minDiff?: number;
}

/**
 * Bubble front height from one frame pair: absolute difference, row-wise mean over a centre
 * column band, adaptive threshold (median + k*MAD, at least minDiff). Returns the highest
 * row above threshold as a fraction of frame height from the bottom (0 bottom, 1 top),
 * or null when no row moves enough to be the bubble. prev and curr are row-major grey
 * levels (0..255) of length width*height.
 */
export function bubbleFront(
  prev: ArrayLike<number>, curr: ArrayLike<number>, width: number, height: number, opts: BubbleFrontOptions = {},
): number | null {
  const { bandFraction = 0.5, k = 3, minDiff = 3 } = opts;
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1) {
    throw new RangeError(`bad frame size ${width}x${height}`);
  }
  if (prev.length !== width * height || curr.length !== width * height) {
    throw new RangeError(`frames must each hold width*height=${width * height} samples`);
  }
  if (!(bandFraction > 0 && bandFraction <= 1)) {
    throw new RangeError(`bandFraction must be in (0, 1], got ${bandFraction}`);
  }
  if (!(k >= 0) || !Number.isFinite(minDiff)) {
    throw new RangeError(`need k >= 0 and a finite minDiff, got ${k},${minDiff}`);
  }
  const bandW = Math.max(1, Math.floor(width * bandFraction));
  const x0 = Math.floor((width - bandW) / 2);
  const rows = new Array<number>(height);
  for (let y = 0; y < height; y++) {
    let s = 0;
    for (let x = x0; x < x0 + bandW; x++) s += Math.abs(curr[y * width + x] - prev[y * width + x]);
    rows[y] = s / bandW;
  }
  const med = median(rows);
  const mad = median(rows.map((v) => Math.abs(v - med)));
  const threshold = Math.max(med + k * mad, minDiff);
  for (let y = 0; y < height; y++) {
    if (rows[y] > threshold) return height > 1 ? (height - 1 - y) / (height - 1) : 1;
  }
  return null;
}

/**
 * Time between the front first reaching lo and first reaching hi (defaults 0.2 and 0.8).
 * Missed frames (null) are skipped, never interpolated. Null when the front never
 * completes the crossing. times and fronts run per frame in the same order.
 */
export function bubbleRiseTime(times: number[], fronts: (number | null)[], lo = 0.2, hi = 0.8): number | null {
  if (times.length !== fronts.length) throw new RangeError("times and fronts need the same length");
  if (!(lo >= 0 && hi <= 1 && lo < hi)) throw new RangeError(`need 0 <= lo < hi <= 1, got ${lo},${hi}`);
  const at = (level: number, from: number): number => {
    for (let i = from; i < fronts.length; i++) if (fronts[i] !== null && (fronts[i] as number) >= level) return i;
    return -1;
  };
  const i = at(lo, 0);
  if (i < 0) return null;
  const j = at(hi, i);
  return j < 0 ? null : times[j] - times[i];
}

/** Share of frames where the front was found (nulls count as missed). 0 when empty. */
export function trackedFraction(fronts: (number | null)[]): number {
  if (fronts.length === 0) return 0;
  return fronts.filter((f) => f !== null).length / fronts.length;
}

/**
 * Evenly thins a per-frame series to at most maxLen entries, keeping the first and last.
 * Short series are returned as a copy. Used to fit the wire's 240-entry track cap.
 */
export function downsampleEvenly<T>(track: T[], maxLen: number): T[] {
  if (!Number.isInteger(maxLen) || maxLen < 1) throw new RangeError(`maxLen must be >= 1, got ${maxLen}`);
  if (track.length <= maxLen) return [...track];
  if (maxLen === 1) return [track[0]];
  const out: T[] = [];
  for (let i = 0; i < maxLen; i++) out.push(track[Math.round((i * (track.length - 1)) / (maxLen - 1))]);
  return out;
}
