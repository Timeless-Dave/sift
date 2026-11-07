import { SCREEN_COLOURS, SCREEN_SEQUENCE } from "../scanner";

/** The 12 colours the screen flashes during a light sweep. Sift's only decorative colour, because it is the measurement. */
export function Spectrum({ className = "", live = false }: { className?: string; live?: boolean }) {
  return (
    <span className={`spectrum ${live ? "live" : ""} ${className}`} aria-hidden="true">
      {SCREEN_SEQUENCE.map((c, i) => (
        <i key={c} style={{ background: SCREEN_COLOURS[c], animationDelay: `${i * 0.12}s` }} />
      ))}
    </span>
  );
}
