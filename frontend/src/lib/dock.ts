import { useCallback, useEffect, useState } from "react";

/**
 * Where the menu rail sits. The user drags it there and it stays.
 *
 * Kept in localStorage rather than on the server: it is a per-person,
 * per-device preference, like a window position. Someone who likes the
 * rail on the right on their big monitor should not have it jump sides
 * when they open the app on a laptop.
 */
export type Dock = "left" | "right" | "bottom";

export const DOCKS: Dock[] = ["left", "right", "bottom"];

export const DOCK_LABEL: Record<Dock, string> = {
  left: "Left edge",
  right: "Right edge",
  bottom: "Bottom edge",
};

const KEY = "ai-employees.dock";

/** Phones get the rail along the bottom, where a thumb reaches it. */
function defaultDock(): Dock {
  if (typeof window === "undefined") return "left";
  return window.matchMedia("(max-width: 860px)").matches ? "bottom" : "left";
}

function read(): Dock {
  try {
    const saved = window.localStorage.getItem(KEY);
    if (saved === "left" || saved === "right" || saved === "bottom") return saved;
  } catch {
    // Private windows and blocked site data both throw here. A menu
    // that forgets where it was put is a small loss; a menu that fails
    // to render is not.
  }
  return defaultDock();
}

export function useDock(): [Dock, (next: Dock) => void] {
  const [dock, setDock] = useState<Dock>(read);

  const set = useCallback((next: Dock) => {
    setDock(next);
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      // Same reasoning as above: remembering is optional.
    }
  }, []);

  // The page can scroll behind a bottom rail, so the content needs to
  // end above it. Done with a CSS variable rather than a class on every
  // page, so a page that knows nothing about the rail still clears it.
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.dock = dock;
    return () => {
      delete root.dataset.dock;
    };
  }, [dock]);

  return [dock, set];
}

/**
 * Which edge a pointer is closest to, as a fraction of the window.
 *
 * Bottom wins its band outright: a pointer near the bottom-left corner
 * is almost always aiming for the bottom bar, because that is the
 * harder target to hit.
 */
export function dockForPoint(x: number, y: number): Dock {
  const { innerWidth: w, innerHeight: h } = window;
  if (y > h * 0.78) return "bottom";
  return x < w / 2 ? "left" : "right";
}
