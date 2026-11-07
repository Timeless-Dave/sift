import { API, api, type Assay } from "../api";
import { esc, getTier, safeUrl } from "../util";

const methodWords: Record<string, string> = {
  colorimetric: "Colour reaction on the reference card",
  screenlight: "Screen-light scan, no reagents",
  microscopy: "Clip-on microscope",
};

export async function homeView(root: HTMLElement) {
  const assays = await api.assays();
  const ready = assays.filter((a) => a.runnable);
  const planned = assays.filter((a) => !a.runnable);
  const research = getTier() === "research";

  root.innerHTML = `
    <section class="intro">
      <a class="back" href="#/">Back to the scanner</a>
      <h1>Lab tests</h1>
      <p>${research
        ? "Reagent tests that follow a published method. Calibrate them per phone, record runs with known answers, export the raw data."
        : "When a scan doesn't match, these confirm it at home: a few drops of a pharmacy reagent, photographed on the printed card."}</p>
    </section>
    <section aria-labelledby="ready-h">
      <h2 id="ready-h">Reagent tests</h2>
      <ul class="assays">${ready.map((a) => row(a, research)).join("")}</ul>
    </section>
    <section aria-labelledby="planned-h" class="planned">
      <h2 id="planned-h">Being built next</h2>
      <p class="muted">Each of these is based on published research and isn't runnable yet.</p>
      <ul class="assays quiet">${planned.map((a) => plannedRow(a)).join("")}</ul>
    </section>
    <section class="card-cta">
      <div>
        <h2>Print the reference card</h2>
        <p>Colour tests need it in every photo. Print at 100% size on plain white paper.</p>
      </div>
      <a class="btn" href="${esc(API + "/v1/card.svg")}" target="_blank" rel="noopener">Open the card</a>
    </section>`;
}

function row(a: Assay, research: boolean) {
  const acc = a.accuracy;
  return `<li>
    <a class="assay" href="#/run/${esc(a.id)}">
      <span class="food">${esc(a.food)}</span>
      <span class="name">${esc(a.name)}</span>
      <span class="q">${esc(a.question)}</span>
      <span class="meta">${esc(methodWords[a.method] ?? a.method)}</span>
      ${research && acc ? `<span class="meta acc">${esc(acc.summary)}</span>` : ""}
    </a>
    ${research ? `<a class="lab-link" href="#/lab/${esc(a.id)}">Calibration and runs</a>` : ""}
  </li>`;
}

function plannedRow(a: Assay) {
  const ref = a.references?.[0];
  const based = ref
    ? `Based on ${safeUrl(ref.url) ? `<a href="${esc(ref.url)}" target="_blank" rel="noopener">${esc(ref.title)}</a>` : esc(ref.title)}`
    : "Based on published research";
  return `<li class="assay quiet">
    <span class="food">${esc(a.food)}</span>
    <span class="name">${esc(a.name)}</span>
    <span class="q">${esc(a.summary)}</span>
    <span class="meta">${based}</span>
  </li>`;
}
