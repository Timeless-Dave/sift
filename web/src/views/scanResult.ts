/**
 * One scan's answer. The headline is what the reference library supports, never more; the readings
 * below are the phone's own measurements, drawn from the capture kept on this device.
 */
import { scanApi, type Food, type ScanResult } from "../api";
import { SCREEN_COLOURS, SENSOR_INFO } from "../scanner";
import type { Capture } from "../sensors/types";
import { esc, getTier } from "../util";

const MIN_GENUINE = 5;

export async function scanResultView(root: HTMLElement, scanId: string) {
  const r = await scanApi.result(scanId);
  const food = await scanApi.food(r.food).catch(() => null);
  const capture = readCapture(scanId);
  const name = food?.name ?? r.food;
  const research = getTier() === "research";

  root.innerHTML = `
    <section class="answer state-${esc(stateOf(r))}">
      <a class="back" href="#/">Scan something else</a>
      <p class="eyebrow">${esc(name)}</p>
      ${headline(r, name)}
      ${r.status === "ok" ? meter(r) : ""}
      ${problems(r)}
      ${r.status === "ok" && r.match.status === "differs" && food && r.report?.agent === "muse-spark" ? causes(food) : ""}
      ${r.report?.text ? `<p class="report">${esc(r.report.text)}</p>
        <p class="agent-tag">${r.report.agent === "muse-spark" ? "Explained by the Lab Agent from Sift's measurements" : "Written from Sift's measurements"}</p>` : ""}
      ${findings(r, food)}
      ${capture ? readings(capture) : ""}
      ${r.status === "ok" && r.match.status === "no_reference" ? `<div class="note">
        <h2>Help Sift learn ${esc(name.toLowerCase())}</h2>
        <p>A verdict needs scans of food whose answer is known: at least ${MIN_GENUINE} genuine samples on this phone model, and
        labelled adulterated samples for each question. ${research ? "Turn on “Add as a reference scan” when you scan a sample you can vouch for." : "Researchers can add them in Researcher mode."}</p></div>` : ""}
      <p class="fine muted">A screening result from phone sensors, not a lab analysis. <a href="#/foods/${esc(r.food)}">How Sift checks ${esc(name.toLowerCase())}</a> ·
        <a href="#/lab-tests">Confirm with a lab test</a></p>
    </section>`;
}

function stateOf(r: ScanResult) {
  if (r.status !== "ok") return r.status;
  return r.match.status;
}

function headline(r: ScanResult, name: string) {
  if (r.status === "rejected") return `<h1>Couldn't read this scan</h1><p class="lede">Sift didn't guess. The fixes are below.</p>`;
  if (r.status === "stored") return `<h1>Reference saved</h1>
    <p class="lede">${r.match.n_genuine} genuine reference scan${r.match.n_genuine === 1 ? "" : "s"} of ${esc(name.toLowerCase())} for this phone model.</p>`;
  if (r.match.status === "matches") return `<h1>Matches genuine ${esc(name.toLowerCase())}</h1>
    <p class="lede">This scan sits within the spread of ${r.match.n_genuine} genuine reference scans from this phone model.</p>`;
  if (r.match.status === "differs") return `<h1>Doesn't match genuine ${esc(name.toLowerCase())}</h1>
    <p class="lede">It falls outside the spread of ${r.match.n_genuine} genuine reference scans from this phone model. That is a reason to look closer, not proof of fraud.</p>`;
  return `<h1>No verdict yet</h1>
    <p class="lede">Sift has ${r.match.n_genuine} of the ${MIN_GENUINE} genuine reference scans it needs for ${esc(name.toLowerCase())} on this phone model, so it won't guess.</p>`;
}

/** Distance from the genuine centre, with the threshold marked. */
function meter(r: ScanResult) {
  const { distance, threshold } = r.match;
  if (distance == null || threshold == null || threshold <= 0) return "";
  const top = Math.max(threshold * 2, distance * 1.1);
  const at = Math.min(100, (distance / top) * 100);
  const cut = (threshold / top) * 100;
  return `<div class="meter" role="img" aria-label="Distance ${distance.toFixed(2)}, genuine limit ${threshold.toFixed(2)}">
      <span class="zone" style="width:${cut}%">genuine spread</span>
      <span class="dot" style="left:${at}%"></span>
    </div>
    <p class="fine muted">Compared using ${esc(r.match.modalities.map((m) => SENSOR_INFO[m]?.name ?? m).join(", ") || "no sensors")}.</p>`;
}

function causes(food: Food) {
  const list = [...new Set(food.targets.flatMap((t) => t.likely_causes ?? []))];
  if (!list.length) return "";
  return `<div class="note"><h2>What a mismatch can mean</h2><ul>${list.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></div>`;
}

function problems(r: ScanResult) {
  const list = r.quality?.problems ?? [];
  if (!list.length) return "";
  return `<div class="note problems"><h2>${r.status === "rejected" ? "How to get a clean scan" : "Worth knowing"}</h2><ul>
    ${list.map((p) => `<li><strong>${esc(p.message)}</strong> ${esc(p.fix)}</li>`).join("")}</ul></div>`;
}

function findings(r: ScanResult, food: Food | null) {
  if (!r.findings?.length) return "";
  const q = new Map((food?.targets ?? []).map((t) => [t.id, t]));
  return `<h2>Questions Sift is working on</h2><ul class="findings">${r.findings.map((f) => {
    const t = q.get(f.target);
    const acc = f.model && typeof f.model.cv_accuracy === "number" ? ` · ${Math.round(Number(f.model.cv_accuracy) * 100)}% cross-validated` : "";
    return `<li class="f-${esc(f.status)}"><p>${esc(t?.question ?? f.target)}</p>
      <span class="badge">${esc(f.status === "research" ? "Research" : f.status === "model" ? "Model" : "No model yet")}</span>
      <span>${esc(f.label)}${esc(acc)}</span></li>`;
  }).join("")}</ul>`;
}

/** The phone's own readings for this scan. */
function readings(c: Capture) {
  const parts: string[] = [];
  const sl = c.screenlight?.frames;
  if (sl?.white && sl?.black) {
    const mean = (rows: number[][]) => rows[0].map((_, i) => rows.reduce((s, r) => s + r[i], 0) / rows.length);
    const dark = mean(sl.black), white = mean(sl.white);
    const bars = Object.entries(sl).filter(([k]) => k !== "white" && k !== "black").map(([k, rows]) => {
      const m = mean(rows);
      const v = m.reduce((s, x, i) => s + Math.max(0, (x - dark[i]) / Math.max(1e-3, white[i] - dark[i])), 0) / 3;
      return `<span title="${esc(k)}: ${v.toFixed(2)}" style="height:${Math.min(100, v * 100)}%;background:${SCREEN_COLOURS[k] ?? "#888"}"></span>`;
    }).join("");
    parts.push(`<figure><figcaption>${SENSOR_INFO.screenlight.name}: light returned per colour</figcaption><div class="bars">${bars}</div></figure>`);
  }
  if (c.acoustic?.bins_hz?.length) {
    const a = c.acoustic;
    const t = a.response_db.map((v, i) => v - a.noise_db[i]);
    const lo = Math.min(...t), hi = Math.max(...t), span = hi - lo || 1;
    const fx = (f: number) => (Math.log(f / a.bins_hz[0]) / Math.log(a.bins_hz[a.bins_hz.length - 1] / a.bins_hz[0])) * 300;
    const pts = a.bins_hz.map((f, i) => `${fx(f).toFixed(1)},${(90 - ((t[i] - lo) / span) * 80).toFixed(1)}`).join(" ");
    const kHz = (f: number) => `${f >= 1000 ? `${Math.round(f / 1000)} kHz` : `${Math.round(f)} Hz`}`;
    parts.push(`<figure><figcaption>${SENSOR_INFO.acoustic.name}: sound through the food, above background</figcaption>
      <svg viewBox="0 0 300 100" class="curve" role="img" aria-label="Sound transmission curve"><polyline points="${pts}"/></svg>
      <div class="axis"><span>${kHz(a.bins_hz[0])}</span><span>${kHz(a.bins_hz[a.bins_hz.length - 1])}</span></div></figure>`);
  }
  if (c.torch) {
    const sw = (m: number[]) => `rgb(${m.map((x) => Math.round(x * 255)).join(",")})`;
    parts.push(`<figure><figcaption>${SENSOR_INFO.torch.name}: colour with the flash off and on</figcaption>
      <div class="swatch-pair"><span style="background:${sw(c.torch.off.mean)}">off</span>${c.torch.on ? `<span style="background:${sw(c.torch.on.mean)}">on</span>` : "<em>No controllable torch on this phone</em>"}</div></figure>`);
  }
  if (c.vibration?.vibrate_available) {
    const ratio = c.vibration.rms_off > 0 ? c.vibration.rms_on / c.vibration.rms_off : 0;
    parts.push(`<figure><figcaption>${SENSOR_INFO.vibration.name}</figcaption><p class="mono">${ratio.toFixed(1)}× motion with the motor on</p></figure>`);
  }
  if (!parts.length) return "";
  return `<details class="readings" open><summary>What the phone measured</summary>${parts.join("")}</details>`;
}

function readCapture(id: string): Capture | null {
  try { const s = sessionStorage.getItem(`sift.capture.${id}`); return s ? JSON.parse(s) as Capture : null; } catch { return null; }
}
