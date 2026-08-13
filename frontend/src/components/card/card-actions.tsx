"use client";

import { useEffect, useRef, useState } from "react";
import type { CardDetail } from "@/lib/types";
import { Button } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/icon";
import { getSaved, recordInteraction } from "@/lib/api";
import { saveOffline, removeOffline, isOffline } from "@/lib/offline";
import { countRead } from "@/components/pwa/install-prompt";

/**
 * Save, mark-as-understood, and the reading timer.
 *
 * Saving is dual-written: to the server for cross-device sync, and to
 * IndexedDB so a saved card is readable with no network. That is what makes
 * the installed app useful on a train.
 */
export function CardActions({ card }: { card: CardDetail }) {
  const [saved, setSaved] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Check the local copy first so the button is correct offline, then
    // reconcile with the server.
    isOffline(card.id).then((local) => {
      if (!cancelled && local) setSaved(true);
    });
    getSaved()
      .then((cards) => {
        if (!cancelled) setSaved(cards.some((c) => c.id === card.id));
      })
      .catch(() => {
        /* offline: the local answer stands */
      });
    return () => {
      cancelled = true;
    };
  }, [card.id]);

  async function toggleSave() {
    const next = !saved;
    setSaved(next);
    setBusy(true);
    try {
      if (next) {
        await saveOffline(card);
        await recordInteraction({ card_id: card.id, kind: "save" });
      } else {
        await removeOffline(card.id);
        await recordInteraction({ card_id: card.id, kind: "unsave" });
      }
    } catch {
      // Keep the optimistic state — the local copy is the one that matters
      // for reading, and the server will reconcile on the next successful call.
    } finally {
      setBusy(false);
    }
  }

  async function markUnderstood() {
    setCompleted(true);
    try {
      await recordInteraction({ card_id: card.id, kind: "complete" });
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        variant={saved ? "accent" : "outline"}
        size="sm"
        onClick={toggleSave}
        disabled={busy}
        aria-pressed={saved}
      >
        <Icon
          name="Bookmark"
          className={saved ? "size-4 fill-current" : "size-4"}
        />
        {saved ? "Saved for offline" : "Save"}
      </Button>

      <Button
        variant={completed ? "accent" : "outline"}
        size="sm"
        onClick={markUnderstood}
        disabled={completed}
      >
        <Icon name={completed ? "CircleCheck" : "Circle"} className="size-4" />
        {completed ? "Understood" : "I understood this"}
      </Button>
    </div>
  );
}

/**
 * Records a view and how long it was actually read for.
 *
 * The duration is what separates a real read from a bounce, and it is the main
 * input to the "minutes learning" statistic. Sent on unmount and on tab hide,
 * because a mobile reader usually leaves by switching apps rather than
 * navigating away.
 */
export function ReadingTracker({ cardId }: { cardId: string }) {
  // Set on mount rather than during render: Date.now() is impure, and a render
  // that React retries would silently reset the clock.
  const startedAt = useRef(0);
  const sent = useRef(false);

  useEffect(() => {
    startedAt.current = Date.now();
    countRead();
    recordInteraction({ card_id: cardId, kind: "view" }).catch(() => {});

    const flush = () => {
      if (sent.current) return;
      const seconds = Math.round((Date.now() - startedAt.current) / 1000);
      // Under ten seconds is a glance, not a read; recording it would pollute
      // both the statistics and the interest model.
      if (seconds < 10) return;
      sent.current = true;
      recordInteraction({
        card_id: cardId,
        kind: "view",
        seconds: Math.min(seconds, 3600),
      }).catch(() => {});
    };

    const onHide = () => {
      if (document.visibilityState === "hidden") flush();
    };

    document.addEventListener("visibilitychange", onHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      flush();
    };
  }, [cardId]);

  return null;
}
