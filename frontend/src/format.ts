/** "5 minutes ago", "3 days ago", "2 months ago": business wording instead of raw timestamps. */
export function ago(epochSeconds: number | null | undefined, now = Date.now()): string {
  if (!epochSeconds) return "unknown";
  const s = Math.max(0, Math.round((now - epochSeconds * 1000) / 1000));
  const units: [number, string][] = [[31536000, "year"], [2592000, "month"], [86400, "day"], [3600, "hour"], [60, "minute"]];
  for (const [secs, name] of units) {
    if (s >= secs) { const n = Math.floor(s / secs); return `${n} ${name}${n > 1 ? "s" : ""} ago`; }
  }
  return "just now";
}
