import { useEffect, useRef, useState } from "react";

type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: { results: { transcript: string }[][] }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
};
// голосовой ввод
export function useDictation(onText: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const recognizer = useRef<Recognition | null>(null);
  const Speech =
    (
      window as unknown as {
        SpeechRecognition?: new () => Recognition;
        webkitSpeechRecognition?: new () => Recognition;
      }
    ).SpeechRecognition ||
    (window as unknown as { webkitSpeechRecognition?: new () => Recognition })
      .webkitSpeechRecognition;
  useEffect(
    () => () => {
      recognizer.current?.stop();
    },
    [],
  );
  function toggle() {
    if (listening) {
      recognizer.current?.stop();
      return;
    }
    if (!Speech) return;
    const recognition = new Speech();
    recognizer.current = recognition;
    recognition.lang = "ru-RU";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event) => onText(event.results[0][0].transcript);
    recognition.onerror = recognition.onend = () => setListening(false);
    recognition.start();
    setListening(true);
  }
  return { listening, available: !!Speech, toggle };
}
