import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

/**
 * How far first-time setup has got, as the server sees it.
 *
 * Steps tick from real events (a key that tested fine, an app that
 * connected), never from a click, and stay ticked. `refresh()` re-reads
 * after something that could have moved a step along, such as testing
 * a key.
 */
export interface SetupState {
  steps: string[];
  done: string[];
  next_step: string | null;
  complete: boolean;
  /** provider key -> guide steps already finished */
  guide: Record<string, string[]>;
}

const EVENT = "setup-changed";

/** Call after something that may have moved a step along, so the bar updates at once. */
export function notifySetup(): void {
  window.dispatchEvent(new Event(EVENT));
}

export function useSetup() {
  const [state, setState] = useState<SetupState | null>(null);

  const refresh = useCallback(async () => {
    try {
      setState(await api.get<SetupState>("/me/setup"));
    } catch {
      // The bar is a hint: if it cannot load, show nothing rather than an error.
    }
  }, []);

  useEffect(() => {
    void refresh();
    const again = () => void refresh();
    window.addEventListener(EVENT, again);
    return () => window.removeEventListener(EVENT, again);
  }, [refresh]);

  const markGuideStep = useCallback(async (provider: string, step: string) => {
    try {
      setState(await api.post<SetupState>("/me/setup/guide", { provider, step }));
    } catch {
      // Losing one guide tick only means the step shows again.
    }
  }, []);

  return { state, refresh, markGuideStep };
}
