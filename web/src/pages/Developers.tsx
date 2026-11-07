import { API } from "../api";
import "../styles/developers.css";

const SCAN_EXAMPLE = `{
  "food": "honey",
  "device": "Pixel 8",
  "mode": "check",
  "capture": {
    "torch": {
      "off": { "mean": [0.42, 0.28, 0.11], "std": [0.03, 0.03, 0.02], "clipped": 0.0 },
      "on": { "mean": [0.81, 0.62, 0.31], "std": [0.04, 0.04, 0.03], "clipped": 0.0 },
      "torch_available": true
    },
    "bubble": { "fps": 30, "track": [0.12, 0.31, 0.55, 0.78], "rise_time_s": 2.4, "tracked_fraction": 0.97 }
  }
}`;

const SCAN_REPLY = `{
  "scan_id": "9d2f7c1a4b6e",
  "food": "honey",
  "mode": "check",
  "status": "ok",
  "quality": { "ok": true, "problems": [] },
  "match": { "status": "matches", "distance": 0.31, "threshold": 0.5,
             "n_genuine": 42, "modalities": ["torch", "bubble"] },
  "findings": [
    { "target": "honey-syrup", "status": "model",
      "label": "Matches genuine", "confidence": 0.88 }
  ],
  "report": { "agent": "muse-spark", "text": "…" }
}`;

const SCREENLIGHT_EXAMPLE = `curl -X POST BASE/v1/runs/screenlight \\
  -H "Content-Type: application/json" \\
  -d '{"assay_id":"olive-oil-screenlight","device":"Pixel 8",
       "frames":{"white":[[0.81,0.80,0.79]],"black":[[0.02,0.02,0.02]],"red":[[0.41,0.12,0.10]]}}'`;

const RUN_REPLY = `{
  "run_id": "3f9c1a2b7d4e",
  "status": "ok",
  "verdict": "flag",
  "label": "Starch detected",
  "confidence": 0.74,
  "mode": "qualitative",
  "quality": { "ok": true, "problems": [], "metrics": { "sharpness": 412.3 } },
  "report": { "agent": "muse-spark", "text": "…" }
}`;

export default function Developers() {
  const base = new URL(API, window.location.href).href.replace(/\/$/, "");
  const docs = `${API}/docs`;

  return (
    <div className="wrap page developers">
      <section className="page-head">
        <p className="eyebrow">API</p>
        <h1 className="h1">Run Sift tests from your own app</h1>
        <p className="lede">
          The Sift app uses the same API you do. Send a capture, get back a result, its confidence,
          the quality checks and the method&apos;s sources.
        </p>
      </section>

      <h2 className="h2">Scan food with the phone&apos;s sensors</h2>
      <p>
        The scanner never uploads raw audio or video. Each sensor module summarises its readings on the
        phone and sends one JSON document.
      </p>

      <h3 className="h3">List the foods</h3>
      <pre><code>{`curl ${base}/v1/foods`}</code></pre>

      <h3 className="h3">Send a scan</h3>
      <pre><code>{`curl -X POST ${base}/v1/scans \\
  -H "Content-Type: application/json" \\
  -d '${SCAN_EXAMPLE}'`}</code></pre>
      <p>
        Every reading is a summary computed on the phone: torch on/off colours, the screen-light
        response per colour, acoustic bins, vibration spectra, contact rings, the bubble track, motion.
        Include only the modalities the food needs; <code>mode</code> is <code>check</code> for a
        screening or <code>reference</code> for a labelled sample.
      </p>

      <h3 className="h3">What comes back</h3>
      <pre><code>{SCAN_REPLY}</code></pre>
      <p>
        <code>match.status</code> is <code>matches</code>, <code>differs</code> or{" "}
        <code>no_reference</code> when that food has too few genuine scans on that phone.{" "}
        <code>status</code> is <code>rejected</code> when a quality check fails, with the fix in{" "}
        <code>quality.problems</code>. Sift never returns a verdict it didn&apos;t measure.
      </p>

      <h3 className="h3">Fetch a past scan</h3>
      <pre><code>{`curl ${base}/v1/scans/{id}`}</code></pre>
      <p>Returns the stored row; the scan result sits under <code>result</code>.</p>

      <h3 className="h3">Identify the food in a frame</h3>
      <pre><code>{`curl -X POST ${base}/v1/identify \\
  -F image=@frame.jpg`}</code></pre>
      <p>Returns the most likely food, a confidence from 0 to 1, and the candidate list.</p>

      <h3 className="h3">Look up a barcode</h3>
      <pre><code>{`curl ${base}/v1/products/{barcode}`}</code></pre>
      <p>Maps a barcode to a product name and, where known, the Sift food it belongs to.</p>

      <h2 className="h2">Run a reagent lab test</h2>

      <h3 className="h3">List the tests</h3>
      <pre><code>{`curl ${base}/v1/assays`}</code></pre>

      <h3 className="h3">Run a colour test from a photo of the reference card</h3>
      <pre><code>{`curl -X POST ${base}/v1/runs/card \\
  -F assay_id=milk-starch-iodine \\
  -F device="Pixel 8" \\
  -F tier=research \\
  -F image=@capture.jpg`}</code></pre>

      <h3 className="h3">Run a screen-light scan</h3>
      <p>
        Send the mean camera colour of each frame, grouped by the colour on screen, in the order of
        the test&apos;s <code>analysis.sequence</code>.
      </p>
      <pre><code>{SCREENLIGHT_EXAMPLE.replaceAll("BASE", base)}</code></pre>

      <h3 className="h3">What comes back</h3>
      <pre><code>{RUN_REPLY}</code></pre>
      <p>
        Status is <code>rejected</code> when the capture fails a quality check, with the fix in{" "}
        <code>quality.problems</code>, and <code>needs_calibration</code> when the phone has no
        trained model yet. Sift never returns a verdict it didn&apos;t measure.
      </p>

      <p><a className="btn" href={docs} target="_blank" rel="noopener">Full API reference</a></p>
    </div>
  );
}
