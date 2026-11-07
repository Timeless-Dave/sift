import { api, type Assay, type Band, type RunResult } from "../api";
import { download, esc, getTier, safeUrl } from "../util";

const verdictWord: Record<string, string> = { pass: "Looks fine", caution: "Check further", flag: "Flagged", unknown: "Not yet known" };

export async function resultView(root: HTMLElement, runId: string) {
  const run = await api.run(runId);
  const r: RunResult = { ...run.result, run_id: runId };
  const assay = await api.assay(run.assay_id);
  const research = getTier() === "research";

  root.innerHTML = `
    <section class="result verdict-${esc(r.verdict ?? r.status)}">
      <a class="back" href="#/run/${esc(assay.id)}">Run this test again</a>
      <p class="food">${esc(assay.food)}: ${esc(assay.name)}</p>
      ${headline(r)}
      ${r.status === "ok" ? scale(r, assay) : ""}
      <p class="report">${esc(r.report?.text)}</p>
      <p class="agent-tag">${r.report?.agent === "muse-spark" ? "Written by the Lab Agent from Sift's measurements" : "Written from Sift's measurements"}</p>
      ${problems(r)}
      ${r.capture_review?.issues?.length ? `<div class="note"><h2>What the Lab Agent noticed</h2><ul>${r.capture_review.issues.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></div>` : ""}
      ${assay.confirm_with && r.status === "ok" ? `<div class="note"><h2>How a lab would confirm this</h2><p>${esc(assay.confirm_with)}</p></div>` : ""}
      <details class="sources"><summary>Method and sources</summary>
        <ul>${assay.references.map((ref) => `<li>${safeUrl(ref.url) ? `<a href="${esc(ref.url)}" target="_blank" rel="noopener">${esc(ref.title)}</a>` : esc(ref.title)}, ${esc(ref.source)}. ${esc(ref.finding)}</li>`).join("")}</ul>
        ${assay.limitations?.length ? `<h3>Limits of this test</h3><ul>${assay.limitations.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : ""}
      </details>
      ${research ? researchPanel(r, assay) : ""}
    </section>`;

  if (research) wireResearch(root, r, assay, run);
}


function headline(r: RunResult) {
  if (r.status === "rejected") return `<h1>Retake needed</h1><p class="lede">Sift couldn't read this capture reliably, so it didn't guess.</p>`;
  if (r.status === "needs_calibration") return `<h1>Calibration needed</h1><p class="lede">${esc(r.label)}</p>`;
  const conf = Math.round((r.confidence ?? 0) * 100);
  return `<p class="verdict">${esc(verdictWord[r.verdict ?? "unknown"])}</p>
    <h1>${esc(r.label)}</h1>
    <p class="confidence"><span class="meter" style="--c:${conf}%"></span>${conf}% confident${r.mode === "qualitative" ? ", present or absent only" : ""}${r.in_range === false ? ", outside the calibrated range" : ""}</p>`;
}

/** The calibration-strip scale: bands as coloured segments, the sample as a marker. */
function scale(r: RunResult, assay: Assay) {
  const bands = assay.analysis?.bands ?? [];
  if (r.mode === "qualitative" || r.value == null || !bands.length) {
    const pos = r.verdict === "flag";
    return `<div class="scale two" role="img" aria-label="${pos ? "Present" : "Absent"}">
      <span class="seg pass ${pos ? "" : "hit"}">Not detected</span><span class="seg flag ${pos ? "hit" : ""}">Detected</span></div>`;
  }
  const top = Math.max(bands.length > 1 ? bands[bands.length - 2].max * 2 : bands[0].max, (r.value ?? 0) * 1.1);
  let prev = 0;
  const segs = bands.map((b: Band) => {
    const hi = Math.min(b.max, top);
    const w = Math.max(0, ((hi - prev) / top) * 100);
    const s = `<span class="seg ${esc(b.verdict)}" style="width:${w}%"><b>${esc(fmt(prev))}</b></span>`;
    prev = hi;
    return s;
  }).join("");
  const at = Math.min(100, ((r.value ?? 0) / top) * 100);
  return `<div class="scale" role="img" aria-label="${esc(fmt(r.value!))} ${esc(r.unit)}">
      ${segs}<span class="marker" style="left:${at}%"><em>${esc(fmt(r.value!))}</em></span></div>
    <p class="unit">${esc(r.unit)}</p>`;
}

const fmt = (n: number) => (Math.abs(n) >= 10 ? n.toFixed(0) : n.toFixed(2).replace(/\.?0+$/, ""));

function problems(r: RunResult) {
  const list = r.quality?.problems ?? [];
  if (!list.length) return "";
  return `<div class="note problems"><h2>${r.status === "rejected" ? "How to fix the capture" : "Worth knowing"}</h2><ul>
    ${list.map((p) => `<li><strong>${esc(p.message)}</strong> ${esc(p.fix)}</li>`).join("")}</ul></div>`;
}

function researchPanel(r: RunResult, assay: Assay) {
  const feats = r.features ?? {};
  const rows = Object.entries({ ...feats, ...(r.quality?.metrics ?? {}) })
    .filter(([k, v]) => k !== "vector" && typeof v !== "object")
    .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("");
  const isNumeric = assay.method === "screenlight" || assay.analysis?.unit;
  return `<section class="research">
    <h2>Run data</h2>
    <table class="data"><tbody>${rows}</tbody></table>
    ${r.segmentation ? `<p class="muted">Sample area found by ${esc(r.segmentation)}. Card swatch fit ΔE ${esc(r.card?.fit_delta_e)}.</p>` : ""}
    ${r.status !== "rejected" ? `
    <form class="known">
      <label>Known answer for this sample${isNumeric ? ` (${esc(assay.analysis?.unit ?? "")})` : " (0 = absent, 1 = present)"}
        <input name="known" type="number" step="any" required></label>
      <div class="row">
        <button class="btn" data-act="sample">Add to calibration</button>
        <button class="btn ghost" data-act="truth">Record as validation run</button>
      </div>
      <p class="muted">Calibration samples train this phone's model. Validation runs measure accuracy; don't use the same sample for both.</p>
      <p class="known-out" role="status"></p>
    </form>` : ""}
    <div class="row"><button class="btn ghost" data-act="export">Export run (JSON)</button>
      <a class="btn ghost" href="#/lab/${esc(assay.id)}">Calibration and history</a></div>
  </section>`;
}

function wireResearch(root: HTMLElement, r: RunResult, assay: Assay, run: { device: string }) {
  const form = root.querySelector<HTMLFormElement>(".known");
  const out = root.querySelector<HTMLElement>(".known-out");
  form?.addEventListener("submit", (e) => e.preventDefault());
  form?.querySelectorAll<HTMLButtonElement>("button").forEach((b) => b.addEventListener("click", async () => {
    const v = Number((form.elements.namedItem("known") as HTMLInputElement).value);
    if (!form.reportValidity()) return;
    try {
      if (b.dataset.act === "sample") {
        const s = await api.addSample(r.run_id, v);
        out!.textContent = `Added. ${s.samples} calibration samples for ${run.device}.`;
      } else {
        const t = await api.setTruth(r.run_id, v);
        out!.textContent = `Recorded. ${t.accuracy.summary}`;
      }
    } catch (e) { out!.textContent = (e as Error).message; }
  }));
  root.querySelector<HTMLButtonElement>('[data-act="export"]')?.addEventListener("click", () =>
    download(`sift-${assay.id}-${r.run_id}.json`, JSON.stringify({ assay: assay.id, device: run.device, ...r }, null, 2)));
}
