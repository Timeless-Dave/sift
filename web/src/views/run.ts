import { api, type Assay, type Step } from "../api";
import { cardCapture, recorder, screenlightCapture } from "../capture";
import { el, esc, getDevice, getTier, go } from "../util";

export async function runView(root: HTMLElement, assayId: string): Promise<() => void> {
  const assay = await api.assay(assayId);
  if (!assay.runnable) {
    root.innerHTML = `<section class="panel"><h1>${esc(assay.name)}</h1><p>This test is planned and can't be run yet.</p>
      <p><a href="#/">Back to tests</a></p></section>`;
    return () => undefined;
  }
  const steps = assay.protocol ?? [];
  if (!steps.length) {
    root.innerHTML = `<section class="panel"><h1>${esc(assay.name)}</h1><p>This test has no steps to follow, so it can't run. Go back and try another test.</p>
      <p><a href="#/">Back to tests</a></p></section>`;
    return () => undefined;
  }
  const tier = getTier();
  const device = await getDevice();
  const history: { role: string; content: string }[] = [];
  let current: Step = steps[0];
  let stopCapture: (() => void) | null = null;
  let timer: number | undefined;
  let practice = false;

  root.innerHTML = `
    <section class="run">
      <a class="back" href="#/">All tests</a>
      <p class="food">${esc(assay.food)}</p>
      <h1>${esc(assay.name)}</h1>
      <p class="lede">${esc(assay.summary)}</p>
      ${kit(assay)}
      ${tier === "research" ? `<label class="practice"><input type="checkbox"> Practice run (walk the protocol, nothing is saved)</label>` : ""}
      <ol class="steps"></ol>
      <div class="stage" aria-live="polite"></div>
      <form class="ask">
        <label for="ask-input" class="sr">Ask the Lab Agent</label>
        <input id="ask-input" autocomplete="off" placeholder="Ask a question, or say “next”" />
        <button type="button" class="btn ghost mic" aria-label="Hold to talk">Hold to talk</button>
        <button class="btn">Send</button>
      </form>
    </section>`;

  const stepsEl = root.querySelector<HTMLOListElement>(".steps")!;
  const stage = root.querySelector<HTMLElement>(".stage")!;
  root.querySelector<HTMLInputElement>(".practice input")?.addEventListener("change", (e) => {
    practice = (e.target as HTMLInputElement).checked; show(current, current.instruction);
  });

  function paintSteps() {
    const idx = steps.indexOf(current);
    stepsEl.innerHTML = steps.map((s, i) =>
      `<li class="${i < idx ? "done" : i === idx ? "now" : ""}" ${i === idx ? 'aria-current="step"' : ""}>${esc(s.title)}</li>`).join("");
  }

  function show(step: Step, text: string, agentName = "") {
    stopCapture?.(); stopCapture = null;
    clearInterval(timer);
    current = step;
    paintSteps();
    const idx = steps.indexOf(step);
    stage.innerHTML = "";
    const card = el(`<div class="step-card">
      <h2>${esc(step.title)}</h2>
      <p class="agent-text">${esc(text)}</p>
      ${agentName ? `<p class="agent-tag">${agentName === "offline" ? "From the written protocol" : "Lab Agent"}</p>` : ""}
      <div class="timer" hidden></div>
      <div class="row nav"></div>
    </div>`);
    stage.append(card);
    const nav = card.querySelector<HTMLElement>(".nav")!;
    if (idx > 0) nav.append(button("Back", "ghost", () => show(steps[idx - 1], steps[idx - 1].instruction)));
    if (step.wait_seconds) startTimer(card, step.wait_seconds);
    if (step.capture && practice) {
      card.append(el(`<p class="muted">In a practice run the capture is skipped. Untick practice to run it for real.</p>`));
    } else if (step.capture === "card") {
      stopCapture = cardCapture(card, (jpeg) => submit(() => api.runCard(assay.id, jpeg, device, tier)));
    } else if (step.capture === "screenlight") {
      const seq = assay.analysis?.sequence;
      if (!seq?.length) {
        card.append(el(`<p class="cam-error" role="alert">This test can't run its light scan: the assay data has no colour sequence. Go back to All tests and try another test.</p>`));
      } else {
        stopCapture = screenlightCapture(card, seq, assay.analysis?.frame_ms ?? 450,
          (frames) => submit(() => api.runScreenlight(assay.id, frames, device, tier)));
      }
    } else if (idx + 1 < steps.length) {
      nav.append(button("Done, next step", "primary", () => show(steps[idx + 1], steps[idx + 1].instruction)));
    }
  }

  function startTimer(card: HTMLElement, seconds: number) {
    const t = card.querySelector<HTMLElement>(".timer")!;
    t.hidden = false;
    let left = seconds;
    const paint = () => { t.textContent = left > 0 ? `${left} s` : "Time's up"; };
    paint();
    timer = window.setInterval(() => { left--; paint(); if (left <= 0) clearInterval(timer); }, 1000);
  }

  async function submit(run: () => Promise<{ run_id: string }>) {
    stopCapture?.(); stopCapture = null;
    stage.querySelector(".capture")?.replaceWith(el(`<p class="working">Reading the sample…</p>`));
    try {
      const r = await run();
      go(`#/result/${r.run_id}`);
    } catch (e) {
      stage.querySelector(".working")?.replaceWith(el(`<p class="cam-error" role="alert">${esc((e as Error).message)}</p>`));
      stage.append(button("Try again", "primary", () => show(current, current.instruction)));
    }
  }

  async function askAgent(message: string) {
    if (!message.trim()) return;
    history.push({ role: "user", content: message });
    const status = el(`<p class="working">Lab Agent is thinking…</p>`);
    stage.prepend(status);
    try {
      const r = await api.agent({ assay_id: assay.id, step_id: current.id, message, history, tier });
      history.push({ role: "assistant", content: r.reply });
      const next = steps.find((s) => s.id === r.step_id) ?? current;
      show(next, r.reply, r.agent);
    } catch (e) {
      status.textContent = (e as Error).message;
    }
  }

  const form = root.querySelector<HTMLFormElement>(".ask")!;
  const input = form.querySelector("input")!;
  form.addEventListener("submit", (e) => { e.preventDefault(); const v = input.value; input.value = ""; askAgent(v); });

  const mic = form.querySelector<HTMLButtonElement>(".mic")!;
  const rec = recorder();
  let recording = false;
  const startRec = async () => {
    try { await rec.start(); recording = true; mic.textContent = "Listening…"; mic.classList.add("live"); }
    catch { mic.textContent = "Mic blocked"; }
  };
  const stopRec = async () => {
    if (!recording) return;
    recording = false; mic.textContent = "Hold to talk"; mic.classList.remove("live");
    const blob = await rec.stop();
    try { const { text } = await api.transcribe(blob); input.value = text; askAgent(text); input.value = ""; }
    catch (e) { stage.prepend(el(`<p class="cam-error">${esc((e as Error).message)}</p>`)); }
  };
  mic.addEventListener("pointerdown", startRec);
  mic.addEventListener("pointerup", stopRec);
  mic.addEventListener("pointerleave", stopRec);

  show(steps[0], steps[0].instruction);
  return () => { stopCapture?.(); clearInterval(timer); };
}

function kit(a: Assay) {
  const items = [...(a.reagents ?? []), ...(a.equipment ?? [])];
  if (!items.length) return "";
  return `<details class="kit"><summary>What you need</summary><ul>${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></details>`;
}

function button(label: string, kind: string, onClick: () => void) {
  const b = el<HTMLButtonElement>(`<button class="btn ${kind}">${esc(label)}</button>`);
  b.addEventListener("click", onClick);
  return b;
}
