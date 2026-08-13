"use client";

import Link from "next/link";
import { MODES, MODE_COOKIE } from "@/lib/mode";
import type { FeedMode } from "@/lib/types";
import { Icon } from "@/components/ui/icon";
import { cn } from "@/lib/utils";

/**
 * The two lenses, as links rather than a stateful control.
 *
 * Links because each mode is a real, shareable page the server renders whole —
 * a client-side toggle would mean shipping both feeds or a loading state for a
 * choice that should feel instant. The cookie is written on the way out so the
 * next bare visit lands in the same place; it is a memory of the choice, not
 * the choice itself.
 */
export function ModeSwitch({ mode }: { mode: FeedMode }) {
  return (
    <div
      role="group"
      aria-label="What to show"
      className="inline-flex items-center gap-0.5 rounded-xl border border-border bg-surface-2 p-0.5"
    >
      {MODES.map((option) => {
        const active = option.key === mode;
        return (
          <Link
            key={option.key}
            href={option.key === "interesting" ? "/" : `/?mode=${option.key}`}
            aria-current={active ? "page" : undefined}
            title={option.blurb}
            onClick={() => {
              // A year is long enough that the setting outlives any single
              // reading habit, and it holds nothing worth protecting.
              document.cookie = `${MODE_COOKIE}=${option.key};path=/;max-age=31536000;samesite=lax`;
            }}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-[10px] px-3 text-[13px] font-medium transition-colors",
              active
                ? "bg-canvas text-text shadow-sm"
                : "text-text-muted hover:text-text",
            )}
          >
            <Icon name={option.icon} className="size-3.5" />
            {option.label}
          </Link>
        );
      })}
    </div>
  );
}
