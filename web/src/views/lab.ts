import { api } from "../api";
import { csvCell, download, esc, getDevice, setDevice } from "../util";

export async function labView(root: HTMLElement, assayId?: string) {
  const assays = (await api.assays()).filter((a) => a.runnable);
  if (!assays.length) {
    root.innerHTML = `<section class="panel"><h1>Calibration and runs</h1><p>No test is runnable yet.</p>
      <p><a href="#/">Back to tests</a></p></section>`;
    return;
  }
  const id = assayId && assays.some((a) => a.id === assayId) ? assayId : assays[0].id;
  const assay = await api.assay(id);
  const device = await getDevice();
  const [calRaw, runsRaw] = await Promise.all([api.calibration(id, device), api.runs(id)]);
  const cal = { ...calRaw, samples: calRaw.samples ?? [] };
  const runs = Array.isArray(runsRaw) ? runsRaw : [];

  root.innerHTML = `
    <section class="lab">
      <h1>Calibration and runs</h1>
      <nav class="assay-tabs" aria-label="Choose a test">
        ${assays.map((a) => `<a href="#/lab/${esc(a.id)}" ${a.id === id ? 'aria-current="page"' : ""}>${esc(a.name)}</a>`).join("")}
      </nav>

      <form class="device">
        <label>This phone's calibration label
          <input name="device" value="${esc(device)}" required></label>
        <button class="btn ghost">Save label</button>
        <p class="muted">Calibration is stored per phone model. Use the same label on every phone of this model.</p>
      </form>

      <h2>Calibration for this phone</h2>
      ${cal.model
        ? `<table class="data"><tbody>${Object.entries(cal.model.metrics).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("")}</tbody></table>`
        : `<p>No model yet. Run the test on samples with known amounts, open each result, and add it to calibration.
           ${assay.method === "screenlight" ? "Training needs at least 6 scans across 3 or more known levels." : "A curve needs 3 or more known levels."}</p>`}
      <p>${cal.samples.length} calibration sample${cal.samples.length === 1 ? "" : "s"} at levels:
        ${esc([...new Set(cal.samples.map((s) => s.known_value))].sort((a, b) => a - b).join(", ") || "none yet")}</p>
      <div class="row">
        <button class="btn primary train" ${cal.samples.length ? "" : "disabled"}>Train model</button>
        <button class="btn ghost csv" ${runs.length ? "" : "disabled"}>Export runs (CSV)</button>
      </div>
      <p class="train-out" role="status"></p>

      <h2>Accuracy so far</h2>
      <p>All phones: ${esc(assay.accuracy?.summary)}</p>
      <p>This phone: ${esc(assay.accuracy?.by_device?.[device]?.summary ?? "Not measured yet: no runs with known answers.")}</p>

      <h2>Recent runs</h2>
      ${runs.length ? `<table class="data runs"><thead><tr><th>When</th><th>Phone</th><th>Result</th><th>Known</th></tr></thead><tbody>
        ${runs.map((r) => `<tr><td><a href="#/result/${esc(r.id)}">${new Date(r.created * 1000).toLocaleString()}</a></td>
          <td>${esc(r.device)}</td><td>${esc(r.result?.label ?? r.status)}${r.result?.value != null ? ` (${esc(r.result.value)})` : ""}</td>
          <td>${r.truth ?? ""}</td></tr>`).join("")}</tbody></table>` : `<p>No runs yet. <a href="#/run/${esc(id)}">Run this test</a>.</p>`}
    </section>`;

  root.querySelector<HTMLFormElement>(".device")!.addEventListener("submit", (e) => {
    e.preventDefault();
    setDevice((new FormData(e.target as HTMLFormElement).get("device") as string).trim());
    labView(root, id);
  });
  root.querySelector(".train")!.addEventListener("click", async () => {
    const out = root.querySelector<HTMLElement>(".train-out")!;
    out.textContent = "Training…";
    try { await api.train(id, device); labView(root, id); }
    catch (e) { out.textContent = (e as Error).message; }
  });
  root.querySelector(".csv")!.addEventListener("click", () => {
    const head = "run_id,created,device,status,label,value,unit,confidence,known\n";
    const body = runs.map((r) => [r.id, new Date(r.created * 1000).toISOString(), r.device, r.status, r.result?.label ?? "",
      r.result?.value ?? "", r.result?.unit ?? "", r.result?.confidence ?? "", r.truth ?? ""]
      .map(csvCell).join(",")).join("\n");
    download(`sift-${id}-runs.csv`, head + body, "text/csv");
  });
}
