import { SCREEN_COLOURS, SCREEN_SEQUENCE } from "../scanner";

/** Line drawings of what each sensor physically does. Stroke follows the text colour. */
export function SensorGlyph({ kind, size = 72 }: { kind: string; size?: number }) {
  const common = { width: size, height: size, viewBox: "0 0 72 72", fill: "none", stroke: "currentColor",
    strokeWidth: 1.4, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  const colours = SCREEN_SEQUENCE.slice(2).map((c) => SCREEN_COLOURS[c]);
  switch (kind) {
    case "screenlight":   // phone screen fanning colours onto a surface
      return (
        <svg {...common}>
          <rect x="8" y="14" width="22" height="40" rx="4" />
          {colours.map((c, i) => (
            <line key={c} x1="30" y1={22 + i * 2.4} x2="62" y2={10 + i * 5.6} stroke={c} strokeWidth="1.6" />
          ))}
          <line x1="62" y1="6" x2="62" y2="66" strokeDasharray="2 3" />
        </svg>
      );
    case "torch":         // flash beam, off then on
      return (
        <svg {...common}>
          <rect x="8" y="26" width="14" height="20" rx="3" />
          <circle cx="15" cy="36" r="3" />
          <path d="M22 30 L58 16 M22 42 L58 56" />
          <path d="M58 16 Q66 36 58 56" />
          <circle cx="48" cy="36" r="2" fill="currentColor" />
        </svg>
      );
    case "contact":       // light scattering into tissue and back out in rings
      return (
        <svg {...common}>
          <path d="M6 30 H66" />
          <rect x="28" y="20" width="16" height="10" rx="2" />
          {[8, 15, 22, 29].map((r, i) => (
            <path key={r} d={`M${36 - r} 30 A ${r} ${r * 0.8} 0 0 0 ${36 + r} 30`} opacity={1 - i * 0.2} stroke="#c0461d" />
          ))}
          <path d="M6 30 V62 H66 V30" strokeDasharray="1 3" />
        </svg>
      );
    case "bubble":        // bubble climbing an upturned jar
      return (
        <svg {...common}>
          <path d="M22 10 H50 V58 Q50 64 44 64 H28 Q22 64 22 58 Z" />
          <path d="M22 14 H50" />
          <circle cx="36" cy="22" r="4" />
          <circle cx="36" cy="38" r="3" opacity="0.5" />
          <circle cx="36" cy="51" r="2" opacity="0.25" />
          <path d="M58 54 V22 M54 26 L58 22 L62 26" />
        </svg>
      );
    case "acoustic":      // a sweep rising in frequency
      return (
        <svg {...common}>
          <path d="M4 36 C 8 18, 12 18, 16 36 S 22 54, 26 36 S 30 22, 33 36 S 36 48, 38.5 36 S 41 26, 43 36 S 45 44, 46.5 36 S 48 30, 49.5 36 S 51 41, 52 36 S 53 33, 54 36 S 55 38.5, 56 36 S 57 34.5, 58 36 S 59 37, 60 36 S 61 35.4, 62 36 S 63 36.5, 64 36 L68 36" />
          <text x="4" y="64" fontFamily="IBM Plex Mono, monospace" fontSize="7" fill="currentColor" stroke="none">200 Hz</text>
          <text x="46" y="64" fontFamily="IBM Plex Mono, monospace" fontSize="7" fill="currentColor" stroke="none">20 kHz</text>
        </svg>
      );
    case "vibration":     // motor buzz damped by what it rests on
      return (
        <svg {...common}>
          <rect x="24" y="12" width="24" height="34" rx="4" />
          <path d="M18 20 L14 24 L18 28 M54 20 L58 24 L54 28" />
          <path d="M6 58 Q 14 50, 22 58 T 38 58 T 50 58 T 58 58 T 66 58" opacity="0.6" />
          <path d="M6 52 H66" />
        </svg>
      );
    default:
      return <svg {...common}><circle cx="36" cy="36" r="20" /></svg>;
  }
}

export const SENSORS: { kind: string; name: string; spec: string; what: string }[] = [
  { kind: "screenlight", name: "Light sweep", spec: "12 colours · front camera",
    what: "The screen floods the food with twelve colours in turn; the camera measures what comes back. A coarse spectrum, from the phone itself." },
  { kind: "torch", name: "Torch", spec: "flash off → on",
    what: "Colour and clarity under the flash compared with room light: haze, tint and how light passes through." },
  { kind: "contact", name: "Light through tissue", spec: "camera pressed on meat or fish",
    what: "Torch light scatters a few millimetres into the flesh and back out. Ring by ring, it carries the colour of myoglobin below the surface." },
  { kind: "bubble", name: "Bubble rise", spec: "jar upside down, then upright",
    what: "How fast the air bubble climbs depends on viscosity and density. Syrup-cut honey rises differently." },
  { kind: "acoustic", name: "Sound sweep", spec: "200 Hz → 20 kHz",
    what: "A tone sweeps into near-ultrasound most adults can't hear; the microphone measures how the package passes and damps it." },
  { kind: "vibration", name: "Vibration", spec: "motor + accelerometer",
    what: "How the food pressed against the phone damps the vibration motor. Coarse in a browser; collected for research." },
];
