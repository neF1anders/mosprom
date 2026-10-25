import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError, requestId } from "../api";
import { extension, rejected } from "../chat";
import type { DraftFile } from "../components/Attachments";
import type { Attachment, Snapshot } from "../types";

export function useUploads(ensureJob: () => Promise<string>) {
  const client = useQueryClient();
  // незавершённые загрузки
  const [uploads, setUploads] = useState<DraftFile[]>([]);
  // файлы по id
  const picked = useRef(new Map<string, File>());
  const fail = (key: string, error: string) =>
    setUploads((list) =>
      list.map((item) =>
        item.key === key ? { ...item, uploading: false, error } : item,
      ),
    );
  async function upload(files: File[]) {
    const queued = files.map((file) => {
      const kind = extension(file.name);
      const problem = rejected(file, kind);
      const card = {
        key: requestId(),
        name: file.name,
        kind,
        uploading: !problem,
        error: problem,
      };
      return { file, card };
    });
    setUploads((list) => [...list, ...queued.map(({ card }) => card)]);
    const accepted = queued.filter(({ card }) => !card.error);
    if (!accepted.length) return;
    let id: string;
    try {
      // чат выбран заранее
      id = await ensureJob();
    } catch (e) {
      for (const { card } of accepted) fail(card.key, (e as Error).message);
      return;
    }
    for (const { file, card } of accepted) {
      try {
        const form = new FormData();
        form.append("file", file);
        form.append("request_id", card.key);
        const attachment = await api<Attachment>(`/jobs/${id}/attachments`, {
          method: "POST",
          body: form,
        });
        picked.current.set(attachment.id, file);
        // замена копией сервера
        await client
          .fetchQuery({
            queryKey: ["job", id],
            queryFn: () => api<Snapshot>(`/jobs/${id}`),
          })
          .catch(() => undefined);
        setUploads((list) => list.filter((item) => item.key !== card.key));
        void client.invalidateQueries({ queryKey: ["jobs"] });
      } catch (e) {
        fail(
          card.key,
          e instanceof ApiError ? e.message : "Не удалось загрузить файл",
        );
      }
    }
  }
  return { uploads, setUploads, picked, upload };
}
