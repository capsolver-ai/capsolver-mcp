// Shared redaction helpers used by both the browser manager (network/console
// capture) and the tool handlers (snapshot output). Kept in one place so the
// data:-URL collapsing logic can't drift between call sites.

// Collapse a single URL if it is a data: URL, keeping only the mime prefix.
export function redactDataUrl(url: string): string {
  if (!url.startsWith("data:")) return url;
  const mime = url.slice(5).split(/[;,]/, 1)[0];
  return `data:${mime}[...]`;
}

// Collapse every data: URL payload embedded in a larger text blob.
export function redactDataUrls(value: string): string {
  return value.replace(/data:([^;,\s"')]*)[^\s"')]*/g, (_m, mime: string) => `data:${mime || ""}[...]`);
}

// Mask common secret shapes in free text (e.g. console logs) so they don't leak.
export function redactSecrets(value: string): string {
  return value
    .replace(/\b(eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,})\b/g, "[REDACTED_JWT]")
    .replace(/\b(sk|pk|rk|api|key|ghp|gho|xox[baprs])[-_][A-Za-z0-9]{16,}\b/gi, "[REDACTED_KEY]")
    .replace(/\bBearer\s+[A-Za-z0-9._-]{12,}/gi, "Bearer [REDACTED]")
    .replace(/\b[A-Za-z0-9]{40,}\b/g, "[REDACTED]");
}
