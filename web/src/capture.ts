import { captureScreenlight } from "./sensors/screenlight";
import { el } from "./util";

async function openCamera(facing: "environment" | "user", width = 1920, height = 1080) {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser can't open the camera. Use the photo upload instead.");
  return navigator.mediaDevices.getUserMedia({
    audio: false,
    video: { facingMode: { ideal: facing }, width: { ideal: width }, height: { ideal: height } },
  });
}

const stop = (s: MediaStream | null) => s?.getTracks().forEach((t) => t.stop());

/** Rear camera with a guide frame for the reference card. Resolves with a JPEG. */
export function cardCapture(root: HTMLElement, onImage: (jpeg: Blob) => void): () => void {
  const box = el(`
    <div class="capture">
      <div class="viewfinder">
        <video playsinline muted autoplay></video>
        <div class="guide" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
      </div>
      <p class="hint">Fit the whole card inside the frame. All four black corner squares must show.</p>
      <div class="row">
        <button class="btn primary shutter">Take photo</button>
        <label class="btn ghost">Upload a photo<input type="file" accept="image/*" capture="environment" hidden></label>
      </div>
      <p class="cam-error" role="alert"></p>
    </div>`);
  root.append(box);
  const video = box.querySelector("video")!;
  const err = box.querySelector<HTMLElement>(".cam-error")!;
  let stream: MediaStream | null = null;

  openCamera("environment")
    .then((s) => { stream = s; video.srcObject = s; })
    .catch((e) => { err.textContent = `${(e as Error).message || "Camera unavailable."} You can upload a photo instead.`; });

  box.querySelector(".shutter")!.addEventListener("click", () => {
    if (!video.videoWidth) { err.textContent = "The camera isn't ready yet."; return; }
    const c = document.createElement("canvas");
    c.width = video.videoWidth; c.height = video.videoHeight;
    c.getContext("2d")!.drawImage(video, 0, 0);
    c.toBlob((b) => b && onImage(b), "image/jpeg", 0.92);
  });
  box.querySelector<HTMLInputElement>("input[type=file]")!.addEventListener("change", (e) => {
    const f = (e.target as HTMLInputElement).files?.[0];
    if (f) onImage(f);
  });
  return () => stop(stream);
}

/**
 * Screen-light scan for the reagent lab tests: countdown UI plus the shared sweep in
 * sensors/screenlight.ts. Returns colour -> list of mean [r,g,b] (0..1) per frame.
 */
export function screenlightCapture(
  root: HTMLElement, sequence: string[], frameMs: number,
  onFrames: (frames: Record<string, number[][]>) => void,
): () => void {
  const box = el(`
    <div class="capture">
      <p class="hint">Turn screen brightness all the way up. Put the phone in the hood with the screen facing the sample.
      The scan starts 3 seconds after you tap.</p>
      <button class="btn primary">Start light scan</button>
      <p class="cam-error" role="alert"></p>
    </div>`);
  root.append(box);
  const err = box.querySelector<HTMLElement>(".cam-error")!;
  const ctrl = new AbortController();
  let running = false;

  box.querySelector("button")!.addEventListener("click", async () => {
    if (running) return;
    running = true;
    err.textContent = "";
    const countdown = el(`<div class="flash" role="status" aria-live="polite"><span>Starting in 3</span></div>`);
    try {
      document.body.append(countdown);
      for (let n = 3; n > 0; n--) {
        countdown.querySelector("span")!.textContent = `Starting in ${n}`;
        await wait(1000, ctrl.signal);
      }
      countdown.remove();
      const { frames } = await captureScreenlight({ sequence, frameMs, signal: ctrl.signal });
      onFrames(frames);
    } catch (e) {
      countdown.remove();
      if (ctrl.signal.aborted) return;
      err.textContent = (e as Error).message || "The scan didn't complete.";
    } finally {
      running = false;
    }
  });
  return () => ctrl.abort();
}

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException("Cancelled.", "AbortError"));
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Cancelled.", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });

/**
 * Muse Voice Transcribe takes only mono 16-bit PCM WAV at 16 or 24 kHz, while browsers record
 * WebM or MP4. Decode the recording, mix it to mono at 16 kHz and wrap it as WAV.
 */
export async function toWav16k(recording: Blob): Promise<Blob> {
  const RATE = 16000;
  const ctx = new AudioContext();
  let decoded: AudioBuffer;
  try { decoded = await ctx.decodeAudioData(await recording.arrayBuffer()); } finally { void ctx.close(); }
  const frames = Math.max(1, Math.ceil(decoded.duration * RATE));
  const offline = new OfflineAudioContext(1, frames, RATE); // one channel: the browser downmixes
  const src = offline.createBufferSource();
  src.buffer = decoded;
  src.connect(offline.destination);
  src.start();
  const pcm = (await offline.startRendering()).getChannelData(0);

  const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const text = (at: number, s: string) => { for (let i = 0; i < s.length; i++) out.setUint8(at + i, s.charCodeAt(i)); };
  text(0, "RIFF"); out.setUint32(4, 36 + pcm.length * 2, true); text(8, "WAVE");
  text(12, "fmt "); out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
  out.setUint32(24, RATE, true); out.setUint32(28, RATE * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true);
  text(36, "data"); out.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) {
    const v = Math.max(-1, Math.min(1, pcm[i]));
    out.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true);
  }
  return new Blob([out.buffer], { type: "audio/wav" });
}

/** Push-to-talk recorder. Resolves with WAV the transcription model accepts. */
export function recorder() {
  let rec: MediaRecorder | null = null;
  let chunks: Blob[] = [];
  let stream: MediaStream | null = null;
  return {
    async start() {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunks = [];
      rec = new MediaRecorder(stream);
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.start();
    },
    stop(): Promise<Blob> {
      return new Promise((resolve) => {
        if (!rec) return resolve(new Blob());
        rec.onstop = () => {
          stop(stream);
          const recording = new Blob(chunks, { type: rec?.mimeType || "audio/webm" });
          toWav16k(recording).then(resolve, () => resolve(new Blob()));
        };
        rec.stop();
      });
    },
  };
}
