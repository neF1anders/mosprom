import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { addThought, type CallThoughts } from "../timeline";
import type { ProgressEvent } from "../types";

// Events that change the snapshot or the chat list; progress and tool calls do not.
const STATE_EVENTS =
  /^(job\.|answers\.|stage1\.|operation\.|files\.(completed|failed)|stl\.(completed|failed)|parameters\.|validation\.|slicing\.|gcode\.|pipeline\.)/;

// The server starts the stream at the revision of the job's work and resumes it by Last-Event-ID.
export function useJobEvents(selected: string, enabled: boolean) {
  const client = useQueryClient();
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  // Reasoning and the narrator's phrases are kept per model call, apart from the timeline events.
  const [thoughts, setThoughts] = useState<Record<string, CallThoughts>>({});
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
    setThoughts({});
    const seen = new Set<number>();
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
      if (
        update.type === "agent.thinking" ||
        update.type === "agent.narration"
      ) {
        if (seen.has(update.event_id)) return;
        seen.add(update.event_id);
        setThoughts((previous) => addThought(previous, update));
        return;
      }
      setEvents((previous) =>
        previous.some((e) => e.event_id === update.event_id)
          ? previous
          : [...previous, update].slice(-1000),
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
  return { events, thoughts, connected };
}
