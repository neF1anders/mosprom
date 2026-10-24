import { useCallback, useState } from "react";
import { api } from "../api";
import type { Message, Snapshot } from "../types";

// Older messages load page by page above the snapshot's latest hundred.
export function useHistory(
  selected: string,
  current: () => string,
  first: number | null | undefined,
  onError: (message: string) => void,
) {
  const [older, setOlder] = useState<Message[]>([]);
  const [cursor, setCursor] = useState<number | null | undefined>();
  const [loading, setLoading] = useState(false);
  const before = cursor === undefined ? first : cursor;
  const reset = useCallback(() => {
    setOlder([]);
    setCursor(undefined);
  }, []);
  async function load() {
    if (!before || loading) return;
    setLoading(true);
    try {
      const page = await api<Snapshot>(`/jobs/${selected}?before=${before}`);
      if (current() !== selected) return;
      setOlder((previous) => [...page.messages, ...previous]);
      setCursor(page.message_cursor);
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setLoading(false);
    }
  }
  return { older, before, loading, load, reset };
}
