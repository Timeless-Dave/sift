/** Synthetic-signal tests for the scanner DSP. Run with `npm test` (Node strips types, no build needed). */
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  addImageDataToAccumulator,
  brightnessCentroid,
  bubbleFront,
  bubbleRiseTime,
  CENTRE_FRACTION,
  CLIP_LEVEL,
  clippedFraction,
  createRgbAccumulator,
  DB_FLOOR,
  downsampleEvenly,
  fft,
  floorPowerOfTwo,
  hannWindow,
  isPowerOfTwo,
  logBinPower,
  logBandMeans,
  mean,
  meanRgbFromImageData,
  meanRgbFullFrame,
  normaliseSpectrum,
  rgbStatsFromAccumulator,
  rgbStatsFromImageData,
  ringProfile,
  rms,
  std,
  trackedFraction,
  welchPower,
  type ImageLike,
} from "../src/sensors/dsp.ts";

const near = (a: number, b: number, tol: number, msg: string) =>
  assert.ok(Math.abs(a - b) <= tol, `${msg}: ${a} vs ${b} (tol ${tol})`);

function cosine(n: number, bin: number, amp = 1): Float64Array {
  const x = new Float64Array(n);
  for (let i = 0; i < n; i++) x[i] = amp * Math.cos((2 * Math.PI * bin * i) / n);
  return x;
}

function magnitude(re: Float64Array, im: Float64Array): number[] {
  return Array.from(re, (_, k) => Math.hypot(re[k], im[k]));
}

function argmax(x: ArrayLike<number>, lo = 0, hi = x.length): number {
  let best = lo;
  for (let i = lo + 1; i < hi; i++) if (x[i] > x[best]) best = i;
  return best;
}

/** Wire limits from docs/scanner.md: bins <= 128, increasing, within 100-24000 Hz, finite levels. */
function assertWireBands(bins_hz: number[], levels_db: number[]) {
  assert.equal(bins_hz.length, levels_db.length);
  assert.ok(bins_hz.length <= 128, `too many bins: ${bins_hz.length}`);
  for (let i = 0; i < bins_hz.length; i++) {
    assert.ok(Number.isFinite(bins_hz[i]), `bin ${i} not finite`);
    assert.ok(Number.isFinite(levels_db[i]), `level ${i} not finite`);
    assert.ok(bins_hz[i] >= 100 && bins_hz[i] <= 24000, `bin ${i}=${bins_hz[i]} out of 100-24000`);
    if (i > 0) assert.ok(bins_hz[i] > bins_hz[i - 1], `bins not increasing at ${i}`);
  }
}

describe("fft", () => {
  it("peaks in the right bin for a pure tone", () => {
    for (const bin of [1, 7, 10, 63]) {
      const re = cosine(256, bin), im = new Float64Array(256);
      fft(re, im);
      const mag = magnitude(re, im);
      assert.equal(argmax(mag, 0, 128), bin, `cosine bin ${bin}`);
      // Tone energy dominates leakage: peak is 100x the median bin.
      const sorted = [...mag.slice(0, 128)].sort((a, b) => a - b);
      assert.ok(mag[bin] > 100 * sorted[64], `peak-to-median for bin ${bin}`);
    }
  });

  it("peaks in the right bin for a sine (imaginary part)", () => {
    const n = 128, re = new Float64Array(n), im = new Float64Array(n);
    for (let i = 0; i < n; i++) re[i] = Math.sin((2 * Math.PI * 5 * i) / n);
    fft(re, im);
    assert.equal(argmax(magnitude(re, im), 0, 64), 5);
  });

  it("rejects bad lengths", () => {
    assert.throws(() => fft(new Float64Array(100), new Float64Array(100)), RangeError);
    assert.throws(() => fft(new Float64Array(64), new Float64Array(32)), RangeError);
    assert.throws(() => fft(new Float64Array(0), new Float64Array(0)), RangeError);
  });

  it("helpers classify powers of two", () => {
    assert.equal(isPowerOfTwo(1024), true);
    assert.equal(isPowerOfTwo(1000), false);
    assert.equal(isPowerOfTwo(0), false);
    assert.equal(floorPowerOfTwo(1000), 512);
    assert.equal(floorPowerOfTwo(64), 64);
    assert.equal(floorPowerOfTwo(0), 0);
  });
});

describe("hannWindow", () => {
  it("tapers to zero at both ends and peaks near one", () => {
    const w = hannWindow(64);
    assert.equal(w.length, 64);
    assert.equal(w[0], 0);
    assert.equal(w[63], 0);
    const peak = Math.max(...w);
    assert.ok(peak > 0.999 && peak <= 1, `peak ${peak}`);
    for (let i = 0; i < 64; i++) near(w[i], w[63 - i], 1e-12, `symmetry ${i}`);
  });

  it("handles n = 1 and rejects n < 1", () => {
    assert.deepEqual([...hannWindow(1)], [1]);
    assert.throws(() => hannWindow(0), RangeError);
  });
});

describe("mean/std/rms", () => {
  it("matches textbook values", () => {
    near(mean([1, 2, 3, 4]), 2.5, 1e-12, "mean");
    near(std([2, 4, 4, 4, 5, 5, 7, 9]), 2, 1e-12, "std");
    near(rms(cosine(1024, 3, 2)), 2 / Math.SQRT2, 1e-9, "sine rms = A/sqrt(2)");
    assert.equal(rms([0, 0, 0]), 0);
    assert.equal(rms([-3]), 3);
  });

  it("returns 0, never NaN, for empty input", () => {
    assert.equal(mean([]), 0);
    assert.equal(std([]), 0);
    assert.equal(rms([]), 0);
  });
});

describe("welchPower", () => {
  it("levels a pure tone at A^2/2 regardless of segment size", () => {
    const sr = 48000;
    for (const seg of [1024, 4096]) {
      const k = 8, f = (k * sr) / seg; // bin-centred tone, amplitude 0.5
      const x = new Float64Array(sr);
      for (let i = 0; i < sr; i++) x[i] = 0.5 * Math.cos((2 * Math.PI * f * i) / sr);
      const { freqs, power } = welchPower(x, sr, seg);
      assert.equal(freqs.length, seg / 2 + 1);
      assert.equal(freqs[0], 0);
      near(freqs[freqs.length - 1], sr / 2, 1e-9, "last freq is Nyquist");
      const peak = argmax(power);
      near(freqs[peak], f, sr / seg, "tone lands in the right bin");
      near(power[peak], 0.125, 0.125 * 0.06, `tone level (seg ${seg})`); // A^2/2 = 0.125
    }
  });

  it("scales totals by the Hann noise bandwidth (1.5x the mean square)", () => {
    const sr = 8192, n = 8192; // bin-centred tones + DC tile the segments exactly
    const x = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      x[i] = 1 + 0.6 * Math.cos((2 * Math.PI * 20 * i) / sr) + 0.4 * Math.cos((2 * Math.PI * 92 * i) / sr);
    }
    const { power } = welchPower(x, sr, 2048);
    const total = power.reduce((a, b) => a + b, 0);
    const expected = 1.5 * (1 + 0.18 + 0.08); // ENBW * (DC^2 + A1^2/2 + A2^2/2)
    near(total, expected, expected * 0.05, "total power");
  });

  it("puts DC in bin zero", () => {
    const { power } = welchPower(new Array(4096).fill(2), 8000, 1024);
    assert.equal(argmax(power), 0);
    near(power[0], 4, 1e-9, "DC level");
  });

  it("shrinks the segment for short signals and rejects tiny ones", () => {
    const { freqs, power } = welchPower(cosine(100, 2), 50, 2048);
    assert.equal(freqs.length, 33); // 64-point segment -> 33 one-sided bins
    assert.equal(power.length, 33);
    assert.throws(() => welchPower([1, 2, 3], 50), RangeError);
  });
});

describe("logBinPower", () => {
  const sr = 48000;
  const flat = welchPower(cosine(sr, 50, 1), sr, 4096);

  it("returns n geometric centres between fLo and fHi", () => {
    const n = 64, fLo = 200, fHi = 20000;
    const { bins_hz, levels_db } = logBinPower(flat.freqs, flat.power, n, fLo, fHi);
    assert.equal(bins_hz.length, n);
    assert.equal(levels_db.length, n);
    for (let i = 0; i < n; i++) {
      const want = fLo * Math.pow(fHi / fLo, (i + 0.5) / n);
      near(bins_hz[i], want, want * 1e-12, `centre ${i}`);
    }
    assert.ok(bins_hz[0] > fLo && bins_hz[n - 1] < fHi, "centres sit strictly inside the edges");
  });

  it("reports mean band power in dB", () => {
    const freqs = [100, 200, 400, 800], power = [1, 1, 1, 1];
    const { levels_db } = logBinPower(freqs, power, 2, 100, 800);
    near(levels_db[0], 0, 1e-9, "0 dB for unit power");
    near(levels_db[1], 0, 1e-9, "0 dB for unit power");
    const quiet = logBinPower(freqs, [0.01, 0.01, 0.01, 0.01], 2, 100, 800);
    near(quiet.levels_db[0], -20, 1e-9, "-20 dB for 0.01 power");
  });

  it("floors empty bands instead of returning -Infinity", () => {
    const { levels_db } = logBinPower([5000], [1], 8, 100, 24000);
    assert.ok(levels_db.every((v) => Number.isFinite(v)), "all finite");
    assert.ok(levels_db.includes(DB_FLOOR), "empty bands hit the floor");
    const silent = logBinPower([100, 200], [0, 0], 2, 100, 800);
    assert.deepEqual(silent.levels_db, [DB_FLOOR, DB_FLOOR]);
  });

  it("ignores out-of-range and non-finite bins", () => {
    const { bins_hz, levels_db } = logBinPower([50, 100, 30000], [9, 1, 9], 1, 100, 1000);
    assert.equal(bins_hz.length, 1);
    near(levels_db[0], 0, 1e-9, "only the in-range bin counts");
    const bad = logBinPower([100, 200], [NaN, Infinity], 1, 100, 1000);
    assert.deepEqual(bad.levels_db, [DB_FLOOR]);
  });

  it("rejects bad arguments", () => {
    assert.throws(() => logBinPower([1], [1, 2], 4, 100, 1000), RangeError);
    assert.throws(() => logBinPower([], [], 4, 100, 1000), RangeError);
    assert.throws(() => logBinPower([100], [1], 0, 100, 1000), RangeError);
    assert.throws(() => logBinPower([100], [1], 4, 1000, 100), RangeError);
  });
});

describe("wire shape limits (docs/scanner.md)", () => {
  it("acoustic-style binnings satisfy the acoustic limits", () => {
    for (const sampleRate of [44100, 48000]) {
      const fHi = Math.min(20000, 0.45 * sampleRate);
      // Rising chirp stand-in: sum of tones across the band.
      const n = sampleRate, x = new Float64Array(n);
      for (const f of [300, 1500, 8000, 15000, 19000]) {
        for (let i = 0; i < n; i++) x[i] += 0.2 * Math.cos((2 * Math.PI * f * i) / sampleRate);
      }
      const { freqs, power } = welchPower(x, sampleRate, 4096);
      const { bins_hz, levels_db } = logBinPower(freqs, power, 64, 200, fHi);
      assertWireBands(bins_hz, levels_db);
      for (const v of levels_db) assert.ok(v >= -200 && v <= 60, `level ${v} outside -200..60`);
    }
  });

  it("vibration-style spectra satisfy the spectrum limits", () => {
    const rate = 60, n = 96; // 1.6 s of fake 8 Hz wobble plus noise
    const x = new Float64Array(n);
    let seed = 42;
    const rand = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff - 0.5);
    for (let i = 0; i < n; i++) x[i] = Math.cos((2 * Math.PI * 8 * i) / rate) + 0.1 * rand();
    const { freqs, power } = welchPower(x, rate, 64);
    const { means } = logBandMeans(freqs, power, 32, 1, 0.45 * rate);
    const spectrum = normaliseSpectrum(means);
    assert.ok(spectrum.length <= 64, `spectrum too long: ${spectrum.length}`);
    assert.equal(spectrum.length, 32);
    for (const v of spectrum) {
      assert.ok(Number.isFinite(v), "spectrum must be finite");
      assert.ok(v >= 0 && v <= 1000, `spectrum value ${v} out of range`);
    }
    near(Math.max(...spectrum), 1, 1e-12, "peak-normalised");
  });

  it("silence normalises to zeros, not NaN", () => {
    assert.deepEqual(normaliseSpectrum([0, 0, 0]), [0, 0, 0]);
    assert.deepEqual(normaliseSpectrum([]), []);
  });
});

describe("RGB stats", () => {
  const W = 10, H = 10; // centre 4x4 at x,y in [3, 7)
  function image(fill: (x: number, y: number) => [number, number, number]): ImageLike {
    const data = new Uint8ClampedArray(W * H * 4);
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const [r, g, b] = fill(x, y), i = (y * W + x) * 4;
        data[i] = r; data[i + 1] = g; data[i + 2] = b; data[i + 3] = 255;
      }
    }
    return { data, width: W, height: H };
  }
  const inCentre = (x: number, y: number) => x >= 3 && x < 7 && y >= 3 && y < 7;

  it("reads mean and std from the centre region only", () => {
    const img = image((x, y) => (inCentre(x, y) ? [128, 64, 0] : [255, 255, 255])); // white surround must not leak in
    const s = rgbStatsFromImageData(img);
    near(s.mean[0], 128 / 255, 1e-12, "red mean");
    near(s.mean[1], 64 / 255, 1e-12, "green mean");
    assert.equal(s.mean[2], 0);
    assert.deepEqual(s.std, [0, 0, 0]);
    assert.equal(s.clipped, 0);
    const m = meanRgbFromImageData(img);
    near(m[0], 128 / 255, 1e-12, "frame mean red");
  });

  it("measures spread across centre pixels", () => {
    const img = image((x, y) => (!inCentre(x, y) ? [0, 0, 0] : x % 2 ? [200, 0, 0] : [100, 0, 0]));
    const s = rgbStatsFromImageData(img);
    near(s.mean[0], 150 / 255, 1e-12, "two-tone mean");
    near(s.std[0], 50 / 255, 1e-12, "two-tone std");
    assert.equal(s.std[1], 0);
  });

  it("counts a pixel as clipped when any channel reaches 250", () => {
    // 16 centre pixels: one clipped in red, one in green, one in blue, rest dark.
    let k = 0;
    const img = image((x, y) => {
      if (!inCentre(x, y)) return [255, 255, 255]; // surround never counts
      k++;
      if (k === 1) return [250, 0, 0];
      if (k === 2) return [0, 255, 10];
      if (k === 3) return [5, 5, 250];
      return [10, 10, 10];
    });
    const s = rgbStatsFromImageData(img);
    near(s.clipped, 3 / 16, 1e-12, "clipped fraction");
    assert.equal(rgbStatsFromImageData(image(() => [249, 249, 249])).clipped, 0, "249 is not clipped");
    assert.equal(rgbStatsFromImageData(image(() => [255, 255, 255])).clipped, 1, "white is fully clipped");
  });

  it("pools several frames through the accumulator", () => {
    const acc = createRgbAccumulator();
    addImageDataToAccumulator(acc, image(() => [100, 0, 0]));
    addImageDataToAccumulator(acc, image(() => [200, 0, 0]));
    const s = rgbStatsFromAccumulator(acc);
    near(s.mean[0], 150 / 255, 1e-12, "pooled mean");
    near(s.std[0], 50 / 255, 1e-9, "pooled std");
    assert.deepEqual(rgbStatsFromAccumulator(createRgbAccumulator()), {
      mean: [0, 0, 0], std: [0, 0, 0], clipped: 0,
    });
  });

  it("rejects short pixel buffers", () => {
    assert.throws(() => rgbStatsFromImageData({ data: new Uint8ClampedArray(8), width: W, height: H }), RangeError);
  });

  it(`uses a ${CENTRE_FRACTION} centre region and a ${CLIP_LEVEL} clip level`, () => {
    assert.equal(CENTRE_FRACTION, 0.4);
    assert.equal(CLIP_LEVEL, 250);
  });
});

describe("contact helpers", () => {
  const W = 12, H = 8;
  function image(fill: (x: number, y: number) => [number, number, number]): ImageLike {
    const data = new Uint8ClampedArray(W * H * 4);
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const [r, g, b] = fill(x, y), i = (y * W + x) * 4;
        data[i] = r; data[i + 1] = g; data[i + 2] = b; data[i + 3] = 255;
      }
    }
    return { data, width: W, height: H };
  }

  it("reads the full-frame mean and clipped fraction", () => {
    const m = meanRgbFullFrame(image(() => [100, 150, 200]));
    near(m[0], 100 / 255, 1e-12, "red");
    near(m[1], 150 / 255, 1e-12, "green");
    near(m[2], 200 / 255, 1e-12, "blue");
    assert.equal(clippedFraction(image(() => [255, 255, 255])), 1);
    assert.equal(clippedFraction(image(() => [249, 249, 249])), 0);
    // Left half clipped in one channel, right half dark.
    assert.equal(clippedFraction(image((x) => (x < W / 2 ? [250, 0, 0] : [10, 10, 10]))), 0.5);
  });

  it("finds the brightness centroid, or the centre when black", () => {
    const c = brightnessCentroid(image((x, y) => (x === 9 && y === 2 ? [255, 255, 255] : [0, 0, 0])));
    assert.deepEqual(c, { cx: 9, cy: 2 });
    const flat = brightnessCentroid(image(() => [40, 40, 40]));
    near(flat.cx, (W - 1) / 2, 1e-12, "uniform cx is centred");
    near(flat.cy, (H - 1) / 2, 1e-12, "uniform cy is centred");
    assert.deepEqual(brightnessCentroid(image(() => [0, 0, 0])), { cx: (W - 1) / 2, cy: (H - 1) / 2 });
  });

  it("profiles a uniform frame as equal rings", () => {
    const rings = ringProfile(image(() => [120, 60, 30]), 5, 3, 8);
    assert.equal(rings.length, 8);
    for (const [r, g, b] of rings) {
      near(r, 120 / 255, 1e-12, "ring red");
      near(g, 60 / 255, 1e-12, "ring green");
      near(b, 30 / 255, 1e-12, "ring blue");
    }
  });

  it("shows radial falloff around the centroid", () => {
    const cx = 5, cy = 3;
    const img = image((x, y) => {
      const v = Math.max(0, Math.round(220 - 22 * Math.hypot(x - cx, y - cy)));
      return [v, v, v];
    });
    const rings = ringProfile(img, cx, cy, 4);
    assert.equal(rings.length, 4);
    for (let i = 1; i < rings.length; i++) {
      assert.ok(rings[i][0] < rings[i - 1][0], `ring ${i} dimmer than ring ${i - 1}`);
    }
    assert.ok(rings[0][0] > 0.5, "inner ring is bright");
  });

  it("covers every pixel: one ring is the frame mean", () => {
    const img = image((x, y) => [(x * 20) % 256, (y * 30) % 256, ((x + y) * 10) % 256]);
    const one = ringProfile(img, 2, 6, 1);
    const full = meanRgbFullFrame(img);
    near(one[0][0], full[0], 1e-12, "one ring is the frame mean");
    const rings = ringProfile(img, 2, 6, 8);
    assert.equal(rings.length, 8);
    for (const ring of rings) for (const v of ring) assert.ok(v >= 0 && v <= 1, "ring values stay sRGB 0..1");
  });

  it("rejects bad ring counts", () => {
    const img = image(() => [10, 10, 10]);
    assert.throws(() => ringProfile(img, 5, 3, 0), RangeError);
    assert.throws(() => ringProfile(img, 5, 3, 2.5), RangeError);
  });
});

describe("bubble front detection", () => {
  const W = 8, H = 21; // H - 1 = 20, so fronts land on exact twentieths
  const blank = () => new Float64Array(W * H);
  function blob(top: number, height = 2, value = 200): Float64Array {
    const f = blank();
    for (let y = top; y < Math.min(H, top + height); y++) for (let x = 0; x < W; x++) f[y * W + x] = value;
    return f;
  }

  it("reports nothing for identical frames", () => {
    assert.equal(bubbleFront(blank(), blank(), W, H), null);
    const f = blob(10);
    assert.equal(bubbleFront(f, Float64Array.from(f), W, H), null);
  });

  it("finds the highest changed row as a fraction from the bottom", () => {
    assert.equal(bubbleFront(blank(), blob(4), W, H), (H - 1 - 4) / (H - 1));
    assert.equal(bubbleFront(blank(), blob(0), W, H), 1); // top row is the top of the frame
    const bottom = blank();
    for (let x = 0; x < W; x++) bottom[(H - 1) * W + x] = 200;
    assert.equal(bubbleFront(blank(), bottom, W, H), 0); // bottom row is the bottom
  });

  it("ignores motion outside the centre column band", () => {
    const prev = blank(), curr = blank();
    for (let y = 0; y < H; y++) curr[y * W] = 200; // first column only, outside the band
    assert.equal(bubbleFront(prev, curr, W, H), null);
  });

  it("ignores calm noise below the absolute floor", () => {
    let seed = 7;
    const rand = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff - 0.5);
    const prev = blank(), curr = blank();
    for (let p = 0; p < W * H; p++) { prev[p] = 100 + rand() * 2; curr[p] = 100 + rand() * 2; }
    assert.equal(bubbleFront(prev, curr, W, H), null);
  });

  it("rejects misshapen frames", () => {
    assert.throws(() => bubbleFront(new Float64Array(10), new Float64Array(10), W, H), RangeError);
    assert.throws(() => bubbleFront(blank(), blank(), 0, H), RangeError);
  });

  it("a blob rising at a known speed gives the right rise time", () => {
    // Blob top climbs 2 rows per 0.5 s frame: 4 rows/s over a 20-row span.
    const tops = [18, 16, 14, 12, 10, 8, 6, 4, 2, 0];
    const frames = tops.map((t) => blob(t));
    const times = frames.map((_, i) => i * 0.5);
    const fronts: (number | null)[] = [null];
    for (let i = 1; i < frames.length; i++) fronts.push(bubbleFront(frames[i - 1], frames[i], W, H));
    assert.equal(trackedFraction(fronts.slice(1)), 1);
    // Front crosses 0.2 at y=16 (t=0.5) and 0.8 at y=4 (t=3.5): 0.6 * 20 rows at 4 rows/s.
    assert.equal(bubbleRiseTime(times, fronts), 3);
  });

  it("static noise gives tracked_fraction near 0 and a null rise time", () => {
    let seed = 42;
    const rand = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff - 0.5);
    const frames: Float64Array[] = [];
    for (let f = 0; f < 12; f++) {
      const frame = blank();
      for (let p = 0; p < W * H; p++) frame[p] = 100 + rand() * 2;
      frames.push(frame);
    }
    const times = frames.map((_, i) => i * 0.1);
    const fronts: (number | null)[] = [null];
    for (let i = 1; i < frames.length; i++) fronts.push(bubbleFront(frames[i - 1], frames[i], W, H));
    assert.ok(trackedFraction(fronts.slice(1)) < 0.1, "almost nothing tracked");
    assert.equal(bubbleRiseTime(times, fronts), null);
  });

  it("rise time skips missed frames and needs the full crossing", () => {
    assert.equal(bubbleRiseTime([0, 1, 2, 3], [0.1, null, 0.5, 0.9]), 1); // 0.2 crossed at t=2, 0.8 at t=3
    assert.equal(bubbleRiseTime([0, 1, 2, 3], [0.3, null, 0.5, 0.9]), 3);
    assert.equal(bubbleRiseTime([0, 1, 2], [0.3, 0.5, 0.6]), null); // never reaches 0.8
    assert.equal(bubbleRiseTime([0, 1], [null, null]), null);
    assert.equal(trackedFraction([]), 0);
    assert.throws(() => bubbleRiseTime([0, 1], [0.5]), RangeError);
    assert.throws(() => bubbleRiseTime([0, 1], [0.5, 0.6], 0.8, 0.2), RangeError);
  });

  it("downsamples long tracks evenly and caps at the wire limit", () => {
    const track = Array.from({ length: 10 }, (_, i) => i);
    assert.deepEqual(downsampleEvenly(track, 5), [0, 2, 5, 7, 9]); // first and last kept
    const short = [0.1, 0.2];
    const copy = downsampleEvenly(short, 240);
    assert.deepEqual(copy, short);
    assert.notEqual(copy, short);
    assert.equal(downsampleEvenly(new Array(300).fill(0), 240).length, 240);
    assert.deepEqual(downsampleEvenly(track, 1), [0]);
    assert.throws(() => downsampleEvenly(track, 0), RangeError);
  });
});
