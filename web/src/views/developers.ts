import { API } from "../api";
import { esc } from "../util";

export function developersView(root: HTMLElement) {
  const base = new URL(API, location.href).href.replace(/\/$/, "");
  root.innerHTML = `
    <section class="dev">
      <h1>Run Sift tests from your own app</h1>
      <p class="lede">The Sift app uses the same API you do. Send a capture, get back a result, its confidence, the quality checks and the method's sources.</p>

      <h2>List the tests</h2>
      <pre><code>curl ${esc(base)}/v1/assays</code></pre>

      <h2>Run a colour test from a photo of the reference card</h2>
      <pre><code>curl -X POST ${esc(base)}/v1/runs/card \\
  -H "X-Sift-Key: $SIFT_KEY" \\
  -F assay_id=milk-starch-iodine \\
  -F device="Pixel 8" \\
  -F tier=enterprise \\
  -F image=@capture.jpg</code></pre>

      <h2>Run a screen-light scan</h2>
      <p>Send the mean camera colour of each frame, grouped by the colour on screen, in the order of the test's <code>analysis.sequence</code>.</p>
      <pre><code>curl -X POST ${esc(base)}/v1/runs/screenlight \\
  -H "Content-Type: application/json" \\
  -d '{"assay_id":"olive-oil-screenlight","device":"Pixel 8",
       "frames":{"white":[[0.81,0.80,0.79]],"black":[[0.02,0.02,0.02]],"red":[[0.41,0.12,0.10]]}}'</code></pre>

      <h2>What comes back</h2>
      <pre><code>{
  "run_id": "3f9c1a2b7d4e",
  "status": "ok",
  "verdict": "flag",
  "label": "Starch detected",
  "confidence": 0.74,
  "mode": "qualitative",
  "quality": { "ok": true, "problems": [], "metrics": { "sharpness": 412.3 } },
  "report": { "agent": "muse-spark", "text": "…" }
}</code></pre>
      <p>Status is <code>rejected</code> when the capture fails a quality check, with the fix in <code>quality.problems</code>, and <code>needs_calibration</code> when the phone has no trained model yet. Sift never returns a verdict it didn't measure.</p>

      <p><a class="btn" href="${esc(base)}/docs" target="_blank" rel="noopener">Full API reference</a></p>
    </section>`;
}
