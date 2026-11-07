import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { scanApi, type Food } from "../api";
import { Spectrum } from "../components/Spectrum";
import { KIND, Status, STATUS_TEXT } from "../components/Status";
import { FOOD_PHOTO } from "../data/foods";
import "../styles/foods.css";

export default function Foods() {
  const [foods, setFoods] = useState<Food[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { scanApi.foods().then(setFoods).catch((e) => setError((e as Error).message)); }, []);
  return (
    <section className="foods wrap page">
      <header className="page-head">
        <p className="eyebrow">What it checks</p>
        <h1 className="h1">Nine foods. Every question,<br /><em>with how far it has got.</em></h1>
        <p className="lede">A question only gets verdicts once Sift has reference scans of samples with known answers. Until then it says so.</p>
      </header>
      <dl className="legend">
        {(["experimental", "research"] as const).map((s) => <div key={s}><dt><Status status={s} /></dt><dd>{STATUS_TEXT[s]}</dd></div>)}
      </dl>
      {error && <p className="muted">{error}</p>}
      {!foods && !error && <p className="muted">Loading…</p>}
      <ul className="food-index">
        {(foods ?? []).map((f) => (
          <li key={f.id}>
            <Link to={`/foods/${f.id}`}>
              {FOOD_PHOTO[f.id] ? <img src={FOOD_PHOTO[f.id]} alt="" loading="lazy" /> : <span className="plate"><Spectrum /></span>}
              <div>
                <h2 className="h2">{f.name}</h2>
                <ul>{f.targets.map((t) => <li key={t.id}><span>{KIND[t.kind] ?? t.kind}</span><Status status={t.status} /></li>)}</ul>
              </div>
              <span className="go mono">→</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
