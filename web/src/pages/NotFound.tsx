import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="wrap page">
      <section className="page-head">
        <p className="eyebrow">404</p>
        <h1 className="h1">Nothing here but crumbs.</h1>
        <p className="lede">
          That page doesn&apos;t exist or moved. The scanner and the front page are both this way.
        </p>
        <div className="row" style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Link to="/" className="btn">Back home</Link>
          <Link to="/scan" className="btn ghost">Open the scanner</Link>
        </div>
      </section>
    </div>
  );
}
