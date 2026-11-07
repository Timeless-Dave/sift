/**
 * The front door: a live viewfinder, what Sift thinks it's looking at, and one Scan control.
 */
import { scanApi, type Food } from "../api";
import { SCREEN_COLOURS, SCREEN_SEQUENCE, SENSOR_INFO, available, scanFood, type ScanStage } from "../scanner";
import { detectBarcode, support as barcodeSupport } from "../sensors/barcode";
import { requestMotionPermission } from "../sensors/motion";
import { el, esc, getDevice, getTier, go } from "../util";

const FOOD_KEY = "sift.food";
const spectrum = () =>
  `<span class="spectrum" aria-hidden="true">${SCREEN_SEQUENCE.map((c) => `<i style="background:${SCREEN_COLOURS[c]}"></i>`).join("")}</span>`;

export async function scanView(root: HTMLElement): Promise<() => void> {
  const foods = await scanApi.foods();
  const byId = new Map(foods.map((f) => [f.id, f]));
  let food: Food | undefined = byId.get(readFood() ?? "") ?? undefined;
  let stream: MediaStream | null = null;
  let barcodeTimer: number | undefined;
  let lastBarcode = "";
  let scanning: AbortController | null = null;
  const research = getTier() === "research";

  root.innerHTML = `
    <section class="scanner">
      <div class="viewfinder" data-state="idle">
        <video playsinline muted></video>
        <div class="reticle" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
        <button class="start-cam" type="button">
          ${spectrum()}
          <strong>Point at food or a barcode</strong>
          <span>Tap to start the camera</span>
        </button>
        <p class="vf-status" role="status" aria-live="polite"></p>
      </div>

      <div class="deck">
        <div class="checking">
          <span class="eyebrow">Checking</span>
          <button class="food-pick" type="button" aria-expanded="false"></button>
          <button class="ask" type="button" hidden>What is this?</button>
        </div>
        <div class="food-list" hidden>
          ${foods.map((f) => `<button type="button" class="chip" data-food="${esc(f.id)}">${esc(f.name)}</button>`).join("")}
        </div>
        <p class="placement"></p>
        <ul class="sensor-list"></ul>
        ${research ? `<label class="ref-toggle"><input type="checkbox"> Add as a reference scan</label>
          <div class="ref-form" hidden>
            <select name="label">
              <option value="genuine">Genuine (known good)</option>
              <option value="adulterated">Adulterated (known)</option>
              <option value="conventional">Conventional meat</option>
              <option value="cultured">Cultivated (lab-grown) meat</option>
            </select>
            <input name="note" maxlength="200" placeholder="What is it? e.g. 20% sunflower oil, lab-mixed">
          </div>` : ""}
        <button class="scan-btn" type="button" disabled>Scan</button>
        <p class="muted fine">About 10 seconds, phone only. Nothing leaves the phone except measurements.</p>
      </div>
    </section>`;

  const vf = root.querySelector<HTMLElement>(".viewfinder")!;
  const video = vf.querySelector("video")!;
  const status = vf.querySelector<HTMLElement>(".vf-status")!;
  const pick = root.querySelector<HTMLButtonElement>(".food-pick")!;
  const list = root.querySelector<HTMLElement>(".food-list")!;
  const ask = root.querySelector<HTMLButtonElement>(".ask")!;
  const placement = root.querySelector<HTMLElement>(".placement")!;
  const sensors = root.querySelector<HTMLElement>(".sensor-list")!;
  const scanBtn = root.querySelector<HTMLButtonElement>(".scan-btn")!;
  const refToggle = root.querySelector<HTMLInputElement>(".ref-toggle input");
  const refForm = root.querySelector<HTMLElement>(".ref-form");
  refToggle?.addEventListener("change", () => { refForm!.hidden = !refToggle.checked; paint(); });

  function paint() {
    pick.textContent = food ? food.name : "Choose a food";
    pick.classList.toggle("empty", !food);
    placement.textContent = food ? food.scan.placement : "Point the camera at the food or its barcode, or choose it.";
    sensors.innerHTML = food ? available(food.scan.modalities).map((a) => {
      const info = SENSOR_INFO[a.modality];
      return `<li class="${a.ok ? "" : "off"}"><b>${esc(info?.name ?? a.modality)}</b> <span>${esc(a.ok ? info?.what : (a.reason || "Not available on this phone"))}</span></li>`;
    }).join("") : "";
    const usable = food ? available(food.scan.modalities).some((a) => a.ok) : false;
    scanBtn.disabled = !food || !usable;
    scanBtn.textContent = refToggle?.checked ? "Scan as reference" : "Scan";
  }

  function choose(id: string, why = "") {
    const f = byId.get(id);
    if (!f) return;
    food = f; saveFood(id);
    list.hidden = true; pick.setAttribute("aria-expanded", "false");
    if (why) say(why);
    paint();
  }

  pick.addEventListener("click", () => {
    list.hidden = !list.hidden;
    pick.setAttribute("aria-expanded", String(!list.hidden));
  });
  list.addEventListener("click", (e) => {
    const id = (e.target as HTMLElement).closest<HTMLElement>("[data-food]")?.dataset.food;
    if (id) choose(id);
  });

  const say = (msg: string) => { status.textContent = msg; };

  async function startCamera() {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
      video.srcObject = stream;
      await video.play();
      vf.dataset.state = "live";
      ask.hidden = false;
      say(barcodeSupport().available ? "Looking for a barcode…" : "Tap “What is this?” or choose the food.");
      if (barcodeSupport().available) barcodeTimer = window.setInterval(lookForBarcode, 900);
    } catch (e) {
      vf.dataset.state = "denied";
      say(`${(e as Error).message || "The camera is unavailable."} Choose the food below instead.`);
    }
  }
  function stopCamera() {
    clearInterval(barcodeTimer);
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
    if (vf.dataset.state === "live") vf.dataset.state = "idle";
  }

  async function lookForBarcode() {
    if (!stream || scanning) return;
    const code = await detectBarcode(video).catch(() => null);
    if (!code || code === lastBarcode) return;
    lastBarcode = code;
    say(`Barcode ${code}: looking it up…`);
    try {
      const p = await scanApi.product(code);
      if (p.food) choose(p.food, `${p.name ?? "Product"}${p.brands ? `, ${p.brands}` : ""}`);
      else say(`${p.name ?? `Barcode ${code}`}: Sift has no profile for this product yet. Choose the closest food.`);
    } catch (e) { say((e as Error).message); }
  }

  ask.addEventListener("click", async () => {
    if (!video.videoWidth) return;
    ask.disabled = true; say("Asking the Lab Agent what this is…");
    try {
      const c = document.createElement("canvas");
      const scale = Math.min(1, 1024 / Math.max(video.videoWidth, video.videoHeight));
      c.width = Math.round(video.videoWidth * scale); c.height = Math.round(video.videoHeight * scale);
      c.getContext("2d")!.drawImage(video, 0, 0, c.width, c.height);
      const jpeg = await new Promise<Blob>((r, j) => c.toBlob((b) => (b ? r(b) : j(new Error("No frame"))), "image/jpeg", 0.85));
      const id = await scanApi.identify(jpeg);
      if (id.food) choose(id.food, `Looks like ${byId.get(id.food)?.name.toLowerCase()} (${Math.round(id.confidence * 100)}% sure). Change it if not.`);
      else if (id.agent === "offline") say("The Lab Agent is offline. Choose the food below.");
      else {
        say(id.seen ? `Not sure: ${id.seen}. Pick one:` : "Not sure what this is. Pick one:");
        list.hidden = false; pick.setAttribute("aria-expanded", "true");
        list.querySelectorAll<HTMLElement>(".chip").forEach((ch) => ch.classList.toggle("hint", id.candidates.includes(ch.dataset.food!)));
      }
    } catch (e) { say((e as Error).message); }
    ask.disabled = false;
  });

  vf.querySelector(".start-cam")!.addEventListener("click", startCamera);

  scanBtn.addEventListener("click", async () => {
    if (!food) return;
    await requestMotionPermission().catch(() => undefined); // iOS needs this inside the tap
    stopCamera();
    scanning = new AbortController();
    const overlay = el(`<div class="scan-overlay" role="dialog" aria-modal="true" aria-label="Scanning">
        ${spectrum()}
        <p class="pose"></p>
        <p class="stage"></p>
        <div class="bar"><i></i></div>
        <button type="button" class="btn ghost cancel">Cancel</button>
      </div>`);
    document.body.append(overlay);
    const pose = overlay.querySelector<HTMLElement>(".pose")!;
    const stage = overlay.querySelector<HTMLElement>(".stage")!;
    const bar = overlay.querySelector<HTMLElement>(".bar i")!;
    overlay.querySelector(".cancel")!.addEventListener("click", () => scanning?.abort());

    const beforePose = async (instruction: string) => {
      pose.textContent = instruction;
      for (let n = 3; n > 0; n--) { stage.textContent = `Starting in ${n}`; await wait(1000, scanning!.signal); }
    };
    const onStage = (s: ScanStage) => {
      pose.textContent = s.instruction;
      if (s.modality) stage.textContent = `${SENSOR_INFO[s.modality]?.name ?? s.modality}${s.hint ? `: ${s.hint}` : ""}`;
      bar.style.width = `${Math.round((s.fraction ?? 0) * 100)}%`;
    };
    try {
      const capture = await scanFood(food.scan.modalities, onStage, beforePose, scanning.signal);
      stage.textContent = "Comparing with reference scans…";
      const device = await getDevice();
      const reference = refToggle?.checked ? {
        label: (refForm!.querySelector("select") as HTMLSelectElement).value as "genuine",
        note: (refForm!.querySelector("input") as HTMLInputElement).value.trim(),
      } : undefined;
      const result = await scanApi.scan({
        food: food.id, device, mode: reference ? "reference" : "check", ...(reference ? { reference } : {}),
        ...(lastBarcode ? { product: { barcode: lastBarcode } } : {}), capture,
      });
      try { sessionStorage.setItem(`sift.capture.${result.scan_id}`, JSON.stringify(capture)); } catch { /* storage off */ }
      overlay.remove();
      go(`#/scan/${result.scan_id}`);
    } catch (e) {
      overlay.remove();
      const aborted = (e as Error).name === "AbortError";
      say(aborted ? "Scan cancelled." : (e as Error).message);
      vf.dataset.state = "idle";
    } finally {
      scanning = null;
    }
  });

  paint();
  return () => { scanning?.abort(); stopCamera(); };
}

function wait(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => { clearTimeout(t); reject(new DOMException("Scan cancelled", "AbortError")); }, { once: true });
  });
}
function readFood() { try { return localStorage.getItem(FOOD_KEY); } catch { return null; } }
function saveFood(id: string) { try { localStorage.setItem(FOOD_KEY, id); } catch { /* storage off */ } }
