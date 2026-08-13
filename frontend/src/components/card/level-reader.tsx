"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import type { CardDetail } from "@/lib/types";
import { Prose } from "./prose";
import { DiagramBlock } from "./diagram";
import { ReexplainPanel } from "./reexplain-panel";
import { Icon } from "@/components/ui/icon";
import { recordInteraction } from "@/lib/api";
import { LEVEL_META, cn } from "@/lib/utils";

/**
 * The progressive explanation.
 *
 * Design decision that matters: levels unfold downward and stay open rather
 * than swapping in a tab panel. A reader who has just understood level 1
 * should be able to glance back at it while reading level 2 — the levels are
 * cumulative, not alternatives, and hiding the previous one makes the deeper
 * levels feel like a different article.
 */
export function LevelReader({
  card,
  startLevel = 1,
}: {
  card: CardDetail;
  startLevel?: number;
}) {
  const levels = card.levels.length ? card.levels : [];
  const [revealed, setRevealed] = useState(() =>
    Math.min(Math.max(startLevel, 1), levels.length || 1),
  );
  const reported = useRef(new Set<number>());
  const nextRef = useRef<HTMLDivElement>(null);

  // Report the deepest level reached, once each. This is what teaches the
  // personalisation layer where a reader is comfortable starting.
  useEffect(() => {
    if (reported.current.has(revealed)) return;
    reported.current.add(revealed);
    recordInteraction({
      card_id: card.id,
      kind: "level_reached",
      level: revealed,
    }).catch(() => {
      /* telemetry must never interrupt reading */
    });
  }, [revealed, card.id]);

  const reveal = useCallback(() => {
    setRevealed((current) => Math.min(current + 1, levels.length));
  }, [levels.length]);

  useEffect(() => {
    if (revealed > 1 && nextRef.current) {
      nextRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [revealed]);

  if (!levels.length) return null;

  const hasMore = revealed < levels.length;
  const nextMeta = LEVEL_META[revealed];

  return (
    <div>
      <LevelRail total={levels.length} revealed={revealed} onJump={setRevealed} />

      <div className="mt-6 space-y-10">
        {levels.slice(0, revealed).map((level, index) => {
          const meta = LEVEL_META[level.level - 1] ?? LEVEL_META[index];
          const isLast = index === revealed - 1;

          return (
            <motion.section
              key={level.level}
              initial={index === 0 ? false : { opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
              ref={isLast ? nextRef : undefined}
              aria-label={`Level ${level.level}: ${level.label}`}
            >
              <header className="mb-3 flex items-baseline gap-3">
                <span className="grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent-text">
                  {level.level}
                </span>
                <div>
                  <h3 className="text-[15px] font-semibold tracking-tight text-text">
                    {level.label}
                  </h3>
                  {meta && (
                    <p className="text-[12px] text-text-faint">{meta.hint}</p>
                  )}
                </div>
              </header>

              <Prose text={level.body} />

              {/* Diagrams belong with the technical level, where the reader
                  has just been given the mechanism to read them against. */}
              {level.level === 4 &&
                card.diagrams.map((diagram, i) => (
                  <DiagramBlock key={i} diagram={diagram} />
                ))}
            </motion.section>
          );
        })}
      </div>

      <AnimatePresence>
        {hasMore && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-8"
          >
            <button
              onClick={reveal}
              className="group flex w-full items-center gap-3 rounded-[--radius-card] border border-border bg-surface-2/60 px-5 py-4 text-left transition-colors hover:border-border-strong hover:bg-surface-2"
            >
              <span className="grid size-8 shrink-0 place-items-center rounded-full bg-surface text-text-muted transition-colors group-hover:text-text">
                <Icon name="ArrowDown" className="size-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-text">
                  Go one level deeper — {nextMeta?.short}
                </span>
                <span className="block text-[12px] text-text-muted">
                  {nextMeta?.hint}
                </span>
              </span>
              <span className="shrink-0 text-[11px] tabular-nums text-text-faint">
                {revealed} / {levels.length}
              </span>
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {!hasMore && (
        <div className="mt-8 flex items-center gap-2 rounded-[--radius-card] border border-border bg-surface-2/40 px-5 py-3.5 text-[13px] text-text-muted">
          <Icon name="Check" className="size-4 text-positive" />
          You&rsquo;ve read every level of this explanation.
        </div>
      )}

      <ReexplainPanel card={card} currentLevel={revealed} />
    </div>
  );
}

/** The level indicator — also a jump control, since re-reading is normal. */
function LevelRail({
  total,
  revealed,
  onJump,
}: {
  total: number;
  revealed: number;
  onJump: (level: number) => void;
}) {
  return (
    <div className="flex items-center gap-1.5" role="tablist" aria-label="Explanation depth">
      {Array.from({ length: total }, (_, i) => i + 1).map((level) => {
        const meta = LEVEL_META[level - 1];
        const isRevealed = level <= revealed;
        return (
          <button
            key={level}
            role="tab"
            aria-selected={level === revealed}
            aria-label={`Level ${level}: ${meta?.short ?? ""}`}
            disabled={!isRevealed}
            onClick={() => onJump(level)}
            title={isRevealed ? meta?.short : "Not unlocked yet"}
            className={cn(
              "h-1.5 flex-1 rounded-full transition-colors duration-300",
              isRevealed ? "bg-accent" : "bg-surface-3",
              isRevealed && "cursor-pointer hover:opacity-80",
            )}
          />
        );
      })}
      <span className="ml-2 shrink-0 text-[11px] tabular-nums text-text-faint">
        {LEVEL_META[revealed - 1]?.short}
      </span>
    </div>
  );
}
