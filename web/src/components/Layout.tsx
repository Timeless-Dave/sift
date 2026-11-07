import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { Spectrum } from "./Spectrum";

export function Header() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on(); window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  return (
    <header className={`site-head ${scrolled ? "scrolled" : ""}`}>
      <div className="wrap bar">
        <Link to="/" className="wordmark" aria-label="Sift home"><Spectrum />Sift</Link>
        <nav className="site-nav" aria-label="Main">
          <NavLink to="/foods">What it checks</NavLink>
          <a className="hide-s" href="/#how">How it works</a>
          <a className="hide-s" href="/#evidence">Evidence</a>
        </nav>
        <Link to="/scan" className="btn small">Open scanner <span className="arrow">→</span></Link>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="site-foot">
      <div className="wrap cols">
        <div>
          <Link to="/" className="wordmark"><Spectrum />Sift</Link>
          <p className="muted fine" style={{ marginTop: 14, maxWidth: "38ch" }}>
            A screening tool, not a lab analysis. Sift says what its reference scans support and nothing more.
          </p>
        </div>
        <div>
          <h4>Use</h4>
          <ul><li><Link to="/scan">Scanner</Link></li><li><Link to="/foods">What it checks</Link></li><li><Link to="/lab-tests">Lab tests</Link></li></ul>
        </div>
        <div>
          <h4>Evidence</h4>
          <ul>
            <li><a href="https://github.com/Timeless-Dave/sift/blob/main/docs/research.md">Research review</a></li>
            <li><a href="https://github.com/Timeless-Dave/sift/blob/main/docs/foods-evidence.md">Per-food evidence</a></li>
            <li><Link to="/credits">Photo credits</Link></li>
          </ul>
        </div>
        <div>
          <h4>Build</h4>
          <ul><li><Link to="/developers">API</Link></li><li><a href="https://github.com/Timeless-Dave/sift">Source</a></li></ul>
        </div>
      </div>
    </footer>
  );
}

/** Scroll to top on route changes (hash links keep their target). */
export function ScrollReset({ children }: { children: ReactNode }) {
  const { pathname, hash } = useLocation();
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView();
    else window.scrollTo(0, 0);
  }, [pathname, hash]);
  return <>{children}</>;
}
