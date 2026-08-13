"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { CardSummary } from "@/lib/types";
import { QuestionRow } from "@/components/discovery/question-card";
import { EmptyState, Skeleton } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/icon";
import { getSaved } from "@/lib/api";
import { listOffline } from "@/lib/offline";

/**
 * Saved cards, merged from two places.
 *
 * IndexedDB is authoritative for what is readable offline; the server is
 * authoritative for what the reader saved on their other device. Showing the
 * union means a phone that has been offline all week still lists the card
 * saved on a laptop, and marks which ones it can actually open.
 */
export default function SavedPage() {
  const [cards, setCards] = useState<CardSummary[]>([]);
  const [offlineIds, setOfflineIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const local = await listOffline().catch(() => []);
      if (cancelled) return;
      setOfflineIds(new Set(local.map((c) => c.id)));
      setCards(local);

      try {
        const remote = await getSaved();
        if (cancelled) return;
        const merged = [...remote];
        for (const card of local) {
          if (!merged.some((c) => c.id === card.id)) merged.push(card);
        }
        setCards(merged);
      } catch {
        // Offline: the local list stands.
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto max-w-3xl px-5 py-8 sm:px-8">
      <header className="mb-6">
        <h1 className="font-serif text-2xl font-medium tracking-[-0.01em]">Saved</h1>
        <p className="mt-1.5 text-sm text-text-secondary">
          Saved cards are downloaded to this device, so they open with no
          connection at all.
        </p>
      </header>

      {loading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : cards.length ? (
        <ul className="divide-y divide-border">
          {cards.map((card) => (
            <li key={card.id} className="relative">
              <QuestionRow card={card} />
              {offlineIds.has(card.id) && (
                <span
                  className="pointer-events-none absolute right-10 top-4 inline-flex items-center gap-1 text-[10px] text-text-faint"
                  title="Available offline"
                >
                  <Icon name="ArrowDownToLine" className="size-3" />
                  offline
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          title="Nothing saved yet"
          description="Save a card while reading it and it stays available here, even with no signal."
          action={
            <Link
              href="/"
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-border px-3 text-[13px] font-medium hover:bg-surface-2"
            >
              <Icon name="Compass" className="size-3.5" />
              Find something
            </Link>
          }
        />
      )}
    </div>
  );
}
