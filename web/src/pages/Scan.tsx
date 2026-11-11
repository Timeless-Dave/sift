/**
 * The scanner: a live viewfinder, what Sift thinks it's looking at, one Scan control, and a full-screen
 * guided capture that tells the user when to turn the phone over.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { scanApi, type Food } from "../api";
import { SensorGlyph } from "../components/SensorGlyph";
import { Spectrum } from "../components/Spectrum";
import { SENSOR_INFO, available, scanFood, type ScanStage } from "../scanner";
import { primeAudio } from "../sensors/acoustic";
import { detectBarcode, support as barcodeSupport } from "../sensors/barcode";
import { close as closeCamera, openRearCamera, setTorch, type RearCamera } from "../sensors/camera";
import { requestMotionPermission } from "../sensors/motion";
import type { ReferenceLabel } from "../sensors/types";
import { getDevice, getTier, setTier, type Tier } from "../util";
import "../styles/scanner.css";

const FOOD_KEY = "sift.food";
const read = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const write = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* storage off */ } };

export default function Scan() {
  const navigate = useNavigate();
  const [foods, setFoods] = useState<Food[]>([]);
  const [foodId, setFoodId] = useState<string | null>(read(FOOD_KEY));
  const [tier, setTierState] = useState<Tier>(getTier());
  const [camera, setCamera] = useState<"idle" | "live" | "denied">("idle");
  const [status, setStatus] = useState("");
  const [picking, setPicking] = useState(false);
  const [hints, setHints] = useState<string[]>([]);
  const [asking, setAsking] = useState(false);
  const [asReference, setAsReference] = useState(false);
  const [refLabel, setRefLabel] = useState<ReferenceLabel>("genuine");
  const [refNote, setRefNote] = useState("");
  const [stage, setStage] = useState<{ pose: string; line: string; progress: number } | null>(null);
  const [loadError, setLoadError] = useState("");

  const videoRef = useRef<HTMLVideoElement>(null);
  const camRef = useRef<RearCamera | null>(null);
  const [torchAvailable, setTorchAvailable] = useState(false);
  const [torchOn, setTorchOn] = useState(false);
  const barcodeRef = useRef("");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => { scanApi.foods().then(setFoods).catch((e) => setLoadError((e as Error).message)); }, []);
  const food = useMemo(() => foods.find((f) => f.id === foodId), [foods, foodId]);
  const sensors = useMemo(() => (food ? available(food.scan.modalities) : []), [food]);
  const usable = sensors.some((s) => s.ok);

  const choose = useCallback((id: string, why = "") => {
    setFoodId(id); write(FOOD_KEY, id); setPicking(false); setHints([]);
    if (why) setStatus(why);
  }, []);

  const stopCamera = useCallback(() => {
    closeCamera(camRef.current);   // stopping the track also switches the torch off
    camRef.current = null;
    setTorchOn(false); setTorchAvailable(false);
    setCamera((c) => (c === "live" ? "idle" : c));
  }, []);

  useEffect(() => () => { abortRef.current?.abort(); stopCamera(); }, [stopCamera]);

  // Barcode polling while the camera is live.
  useEffect(() => {
    if (camera !== "live" || !barcodeSupport().available) return;
    const t = window.setInterval(async () => {
      const v = videoRef.current;
      if (!v || abortRef.current) return;
      const code = await detectBarcode(v).catch(() => null);
      if (!code || code === barcodeRef.current) return;
      barcodeRef.current = code;
      setStatus(`Barcode ${code}: looking it up…`);
      try {
        const p = await scanApi.product(code);
        if (p.food) choose(p.food, `${p.name ?? "Product"}${p.brands ? `, ${p.brands}` : ""}`);
        else setStatus(`${p.name ?? `Barcode ${code}`}: Sift has no profile for this product yet. Choose the closest food.`);
      } catch (e) { setStatus((e as Error).message); }
    }, 900);
    return () => clearInterval(t);
  }, [camera, choose]);

  async function startCamera() {
    try {
      // The lens with the flash is also the main lens, which focuses best on barcodes.
      const cam = await openRearCamera({ needTorch: true });
      camRef.current = cam;
      if (videoRef.current) { videoRef.current.srcObject = cam.stream; await videoRef.current.play(); }
      setTorchAvailable(cam.torch);
      setCamera("live");
      setStatus(barcodeSupport().available ? "Point at the barcode, or tap “What is this?”" : "Tap “What is this?” or choose the food.");
    } catch (e) {
      setCamera("denied");
      setStatus(`${(e as Error).message || "The camera is unavailable."} Choose the food instead.`);
    }
  }

  async function toggleTorch() {
    const cam = camRef.current;
    if (!cam) return;
    const want = !torchOn;
    const ok = await setTorch(cam.track, want);
    if (ok) setTorchOn(want);
    else setStatus(want ? "The torch didn't turn on. Another app may be using it." : "The torch didn't switch off.");
  }

  async function identify() {
    const v = videoRef.current;
    if (!v?.videoWidth) return;
    setAsking(true); setStatus("Asking the Lab Agent what this is…");
    try {
      const c = document.createElement("canvas");
      const k = Math.min(1, 1024 / Math.max(v.videoWidth, v.videoHeight));
      c.width = Math.round(v.videoWidth * k); c.height = Math.round(v.videoHeight * k);
      c.getContext("2d")!.drawImage(v, 0, 0, c.width, c.height);
      const jpeg = await new Promise<Blob>((ok, no) => c.toBlob((b) => (b ? ok(b) : no(new Error("No frame"))), "image/jpeg", 0.85));
      const id = await scanApi.identify(jpeg);
      if (id.food) choose(id.food, `Looks like ${foods.find((f) => f.id === id.food)?.name.toLowerCase()} (${Math.round(id.confidence * 100)}% sure). Change it if not.`);
      else if (id.agent === "offline") setStatus("The Lab Agent is offline. Choose the food.");
      else { setStatus(id.seen ? `Not sure: ${id.seen}. Pick one:` : "Not sure what this is. Pick one:"); setHints(id.candidates); setPicking(true); }
    } catch (e) { setStatus((e as Error).message); }
    setAsking(false);
  }

  function toggleTier() {
    const next: Tier = tier === "research" ? "public" : "research";
    setTier(next); setTierState(next); if (next === "public") setAsReference(false);
  }

  async function runScan() {
    if (!food) return;
    // Everything that needs the tap's user activation starts synchronously, before any await:
    // fullscreen for the whole scan, the audio unlock for the sound sweep, and motion permission (iOS).
    const fullscreen = document.fullscreenElement ? null : document.documentElement.requestFullscreen?.().catch(() => undefined);
    primeAudio();
    const motion = requestMotionPermission().catch(() => undefined);
    await Promise.all([fullscreen, motion]);
    stopCamera();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let flipped = false;
    const wait = (ms: number) => new Promise<void>((ok, no) => {
      const t = setTimeout(ok, ms);
      ctrl.signal.addEventListener("abort", () => { clearTimeout(t); no(new DOMException("Scan cancelled", "AbortError")); }, { once: true });
    });
    const beforePose = async (instruction: string) => {
      for (let n = 3; n > 0; n--) { setStage({ pose: instruction, line: `Starting in ${n}`, progress: 0 }); await wait(1000); }
    };
    const onStage = (s: ScanStage) => {
      let pose = s.instruction;
      if (s.modality === "bubble" && (s.fraction ?? 0) >= 0.05) {
        pose = "Turn it upright now";
        if (!flipped) { flipped = true; navigator.vibrate?.(120); }
      }
      const name = s.modality ? SENSOR_INFO[s.modality]?.name ?? s.modality : "";
      setStage({ pose, line: name ? `${name}${s.hint ? `: ${s.hint}` : ""}` : "", progress: s.fraction ?? 0 });
    };
    try {
      setStage({ pose: "Get ready", line: "", progress: 0 });
      const capture = await scanFood(food.scan.modalities, onStage, beforePose, ctrl.signal);
      setStage({ pose: "Comparing with reference scans", line: "", progress: 1 });
      const device = await getDevice();
      const result = await scanApi.scan({
        food: food.id, device, mode: asReference ? "reference" : "check",
        ...(asReference ? { reference: { label: refLabel, note: refNote.trim() } } : {}),
        ...(barcodeRef.current ? { product: { barcode: barcodeRef.current } } : {}), capture,
      });
      try { sessionStorage.setItem(`sift.capture.${result.scan_id}`, JSON.stringify(capture)); } catch { /* storage off */ }
      navigate(`/scan/${result.scan_id}`);
    } catch (e) {
      setStatus((e as Error).name === "AbortError" ? "Scan cancelled." : (e as Error).message);
    } finally {
      abortRef.current = null; setStage(null);
      if (document.fullscreenElement === document.documentElement) await document.exitFullscreen().catch(() => undefined);
    }
  }

  const research = tier === "research";
  return (
    <div className="scanner">
      <header className="scanner-top">
        <Link to="/" className="wordmark light" aria-label="Sift home"><Spectrum />Sift</Link>
        <div className="scanner-top-actions">
          <Link to="/foods" className="top-link">What it checks</Link>
          <button type="button" className="tier" aria-pressed={research} onClick={toggleTier}
            title="Researcher mode: add reference scans of samples you can vouch for">Researcher</button>
        </div>
      </header>

      <section className={`viewfinder ${camera}`} aria-label="Camera">
        <video ref={videoRef} playsInline muted />
        <div className="reticle" aria-hidden="true"><i /><i /><i /><i /></div>
        {camera === "live" && torchAvailable && (
          <button type="button" className={`torch-btn ${torchOn ? "on" : ""}`} aria-pressed={torchOn} onClick={toggleTorch}
            aria-label={torchOn ? "Turn the torch off" : "Turn the torch on"}>
            <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6"
              strokeLinecap="round" strokeLinejoin="round"><path d="M8 3h8l-1 5H9z" /><path d="M9 8h6v4l-1 9h-4l-1-9z" />
              {torchOn && <path d="M4 5l2 1M20 5l-2 1M12 0.5v1.5" />}</svg>
            {torchOn ? "On" : "Torch"}
          </button>
        )}
        {camera !== "live" && (
          <button type="button" className="start" onClick={startCamera}>
            <Spectrum className="big" live />
            <strong>Point at the food<br />or its barcode</strong>
            <span>Tap to start the camera</span>
          </button>
        )}
        {status && <p className="vf-status" role="status" aria-live="polite">{status}</p>}
      </section>

      <section className="deck">
        <div className="checking">
          <span className="eyebrow">Checking</span>
          <button type="button" className={`food-pick ${food ? "" : "empty"}`} aria-expanded={picking} onClick={() => setPicking((p) => !p)}>
            {food ? food.name : "Choose a food"}
          </button>
          {camera === "live" && <button type="button" className="chip" onClick={identify} disabled={asking}>What is this?</button>}
        </div>

        {loadError && <p className="vf-error">{loadError}</p>}
        {(picking || !food) && (
          <div className="food-list" role="listbox" aria-label="Foods">
            {foods.map((f) => (
              <button key={f.id} type="button" className={`chip ${hints.includes(f.id) ? "hint" : ""}`}
                aria-pressed={f.id === foodId} onClick={() => choose(f.id)}>{f.name}</button>
            ))}
          </div>
        )}

        {food && (
          <>
            <p className="placement">{food.scan.placement}</p>
            <ul className="sensor-row">
              {sensors.map((s) => (
                <li key={s.modality} className={s.ok ? "" : "off"} title={s.ok ? SENSOR_INFO[s.modality]?.what : s.reason}>
                  <SensorGlyph kind={s.modality} size={34} />
                  <span>{SENSOR_INFO[s.modality]?.name ?? s.modality}</span>
                  {!s.ok && <em>not on this phone</em>}
                </li>
              ))}
            </ul>
          </>
        )}

        {research && food && (
          <div className="reference">
            <label className="ref-toggle">
              <input type="checkbox" checked={asReference} onChange={(e) => setAsReference(e.target.checked)} />
              Add as a reference scan
            </label>
            {asReference && (
              <div className="ref-form">
                <select value={refLabel} onChange={(e) => setRefLabel(e.target.value as ReferenceLabel)}>
                  <option value="genuine">Genuine (known good)</option>
                  <option value="adulterated">Adulterated (known)</option>
                  <option value="conventional">Conventional meat</option>
                  <option value="cultured">Cultivated (lab-grown) meat</option>
                </select>
                <input value={refNote} maxLength={200} onChange={(e) => setRefNote(e.target.value)}
                  placeholder="What is it? e.g. 20% rice syrup, mixed by weight" />
              </div>
            )}
          </div>
        )}

        <button type="button" className="scan-btn" disabled={!food || !usable} onClick={runScan}>
          {asReference ? "Scan as reference" : "Scan"}
        </button>
        <p className="fine deck-note">About 10 seconds, phone only. Only measurements leave the phone, never images or audio.</p>
      </section>

      {stage && (
        <div className="scan-overlay" role="dialog" aria-modal="true" aria-label="Scanning">
          <Spectrum className="big" live />
          <p className="pose">{stage.pose}</p>
          <p className="stage-line mono">{stage.line}</p>
          <div className="bar"><i style={{ width: `${Math.round(stage.progress * 100)}%` }} /></div>
          <button type="button" className="btn ghost light small" onClick={() => abortRef.current?.abort()}>Cancel</button>
        </div>
      )}
    </div>
  );
}
