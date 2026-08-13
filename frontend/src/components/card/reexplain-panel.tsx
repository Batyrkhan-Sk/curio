"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import type { CardDetail, Reexplanation } from "@/lib/types";
import { Prose } from "./prose";
import { Button } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/icon";
import { ApiError, reexplain } from "@/lib/api";

/**
 * "I still don't understand."
 *
 * The contract with the reader is that pressing this never returns the same
 * explanation reworded. The server tracks which approaches have been spent
 * (`tried`) and picks a structurally different one each time — simpler, then a
 * new analogy, then a worked example, then steps, then a picture, then first
 * principles. Attempts accumulate on screen rather than replacing each other,
 * because one of them landing is often clearer alongside the one that didn't.
 */
export function ReexplainPanel({
  card,
  currentLevel,
}: {
  card: CardDetail;
  currentLevel: number;
}) {
  const [attempts, setAttempts] = useState<Reexplanation[]>([]);
  const [tried, setTried] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask() {
    setLoading(true);
    setError(null);
    try {
      const last =
        attempts.at(-1)?.body ?? card.levels[currentLevel - 1]?.body ?? "";
      const result = await reexplain(card.slug, { tried, last_response: last });
      setAttempts((prev) => [...prev, result]);
      setTried(result.tried);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not reach the explainer just now.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mt-10 border-t border-border pt-8">
      <AnimatePresence initial={false}>
        {attempts.map((attempt, i) => (
          <motion.div
            key={`${attempt.mode}-${i}`}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            className="mb-8"
          >
            <div className="mb-3 flex items-center gap-2">
              <span className="grid size-6 place-items-center rounded-full bg-accent-soft text-accent-text">
                <Icon name="Lightbulb" className="size-3.5" />
              </span>
              <h4 className="text-[13px] font-semibold uppercase tracking-[0.08em] text-text-muted">
                {attempt.label}
              </h4>
              {!attempt.generated && (
                <span className="text-[11px] text-text-faint">
                  from this card
                </span>
              )}
            </div>
            <Prose text={attempt.body} />
          </motion.div>
        ))}
      </AnimatePresence>

      {error && (
        <p className="mb-4 flex items-start gap-2 text-[13px] text-critical">
          <Icon name="TriangleAlert" className="mt-0.5 size-3.5 shrink-0" />
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" onClick={ask} disabled={loading}>
          {loading ? (
            <>
              <Icon name="LoaderCircle" className="size-4 animate-spin" />
              Finding another way
            </>
          ) : (
            <>
              <Icon name="HelpCircle" className="size-4" />
              {attempts.length
                ? "Still not clear — try again"
                : "I still don't understand"}
            </>
          )}
        </Button>
        {attempts.length > 0 && (
          <span className="text-[12px] text-text-faint">
            {attempts.length === 1
              ? "One more angle tried"
              : `${attempts.length} different angles tried`}
          </span>
        )}
      </div>
    </div>
  );
}
