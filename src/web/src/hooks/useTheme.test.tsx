import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeToggle } from "../components/ThemeToggle";
import { useTheme } from "./useTheme";

function Switch() {
  const { theme, toggle } = useTheme();
  return <ThemeToggle theme={theme} onToggle={toggle} />;
}
describe("theme switch", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("dark"),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
  });
  afterEach(() => vi.unstubAllGlobals());
  it("follows the system until used, then remembers the choice", async () => {
    render(<Switch />);
    expect(document.documentElement.dataset.theme).toBeUndefined();
    await userEvent.click(screen.getByRole("button", { name: "Светлая тема" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("mosprom.theme")).toBe("light");
    expect(screen.getByRole("button", { name: "Тёмная тема" })).toBeVisible();
  });
  it("starts from the remembered theme", () => {
    localStorage.setItem("mosprom.theme", "light");
    render(<Switch />);
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
