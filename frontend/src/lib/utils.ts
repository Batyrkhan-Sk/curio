import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatMinutes(minutes: number): string {
  if (minutes < 1) return "under a minute";
  if (minutes === 1) return "1 min read";
  return `${minutes} min read`;
}

export const LEVEL_META = [
  { level: 1, short: "Intuition", hint: "The plain reason, in everyday words" },
  { level: 2, short: "Analogy", hint: "Something you can picture" },
  { level: 3, short: "Example", hint: "A real case, with specifics" },
  { level: 4, short: "Technical", hint: "The mechanism, as an engineer states it" },
  { level: 5, short: "Expert", hint: "Edge cases, trade-offs, open questions" },
] as const;

/** A stable colour for a category, falling back to the accent. */
export function categoryAccent(accent?: string | null): string {
  return accent && /^#[0-9a-f]{6}$/i.test(accent) ? accent : "var(--color-accent)";
}

export function pluralize(count: number, singular: string, plural?: string): string {
  return `${count} ${count === 1 ? singular : (plural ?? `${singular}s`)}`;
}

/**
 * Split a body of prose into paragraphs. The pipeline emits plain text with
 * blank-line separators rather than markdown, deliberately — see the format
 * rules in `backend/app/ai/prompts.py`.
 */
export function paragraphs(text: string): string[] {
  return text
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);
}

/** Render the limited inline markup the prompts do allow: **bold**. */
export function renderInline(text: string): { bold: boolean; text: string }[] {
  return text
    .split(/(\*\*[^*]+\*\*)/g)
    .filter(Boolean)
    .map((chunk) =>
      chunk.startsWith("**") && chunk.endsWith("**")
        ? { bold: true, text: chunk.slice(2, -2) }
        : { bold: false, text: chunk },
    );
}

export function debounce<A extends unknown[]>(
  fn: (...args: A) => void,
  ms: number,
): (...args: A) => void {
  let timer: ReturnType<typeof setTimeout>;
  return (...args: A) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}
