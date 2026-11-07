export type Tier = "public" | "research";

const TIER_KEY = "sift.tier";
const DEVICE_KEY = "sift.device";

export function getTier(): Tier {
  try { return (localStorage.getItem(TIER_KEY) as Tier) || "public"; } catch { return "public"; }
}
export function setTier(t: Tier) { try { localStorage.setItem(TIER_KEY, t); } catch { /* storage off */ } }

/** Labels the API accepts: letters, digits, spaces and . , ( ) + - / _ ; at most 80 characters. */
export const cleanLabel = (s: string) => s.replace(/[^\w .,()+\-/]/g, "").replace(/\s+/g, " ").trim().slice(0, 80) || "unknown";

/** Calibration is per phone model, so each phone needs a stable label. */
export async function getDevice(): Promise<string> {
  try {
    const saved = localStorage.getItem(DEVICE_KEY);
    if (saved) return cleanLabel(saved);
  } catch { /* storage off */ }
  let model = "";
  const uaData = (navigator as unknown as { userAgentData?: { getHighEntropyValues(h: string[]): Promise<{ model?: string; platform?: string }> } }).userAgentData;
  if (uaData) {
    try { const v = await uaData.getHighEntropyValues(["model", "platform"]); model = [v.platform, v.model].filter(Boolean).join(" "); } catch { /* ignore */ }
  }
  if (!model) {
    const ua = navigator.userAgent;
    model = /iPhone/.test(ua) ? "iPhone" : /Android/.test(ua) ? (ua.match(/Android[^;]*;\s*([^;)]+)/)?.[1] ?? "Android") : "Desktop";
    model += ` ${screen.width * devicePixelRatio}x${screen.height * devicePixelRatio}`;
  }
  return cleanLabel(model);
}
export function setDevice(label: string) { try { localStorage.setItem(DEVICE_KEY, cleanLabel(label)); } catch { /* storage off */ } }

export function esc(s: unknown): string {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}

/** Only http(s) links from API data become anchors; anything else renders as text. */
export const safeUrl = (u: unknown) => (typeof u === "string" && /^https?:\/\//i.test(u) ? u : "");

export function el<T extends HTMLElement = HTMLElement>(html: string): T {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild as T;
}

export function go(hash: string) { location.hash = hash; }

export function download(name: string, text: string, type = "application/json") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/** The eight printed swatches of the reference card; the app's visual signature. */
export const SWATCHES = ["#ffffff", "#c0c0c0", "#808080", "#181818", "#dc2828", "#28aa46", "#2846c8", "#f0d228"];
export const swatchStrip = (cls = "") =>
  `<span class="swatches ${cls}" aria-hidden="true">${SWATCHES.map((c) => `<i style="background:${c}"></i>`).join("")}</span>`;
