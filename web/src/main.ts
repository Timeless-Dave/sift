import "./style.css";
import "./scanner.css";
import { api } from "./api";
import { esc, getTier, setTier, type Tier } from "./util";
import { scanView } from "./views/scan";
import { scanResultView } from "./views/scanResult";
import { foodsView } from "./views/foods";
import { homeView } from "./views/home";
import { runView } from "./views/run";
import { resultView } from "./views/result";
import { labView } from "./views/lab";
import { developersView } from "./views/developers";

const app = document.getElementById("app")!;

app.innerHTML = `
  <header class="top">
    <a class="brand" href="#/" aria-label="Sift, scan">Sift</a>
    <nav class="nav" aria-label="Main">
      <a href="#/" data-nav="scan">Scan</a>
      <a href="#/foods" data-nav="foods">What it checks</a>
    </nav>
    <button class="tier-toggle" type="button" aria-pressed="false" title="Researcher mode: add reference scans, see raw data">Researcher</button>
  </header>
  <main id="view" tabindex="-1"></main>
  <footer class="foot">
    <span id="agent-status">Checking the Lab Agent…</span>
    <a href="#/lab-tests">Lab tests</a>
    <a href="#/developers">API</a>
  </footer>`;

const view = document.getElementById("view")!;
const tierBtn = app.querySelector<HTMLButtonElement>(".tier-toggle")!;

function paintTier() {
  const t = getTier();
  document.body.dataset.tier = t;
  tierBtn.setAttribute("aria-pressed", String(t === "research"));
}
tierBtn.addEventListener("click", () => { setTier((getTier() === "research" ? "public" : "research") as Tier); paintTier(); route(); });
paintTier();

api.health()
  .then((h) => {
    document.getElementById("agent-status")!.textContent =
      h.agent === "offline" ? "Lab Agent offline" : `Lab Agent: ${h.chat_model}`;
  })
  .catch(() => { document.getElementById("agent-status")!.textContent = "Can't reach the Sift server"; });

let cleanup: (() => void) | void;

async function route() {
  if (cleanup) cleanup();
  cleanup = undefined;
  const [, page, id] = (location.hash || "#/").split("/");
  view.innerHTML = "";
  document.body.dataset.page = page || "scan";
  app.querySelectorAll<HTMLElement>("[data-nav]").forEach((a) =>
    a.toggleAttribute("aria-current", a.dataset.nav === (page === "foods" ? "foods" : !page || page === "scan" ? "scan" : "")));
  try {
    if (page === "scan" && id) await scanResultView(view, id);
    else if (page === "foods") await foodsView(view, id);
    else if (page === "lab-tests") await homeView(view);
    else if (page === "run" && id) cleanup = await runView(view, id);
    else if (page === "result" && id) await resultView(view, id);
    else if (page === "lab") await labView(view, id);
    else if (page === "developers") developersView(view);
    else cleanup = await scanView(view);
  } catch (e) {
    view.innerHTML = `<section class="panel error"><h1>Something went wrong</h1><p>${esc((e as Error).message)}</p>
      <p><a href="#/">Back to the scanner</a></p></section>`;
  }
  view.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

window.addEventListener("hashchange", route);
route();
