/** Display helpers for the admin pages. */

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 1000) / 10}%`;
}

export function bytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = value;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${i === 0 ? v : v.toFixed(1)} ${units[i]}`;
}

export function count(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString();
}

export function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "not priced";
  return `$${Number(value).toFixed(4)}`;
}

/** "document.permission_granted" -> "Document permission granted". */
export function actionLabel(action: string): string {
  const text = action.replace(/[._]/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Parse "a, b; c" into trimmed, non-empty facts. */
export function parseFacts(text: string): string[] {
  return text
    .split(/[;,\n]/)
    .map((f) => f.trim())
    .filter(Boolean);
}

/** Share of a quota used (0-1), or null when unlimited. */
export function usageShare(item: { limit: number | null; used: number }): number | null {
  if (item.limit === null || item.limit === 0) return null;
  return Math.min(1, item.used / item.limit);
}
