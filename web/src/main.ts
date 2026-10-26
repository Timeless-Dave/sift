import "./style.css";
import { api } from "./api";
import { getTier, setTier, swatchStrip, esc, type Tier } from "./util";
import { homeView } from "./views/home";
import { runView } from "./views/run";
import { resultView } from "./views/result";
import { labView } from "./views/lab";
import { developersView } from "./views/developers";

const app = document.getElementById("app")!;

app.innerHTML = `
  <header class="top">
    <a class="brand" href="#/">${swatchStrip()}<span>Sift Lab</span></a>
    <div class="tier" role="group" aria-label="Who is using Sift">
      <button data-tier="public">Shopper</button>
      <button data-tier="research">Researcher</button>
    </div>
  </header>
  <main id="view" tabindex="-1"></main>
  <footer class="foot">
    <span id="agent-status">Checking the Lab Agent…</span>
    <a href="#/developers">API for developers</a>
  </footer>`;

const view = document.getElementById("view")!;

function paintTier() {
  const t = getTier();
  document.body.dataset.tier = t;
  app.querySelectorAll<HTMLButtonElement>(".tier button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tier === t)));
}
app.querySelectorAll<HTMLButtonElement>(".tier button").forEach((b) =>
  b.addEventListener("click", () => { setTier(b.dataset.tier as Tier); paintTier(); route(); }));
paintTier();

api.health()
  .then((h) => {
    document.getElementById("agent-status")!.textContent =
      h.agent === "offline" ? "Lab Agent offline: guidance follows the written protocol" : `Lab Agent: ${h.chat_model}`;
  })
  .catch(() => { document.getElementById("agent-status")!.textContent = "Can't reach the Sift server"; });

let cleanup: (() => void) | void;

async function route() {
  if (cleanup) cleanup();
  cleanup = undefined;
  const [, page, id] = (location.hash || "#/").split("/");
  view.innerHTML = "";
  try {
    if (page === "run" && id) cleanup = await runView(view, id);
    else if (page === "result" && id) await resultView(view, id);
    else if (page === "lab") await labView(view, id);
    else if (page === "developers") developersView(view);
    else await homeView(view);
  } catch (e) {
    view.innerHTML = `<section class="panel error"><h1>Something went wrong</h1><p>${esc((e as Error).message)}</p>
      <p><a href="#/">Back to tests</a></p></section>`;
  }
  view.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

window.addEventListener("hashchange", route);
route();
