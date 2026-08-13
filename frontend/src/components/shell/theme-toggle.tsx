"use client";

import { useTheme } from "next-themes";
import { Icon } from "@/components/ui/icon";
import { useIsClient } from "@/hooks/use-client";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  // The server cannot know the reader's theme, so render a stable placeholder
  // until hydration rather than flashing the wrong icon.
  const mounted = useIsClient();

  return (
    <button
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      className="grid size-9 place-items-center rounded-lg text-text-muted transition-colors hover:bg-surface-2 hover:text-text"
      aria-label={
        mounted
          ? `Switch to ${resolvedTheme === "dark" ? "light" : "dark"} theme`
          : "Switch theme"
      }
    >
      {mounted ? (
        <Icon name={resolvedTheme === "dark" ? "Sun" : "Moon"} className="size-4" />
      ) : (
        <span className="size-4" />
      )}
    </button>
  );
}
