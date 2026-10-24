import { useEffect, useState } from "react";

type Theme = "light" | "dark";
const KEY = "mosprom.theme";
const media = () => window.matchMedia("(prefers-color-scheme: dark)");
function stored(): Theme | null {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}
// The theme the switch chose, or the system one until it is used; the choice is remembered.
export function useTheme() {
  const [chosen, setChosen] = useState<Theme | null>(stored);
  const [system, setSystem] = useState<Theme>(() =>
    media().matches ? "dark" : "light",
  );
  useEffect(() => {
    const list = media();
    const change = () => setSystem(list.matches ? "dark" : "light");
    list.addEventListener("change", change);
    return () => list.removeEventListener("change", change);
  }, []);
  useEffect(() => {
    if (chosen) document.documentElement.dataset.theme = chosen;
    else delete document.documentElement.dataset.theme;
  }, [chosen]);
  const theme = chosen ?? system;
  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setChosen(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // Without storage the choice lasts until the page is closed.
    }
  }
  return { theme, toggle };
}
