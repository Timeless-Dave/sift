import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { scanApi, type Food as FoodT } from "../api";
import { SensorGlyph } from "../components/SensorGlyph";
import { Spectrum } from "../components/Spectrum";
import { KIND, Status, STATUS_TEXT } from "../components/Status";
import { FOOD_PHOTO } from "../data/foods";
import { SENSOR_INFO } from "../scanner";
import { safeUrl } from "../util";
import "../styles/foods.css";

export default function Food() {
  const { id = "" } = useParams();
  const [f, setF] = useState<FoodT | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { scanApi.food(id).then(setF).catch((e) => setError((e as Error).message)); }, [id]);
  if (error) return <section className="wrap page"><Link className="back" to="/foods">← All foods</Link><h1 className="h1">{error}</h1></section>;
  if (!f) return <section className="wrap page muted">Loading…</section>;
  return (
    <article className="food wrap page">
      <Link className="back" to="/foods">← All foods</Link>
      <header className="food-hero">
        <div className="food-hero-copy">
          <p className="eyebrow">{f.category}</p>
          <h1 className="display">{f.name}</h1>
          {f.summary && <p className="lede">{f.summary}</p>}
          <p className="hold"><span className="eyebrow">Hold the phone</span>{f.scan.placement}</p>
          <Link to="/scan" className="btn" onClick={() => { try { localStorage.setItem("sift.food", f.id); } catch { /* storage off */ } }}>
            Scan {f.name.toLowerCase()} <span className="arrow">→</span></Link>
        </div>
        {FOOD_PHOTO[f.id] ? <img className="food-photo" src={FOOD_PHOTO[f.id]} alt="" /> : <div className="food-photo plate"><Spectrum className="big" /></div>}
      </header>

      <section className="senses">
        <p className="eyebrow">Senses used</p>
        <ul>{f.scan.modalities.map((m) => <li key={m}><SensorGlyph kind={m} size={40} /><span>{SENSOR_INFO[m]?.name ?? m}</span></li>)}</ul>
      </section>

      {f.targets.map((t) => (
        <section key={t.id} className="target">
          <div className="target-head">
            <p className="eyebrow">{KIND[t.kind] ?? t.kind}</p>
            <Status status={t.status} />
          </div>
          <h2 className="h1">{t.question}</h2>
          <p className="muted">{STATUS_TEXT[t.status]}</p>
          {t.signals && (
            <dl className="signals">
              {Object.entries(t.signals).map(([m, why]) => (
                <div key={m}><dt><SensorGlyph kind={m} size={28} />{SENSOR_INFO[m]?.name ?? m}</dt><dd>{why}</dd></div>
              ))}
            </dl>
          )}
          {t.likely_causes?.length ? <div className="note"><p className="eyebrow">If a scan doesn't match, it could be</p><ul>{t.likely_causes.map((c) => <li key={c}>{c}</li>)}</ul></div> : null}
          {t.references?.length ? (
            <details className="sources"><summary>Sources ({t.references.length})</summary>
              <ol>{t.references.map((r) => (
                <li key={r.url}>{safeUrl(r.url) ? <a href={r.url} target="_blank" rel="noopener">{r.title}</a> : r.title}
                  <span className="muted">, {r.source}.</span> <span>{r.finding}</span></li>
              ))}</ol>
            </details>
          ) : null}
        </section>
      ))}

      {f.limits?.length ? <section className="limits"><p className="eyebrow">Limits</p><ul>{f.limits.map((l) => <li key={l}>{l}</li>)}</ul></section> : null}
    </article>
  );
}
