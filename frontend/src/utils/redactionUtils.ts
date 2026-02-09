export function newId(): string {
  const g = (globalThis as any).crypto;
  if (g && typeof g.randomUUID === "function") return g.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function truncate(s: string, max = 56): string {
  const t = (s || "").trim();
  if (t.length <= max) return t;
  return t.slice(0, max - 1) + "…";
}
