import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { scanApi, type Food } from "../api";
import { SensorGlyph, SENSORS } from "../components/SensorGlyph";
import { Spectrum } from "../components/Spectrum";
import { KIND, Status } from "../components/Status";
import { FOOD_PHOTO } from "../data/foods";
import { SCREEN_COLOURS, SCREEN_SEQUENCE } from "../scanner";
import "../styles/landing.css";

const FEATURED = ["honey", "olive-oil", "beef", "cow-milk", "fish-fillet", "turmeric"];

export default function Landing() {
  const [foods, setFoods] = useState<Food[] | null>(null);
  useEffect(() => { scanApi.foods().then(setFoods).catch(() => setFoods([])); }, []);
  const byId = new Map((foods ?? []).map((f) => [f.id, f]));

  return (
    <div className="landing">
      {/* ---- Hero ------------------------------------------------------------------- */}
      <section className="hero wrap">
        <div className="hero-copy">
          <p className="eyebrow">Food screening · phone only · no reagents</p>
          <h1 className="display">Check the food,<br /><em>not the label.</em></h1>
          <p className="lede">
            Sift turns your phone's screen, torch, speaker and camera into a pocket instrument. In about ten seconds in the
            aisle, it fingerprints honey, oil, milk, meat and spices and compares them with genuine samples.
          </p>
          <div className="hero-cta">
            <Link to="/scan" className="btn">Open the scanner <span className="arrow">→</span></Link>
            <a href="#evidence" className="btn ghost">See the evidence</a>
          </div>
          <p className="fine muted honest">No verdict without evidence. When Sift doesn't know, it says so.</p>
        </div>
        <ScanFigure />
      </section>

      {/* ---- Strip --------------------------------------------------------------------- */}
      <section className="strip" aria-label="Foods Sift checks">
        <div className="strip-track">
          {[0, 1].map((k) => (
            <span key={k} aria-hidden={k === 1}>
              {["Honey", "Olive oil", "Cow milk", "Beef", "Chicken", "Fish", "Turmeric", "Chilli powder", "Sunflower oil"].map((n) => (
                <span key={n} className="strip-item">{n}<i /></span>
              ))}
            </span>
          ))}
        </div>
      </section>

      {/* ---- Sensors ------------------------------------------------------------------- */}
      <section className="wrap section" id="how">
        <div className="section-head">
          <p className="eyebrow">How it works</p>
          <h2 className="h1">One phone.<br />Six ways to look.</h2>
          <p className="lede">
            No attachments. Sift uses only hardware already in your pocket, picks the senses that fit the food, and tells
            you when to turn the phone over.
          </p>
        </div>
        <ol className="sensors">
          {SENSORS.map((s, i) => (
            <li key={s.kind} className="sensor">
              <span className="sensor-n mono">{String(i + 1).padStart(2, "0")}</span>
              <SensorGlyph kind={s.kind} />
              <h3 className="h3">{s.name}</h3>
              <p className="mono fine sensor-spec">{s.spec}</p>
              <p className="muted">{s.what}</p>
            </li>
          ))}
        </ol>
        <p className="fine muted physics">
          What a phone can't do: see infrared or ultraviolet, or send real ultrasound. Light reads the surface and the first
          few millimetres, and tinted packaging blocks it. Sift is built around those limits, not around claims.
        </p>
      </section>

      {/* ---- Answers ------------------------------------------------------------------- */}
      <section className="answers-band">
        <div className="wrap section">
          <div className="section-head">
            <p className="eyebrow">What you get back</p>
            <h2 className="h1">Three answers.<br /><em>Never a guess.</em></h2>
          </div>
          <div className="answers">
            <article className="answer-card match">
              <span className="mono fine">01</span>
              <h3 className="h2">Matches genuine</h3>
              <p>The scan sits inside the spread of genuine samples of that food, measured on the same kind of phone.</p>
            </article>
            <article className="answer-card differs">
              <span className="mono fine">02</span>
              <h3 className="h2">Doesn't match</h3>
              <p>A reason to look closer, with the likely causes: dilution, a different grade, a different harvest. Never "fake".</p>
            </article>
            <article className="answer-card pending">
              <span className="mono fine">03</span>
              <h3 className="h2">No verdict yet</h3>
              <p>Not enough reference scans for that food on that phone. Sift says how many it still needs instead of guessing.</p>
            </article>
          </div>
        </div>
      </section>

      {/* ---- Foods --------------------------------------------------------------------- */}
      <section className="wrap section">
        <div className="section-head row">
          <div>
            <p className="eyebrow">What it checks</p>
            <h2 className="h1">Commonly faked foods,<br />checked honestly.</h2>
          </div>
          <Link to="/foods" className="btn ghost small">All nine foods <span className="arrow">→</span></Link>
        </div>
        <div className="food-grid">
          {FEATURED.map((id) => {
            const f = byId.get(id);
            return (
              <Link key={id} to={`/foods/${id}`} className="food-tile">
                <img src={FOOD_PHOTO[id]} alt="" loading="lazy" />
                <div className="food-tile-body">
                  <h3 className="h2">{f?.name ?? id.replace("-", " ")}</h3>
                  <ul>
                    {(f?.targets ?? []).map((t) => (
                      <li key={t.id}><span>{KIND[t.kind] ?? t.kind}</span><Status status={t.status} /></li>
                    ))}
                  </ul>
                </div>
              </Link>
            );
          })}
        </div>
      </section>

      {/* ---- Evidence ------------------------------------------------------------------ */}
      <section className="wrap section" id="evidence">
        <div className="section-head">
          <p className="eyebrow">The evidence</p>
          <h2 className="h1">What the research says<br /><em>a phone can do.</em></h2>
          <p className="lede">
            These are other researchers' results on their own setups. Sift doesn't borrow them. It measures its own accuracy
            from reference scans.
          </p>
        </div>
        <div className="evidence">
          <Fact n="95.0%" text="of adulterated honey identified through sealed jars, from a phone video of the rising bubble."
            cite="Sun et al., LiquidHash, MobiSys 2022" href="https://doi.org/10.1145/3498361.3539776" />
          <Fact n="93% vs 57%" text="Visible-light sensing told pure from adulterated meat well, but not how much. So Sift screens; it doesn't measure."
            cite="Fengou et al., Foods 2021" href="https://pmc.ncbi.nlm.nih.gov/articles/PMC8071343/" />
          <Fact n="35.2%" text="more veins found with a phone-driven near-infrared prototype than by nursing students: light through tissue carries contrast."
            cite="Juric & Žalik, BMC Med Inform 2014" href="https://doi.org/10.1186/s12911-014-0100-z" />
          <Fact n="None" text="validated methods, phone or lab, to tell lab-grown from conventional meat. Sift collects labelled scans and gives no verdicts."
            cite="UK Food Standards Agency, 2026" href="https://science.food.gov.uk/article/167297-review-of-analytical-methods-for-cell-cultivated-products" />
        </div>
        <p className="fine muted">
          Full review, including papers we couldn't read in full:{" "}
          <a href="https://github.com/Timeless-Dave/sift/blob/main/docs/research.md">docs/research.md</a>.
        </p>
      </section>

      {/* ---- Aisle CTA ----------------------------------------------------------------- */}
      <section className="aisle">
        <img src="/img/aisle.webp" alt="" loading="lazy" />
        <div className="aisle-inner wrap">
          <Spectrum className="thin" />
          <h2 className="display">Built for the aisle,<br /><em>not the lab.</em></h2>
          <div className="hero-cta">
            <Link to="/scan" className="btn light">Open the scanner <span className="arrow">→</span></Link>
            <Link to="/scan" className="btn ghost light" onClick={() => { try { localStorage.setItem("sift.tier", "research"); } catch { /* storage off */ } }}>
              Help build the reference library
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}

function Fact({ n, text, cite, href }: { n: string; text: string; cite: string; href: string }) {
  return (
    <figure className="fact">
      <p className="fact-n">{n}</p>
      <figcaption>
        <p>{text}</p>
        <a className="mono fine" href={href} target="_blank" rel="noopener">{cite} ↗</a>
      </figcaption>
    </figure>
  );
}

/** The hero figure: a jar of honey under a scan overlay. Labelled as an illustration, because it is one. */
function ScanFigure() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = window.setInterval(() => setTick((v) => v + 1), 900);
    return () => clearInterval(t);
  }, []);
  const active = tick % SCREEN_SEQUENCE.length;
  const bars = SCREEN_SEQUENCE.slice(2);
  const levels = [0.62, 0.71, 0.88, 0.8, 0.55, 0.42, 0.38, 0.33, 0.24, 0.29];
  return (
    <figure className="scan-figure">
      <div className="frame" style={{ ["--flash" as string]: SCREEN_COLOURS[SCREEN_SEQUENCE[active]] }}>
        <img src="/img/honey-hero.webp" alt="Jars of honey on a shelf" />
        <div className="flash" aria-hidden="true" />
        <div className="hud" aria-hidden="true">
          <span className="corner tl" /><span className="corner tr" /><span className="corner bl" /><span className="corner br" />
          <div className="hud-top mono">
            <span>SIFT · HONEY</span>
            <span>LIGHT SWEEP {String(active + 1).padStart(2, "0")}/12</span>
          </div>
          <div className="hud-bars">
            {bars.map((c, i) => (
              <i key={c} style={{ background: SCREEN_COLOURS[c], height: `${levels[i] * (i <= active - 2 ? 100 : 18)}%` }} />
            ))}
          </div>
          <div className="hud-bottom mono">
            <span>BUBBLE RISE · SOUND 200 Hz→20 kHz</span>
            <span className="hud-state">COMPARING…</span>
          </div>
        </div>
      </div>
      <figcaption className="fine muted mono">Illustration. A real scan shows your phone's own readings.</figcaption>
    </figure>
  );
}
