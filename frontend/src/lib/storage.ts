/**
 * Read a saved preference that used to live under an older key.
 *
 * The app's browser-storage keys were renamed from "ai-employees.*" to
 * "baton.*". Reading the new key first and falling back to the old one
 * means nobody loses their saved menu position, tips or inbox marks; the
 * value is copied across the first time it is read. Storage can be
 * blocked, so every access is guarded and a failure reads as "nothing saved".
 */
export function readCompat(key: string, oldKey: string): string | null {
  try {
    const current = window.localStorage.getItem(key);
    if (current !== null) return current;
    const old = window.localStorage.getItem(oldKey);
    if (old !== null) window.localStorage.setItem(key, old);
    return old;
  } catch {
    return null;
  }
}
