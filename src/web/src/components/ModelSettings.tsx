import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, command } from "../api";
import styles from "../App.module.css";

interface ModelState {
  base_url: string | null;
  model: string | null;
  api_key_set: boolean;
  configured: boolean;
}
// настройки модели
export function ModelSettings({ onClose }: { onClose: () => void }) {
  const client = useQueryClient();
  const current = useQuery({
    queryKey: ["model"],
    queryFn: () => api<ModelState>("/model"),
  });
  const [address, setAddress] = useState("");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  useEffect(() => {
    if (!current.data) return;
    setAddress(current.data.base_url || "");
    setModel(current.data.model || "");
  }, [current.data]);
  const save = useMutation({
    mutationFn: () =>
      command<ModelState>("/model", {
        base_url: address.trim(),
        model: model.trim(),
        api_key: key.trim() || null,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["model"] });
      void client.invalidateQueries({ queryKey: ["capabilities"] });
      onClose();
    },
  });
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [onClose]);
  const saved = !!current.data?.api_key_set;
  return (
    <div className={styles.overlay}>
      <form
        className={styles.modal}
        role="dialog"
        aria-modal="true"
        aria-labelledby="model-title"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <h2 id="model-title">Подключите модель</h2>
        <p>
          Для начала работы укажите OpenAI-совместимый API, на котором будет
          работать плагин
        </p>
        <label>
          Адрес API
          <input
            autoFocus
            value={address}
            placeholder="https://api.example.com/v1"
            onChange={(event) => setAddress(event.target.value)}
          />
        </label>
        <label>
          Имя модели
          <input
            value={model}
            placeholder="qwen3-max"
            onChange={(event) => setModel(event.target.value)}
          />
        </label>
        <label>
          API ключ
          <input
            type="password"
            autoComplete="off"
            value={key}
            placeholder={saved ? "Ключ сохранён, можно не вводить" : "sk-..."}
            onChange={(event) => setKey(event.target.value)}
          />
        </label>
        {save.isError && (
          <p className={styles.modalError} role="alert">
            {save.error.message}
          </p>
        )}
        <div className={styles.modalActions}>
          <button type="button" className={styles.ghost} onClick={onClose}>
            Позже
          </button>
          <button
            type="submit"
            className={styles.next}
            data-ready="true"
            disabled={save.isPending}
          >
            Подключить
          </button>
        </div>
      </form>
    </div>
  );
}
