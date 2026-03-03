/**
 * Safe localStorage wrappers that handle exceptions from disabled storage,
 * quota exceeded, or restrictive security policies (e.g., iframe sandboxing).
 *
 * All getters return `null` on failure; all setters/removers silently swallow
 * errors so callers don't need try-catch for every persistence operation.
 */

export function safeGetItem(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function safeSetItem(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Storage full or unavailable — silently ignore
  }
}

export function safeRemoveItem(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // Storage unavailable — silently ignore
  }
}
