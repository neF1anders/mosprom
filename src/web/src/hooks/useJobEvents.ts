import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { ProgressEvent } from "../types";

// Events that change the snapshot or the chat list; progress and tool calls do not.
const STATE_EVENTS =
  /^(job\.|answers\.|stage1\.|operation\.|triage\.completed|files\.(completed|failed)|stl\.(completed|failed))/;

// The server starts the stream at the current revision and resumes it by Last-Event-ID.
export function useJobEvents(selected: string, enabled: boolean) {
  const client = useQueryClient();
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [connected, setConnected] = useState(true);
  const [epoch, setEpoch] = useState(0);
  useEffect(() => {
    const offline = () => setConnected(false);
    const online = () => setEpoch((value) => value + 1);
    window.addEventListener("offline", offline);
    window.addEventListener("online", online);
    return () => {
      window.removeEventListener("offline", offline);
      window.removeEventListener("online", online);
    };
  }, []);
  useEffect(() => {
    if (!selected || !enabled) return;
    setEvents([]);
    setConnected(navigator.onLine);
    const source = new EventSource(`/api/v1/jobs/${selected}/events`);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = () => {
      void client.invalidateQueries({ queryKey: ["job", selected] });
      void client.invalidateQueries({ queryKey: ["jobs"] });
      timer = undefined;
    };
    source.onmessage = (message) => {
      const update: ProgressEvent = JSON.parse(message.data);
      setEvents((previous) =>
        previous.some((e) => e.event_id === update.event_id)
          ? previous
          : [...previous, update].slice(-200),
      );
      // Several state events in a burst cost one refetch.
      if (STATE_EVENTS.test(update.type) && !timer)
        timer = setTimeout(refresh, 100);
    };
    source.onopen = () => {
      setConnected(navigator.onLine);
      void client.invalidateQueries({ queryKey: ["job", selected] });
    };
    source.onerror = () => setConnected(false);
    return () => {
      source.close();
      clearTimeout(timer);
    };
  }, [selected, enabled, client, epoch]);
  return { events, connected };
}
