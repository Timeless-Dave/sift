import credits from "../data/photo-credits.json";
import { safeUrl } from "../util";

type Credit = { title: string; creator: string | null; creator_url: string | null; license: string; license_version: string | null;
  license_url: string | null; foreign_landing_url: string | null; source: string };

export default function Credits() {
  const rows = Object.entries(credits as Record<string, Credit>);
  return (
    <section className="wrap page">
      <header className="page-head">
        <p className="eyebrow">Credits</p>
        <h1 className="h1">Photographs</h1>
        <p className="lede">Every photo on Sift is openly licensed and was found through Openverse. Thank you to the photographers.</p>
      </header>
      <ul className="credit-list">
        {rows.map(([key, c]) => (
          <li key={key} className="card">
            <img src={`/img/${key}.webp`} alt="" loading="lazy" />
            <div>
              <p><b>{c.foreign_landing_url && safeUrl(c.foreign_landing_url) ? <a href={c.foreign_landing_url} target="_blank" rel="noopener">{c.title}</a> : c.title}</b></p>
              <p className="muted fine">
                {c.creator ? <>by {c.creator_url && safeUrl(c.creator_url) ? <a href={c.creator_url} target="_blank" rel="noopener">{c.creator}</a> : c.creator}, </> : null}
                {c.license === "cc0" ? "CC0 (public domain)" : <>{c.license_url && safeUrl(c.license_url) ? <a href={c.license_url} target="_blank" rel="noopener">CC {c.license.toUpperCase()} {c.license_version}</a> : `CC ${c.license.toUpperCase()}`}</>}
                {" "}· via {c.source}. Resized for the web.
              </p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
