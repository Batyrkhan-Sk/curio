"use client";

import { useState } from "react";
import type { CardDetail } from "@/lib/types";
import { Icon } from "@/components/ui/icon";
import { SectionLabel } from "@/components/ui/primitives";

/**
 * The card's own vocabulary, collapsed behind a button.
 *
 * These definitions exist because of the rule that no card may use a term it
 * has not explained — but a reader who already knows the words should not have
 * to scroll past them. Closed by default, one click away, and it stays open
 * once opened so it can be read alongside the explanation.
 */
export function Glossary({ card }: { card: CardDetail }) {
  const [open, setOpen] = useState(false);

  if (!card.key_terms.length) return null;

  return (
    <section>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-lg border border-border bg-surface-2/50 px-3 py-2.5 text-left transition-colors hover:border-border-strong hover:bg-surface-2"
      >
        <Icon name="BookA" className="size-4 shrink-0 text-text-muted" />
        <span className="min-w-0 flex-1 text-[13px] font-medium text-text">
          Glossary
        </span>
        <span className="shrink-0 text-[11px] tabular-nums text-text-faint">
          {card.key_terms.length}
        </span>
        <Icon
          name={open ? "ChevronUp" : "ChevronDown"}
          className="size-3.5 shrink-0 text-text-faint"
        />
      </button>

      {open && (
        <dl className="mt-3 space-y-3 px-1">
          {card.key_terms.map((term) => (
            <div key={term.term}>
              <dt className="text-[13px] font-semibold text-text">
                {term.term}
              </dt>
              <dd className="mt-0.5 text-[12px] leading-relaxed text-text-secondary">
                {term.plain_definition}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

/** The same words, laid out for the bottom of a narrow screen. */
export function GlossaryInline({ card }: { card: CardDetail }) {
  if (!card.key_terms.length) return null;

  return (
    <section className="mt-12">
      <SectionLabel className="mb-4">Words this card uses</SectionLabel>
      <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
        {card.key_terms.map((term) => (
          <div key={term.term}>
            <dt className="text-[14px] font-semibold text-text">{term.term}</dt>
            <dd className="mt-0.5 text-[13px] leading-relaxed text-text-secondary">
              {term.plain_definition}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
