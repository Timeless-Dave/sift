/**
 * One scan's answer. The headline says only what the reference library supports; the readings are the
 * phone's own measurements, drawn from the capture kept on this device.
 */
import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { scanApi, type Food, type ScanResult as Result } from "../api";
import { SensorGlyph } from "../components/SensorGlyph";
import { Status } from "../components/Status";
import { SCREEN_COLOURS, SENSOR_INFO } from "../scanner";
import type { Capture } from "../sensors/types";
import { getTier } from "../util";
import "../styles/result.css";

const MIN_GENUINE = 5;

export default function ScanResult() {
  const { id = "" } = useParams();
  const [r, setR] = useState<Result | null>(null);
  const [food, setFood] = useState<Food | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    scanApi.result(id).then((res) => { setR(res); return scanApi.food(res.food).then(setFood).catch(() => null); })
      .catch((e) => setError((e as Error).message));
  }, [id]);
  const capture = readCapture(id);

  if (error) return <section className="wrap page"><h1 className="h1">Couldn't load this scan</h1><p className="muted">{error}</p><Link className="btn" to="/scan">Back to the scanner</Link></section>;
  if (!r) return <section className="wrap page muted">Loading the result…</section>;

  const name = food?.name ?? r.food;
  const lower = name.toLowerCase();
  const state = r.status !== "ok" ? r.status : r.match.status;
  const causes = [...new Set((food?.targets ?? []).flatMap((t) => t.likely_causes ?? []))];
  const research = getTier() === "research";

  return (
    <article className={`result wrap page state-${state}`}>
      <Link to="/scan" className="back">← Scan something else</Link>

      <header className="result-head">
        <p className="eyebrow">{name} · scan {r.scan_id}</p>
        <Headline r={r} lower={lower} />
        {r.status === "ok" && <Meter r={r} />}
      </header>

      <div className="result-grid">
        <div className="result-main">
          {r.quality.problems.length > 0 && (
            <section className={`card problems ${r.status === "rejected" ? "reject" : ""}`}>
              <h2 className="h3">{r.status === "rejected" ? "How to get a clean scan" : "Worth knowing"}</h2>
              <ul>{r.quality.problems.map((p) => <li key={p.modality + p.code}><strong>{p.message}</strong> {p.fix}</li>)}</ul>
            </section>
          )}

          {r.status === "ok" && r.match.status === "differs" && causes.length > 0 && (
            <section className="card">
              <h2 className="h3">What a mismatch can mean</h2>
              <ul>{causes.map((c) => <li key={c}>{c}</li>)}</ul>
            </section>
          )}

          {r.report?.text && (
            <section className="report">
              <p>{r.report.text}</p>
              <p className="fine muted mono">{r.report.agent === "muse-spark" ? "Explained by the Lab Agent from Sift's measurements" : "Written from Sift's measurements"}</p>
            </section>
          )}

          {r.findings.length > 0 && (
            <section>
              <h2 className="h2 sub">Questions Sift is working on</h2>
              <ul className="findings">
                {r.findings.map((f) => {
                  const t = food?.targets.find((x) => x.id === f.target);
                  const acc = typeof f.model?.cv_accuracy === "number" ? ` · ${Math.round(Number(f.model.cv_accuracy) * 100)}% cross-validated` : "";
                  return (
                    <li key={f.target}>
                      <p>{t?.question ?? f.target}</p>
                      <div><Status status={t?.status ?? "research"} /><span className="muted fine">{f.label}{acc}</span></div>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          {r.status === "ok" && r.match.status === "no_reference" && (
            <section className="card learn">
              <h2 className="h3">Help Sift learn {lower}</h2>
              <p>A verdict needs scans of samples whose answer is known: at least {MIN_GENUINE} genuine ones on this phone model,
                and labelled adulterated ones for each question. {research
                  ? "Turn on “Add as a reference scan” when you scan a sample you can vouch for."
                  : "Switch on Researcher in the scanner to add them."}</p>
              <Link to="/scan" className="btn small">Back to the scanner</Link>
            </section>
          )}
        </div>

        <aside className="result-side">
          {capture ? <Readings c={capture} /> : <p className="muted fine">This device didn't keep the raw readings for this scan.</p>}
          <p className="fine muted">A screening result from phone sensors, not a lab analysis.{" "}
            <Link to={`/foods/${r.food}`}>How Sift checks {lower}</Link> · <Link to="/lab-tests">Confirm with a lab test</Link></p>
        </aside>
      </div>
    </article>
  );
}

function Headline({ r, lower }: { r: Result; lower: string }) {
  if (r.status === "rejected") return <><h1 className="h1">Couldn't read this scan</h1><p className="lede">Sift didn't guess. The fixes are below.</p></>;
  if (r.status === "stored") return <><h1 className="h1">Reference saved</h1><p className="lede">{r.match.n_genuine} genuine reference scan{r.match.n_genuine === 1 ? "" : "s"} of {lower} for this phone model.</p></>;
  if (r.match.status === "matches") return <><h1 className="h1">Matches genuine {lower}</h1><p className="lede">This scan sits inside the spread of {r.match.n_genuine} genuine reference scans from this phone model.</p></>;
  if (r.match.status === "differs") return <><h1 className="h1">Doesn't match genuine {lower}</h1><p className="lede">It falls outside the spread of {r.match.n_genuine} genuine reference scans from this phone model. A reason to look closer, not proof of fraud.</p></>;
  return <><h1 className="h1">No verdict yet</h1><p className="lede">Sift has {r.match.n_genuine} of the {MIN_GENUINE} genuine reference scans it needs for {lower} on this phone model, so it won't guess.</p></>;
}

/** Distance from the genuine centre, with the genuine spread shaded. */
function Meter({ r }: { r: Result }) {
  const { distance, threshold, modalities } = r.match;
  if (distance == null || threshold == null || threshold <= 0) return null;
  const top = Math.max(threshold * 2, distance * 1.1);
  return (
    <div className="meter-wrap">
      <div className="meter" role="img" aria-label={`Distance ${distance.toFixed(2)}; genuine limit ${threshold.toFixed(2)}`}>
        <span className="zone" style={{ width: `${(threshold / top) * 100}%` }}>{threshold / top > 0.22 && <span className="mono">genuine spread</span>}</span>
        <span className="dot" style={{ left: `${Math.min(100, (distance / top) * 100)}%` }} />
      </div>
      <p className="fine muted mono">distance {distance.toFixed(2)} · limit {threshold.toFixed(2)} · {modalities.map((m) => SENSOR_INFO[m]?.name ?? m).join(", ")}</p>
    </div>
  );
}

/** The phone's own readings for this scan. */
function Readings({ c }: { c: Capture }) {
  const blocks: ReactNode[] = [];
  const sl = c.screenlight?.frames;
  if (sl?.white && sl?.black) {
    const mean = (rows: number[][]) => rows[0].map((_, i) => rows.reduce((s, row) => s + row[i], 0) / rows.length);
    const dark = mean(sl.black), white = mean(sl.white);
    const bars = Object.entries(sl).filter(([k]) => k !== "white" && k !== "black").map(([k, rows]) => {
      const m = mean(rows);
      const v = m.reduce((s, x, i) => s + Math.max(0, (x - dark[i]) / Math.max(1e-3, white[i] - dark[i])), 0) / 3;
      return <span key={k} title={`${k}: ${v.toFixed(2)}`} style={{ height: `${Math.min(100, v * 100)}%`, background: SCREEN_COLOURS[k] ?? "#888" }} />;
    });
    blocks.push(<Reading key="sl" kind="screenlight" caption="Light returned under each screen colour"><div className="bars">{bars}</div></Reading>);
  }
  if (c.acoustic?.bins_hz?.length) {
    const a = c.acoustic;
    const t = a.response_db.map((v, i) => v - a.noise_db[i]);
    const lo = Math.min(...t), hi = Math.max(...t), span = hi - lo || 1;
    const fx = (f: number) => (Math.log(f / a.bins_hz[0]) / Math.log(a.bins_hz[a.bins_hz.length - 1] / a.bins_hz[0])) * 300;
    const pts = a.bins_hz.map((f, i) => `${fx(f).toFixed(1)},${(92 - ((t[i] - lo) / span) * 84).toFixed(1)}`).join(" ");
    const hz = (f: number) => (f >= 1000 ? `${Math.round(f / 1000)} kHz` : `${Math.round(f)} Hz`);
    blocks.push(<Reading key="ac" kind="acoustic" caption="Sound through the food, above background">
      <svg viewBox="0 0 300 100" className="curve" role="img" aria-label="Sound transmission curve"><polyline points={pts} /></svg>
      <div className="axis mono"><span>{hz(a.bins_hz[0])}</span><span>{hz(a.bins_hz[a.bins_hz.length - 1])}</span></div>
    </Reading>);
  }
  if (c.torch) {
    const sw = (m: number[]) => `rgb(${m.map((x) => Math.round(x * 255)).join(",")})`;
    blocks.push(<Reading key="to" kind="torch" caption="Colour with the flash off and on">
      <div className="swatches"><span style={{ background: sw(c.torch.off.mean) }}>off</span>
        {c.torch.on ? <span style={{ background: sw(c.torch.on.mean) }}>on</span> : <em className="muted fine">No controllable torch on this phone</em>}</div>
    </Reading>);
  }
  if (c.contact) {
    const rings = c.contact.rings.map((rgb, i) => <span key={i} style={{ background: `rgb(${rgb.map((x) => Math.round(x * 255)).join(",")})` }} />);
    blocks.push(<Reading key="co" kind="contact" caption="Torch light coming back out of the tissue, centre to edge"><div className="rings">{rings}</div></Reading>);
  }
  if (c.bubble) {
    const b = c.bubble;
    const pts = b.track.map((y, i) => `${((i / Math.max(1, b.track.length - 1)) * 300).toFixed(1)},${(95 - y * 90).toFixed(1)}`).join(" ");
    blocks.push(<Reading key="bu" kind="bubble" caption={`Bubble height over time${b.rise_time_s != null ? ` · rise ${b.rise_time_s.toFixed(2)} s` : ""}`}>
      <svg viewBox="0 0 300 100" className="curve" role="img" aria-label="Bubble track"><polyline points={pts} /></svg>
    </Reading>);
  }
  if (c.vibration?.vibrate_available) {
    const ratio = c.vibration.rms_off > 0 ? c.vibration.rms_on / c.vibration.rms_off : 0;
    blocks.push(<Reading key="vi" kind="vibration" caption="Motion with the motor on, relative to off"><p className="big-n">{ratio.toFixed(1)}×</p></Reading>);
  }
  if (!blocks.length) return null;
  return <section className="readings"><p className="eyebrow">What the phone measured</p>{blocks}</section>;
}

function Reading({ kind, caption, children }: { kind: string; caption: string; children: ReactNode }) {
  return (
    <figure className="reading">
      <figcaption><SensorGlyph kind={kind} size={28} /><span><b>{SENSOR_INFO[kind]?.name ?? kind}</b> {caption}</span></figcaption>
      {children}
    </figure>
  );
}

function readCapture(id: string): Capture | null {
  try { const s = sessionStorage.getItem(`sift.capture.${id}`); return s ? (JSON.parse(s) as Capture) : null; } catch { return null; }
}
