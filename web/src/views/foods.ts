/**
 * What Sift can check, food by food, with the honest status of each question and its sources.
 */
import { scanApi, type Food, type FoodTarget } from "../api";
import { SENSOR_INFO } from "../scanner";
import { esc, safeUrl } from "../util";

const STATUS: Record<string, { label: string; text: string }> = {
  experimental: { label: "Experimental", text: "A published phone method exists; Sift hasn't validated it yet." },
  research: { label: "Research", text: "No published phone method yet. Sift collects reference scans; no verdicts." },
  validated: { label: "Validated", text: "Measured by Sift on samples with known answers." },
};
const KIND: Record<string, string> = {
  adulteration: "Adulteration", cultured: "Lab-grown vs conventional", freshness: "Freshness", identity: "Identity",
};

export async function foodsView(root: HTMLElement, foodId?: string) {
  if (foodId) return foodDetail(root, await scanApi.food(foodId));
  const foods = await scanApi.foods();
  root.innerHTML = `
    <section class="foods">
      <h1>What Sift checks</h1>
      <p class="lede">Each food lists the questions Sift is working on and how far each one has got. A question only gets
        verdicts once Sift has reference scans of samples with known answers.</p>
      <div class="legend">${Object.values(STATUS).map((s) => `<p><span class="badge">${esc(s.label)}</span> ${esc(s.text)}</p>`).join("")}</div>
      <ul class="food-index">${foods.map((f) => `<li><a href="#/foods/${esc(f.id)}">
          <span class="name">${esc(f.name)}</span>
          <span class="qs">${f.targets.map((t) => `<span class="q s-${esc(t.status)}">${esc(KIND[t.kind] ?? t.kind)}: ${esc(STATUS[t.status]?.label ?? t.status)}</span>`).join("")}</span>
        </a></li>`).join("")}</ul>
    </section>`;
}

function foodDetail(root: HTMLElement, f: Food) {
  root.innerHTML = `
    <section class="foods">
      <a class="back" href="#/foods">All foods</a>
      <h1>${esc(f.name)}</h1>
      ${f.summary ? `<p class="lede">${esc(f.summary)}</p>` : ""}
      <p><strong>How to hold the phone:</strong> ${esc(f.scan.placement)}</p>
      <p class="muted">Sensors: ${esc(f.scan.modalities.map((m) => SENSOR_INFO[m]?.name ?? m).join(", "))}</p>
      ${f.targets.map(target).join("")}
      ${f.limits?.length ? `<h2>Limits</h2><ul>${f.limits.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : ""}
      <p><a class="btn primary" href="#/">Scan ${esc(f.name.toLowerCase())}</a></p>
    </section>`;
}

function target(t: FoodTarget) {
  const st = STATUS[t.status];
  return `<article class="target">
    <p class="eyebrow">${esc(KIND[t.kind] ?? t.kind)} · <span class="badge">${esc(st?.label ?? t.status)}</span></p>
    <h2>${esc(t.question)}</h2>
    <p class="muted">${esc(st?.text)}</p>
    ${t.signals ? `<dl>${Object.entries(t.signals).map(([m, why]) => `<dt>${esc(SENSOR_INFO[m]?.name ?? m)}</dt><dd>${esc(why)}</dd>`).join("")}</dl>` : ""}
    ${t.references?.length ? `<details><summary>Sources (${t.references.length})</summary><ul>${t.references.map((r) =>
      `<li>${safeUrl(r.url) ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>` : esc(r.title)}, ${esc(r.source)}. ${esc(r.finding)}</li>`).join("")}</ul></details>` : ""}
  </article>`;
}
