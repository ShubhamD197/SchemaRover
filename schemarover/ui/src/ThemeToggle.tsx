import { Moon, Sun } from "lucide-react";
import { useTheme } from "./theme";

export default function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  return (
    <button
      onClick={toggle}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      title={dark ? "Light mode" : "Dark mode"}
      className="size-8 grid place-items-center rounded-full text-slate transition hover:text-signal hover:bg-card"
    >
      {dark ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  );
}
