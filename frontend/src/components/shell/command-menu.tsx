"use client";

import { Command } from "cmdk";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import type { SearchResult } from "@/lib/types";
import { Icon } from "@/components/ui/icon";
import { getRandomCard, search } from "@/lib/api";
import { debounce } from "@/lib/utils";

/**
 * Search exists, but it is not the front door — so it lives behind ⌘K rather
 * than occupying the top of every page. The empty state offers exploration
 * routes instead of a blank box, which is the brief's whole premise.
 */
export function CommandMenu({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [semantic, setSemantic] = useState(false);
  // Which query the results on screen belong to. Comparing it against the live
  // input derives the loading state, instead of a second piece of state that
  // has to be kept in step with it.
  const [settledQuery, setSettledQuery] = useState("");

  const trimmed = query.trim();
  const loading = trimmed.length >= 2 && settledQuery !== trimmed;

  const runSearch = useMemo(
    () =>
      debounce(async (value: string) => {
        const term = value.trim();
        if (term.length < 2) {
          setResults([]);
          setSuggestions([]);
          setSettledQuery(term);
          return;
        }
        try {
          const response = await search(term);
          setResults(response.results);
          setSuggestions(response.suggestions);
          setSemantic(response.semantic);
        } catch {
          setResults([]);
        } finally {
          setSettledQuery(term);
        }
      }, 220),
    [],
  );

  useEffect(() => {
    runSearch(query);
  }, [query, runSearch]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function go(href: string) {
    onClose();
    router.push(href);
  }

  async function surpriseMe() {
    try {
      const card = await getRandomCard();
      go(`/q/${card.slug}`);
    } catch {
      go("/");
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/25 px-4 pt-[12vh] backdrop-blur-sm"
      onClick={onClose}
    >
      <Command
        shouldFilter={false}
        loop
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-border bg-surface shadow-[--shadow-lift]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-border px-4">
          <Icon name="Search" className="size-4 shrink-0 text-text-faint" />
          <Command.Input
            value={query}
            onValueChange={setQuery}
            autoFocus
            placeholder="Ask something, or describe what you're curious about…"
            className="h-13 flex-1 bg-transparent py-4 text-[15px] text-text outline-none placeholder:text-text-faint"
          />
          {loading && (
            <Icon name="LoaderCircle" className="size-4 animate-spin text-text-faint" />
          )}
          <kbd className="rounded border border-border bg-surface-2 px-1.5 py-0.5 text-[10px] text-text-faint">
            esc
          </kbd>
        </div>

        <Command.List className="max-h-[52vh] overflow-y-auto p-2">
          {trimmed.length < 2 ? (
            <Command.Group
              heading="Start somewhere"
              className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.1em] [&_[cmdk-group-heading]]:text-text-faint"
            >
              <Item icon="Shuffle" label="Surprise me" onSelect={surpriseMe} />
              <Item
                icon="Sun"
                label="Today's discoveries"
                onSelect={() => go("/shelf/todays-discoveries")}
              />
              <Item
                icon="Users"
                label="Questions everyone eventually asks"
                onSelect={() => go("/shelf/everyone-asks")}
              />
              <Item
                icon="CircleHelp"
                label="Things nobody properly explains"
                onSelect={() => go("/shelf/nobody-explains")}
              />
              <Item
                icon="Waypoints"
                label="Browse the knowledge graph"
                onSelect={() => go("/graph")}
              />
            </Command.Group>
          ) : (
            <>
              {results.length > 0 && (
                <Command.Group
                  heading={semantic ? "Matches by words and meaning" : "Matches"}
                  className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.1em] [&_[cmdk-group-heading]]:text-text-faint"
                >
                  {results.map((result) => (
                    <Command.Item
                      key={result.id}
                      value={result.id}
                      onSelect={() => go(`/q/${result.slug}`)}
                      className="flex cursor-pointer items-start gap-3 rounded-lg px-3 py-2.5 data-[selected=true]:bg-surface-2"
                    >
                      <Icon
                        name={result.category?.icon ?? "Sparkles"}
                        className="mt-0.5 size-4 shrink-0 text-text-faint"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block font-serif text-[14px] leading-snug text-text">
                          {result.title}
                        </span>
                        <span className="mt-0.5 line-clamp-1 block text-[12px] text-text-muted">
                          {result.one_sentence_answer}
                        </span>
                      </span>
                      {result.matched_by.includes("meaning") &&
                        !result.matched_by.includes("keyword") && (
                          <span className="mt-1 shrink-0 text-[10px] text-text-faint">
                            by meaning
                          </span>
                        )}
                    </Command.Item>
                  ))}
                </Command.Group>
              )}

              {!loading && results.length === 0 && (
                <div className="px-3 py-8 text-center">
                  <p className="text-sm text-text-secondary">
                    Nothing on this yet.
                  </p>
                  <p className="mt-1 text-[13px] text-text-muted">
                    Curio has a finite, deliberately curated corpus — it is not
                    trying to answer everything.
                  </p>
                  <button
                    onClick={surpriseMe}
                    className="mt-4 text-[13px] font-medium text-accent-text hover:underline"
                  >
                    Show me something else instead
                  </button>
                </div>
              )}

              {suggestions.length > 0 && (
                <Command.Group
                  heading="Related questions"
                  className="mt-1 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.1em] [&_[cmdk-group-heading]]:text-text-faint"
                >
                  {suggestions.slice(0, 4).map((suggestion) => (
                    <Command.Item
                      key={suggestion}
                      value={`suggest-${suggestion}`}
                      onSelect={() => setQuery(suggestion)}
                      className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-[13px] text-text-secondary data-[selected=true]:bg-surface-2"
                    >
                      <Icon name="CornerDownRight" className="size-3.5 text-text-faint" />
                      {suggestion}
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
            </>
          )}
        </Command.List>
      </Command>
    </div>
  );
}

function Item({
  icon,
  label,
  onSelect,
}: {
  icon: string;
  label: string;
  onSelect: () => void;
}) {
  return (
    <Command.Item
      value={label}
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-[14px] text-text data-[selected=true]:bg-surface-2"
    >
      <Icon name={icon} className="size-4 text-text-faint" />
      {label}
    </Command.Item>
  );
}
