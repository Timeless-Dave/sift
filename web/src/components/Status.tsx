const LABEL: Record<string, string> = { experimental: "Experimental", research: "Research", validated: "Validated" };
export const STATUS_TEXT: Record<string, string> = {
  experimental: "A published phone method exists; Sift hasn't validated it yet.",
  research: "No published phone method yet. Sift collects reference scans and gives no verdicts.",
  validated: "Measured by Sift on samples with known answers.",
};
export function Status({ status }: { status: string }) {
  return <span className={`status ${status}`}>{LABEL[status] ?? status}</span>;
}
export const KIND: Record<string, string> = {
  adulteration: "Adulteration", cultured: "Lab-grown vs conventional", freshness: "Freshness", identity: "Identity",
};
