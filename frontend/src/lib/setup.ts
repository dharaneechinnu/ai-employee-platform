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
