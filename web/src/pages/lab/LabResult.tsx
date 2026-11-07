import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Assay, type Band, type RunResult, type RunRow } from "../../api";
import { download, getTier, safeUrl } from "../../util";
import "../../styles/lab.css";

const verdictWord: Record<string, string> = {
  pass: "Looks fine",
  caution: "Check further",
  flag: "Flagged",
  unknown: "Not yet known",
};

const fmt = (n: unknown) => {
  const v = Number(n);
  if (!Number.isFinite(v)) return "–";
  return Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(2).replace(/\.?0+$/, "");
};

export default function LabResult() {
  const { id = "" } = useParams();
  const [run, setRun] = useState<RunRow | null>(null);
  const [assay, setAssay] = useState<Assay | null>(null);
  const [error, setError] = useState("");
  const research = getTier() === "research";

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const row = await api.run(id);
        const a = await api.assay(row.assay_id);
        if (!live) return;
        setRun(row);
        setAssay(a);
      } catch (e) {
        if (live) setError((e as Error).message);
      }
    })();
    return () => { live = false; };
  }, [id]);

  if (error) {
    return (
      <div className="wrap page lab-result">
        <section className="page-head">
          <Link className="back" to="/lab-tests">← All tests</Link>
          <h1 className="h1">Result</h1>
          <p role="alert">Couldn&apos;t load the result: {error}</p>
        </section>
      </div>
    );
  }
  if (!run || !assay) return <div className="wrap page lab-result"><p className="muted">Loading the result…</p></div>;

  const r: RunResult = { ...run.result, run_id: id };

  return (
    <div className={`wrap page lab-result verdict-${r.verdict ?? r.status}`}>
      <section className="result">
        <Link className="back" to={`/lab-tests/run/${assay.id}`}>← Run this test again</Link>
        <p className="food">{assay.food}: {assay.name}</p>
        <Headline r={r} />
        {r.status === "ok" && <Scale r={r} assay={assay} />}
        <p className="report">{r.report?.text}</p>
        <p className="agent-tag">
          {r.report?.agent === "muse-spark"
            ? "Written by the Lab Agent from Sift's measurements"
            : "Written from Sift's measurements"}
        </p>
        <Problems r={r} />
        {r.capture_review?.issues?.length ? (
          <div className="note">
            <h2 className="h3">What the Lab Agent noticed</h2>
            <ul>{r.capture_review.issues.map((i) => <li key={i}>{i}</li>)}</ul>
          </div>
        ) : null}
        {assay.confirm_with && r.status === "ok" ? (
          <div className="note">
            <h2 className="h3">How a lab would confirm this</h2>
            <p>{assay.confirm_with}</p>
          </div>
        ) : null}
        <details className="sources">
          <summary>Method and sources</summary>
          <ul>
            {assay.references.map((ref) => {
              const url = safeUrl(ref.url);
              return (
                <li key={ref.title}>
                  {url
                    ? <a href={url} target="_blank" rel="noopener">{ref.title}</a>
                    : ref.title}, {ref.source}. {ref.finding}
                </li>
              );
            })}
          </ul>
          {assay.limitations?.length ? (
            <>
              <h3 className="h3">Limits of this test</h3>
              <ul>{assay.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
            </>
          ) : null}
        </details>
        {research && <ResearchPanel r={r} assay={assay} device={run.device} />}
      </section>
    </div>
  );
}

function Headline({ r }: { r: RunResult }) {
  if (r.status === "rejected") {
    return (
      <>
        <h1 className="h1">Retake needed</h1>
        <p className="lede">Sift couldn&apos;t read this capture reliably, so it didn&apos;t guess.</p>
      </>
    );
  }
  if (r.status === "needs_calibration") {
    return (
      <>
        <h1 className="h1">Calibration needed</h1>
        <p className="lede">{r.label}</p>
      </>
    );
  }
  const conf = Math.round((r.confidence ?? 0) * 100);
  return (
    <>
      <p className="verdict">{verdictWord[r.verdict ?? "unknown"]}</p>
      <h1 className="h1">{r.label}</h1>
      <p className="confidence">
        <span className="meter" style={{ ["--c" as string]: `${conf}%` }} />
        {conf}% confident
        {r.mode === "qualitative" ? ", present or absent only" : ""}
        {r.in_range === false ? ", outside the calibrated range" : ""}
      </p>
    </>
  );
}

/** The calibration-strip scale: bands as coloured segments, the sample as a marker. */
function Scale({ r, assay }: { r: RunResult; assay: Assay }) {
  const bands = assay.analysis?.bands ?? [];
  if (r.mode === "qualitative" || r.value == null || !bands.length) {
    const pos = r.verdict === "flag";
    return (
      <div className="scale two" role="img" aria-label={pos ? "Present" : "Absent"}>
        <span className={`seg pass${pos ? "" : " hit"}`}>Not detected</span>
        <span className={`seg flag${pos ? " hit" : ""}`}>Detected</span>
      </div>
    );
  }
  const top = Math.max(
    bands.length > 1 ? bands[bands.length - 2].max * 2 : bands[0].max,
    (r.value ?? 0) * 1.1,
  );
  let prev = 0;
  const segs = bands.map((b: Band) => {
    const hi = Math.min(b.max, top);
    const w = Math.max(0, ((hi - prev) / top) * 100);
    const label = fmt(prev);
    prev = hi;
    return (
      <span key={`${b.max}-${b.label}`} className={`seg ${b.verdict}`} style={{ width: `${w}%` }}>
        <b>{label}</b>
      </span>
    );
  });
  const at = Math.min(100, ((r.value ?? 0) / top) * 100);
  return (
    <>
      <div className="scale" role="img" aria-label={`${fmt(r.value)} ${r.unit ?? ""}`}>
        {segs}
        <span className="marker" style={{ left: `${at}%` }}><em>{fmt(r.value)}</em></span>
      </div>
      <p className="unit">{r.unit}</p>
    </>
  );
}

function Problems({ r }: { r: RunResult }) {
  const list = r.quality?.problems ?? [];
  if (!list.length) return null;
  return (
    <div className="note problems">
      <h2 className="h3">{r.status === "rejected" ? "How to fix the capture" : "Worth knowing"}</h2>
      <ul>
        {list.map((p) => (
          <li key={p.code}><strong>{p.message}</strong> {p.fix}</li>
        ))}
      </ul>
    </div>
  );
}

function ResearchPanel({ r, assay, device }: { r: RunResult; assay: Assay; device: string }) {
  const feats = r.features ?? {};
  const rows = Object.entries({ ...feats, ...(r.quality?.metrics ?? {}) })
    .filter(([k, v]) => k !== "vector" && typeof v !== "object");
  const isNumeric = assay.method === "screenlight" || r.value != null;
  const [known, setKnown] = useState("");
  const [out, setOut] = useState("");

  const record = async (act: "sample" | "truth") => {
    const v = Number(known);
    if (known.trim() === "" || !Number.isFinite(v)) return;
    try {
      if (act === "sample") {
        const s = await api.addSample(r.run_id, v);
        setOut(`Added. ${s.samples} calibration samples for ${device}.`);
      } else {
        const t = await api.setTruth(r.run_id, v);
        setOut(`Recorded. ${t.accuracy.summary}`);
      }
    } catch (e) {
      setOut((e as Error).message);
    }
  };

  return (
    <section className="research">
      <h2 className="h2">Run data</h2>
      <table className="data">
        <tbody>
          {rows.map(([k, v]) => <tr key={k}><th>{k}</th><td>{String(v)}</td></tr>)}
        </tbody>
      </table>
      {r.segmentation && (
        <p className="muted">
          Sample area found by {r.segmentation}. Card swatch fit ΔE {String(r.card?.fit_delta_e)}.
        </p>
      )}
      {r.status !== "rejected" && (
        <form className="known" onSubmit={(e) => e.preventDefault()}>
          <label>
            Known answer for this sample{isNumeric ? ` (${assay.analysis?.unit ?? ""})` : " (0 = absent, 1 = present)"}
            <input
              name="known"
              type="number"
              step="any"
              required
              value={known}
              onChange={(e) => setKnown(e.target.value)}
            />
          </label>
          <div className="row">
            <button type="submit" className="btn" onClick={() => void record("sample")}>Add to calibration</button>
            <button type="submit" className="btn ghost" onClick={() => void record("truth")}>Record as validation run</button>
          </div>
          <p className="muted">Calibration samples train this phone&apos;s model. Validation runs measure accuracy; don&apos;t use the same sample for both.</p>
          <p className="known-out" role="status">{out}</p>
        </form>
      )}
      <div className="row">
        <button
          type="button"
          className="btn ghost"
          onClick={() => download(`sift-${assay.id}-${r.run_id}.json`, JSON.stringify({ assay: assay.id, device, ...r }, null, 2))}
        >
          Export run (JSON)
        </button>
        <Link className="btn ghost" to={`/lab-tests/calibration/${assay.id}`}>Calibration and history</Link>
      </div>
    </section>
  );
}
