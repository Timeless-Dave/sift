import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API, api, type Assay } from "../../api";
import { getTier, safeUrl } from "../../util";
import "../../styles/lab.css";

const methodWords: Record<string, string> = {
  colorimetric: "Colour reaction on the reference card",
  screenlight: "Screen-light scan, no reagents",
  microscopy: "Clip-on microscope",
};

export default function LabTests() {
  const [assays, setAssays] = useState<Assay[] | null>(null);
  const [error, setError] = useState("");
  const research = getTier() === "research";

  useEffect(() => {
    let live = true;
    api.assays().then(
      (a) => { if (live) setAssays(a); },
      (e) => { if (live) setError((e as Error).message); },
    );
    return () => { live = false; };
  }, []);

  if (error) {
    return (
      <div className="wrap page lab-tests">
        <section className="page-head">
          <Link className="back" to="/scan">← Back to the scanner</Link>
          <h1 className="h1">Lab tests</h1>
          <p role="alert">Couldn&apos;t load the tests: {error}</p>
        </section>
      </div>
    );
  }
  if (!assays) {
    return <div className="wrap page lab-tests"><p className="muted">Loading the tests…</p></div>;
  }

  const ready = assays.filter((a) => a.runnable);
  const planned = assays.filter((a) => !a.runnable);

  return (
    <div className="wrap page lab-tests">
      <section className="page-head">
        <Link className="back" to="/scan">← Back to the scanner</Link>
        <p className="eyebrow">Reagent tests</p>
        <h1 className="h1">Lab tests</h1>
        <p className="lede">
          {research
            ? "Reagent tests that follow a published method. Calibrate them per phone, record runs with known answers, export the raw data."
            : "When a scan doesn't match, these confirm it at home: a few drops of a pharmacy reagent, photographed on the printed card."}
        </p>
      </section>

      <section aria-labelledby="ready-h">
        <h2 id="ready-h" className="h2">Reagent tests</h2>
        <ul className="assays">
          {ready.map((a) => (
            <li key={a.id}>
              <Link className="assay" to={`/lab-tests/run/${a.id}`}>
                <span className="food">{a.food}</span>
                <span className="name">{a.name}</span>
                <span className="q">{a.question}</span>
                <span className="meta">{methodWords[a.method] ?? a.method}</span>
                {research && a.accuracy ? <span className="meta acc mono">{a.accuracy.summary}</span> : null}
              </Link>
              {research ? <Link className="lab-link" to={`/lab-tests/calibration/${a.id}`}>Calibration and runs</Link> : null}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="planned-h" className="planned">
        <h2 id="planned-h" className="h2">Being built next</h2>
        <p className="muted">Each of these is based on published research and isn&apos;t runnable yet.</p>
        <ul className="assays quiet">
          {planned.map((a) => {
            const ref = a.references?.[0];
            const url = ref ? safeUrl(ref.url) : "";
            return (
              <li className="assay quiet" key={a.id}>
                <span className="food">{a.food}</span>
                <span className="name">{a.name}</span>
                <span className="q">{a.summary}</span>
                <span className="meta">
                  {ref ? (
                    <>Based on {url
                      ? <a href={url} target="_blank" rel="noopener">{ref.title}</a>
                      : ref.title}</>
                  ) : "Based on published research"}
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="card-cta card">
        <div>
          <h2 className="h3">Print the reference card</h2>
          <p>Colour tests need it in every photo. Print at 100% size on plain white paper.</p>
        </div>
        <a className="btn" href={`${API}/v1/card.svg`} target="_blank" rel="noopener">Open the card</a>
      </section>
    </div>
  );
}
