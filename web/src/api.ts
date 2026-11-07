export const API = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") || "/api";

export type Verdict = "pass" | "caution" | "flag" | "unknown";

export interface Reference { title: string; source: string; url: string; finding: string }
export interface Step { id: string; title: string; instruction: string; capture?: "card" | "screenlight"; wait_seconds?: number }
export interface Band { max: number; label: string; verdict: Verdict }
export interface Score { n: number; summary: string; mae?: number; agreement?: number }
export interface Accuracy extends Score { by_device?: Record<string, Score> }

export interface Assay {
  id: string; name: string; food: string; question?: string; status: string; method: string;
  summary?: string; runnable: boolean; instruments?: string[];
  reagents?: string[]; equipment?: string[]; protocol?: Step[];
  analysis?: { type: string; unit?: string; bands?: Band[]; sequence?: string[]; frame_ms?: number;
               feature?: string; qualitative?: { rule: string; positive: string; negative: string } };
  confirm_with?: string; references: Reference[]; limitations?: string[];
  accuracy?: Accuracy | null; models?: { device: string; kind: string; metrics: Record<string, unknown> }[];
}

export interface Problem { code: string; severity: "reject" | "warn"; message: string; fix: string }
export interface RunResult {
  run_id: string; assay_id: string; status: "ok" | "rejected" | "needs_calibration";
  mode?: "calibrated" | "qualitative"; label?: string; verdict?: Verdict; value?: number | null;
  unit?: string | null; confidence?: number; in_range?: boolean; rule?: string; next_step?: string;
  quality: { ok: boolean; problems: Problem[]; metrics: Record<string, number> };
  features?: Record<string, unknown>; card?: { fit_delta_e: number; swatches: [string, number[]][] };
  segmentation?: string; model?: Record<string, unknown>;
  report: { agent: string; text: string };
  capture_review?: { sample_visible: boolean; matches_expected: boolean; issues: string[]; advice: string };
}

export interface RunRow {
  id: string; assay_id: string; created: number; tier: string; device: string; status: string;
  result: RunResult; truth: number | null;
}

export interface AgentReply { agent: string; reply: string; step_id: string; actions: { name: string; args: Record<string, unknown> }[] }

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API + path, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const b = body as { detail?: string; error?: { code?: string; message?: string; request_id?: string } };
    const msg = b.detail || b.error?.message || `Request failed (${res.status})`;
    const tag = [b.error?.code, b.error?.request_id ? `request ${b.error.request_id}` : ""].filter(Boolean).join(", ");
    throw new Error(tag ? `${msg} (${tag})` : msg);
  }
  return body as T;
}

const json = (data: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
});

export const api = {
  health: () => req<{ agent: string; version: string; chat_model: string }>("/health"),
  assays: () => req<Assay[]>("/v1/assays"),
  assay: (id: string) => req<Assay>(`/v1/assays/${encodeURIComponent(id)}`),
  runCard: (assayId: string, image: Blob, device: string, tier: string) => {
    const fd = new FormData();
    fd.append("assay_id", assayId); fd.append("device", device); fd.append("tier", tier);
    fd.append("image", image, "capture.jpg");
    return req<RunResult>("/v1/runs/card", { method: "POST", body: fd });
  },
  runScreenlight: (assayId: string, frames: Record<string, number[][]>, device: string, tier: string) =>
    req<RunResult>("/v1/runs/screenlight", json({ assay_id: assayId, frames, device, tier })),
  runs: (assayId?: string) => req<RunRow[]>(`/v1/runs${assayId ? `?assay_id=${encodeURIComponent(assayId)}` : ""}`),
  run: (id: string) => req<RunRow>(`/v1/runs/${encodeURIComponent(id)}`),
  setTruth: (runId: string, value: number) =>
    req<{ accuracy: Accuracy }>(`/v1/runs/${encodeURIComponent(runId)}/truth`, json({ value })),
  addSample: (runId: string, known: number) => req<{ samples: number }>("/v1/calibration/samples", json({ run_id: runId, known_value: known })),
  train: (assayId: string, device: string) => req<{ metrics: Record<string, unknown> }>("/v1/calibration/train", json({ assay_id: assayId, device })),
  calibration: (assayId: string, device: string) =>
    req<{ samples: { known_value: number; created: number }[]; model: { kind: string; metrics: Record<string, unknown> } | null }>(
      `/v1/calibration/${encodeURIComponent(assayId)}?device=${encodeURIComponent(device)}`),
  agent: (body: { assay_id: string; step_id: string; message: string; history: { role: string; content: string }[]; tier: string }) =>
    req<AgentReply>("/v1/agent/turn", json(body)),
  transcribe: (audio: Blob) => {
    const fd = new FormData(); fd.append("audio", audio, "voice.wav");
    return req<{ text: string; agent: string }>("/v1/transcribe", { method: "POST", body: fd });
  },
};
