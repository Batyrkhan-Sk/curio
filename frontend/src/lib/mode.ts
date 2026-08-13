import type { FeedMode } from "./types";

/**
 * The reader's lens: curiosity, or the answers that change what they do.
 *
 * The URL is the source of truth so the two feeds are linkable and cacheable,
 * and a cookie remembers the last choice so a bare visit to "/" comes back to
 * the mode the reader left in. localStorage would not do — the homepage is a
 * server component and has to know the mode before it renders anything.
 */
export const MODE_COOKIE = "curio.mode";
export const DEFAULT_MODE: FeedMode = "interesting";

export const MODES: { key: FeedMode; label: string; icon: string; blurb: string }[] = [
  {
    key: "interesting",
    label: "Interesting",
    icon: "Sparkles",
    blurb: "Questions that are a pleasure to know the answer to",
  },
  {
    key: "useful",
    label: "Useful in life",
    icon: "LifeBuoy",
    blurb: "Answers worth having before you need them",
  },
];

export function resolveMode(value: string | string[] | undefined | null): FeedMode {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw === "useful" ? "useful" : DEFAULT_MODE;
}

/** A link that keeps the reader in their current mode. */
export function withMode(href: string, mode: FeedMode): string {
  if (mode === DEFAULT_MODE) return href;
  const separator = href.includes("?") ? "&" : "?";
  return `${href}${separator}mode=${mode}`;
}
